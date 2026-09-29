# MediaGuard

MediaGuard is a Discord moderation bot that watches protected channels, detects configured prohibited content, and deletes the containing message. A local dashboard controls protection and moderator notifications.

## Detection

- Direct and forwarded audio attachments are checked by file signature, not just filename. Supported formats are MP3, WAV, FLAC, Ogg Opus, Ogg Vorbis, and M4A.
- Enabled blocked phrases are matched in Discord embed titles, descriptions, and field values, including embeds posted by other bots. Matching is case-insensitive. MediaGuard does not fetch linked pages or call music services.

## Moderation flow

Detect → delete → notify → clean up → forget. After Discord confirms deletion, MediaGuard can post a Detection notification in the configured moderator channel. That channel is the moderator-facing audit trail. MediaGuard does not write new moderation-event history or retain attachment copies. Protection settings and blocked phrases remain saved locally.

## Setup and running

Use Python 3.11+ and Node.js 20+ for the one-time frontend build. Create a Discord bot, enable **Message Content Intent** in the Developer Portal, and grant **View Channel** and **Manage Messages** in protected channels. If notifications are enabled, also grant **View Channel** and **Send Messages** in the Detection channel.

On Windows, from the repository folder:

```bat
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[test]"
cd web
npm ci
npm run build
cd ..
copy config.example.json config.json
copy secrets.example.env secrets.env
```

Set `discord.enabled` to `true` in `config.json`. Put the bot token in ignored `secrets.env` as `DISCORD_BOT_TOKEN=...`, or set that environment variable locally. Never commit the token. Double-click `start.bat`, then open `http://127.0.0.1:8765`. Use the Protection section to enable each guild and select channels. Stop the bot with Ctrl+C or by closing its console.

The batch file uses `.venv` when present, checks required setup, and starts the Discord bot and dashboard in one process. It does not install dependencies or rebuild the frontend. For manual startup, run `.venv\Scripts\python.exe -m mediaguard.main`.

## Development

Run backend tests with `.venv\Scripts\python.exe -m pytest -q`. Run `npm run format:check` and `npm run build` in `web/`.
