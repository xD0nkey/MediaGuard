import json
from dataclasses import dataclass
from pathlib import Path
from .attachments import DEFAULT_MAX_ATTACHMENT_BYTES
from .paths import project_root


@dataclass(frozen=True)
class Config:
    discord_enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    max_attachment_bytes: int = DEFAULT_MAX_ATTACHMENT_BYTES


def load(root: Path | None = None) -> Config:
    path = (root or project_root()) / "config.json"
    if not path.exists():
        return Config()
    data = json.loads(path.read_text(encoding="utf-8"))
    discord = data.get("discord", {})
    operator = data.get("operator", {})
    host = operator.get("host", "127.0.0.1")
    if host not in ("127.0.0.1", "::1", "localhost"):
        raise ValueError("Operator API must bind to loopback")
    port = int(operator.get("port", 8765))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid operator port")
    max_attachment_bytes = int(discord.get("max_attachment_bytes", DEFAULT_MAX_ATTACHMENT_BYTES))
    if not 1 <= max_attachment_bytes <= 100 * 1024 * 1024:
        raise ValueError("Invalid attachment inspection size limit")
    return Config(bool(discord.get("enabled", False)), host, port, max_attachment_bytes)
