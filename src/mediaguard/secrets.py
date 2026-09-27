import os
from pathlib import Path
from .paths import project_root


def discord_token(root: Path | None = None) -> str | None:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if token:
        return token
    path = (root or project_root()) / "secrets.env"
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("DISCORD_BOT_TOKEN="):
            return line.partition("=")[2].strip().strip('"') or None
    return None
