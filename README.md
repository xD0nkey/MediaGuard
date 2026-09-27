# MediaGuard

MediaGuard is a focused Discord audio-file protection bot. It inspects direct attachments and forwarded-message snapshots in guild messages. A confirmed MP3, WAV, FLAC, Ogg Opus, Ogg Vorbis, or M4A match triggers one deletion of the source message. Optional Detection notifications report successful removals to a configured channel.

## Setup

Use Python 3.11+ and Node.js 20+:

```text
pip install -e ".[test]"
cd web
npm ci
npm run build
cd ..
mediaguard
```

Open `http://127.0.0.1:8765`. Copy `config.example.json` to ignored `config.json` and `secrets.example.env` to ignored `secrets.env`. Set a dedicated MediaGuard token in `secrets.env` or `DISCORD_BOT_TOKEN`. Set `discord.enabled` and `protection.enabled` to `true` to connect and enforce. Both default to `false`.

`protection.channel_ids` is an array of Discord channel IDs. An empty array protects all guild text channels the bot can receive; a nonempty array protects only those exact IDs. `protection.notifications_enabled` enables one informational Detection embed after a successful deletion. Set `protection.detection_channel_id` to its destination. If notification delivery fails or the channel is unconfigured, deletion still occurs and the audit records the failure. Changes to `config.json` take effect after restart. The dashboard is read-only.

## Discord permissions

Enable the privileged Message Content Intent in the Discord developer portal. The bot requests Guilds, Guild Messages, and Message Content intents. Grant **View Channel** and **Manage Messages** in each protected channel. Grant **View Channel** and **Send Messages** in the Detection channel when notifications are enabled. Administrator, Members, Presences, and Read Message History are not required for this flow. MediaGuard checks the relevant channel permissions before each action and records failures. See [Discord permissions](https://discord.com/developers/docs/topics/permissions), [message content intent](https://support-dev.discord.com/hc/en-us/articles/6207308062871-What-are-Privileged-Intents), and [discord.py message API](https://discordpy.readthedocs.io/en/stable/api.html).

## Inspection and evidence

Inspection uses filename, declared MIME type, size, and at most the first 4 KiB of an eligible Discord CDN attachment. The size limit defaults to 25 MiB and can be changed with `discord.max_attachment_bytes` (up to 100 MiB). `MATCH` takes precedence over `UNAVAILABLE`, which takes precedence over `SAFE`. Unavailable inspections do not cause deletion or a blocked-audio notification. Forward support is limited to attachments Discord exposes in message snapshots. URLs and external-service sharing, including Last.fm, are outside this boundary and need investigation with real bypass examples.

MediaGuard never preserves, reposts, mirrors, archives, or links to prohibited audio. Detection embeds contain a display name and stable user ID, source channel, filename when available, recognized media type, source type, actual action, and confirmed deletion time in UTC. They contain no emoji, message body, attachment URL, or media copy. The ignored SQLite database under `runtime/` stores only minimal enforcement metadata and outcomes, including the original guild, channel, message, and user IDs. A deletion attempt is reserved before its Discord call; a duplicate event does not retry an ambiguous deletion.

## Development

Run `py -3 -m pytest -q`, `cd web && npm run format:check`, and `npm run build`. Tests use synthetic attachments and mocked Discord boundaries; no real token or Discord connection is needed. See [architecture](docs/architecture.md), [development](docs/development.md), [security](SECURITY.md), and [contributing](CONTRIBUTING.md).

The repository remains private. No license has been selected. Public visibility alone would not grant permission to reuse, modify, or redistribute the code.
