import asyncio
from types import SimpleNamespace

import pytest
from discord import MessageReferenceType

from mediaguard.activity import Activity
from mediaguard.attachments import PREFIX_BYTES, Status, detect_audio, download_prefix
from mediaguard.discord_service import DiscordService, make_client


MP3_FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 413
MP3 = MP3_FRAME * 2
WAV = b"RIFF" + b"\x24\x00\x00\x00" + b"WAVEfmt " + b"\x00" * 24
FLAC = b"fLaC\x80\x00\x00\x22" + b"\x00" * 34
OPUS = b"OggS\x00\x02" + b"\x00" * 20 + b"\x01\x08OpusHead" + b"\x00" * 16
VORBIS = b"OggS\x00\x02" + b"\x00" * 20 + b"\x01\x07\x01vorbis" + b"\x00" * 16
M4A = b"\x00\x00\x00\x14ftypM4A \x00\x00\x00\x00isom"


def attachment(filename="file.txt", content=b"plain text", mime="text/plain", size=None):
    return SimpleNamespace(
        filename=filename,
        content_type=mime,
        size=len(content) if size is None else size,
        url="https://cdn.discordapp.com/attachments/1/2/synthetic",
        content=content,
    )


def message(*attachments, guild=True, author_id=10, forward=False, snapshots=(), content="private message body"):
    return SimpleNamespace(
        guild=object() if guild else None,
        author=SimpleNamespace(id=author_id),
        attachments=list(attachments),
        reference=SimpleNamespace(type=MessageReferenceType.forward) if forward else None,
        message_snapshots=list(snapshots),
        content=content,
    )


def service():
    fetched = []

    async def fetch(item):
        fetched.append(item.url)
        if item.content is None:
            raise OSError("synthetic download failure")
        return item.content[:PREFIX_BYTES]

    activity = Activity()
    return DiscordService(activity, fetch_prefix=fetch), fetched


def inspect(bot, msg, bot_user_id=99):
    return asyncio.run(bot.inspect_message(msg, bot_user_id))


def test_text_own_message_and_dm_do_no_work():
    bot, fetched = service()
    assert inspect(bot, message(content="https://example.invalid/audio.mp3")) == ()
    assert inspect(bot, message(attachment("song.mp3", MP3), author_id=99)) == ()
    assert inspect(bot, message(attachment("song.mp3", MP3), guild=False)) == ()
    assert fetched == []
    assert bot.activity.recent() == []


@pytest.mark.parametrize(
    ("filename", "content", "media_type"),
    [
        ("song.mp3", MP3, "mp3"),
        ("song.wav", WAV, "wav"),
        ("song.flac", FLAC, "flac"),
        ("song.opus", OPUS, "opus"),
        ("song.ogg", VORBIS, "ogg-vorbis"),
        ("song.m4a", M4A, "m4a"),
    ],
)
def test_supported_audio_signatures(filename, content, media_type):
    bot, fetched = service()
    result, = inspect(bot, message(attachment(filename, content, "application/octet-stream")))
    assert result.status is Status.MATCH
    assert result.media_type == media_type
    assert result.inspection_complete
    assert len(fetched) == 1


def test_id3_mp3_and_renamed_audio():
    with_tag = b"ID3\x03\x00\x00\x00\x00\x00\x00" + MP3
    assert detect_audio(with_tag) == "mp3"
    bot, _ = service()
    result, = inspect(bot, message(attachment("notes.txt", WAV, "text/plain")))
    assert result.status is Status.MATCH
    assert result.extension == ".txt"
    assert result.declared_mime == "text/plain"


def test_ordinary_attachment_is_safe_and_misleading_audio_is_unavailable():
    bot, _ = service()
    safe, unresolved = inspect(bot, message(attachment(), attachment("song.mp3", b"not an mp3", "audio/mpeg")))
    assert safe.status is Status.SAFE
    assert safe.inspection_complete
    assert unresolved.status is Status.UNAVAILABLE
    assert not unresolved.inspection_complete
    assert unresolved.extension == ".mp3"
    assert unresolved.declared_mime == "audio/mpeg"


def test_generic_mp4_brand_and_video_are_not_claimed_as_audio():
    bot, _ = service()
    generic = b"\x00\x00\x00\x10ftypisom\x00\x00\x00\x00"
    container, video = inspect(bot, message(attachment("song.m4a", generic), attachment("clip.mp4", b"unknown")))
    assert container.status is Status.UNAVAILABLE
    assert video.status is Status.UNAVAILABLE


def test_download_failure_and_size_limit_are_not_safe():
    bot, fetched = service()
    failed = attachment("song.mp3", None, "audio/mpeg", size=100)
    large = attachment("large.txt", b"", size=bot.max_attachment_bytes + 1)
    first, second = inspect(bot, message(failed, large))
    assert [item.status for item in (first, second)] == [Status.UNAVAILABLE, Status.UNAVAILABLE]
    assert [item.reason for item in (first, second)] == ["download_failed", "size_limit"]
    assert len(fetched) == 1


