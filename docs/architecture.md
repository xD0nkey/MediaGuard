# Architecture

## Current boundary

`Runtime` owns startup and shutdown. `DiscordService` owns one `discord.py` client and an asyncio loop on a dedicated thread. Its `on_message` callback inspects guild messages, ignoring MediaGuard's own messages and DMs. `attachments.py` returns one explicit result per inspected attachment. Forwarded attachments exposed in `Message.message_snapshots` use the same inspector. Inspection results are ephemeral; Activity records only match and failure codes, without message bodies or filenames.

`Database` owns a SQLite file under this project's `runtime/` directory and applies numbered, idempotent migrations. It stores no inspection results. FastAPI exposes read-only status and activity endpoints to the local dashboard. There are no rules, enforcement actions, or case records yet.

The dashboard shows actual runtime state. Cases and Rules are explicit placeholders.

## Future boundaries

The next phase should add deterministic rules, enforcement, moderator cases, and persistent audit records. Cases and audit events must be written transactionally with enforcement intent and outcome. Each moderator action must store moderator ID; each rule match must store its exact reason and rule version. Case records should never be deleted silently. These are future design constraints, not implemented features.

## Discord intents

The client requests `guilds`, `messages`, and privileged `message_content`. `messages` supplies guild message events; `message_content` is needed because Discord otherwise withholds attachments from ordinary guild messages. `guilds` supplies guild identity and connected guild count. `members` and `presences` are not requested. Enable Message Content Intent for MediaGuard's own application in the Discord developer portal. No slash commands are registered.

## Inspection limits

MediaGuard checks the filename extension, Discord-declared MIME type, size, and up to 4 KiB of leading bytes. It recognizes MP3 Layer III frames, RIFF/WAVE, native FLAC, Ogg Opus, Ogg Vorbis, and ISO BMFF files with an `M4A ` brand. An M4A brand identifies an audio-oriented container, not its exact tracks or codec. A generic `ftyp` box does not prove audio, so it remains unresolved. The attachment size limit defaults to 25 MiB and is configurable to at most 100 MiB. Downloads use a bounded streaming read from a Discord attachment CDN URL, with an eight-second timeout and no redirects. `discord.py`'s `Attachment.read()` retrieves the complete body, so the inspector uses `aiohttp` directly to stop after the prefix. Attachment bytes are discarded after inspection.

`MATCH` requires a recognized audio or M4A-container signature. `SAFE` means no supported media evidence appeared in the inspected prefix; `inspection_complete` means this configured prefix check completed, not that the whole file was decoded. `UNAVAILABLE` covers download failure, size limits, unresolved extension/MIME evidence, missing forward snapshots, and forward embeds not inspected in this phase. It is never equivalent to `SAFE`. A forwarded snapshot's author or origin is not inferred, and forwarded text or embeds are not scraped for media. Discord may omit snapshot data or attachment fields, so forward support is limited to metadata actually exposed by discord.py.

The format checks follow the [MP3 frame header](https://www.mp3-tech.org/programmer/frame_header.html), [RIFF/WAVE structure](https://learn.microsoft.com/en-us/windows/win32/xaudio2/resource-interchange-file-format--riff-), [FLAC RFC](https://www.rfc-editor.org/rfc/rfc9639.html), [Ogg framing](https://datatracker.ietf.org/doc/html/rfc3533), [Opus RFC](https://datatracker.ietf.org/doc/rfc7845/), [Vorbis specification](https://xiph.org/vorbis/doc/Vorbis_I_spec.html), and [registered M4A brand](https://mp4ra.org/registered-types/brands). Forward snapshots and attachment fields are documented in the [discord.py API reference](https://discordpy.readthedocs.io/en/stable/api.html); Discord documents the [privileged Message Content Intent](https://support-dev.discord.com/hc/en-us/articles/6207308062871-What-are-Privileged-Intents).

## Operator access

The backend binds to loopback only. Host and Origin are checked. Endpoints are read-only and expose no message bodies, notes, or secrets. Remote deployment requires a separately designed authentication layer.
