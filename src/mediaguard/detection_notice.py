from datetime import datetime
from unicodedata import category

import discord


BLOCKED_COLOR = 0xD94A4A
UNRESOLVED_COLOR = 0xD9A441
UNRESOLVED_REASONS = {
    "size_unavailable": "The attachment size was not available.",
    "download_failed": "The attachment could not be downloaded or the download timed out.",
    "incomplete_download": "Only part of the attachment could be downloaded.",
    "media_evidence_unresolved": "The attachment looks like audio or video, but its format could not be confirmed.",
    "forward_snapshot_unavailable": "The forwarded message content was not available.",
    "forward_media_metadata_unavailable": "The forwarded message had no inspectable attachments or embeds.",
    "forward_embeds_not_inspected": "Forwarded embeds could not be checked because no embed phrases are configured.",
}


def _label(value, limit):
    cleaned = "".join(
        char for char in str(value)
        if category(char) not in {"So", "Sk", "Cf", "Cc"}
        and char not in {"\ufe0e", "\ufe0f", "\u20e3"}
    )
    return discord.utils.escape_markdown(cleaned).strip()[:limit]


def detection_embed(message, result, deleted_at: datetime):
    if deleted_at.tzinfo is None or deleted_at.utcoffset() is None:
        raise ValueError("Deletion timestamp must be timezone-aware")
    names = {"mp3": "MP3", "wav": "WAV", "flac": "FLAC", "opus": "Ogg Opus",
             "ogg-vorbis": "Ogg Vorbis", "m4a": "M4A"}
    phrase_match = result.rule_id is not None
    embed = discord.Embed(
        title="Blocked embed phrase" if phrase_match else "Audio file blocked",
        description="A configured embed phrase was detected and removed." if phrase_match else
                    "A prohibited audio file was detected and removed.",
        color=BLOCKED_COLOR,
        timestamp=deleted_at,
    )
    author = _label(getattr(message.author, "display_name", str(message.author.id)), 200) or str(message.author.id)
    avatar = getattr(message.author, "display_avatar", None)
    avatar_url = getattr(avatar, "url", None)
    embed.set_author(name=author, icon_url=None if phrase_match else avatar_url)
    embed.add_field(name="User", value=f"<@{message.author.id}>", inline=False)
    embed.add_field(name="Channel", value=f"<#{message.channel.id}>", inline=False)
    if not phrase_match and result.filename:
        filename = _label(result.filename, 200)
        if filename:
            embed.add_field(name="File", value=filename, inline=False)
    if phrase_match:
        embed.add_field(name="Detection", value="Blocked embed phrase", inline=True)
        embed.add_field(name="Rule", value=_label(result.rule_name, 80) or result.rule_id, inline=True)
        embed.add_field(name="Source", value="Forwarded embed" if result.source == "forwarded_embed" else "Discord embed", inline=True)
    else:
        embed.add_field(name="Detected as", value=f"{names[result.media_type]} audio", inline=True)
        embed.add_field(name="Source", value="Forwarded message" if result.source == "forward" else "Direct attachment", inline=True)
    embed.add_field(name="Action", value="Message deleted", inline=False)
    embed.add_field(name="Deleted at", value=f"<t:{int(deleted_at.timestamp())}:F>", inline=False)
    embed.set_footer(text="MediaGuard")
    return embed


def unresolved_embed(message, result, checked_at: datetime):
    embed = discord.Embed(
        title="Inspection inconclusive",
        description="MediaGuard could not conclusively determine the media in this message. "
                    "The message was NOT deleted.",
        color=UNRESOLVED_COLOR,
        timestamp=checked_at,
    )
    embed.add_field(name="User", value=f"<@{message.author.id}>", inline=False)
    embed.add_field(name="Channel", value=f"<#{message.channel.id}>", inline=False)
    embed.add_field(name="Reason", value=UNRESOLVED_REASONS.get(result.reason, "Inspection was incomplete."),
                    inline=False)
    embed.add_field(name="Action", value="Message not deleted", inline=False)
    embed.add_field(name="Message", value=f"[Jump to message]({message.jump_url})", inline=False)
    embed.set_footer(text="MediaGuard")
    return embed


def blocked_audio_embed(message, result, deleted_at: datetime):
    return detection_embed(message, result, deleted_at)
