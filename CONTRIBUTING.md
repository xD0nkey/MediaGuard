# Contributing

Install Python 3.11+ and Node.js 20+, then run `pip install -e ".[test]"`, `pytest`, `cd web && npm ci && npm run build`. Keep changes small and readable. Run `npm run format:check` for the frontend and keep TypeScript type checking clean. Python has no formatter configured yet; follow the surrounding code.

Pull requests should explain the behavior, tests, and any privacy impact. New moderation behavior must be deterministic and testable with synthetic Discord data. Never commit credentials, real Discord identifiers, message contents, private notes, databases, or other runtime state. Check `git diff --cached` and scan staged files for secrets before pushing.
