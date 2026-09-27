# Development

Install with `pip install -e ".[test]"` and run `py -3 -m pytest -q`. In `web/`, run `npm ci`, `npm run format:check`, and `npm run build`. Start the backend with `mediaguard`. For Vite development, run `npm run dev` in `web/` while the backend runs on port 8765.

Local, ignored `config.json` contains `discord.enabled`, `discord.max_attachment_bytes`, `operator.host`, `operator.port`, and the `protection` settings shown in `config.example.json`. The operator host must bind to loopback. The attachment size limit defaults to 25 MiB and accepts 1 byte to 100 MiB. The inspector reads at most 4 KiB. The bot token belongs in ignored `secrets.env` or `DISCORD_BOT_TOKEN`. Missing token leaves the Discord service unconfigured while the dashboard works. Configuration is loaded at startup; restart after editing it.

Tests inject a fake Discord client, attachment downloader, and message/channel objects. They do not contact Discord, read a real token, or use a production database. The service inspects direct attachments and forwarded snapshots exposed by Discord. A matching message is deleted once. If Detection notifications are enabled, one embed is sent after confirmed deletion. Unresolved inspection never triggers deletion. Audit rows under ignored `runtime/` record metadata and outcomes only, without message or attachment bodies, URLs, or links.
