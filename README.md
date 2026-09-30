# MediaGuard

MediaGuard is a Discord moderation bot that watches protected channels and detects configured prohibited content. It can report matches without deleting messages or automatically delete them. A local dashboard and Discord admin commands control protection and moderator notifications.

## Detection

- Direct and forwarded audio attachments are checked by file signature, not just filename. Supported formats are MP3, WAV, FLAC, Ogg Opus, Ogg Vorbis, and M4A.
- Enabled blocked phrases are matched in Discord embed titles, descriptions, and field values, including embeds posted by other bots. Matching is case-insensitive. MediaGuard does not fetch linked pages or call music services.

## Moderation flow

Detect → apply the selected moderation mode → notify → clean up → forget. **Warn / Log Only** reports confirmed matches to the Detection channel and leaves the original message in place. **Auto Delete** deletes qualifying messages and can notify moderators after Discord confirms deletion. MediaGuard does not write new moderation-event history or retain attachment copies. Protection settings and blocked phrases remain saved locally.

## Discord admin commands

Commands are available in servers to members with **Manage Server** permission. MediaGuard checks this permission when each command runs, and replies privately. Commands use the same saved guild settings as the dashboard. Restart the bot after updating MediaGuard so it can register the commands.

| Command | What it does |
| --- | --- |
| `/protection status` | Shows the current protection, channel, notification, exemption, moderation-mode, and blocked-phrase settings. |
| `/protection enable` | Turns on message protection. |
| `/protection disable` | Turns off message protection. |
| `/protection-channels all` | Protects all relevant channels the bot can access. |
| `/protection-channels add <channel>` | Selects a text or forum channel for protection. |
| `/protection-channels remove <channel>` | Removes a selected channel. The last selected channel cannot be removed because an empty selection means all relevant channels. |
| `/protection-channels list` | Shows the selected channels or the all-channels setting. |
| `/exempt-role add <role>` | Exempts a role from audio enforcement; blocked embed phrases still apply. |
| `/exempt-role remove <role>` | Removes an audio exemption. |
| `/exempt-role list` | Shows audio-exempt roles. |
| `/moderation-mode warn-only` | Reports confirmed matches without deleting the original message. Detection notifications must be enabled while protection is on. |
| `/moderation-mode auto-delete` | Requests Auto Delete. A private confirmation is required before the mode changes. |
| `/detection-notifications enable` | Turns on Detection channel reports; a Detection channel must be set first. |
| `/detection-notifications disable` | Turns off reports and clears the Detection channel, unless active Warn / Log Only protection requires reports. |
| `/detection-channel set <channel>` | Chooses a text channel where the bot can send Detection reports. |
| `/detection-channel clear` | Clears the channel when notifications are off. |
| `/unconfirmed allow` | Allows inconclusive audio without a Detection report. |
| `/unconfirmed report` | Reports inconclusive audio to the Detection channel when notifications are enabled. Inconclusive audio is never deleted. |
| `/blocked-phrase add <phrase>` | Adds and enables a phrase matched against Discord embed text. |
| `/blocked-phrase remove <phrase>` | Removes an existing blocked phrase. |
| `/blocked-phrase enable <phrase>` | Enables an existing blocked phrase. |
| `/blocked-phrase disable <phrase>` | Disables an existing blocked phrase without removing it. |
| `/blocked-phrase list` | Shows the configured phrases and whether each is enabled. |

Role and channel options use Discord's native picker. To edit a blocked phrase or its display name, use the dashboard.

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
