from datetime import datetime
from unicodedata import category

import discord


BLOCKED_COLOR = 0xD94A4A


def _label(value, limit):
    cleaned = "".join(
        char for char in str(value)
        if category(char) not in {"So", "Sk", "Cf", "Cc"}
        and char not in {"\ufe0e", "\ufe0f", "\u20e3"}
    )
    return discord.utils.escape_markdown(cleaned).strip()[:limit]


def detection_embed(message, result, deleted_at: datetime):
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
    if phrase_match:
        embed.add_field(name="User", value=author, inline=False)
        embed.add_field(name="Discord user ID", value=str(message.author.id), inline=False)
    else:
        embed.add_field(name="User", value=f"{author}\n{message.author.id}", inline=False)
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
    embed.add_field(name="Deleted at", value=deleted_at.strftime("%d %B %Y %H:%M:%S UTC"), inline=False)
    embed.set_footer(text="MediaGuard")
    return embed


def blocked_audio_embed(message, result, deleted_at: datetime):
    return detection_embed(message, result, deleted_at)
