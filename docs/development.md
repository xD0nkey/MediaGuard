# Development

Run `pip install -e ".[test]"`, then `pytest`. Frontend: `cd web`, `npm ci`, `npm run build`. Start the backend with `mediaguard`; for Vite development, run `npm run dev` in `web/` and keep the backend on port 8765.

`config.json` is a local file with `discord.enabled`, `operator.host`, and `operator.port`. The host must be loopback. `secrets.env` or the `DISCORD_BOT_TOKEN` environment variable may supply MediaGuard's own token. Missing token leaves Discord unconfigured while the dashboard still works. SQLite is created at `runtime/mediaguard.sqlite3`; no other project's paths are read.

Tests inject a fake Discord client and never connect to Discord. Do not use production tokens or databases in tests. Build and test before enabling a real connection. The current bot has no listener and performs no moderation.
