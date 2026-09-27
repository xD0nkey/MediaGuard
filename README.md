# MediaGuard

MediaGuard is an independent Discord moderation project. It aims to inspect media entering a server, apply explainable rules, and support moderators with auditable cases. When the bot is enabled, it observes guild messages and inspects direct and forwarded attachments. It does **not** delete or quarantine messages, send moderator alerts, create cases, or register moderation commands.

## Implemented

- Discord client lifecycle with reconnect support and safe local status reporting.
- Guild message intake that ignores MediaGuard's own messages and DMs. Text-only messages require no attachment work.
- Bounded signature inspection of direct attachments and attachments exposed in Discord forwarded-message snapshots. Recognized audio: MP3, WAV, FLAC, Ogg Opus, Ogg Vorbis, and M4A with an `M4A ` brand.
- Explicit `SAFE`, `MATCH`, and `UNAVAILABLE` inspection results. A download failure, size limit, conflicting media evidence, or missing forward metadata is never treated as safe.
- SQLite database ownership and an idempotent migration mechanism. Only the migration ledger exists today.
- A read-only local FastAPI operator API and a responsive React dashboard showing real runtime status and Activity.
- Fake-client tests that do not contact Discord.

## Planned

The [concept document](docs/MediaGuard_concept.md) also describes deterministic rules, enforcement, moderator cases, Last.fm handling, link inspection, and more media formats. These remain planned. See [architecture](docs/architecture.md) for current boundaries.

## Requirements and setup

Use Python 3.11+ and Node.js 20+. Clone the repository, create a virtual environment, and run:

```text
pip install -e ".[test]"
cd web
npm ci
npm run build
cd ..
mediaguard
```

Open `http://127.0.0.1:8765`. The bot is disabled by default; the dashboard and tests need no credential. To connect a dedicated bot, copy `config.example.json` to ignored `config.json`, set `discord.enabled` to `true`, copy `secrets.example.env` to ignored `secrets.env`, and set the **MediaGuard-only** bot token. Enable the privileged **Message Content Intent** in the Discord developer portal: Discord otherwise withholds attachment fields from ordinary guild messages. The client also requests Guilds and Guild Messages, but not Members or Presences. The current bot only inspects; it performs no moderation.

## Configuration and data

Safe defaults live in source code and `config.example.json`. Local operator configuration belongs in ignored `config.json`. `discord.max_attachment_bytes` defaults to 25 MiB (26,214,400 bytes) and may be set from 1 byte to 100 MiB. Attachments above the limit are `UNAVAILABLE` without a download. For eligible attachments, MediaGuard reads at most the first 4 KiB and does not persist attachment bytes. Credentials belong in ignored `secrets.env` or the `DISCORD_BOT_TOKEN` environment variable. Mutable SQLite state lives in ignored `runtime/`; inspection results are not persisted. Never commit real guild IDs, messages, cases, notes, or tokens.

The API binds to loopback and serves read-only status and activity. It is not designed for remote access. The Activity feed contains fixed service codes, not Discord message content. See [development](docs/development.md), [security](SECURITY.md), and [contributing](CONTRIBUTING.md).

## Testing and limitations

Run `pytest` and `cd web && npm run build`. CI runs both with synthetic configuration and no Discord token. Forward inspection depends on snapshots exposed by Discord; missing snapshots and uninspected forward embeds yield `UNAVAILABLE`. `SAFE` means no supported audio evidence was found in the inspected prefix, not that the entire file or message is harmless. Video, links, and other audio formats are not identified in this phase. Before pushing, review staged paths and run a secret scan; GitHub secret scanning may depend on repository/account settings and should not be assumed active. No license has been selected yet. Public visibility alone does not grant permission to reuse, modify, or redistribute this code.
