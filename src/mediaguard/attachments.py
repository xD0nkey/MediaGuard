import asyncio
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePath
from urllib.parse import urlsplit

import aiohttp


PREFIX_BYTES = 4096
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg", ".opus", ".m4a", ".m4b", ".aac"}
MP4_AUDIO_EXTENSIONS = {".m4a", ".m4b", ".aac"}
MP4_AUDIO_BRANDS = {b"M4A ", b"M4B ", b"mp42", b"isom"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}


class Status(StrEnum):
    SAFE = "safe"
    MATCH = "match"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class InspectionResult:
    status: Status
    reason: str
    source: str
    filename: str | None = None
    extension: str | None = None
    declared_mime: str | None = None
    size: int | None = None
    media_type: str | None = None
    rule_id: str | None = None
    rule_name: str | None = None

    @property
    def inspection_complete(self) -> bool:
        return self.status is not Status.UNAVAILABLE


def _mp3_frame_length(data: bytes, offset: int) -> int | None:
    if len(data) < offset + 4:
        return None
    header = int.from_bytes(data[offset:offset + 4], "big")
    if header >> 21 != 0x7FF:
        return None
    version = (header >> 19) & 3
    layer = (header >> 17) & 3
    bitrate_index = (header >> 12) & 15
    sample_index = (header >> 10) & 3
    if version == 1 or layer != 1 or bitrate_index in (0, 15) or sample_index == 3:
        return None
    if version == 3:
        rates = (44100, 48000, 32000)
        bitrates = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
    else:
        rates = (22050, 24000, 16000) if version == 2 else (11025, 12000, 8000)
        bitrates = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
    factor = 144000 if version == 3 else 72000
    return factor * bitrates[bitrate_index] // rates[sample_index] + ((header >> 9) & 1)


def id3_tag_end(data: bytes) -> int | None:
    if len(data) < 10 or not data.startswith(b"ID3") or data[3] not in (2, 3, 4):
        return None
    if any(byte >= 128 for byte in data[6:10]):
        return None
    size = 0
    for byte in data[6:10]:
        size = (size << 7) | byte
    return 10 + size


def _is_flac(data: bytes) -> bool:
    return (
        len(data) >= 8
        and data[:4] == b"fLaC"
        and data[4] & 0x7F == 0
        and int.from_bytes(data[5:8], "big") == 34
    )


def _is_mp3_at(data: bytes, offset: int) -> bool:
    first = _mp3_frame_length(data, offset)
    return bool(first and _mp3_frame_length(data, offset + first))


def detect_audio_after_id3(data: bytes) -> str | None:
    if _is_flac(data):
        return "flac"
    if _is_mp3_at(data, 0):
        return "mp3"
    return None


def _insufficient_post_id3(data: bytes) -> bool:
    if len(data) < 8:
        return True
    first_frame = _mp3_frame_length(data, 0)
    return first_frame is not None and len(data) < first_frame + 4


def detect_audio(data: bytes) -> str | None:
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if _is_flac(data):
        return "flac"
    if len(data) >= 28 and data[:4] == b"OggS" and data[4] == 0 and data[5] & 0x02:
        payload = 27 + data[26]
        if data[payload:payload + 8] == b"OpusHead":
            return "opus"
        if data[payload:payload + 7] == b"\x01vorbis":
            return "ogg-vorbis"
    if data.startswith(b"ID3"):
        tag_end = id3_tag_end(data)
        return detect_audio_after_id3(data[tag_end:]) if tag_end is not None else None
    return "mp3" if _is_mp3_at(data, 0) else None


def mp4_brands(data: bytes) -> set[bytes]:
    if len(data) < 16 or data[4:8] != b"ftyp":
        return set()
    box_size = int.from_bytes(data[:4], "big")
    if not 16 <= box_size <= len(data) or (box_size - 16) % 4:
        return set()
    return {data[8:12], *(data[index:index + 4] for index in range(16, box_size, 4))}


