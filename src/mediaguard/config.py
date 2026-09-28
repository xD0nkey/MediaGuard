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
    protection_enabled: bool = False
    protected_channel_ids: tuple[int, ...] = ()
    notifications_enabled: bool = False
    detection_channel_id: int | None = None
    detection_retention_days: int = 90


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
    protection = data.get("protection", {})
    enabled = protection.get("enabled", False)
    channels = protection.get("channel_ids", [])
    notifications = protection.get("notifications_enabled", False)
    detection_channel = protection.get("detection_channel_id")
    if not isinstance(enabled, bool) or not isinstance(notifications, bool):
        raise ValueError("Invalid protection configuration")
    if not isinstance(channels, list) or any(type(value) is not int or value <= 0 for value in channels):
        raise ValueError("Invalid protected channel IDs")
    if detection_channel is not None and (type(detection_channel) is not int or detection_channel <= 0):
        raise ValueError("Invalid detection channel ID")
    retention_days = data.get("detection_retention_days", 90)
    if type(retention_days) is not int or not 1 <= retention_days <= 3650:
        raise ValueError("Invalid detection retention period")
    return Config(bool(discord.get("enabled", False)), host, port, max_attachment_bytes,
                  enabled, tuple(channels), notifications, detection_channel, retention_days)
