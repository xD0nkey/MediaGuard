import time
from pathlib import Path
from .activity import Activity
from .config import Config
from .database import Database
from .discord_service import DiscordService
from .paths import database_path
from .secrets import discord_token


class Runtime:
    def __init__(self, config: Config | None = None, root: Path | None = None, discord=None):
        self.config = config or Config()
        self.root = root
        self.activity = Activity()
        self.database = Database(database_path(root))
        self.discord = discord or DiscordService(self.activity, max_attachment_bytes=self.config.max_attachment_bytes,
                                                 config=self.config, database=self.database)
        self.started_at = None

    def start(self):
        self.database.migrate()
        self.started_at = time.monotonic()
        self.activity.record("System", "runtime_started")
        if self.config.discord_enabled:
            self.discord.start(discord_token(self.root))

    def stop(self):
        self.discord.stop()
        self.activity.record("System", "runtime_stopped")

    def snapshot(self):
        return {"app": "MediaGuard", "uptime_seconds": int(time.monotonic() - self.started_at) if self.started_at else 0,
                "database": self.database.status(), "discord": self.discord.snapshot(),
                "services": [{"name": "Operator backend", "state": "running" if self.started_at else "stopped"}]}