def _is_declared_audio(extension, mime) -> bool:
    return extension in MP4_AUDIO_EXTENSIONS or bool(mime and mime.startswith("audio/"))


async def download_prefix(attachment, start: int = 0) -> bytes:
    if type(start) is not int or start < 0:
        raise ValueError("Invalid range start")
    url = urlsplit(attachment.url)
    if (
        url.scheme != "https"
        or url.hostname not in {"cdn.discordapp.com", "cdn.discord.com"}
        or not url.path.startswith("/attachments/")
        or url.username
        or url.password
        or url.port not in (None, 443)
    ):
        raise OSError("Unsupported attachment URL")
    timeout = aiohttp.ClientTimeout(total=8)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(
            attachment.url,
            headers={"Range": f"bytes={start}-{start + PREFIX_BYTES - 1}"},
            allow_redirects=False,
        ) as response:
            if response.status not in ((200, 206) if start == 0 else (206,)):
                raise OSError("Attachment fetch failed")
            prefix = bytearray()
            while len(prefix) < PREFIX_BYTES:
                chunk = await response.content.read(PREFIX_BYTES - len(prefix))
                if not chunk:
                    break
                prefix.extend(chunk)
            return bytes(prefix)


async def inspect_attachment(
    attachment, fetch_prefix=download_prefix, source="direct"
) -> InspectionResult:
    filename = attachment.filename
    extension = PurePath(filename).suffix.lower() if filename else None
    mime = (attachment.content_type or "").split(";", 1)[0].strip().lower() or None
    size = attachment.size
    evidence = {
        "source": source,
        "filename": filename,
        "extension": extension,
        "declared_mime": mime,
        "size": size,
    }

    if not isinstance(size, int) or size < 0:
        return InspectionResult(Status.UNAVAILABLE, "size_unavailable", **evidence)
    try:
        prefix = await fetch_prefix(attachment)
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):
        return InspectionResult(Status.UNAVAILABLE, "download_failed", **evidence)
    if len(prefix) < min(size, PREFIX_BYTES):
        return InspectionResult(Status.UNAVAILABLE, "incomplete_download", **evidence)

    media_type = detect_audio(prefix)
    if media_type is None and mp4_brands(prefix) & MP4_AUDIO_BRANDS and _is_declared_audio(extension, mime):
        media_type = "m4a"
    if media_type:
        return InspectionResult(Status.MATCH, "audio_signature", media_type=media_type, **evidence)
    tag_end = id3_tag_end(prefix)
    if tag_end is not None and len(prefix) < tag_end + PREFIX_BYTES and tag_end < size:
        return await _inspect_after_id3(attachment, tag_end, fetch_prefix, evidence) or _unresolved_or_safe(
            prefix, extension, mime, evidence)
    return _unresolved_or_safe(prefix, extension, mime, evidence)


async def _inspect_after_id3(attachment, tag_end, fetch_prefix, evidence) -> InspectionResult | None:
    try:
        after_tag = await fetch_prefix(attachment, tag_end)
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):
        return InspectionResult(Status.MATCH, "id3_tag", media_type="mp3", **evidence)
    media_type = detect_audio_after_id3(after_tag)
    if media_type:
        return InspectionResult(Status.MATCH, "audio_signature", media_type=media_type, **evidence)
    if _insufficient_post_id3(after_tag):
        return InspectionResult(Status.MATCH, "id3_tag", media_type="mp3", **evidence)
    return None


def _unresolved_or_safe(prefix, extension, mime, evidence) -> InspectionResult:
    media_hint = (
        extension in AUDIO_EXTENSIONS
        or extension in VIDEO_EXTENSIONS
        or (mime and mime.startswith(("audio/", "video/")))
        or prefix.startswith((b"ID3", b"OggS"))
        or prefix[4:8] == b"ftyp"
    )
    if media_hint:
        return InspectionResult(Status.UNAVAILABLE, "media_evidence_unresolved", **evidence)
    return InspectionResult(Status.SAFE, "no_supported_media_evidence", **evidence)
