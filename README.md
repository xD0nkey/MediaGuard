# MediaGuard

MediaGuard is an independent Discord moderation project. It aims to inspect media entering a server, apply explainable rules, and support moderators with auditable cases. This repository currently contains **bootstrap infrastructure only**. It does not inspect messages, remove content, create cases, or register moderation commands.

## Implemented

- Discord client lifecycle with reconnect support and safe local status reporting.
- SQLite database ownership and an idempotent migration mechanism. Only the migration ledger exists today.
- A read-only local FastAPI operator API and a responsive React dashboard showing real runtime status and Activity.
- Fake-client tests that do not contact Discord.

## Planned

The [concept document](docs/MediaGuard_concept.md) describes attachment and forward inspection, deterministic rules, enforcement, moderator cases, Last.fm handling, and link inspection. [Architecture](docs/architecture.md) identifies the intended boundaries; these are not implemented features.

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

Open `http://127.0.0.1:8765`. The bot is disabled by default; the dashboard and tests need no credential. For a future dedicated bot connection, copy `config.example.json` to ignored `config.json`, set `discord.enabled` to `true`, copy `secrets.example.env` to ignored `secrets.env`, and set the **MediaGuard-only** bot token. In the Discord developer portal, enable the Message Content Intent for that application. The current bot still performs no moderation.

## Configuration and data

Safe defaults live in source code and `config.example.json`. Local operator configuration belongs in ignored `config.json`. Credentials belong in ignored `secrets.env` or the `DISCORD_BOT_TOKEN` environment variable. Mutable SQLite state lives in ignored `runtime/`. Never commit real guild IDs, messages, cases, notes, or tokens.

The API binds to loopback and serves read-only status and activity. It is not designed for remote access. The Activity feed contains fixed service codes, not Discord message content. See [development](docs/development.md), [security](SECURITY.md), and [contributing](CONTRIBUTING.md).

## Testing and limitations

Run `pytest` and `cd web && npm run build`. CI runs both with synthetic configuration and no Discord token. Before pushing, review staged paths and run a secret scan; GitHub secret scanning may depend on repository/account settings and should not be assumed active. No license has been selected yet. Public visibility alone does not grant permission to reuse, modify, or redistribute this code.