def test_short_download_is_unavailable_even_for_plain_filename():
    bot, _ = service()
    result, = inspect(bot, message(attachment("note.txt", b"", size=100)))
    assert result.status is Status.UNAVAILABLE
    assert result.reason == "incomplete_download"


def test_forwarded_attachment_uses_same_inspector():
    bot, fetched = service()
    snapshot = SimpleNamespace(attachments=[attachment("renamed.bin", FLAC)], embeds=[])
    result, = inspect(bot, message(forward=True, snapshots=[snapshot]))
    assert result.status is Status.MATCH
    assert result.source == "forward"
    assert result.media_type == "flac"
    assert len(fetched) == 1


def test_forward_without_snapshot_is_unavailable():
    bot, fetched = service()
    result, = inspect(bot, message(forward=True))
    assert result.status is Status.UNAVAILABLE
    assert result.reason == "forward_snapshot_unavailable"
    assert fetched == []


def test_forward_embed_is_not_claimed_safe():
    bot, _ = service()
    snapshot = SimpleNamespace(attachments=[], embeds=[object()])
    result, = inspect(bot, message(forward=True, snapshots=[snapshot]))
    assert result.status is Status.UNAVAILABLE
    assert result.reason == "forward_embeds_not_inspected"


def test_forward_snapshot_without_media_metadata_is_unavailable():
    bot, fetched = service()
    snapshot = SimpleNamespace(attachments=[], embeds=[])
    result, = inspect(bot, message(forward=True, snapshots=[snapshot]))
    assert result.status is Status.UNAVAILABLE
    assert result.reason == "forward_media_metadata_unavailable"
    assert fetched == []


def test_no_body_or_attachment_content_is_logged_or_persisted(tmp_path):
    from mediaguard.config import Config
    from mediaguard.runtime import Runtime

    runtime = Runtime(Config(), tmp_path)
    runtime.start()
    async def fetch(item):
        return item.content
    runtime.discord.fetch_prefix = fetch
    inspect(runtime.discord, message(attachment("sensitive-name.mp3", MP3), content="private phrase"))
    activity = str(runtime.activity.recent())
    assert "sensitive-name" not in activity
    assert "private phrase" not in activity
    assert "media_match_observed" in activity
    with runtime.database.connect() as connection:
        assert {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {"schema_migrations", "enforcement_events", "guild_protection", "blocked_embed_phrases"}
    runtime.stop()


def test_no_enforcement_or_arbitrary_url_fetch():
    bot, fetched = service()
    msg = message(content="https://example.invalid/file.mp3")
    msg.delete = lambda: pytest.fail("enforcement was invoked")
    msg.edit = lambda: pytest.fail("enforcement was invoked")
    msg.reply = lambda: pytest.fail("moderator alert was invoked")
    assert inspect(bot, msg) == ()
    assert fetched == []


def test_discord_on_message_hook_uses_existing_client_without_network():
    bot, fetched = service()

    async def run():
        client = make_client(bot)
        try:
            await client.on_message(message(attachment("song.wav", WAV)))
        finally:
            await client.close()

    asyncio.run(run())
    assert len(fetched) == 1
    assert bot.activity.recent()[0]["code"] == "media_match_observed"


def test_unexpected_intake_error_records_only_a_code():
    async def broken_fetch(_):
        raise RuntimeError("private phrase")

    bot = DiscordService(Activity(), fetch_prefix=broken_fetch)

    async def run():
        client = make_client(bot)
        try:
            await client.on_message(message(attachment("private-name.wav", WAV)))
        finally:
            await client.close()

    asyncio.run(run())
    activity = str(bot.activity.recent())
    assert "discord_intake_error" in activity
    assert "private phrase" not in activity
    assert "private-name" not in activity


def test_download_prefix_rejects_non_discord_url():
    item = attachment()
    item.url = "https://example.invalid/private"
    with pytest.raises(OSError):
        asyncio.run(download_prefix(item))


def test_download_prefix_reads_only_bounded_bytes(monkeypatch):
    calls = {}

    class Content:
        remaining = PREFIX_BYTES

        async def read(self, count):
            calls.setdefault("read_counts", []).append(count)
            sent = min(count, 1024, self.remaining)
            self.remaining -= sent
            return b"x" * sent

    class Response:
        status = 200
        content = Content()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

    class Session:
        def __init__(self, timeout):
            calls["timeout"] = timeout.total

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        def get(self, url, **kwargs):
            calls.update(url=url, **kwargs)
            return Response()

    monkeypatch.setattr("mediaguard.attachments.aiohttp.ClientSession", Session)
    prefix = asyncio.run(download_prefix(attachment()))
    assert len(prefix) == PREFIX_BYTES
    assert calls["read_counts"][0] == PREFIX_BYTES
    assert calls["read_counts"] == [4096, 3072, 2048, 1024]
    assert calls["headers"] == {"Range": f"bytes=0-{PREFIX_BYTES - 1}"}
    assert calls["allow_redirects"] is False
    assert calls["timeout"] == 8
