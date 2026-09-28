import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .paths import database_path


MIGRATIONS = [
    (1, "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"),
    (2, """CREATE TABLE enforcement_events (
        message_id TEXT PRIMARY KEY, at TEXT NOT NULL, guild_id TEXT NOT NULL,
        channel_id TEXT NOT NULL, author_id TEXT NOT NULL, media_type TEXT NOT NULL,
        source TEXT NOT NULL, original_filename TEXT, mode TEXT NOT NULL,
        deletion TEXT NOT NULL, deleted_at TEXT, notification TEXT NOT NULL
    )"""),
    (3, "ALTER TABLE enforcement_events ADD COLUMN author_name TEXT"),
    (4, "ALTER TABLE enforcement_events ADD COLUMN channel_name TEXT"),
    (5, "ALTER TABLE enforcement_events ADD COLUMN guild_name TEXT"),
    (6, """CREATE TABLE guild_protection (
        guild_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL,
        channel_ids TEXT NOT NULL, notifications_enabled INTEGER NOT NULL,
        detection_channel_id TEXT, updated_at TEXT NOT NULL
    )"""),
]


class Database:
    def __init__(self, path: Path | None = None):
        self.path = path or database_path()

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def migrate(self):
        with self.connect() as connection:
            connection.execute(MIGRATIONS[0][1])
            for version, sql in MIGRATIONS:
                exists = connection.execute("SELECT 1 FROM schema_migrations WHERE version=?", (version,)).fetchone()
                if not exists:
                    connection.execute(sql)
                    connection.execute("INSERT INTO schema_migrations VALUES (?, datetime('now'))", (version,))

    def status(self):
        try:
            with self.connect() as connection:
                connection.execute("SELECT 1 FROM schema_migrations LIMIT 1").fetchone()
            return "ready"
        except sqlite3.Error:
            return "error"

    def protection_for(self, guild_id, config):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT enabled, channel_ids, notifications_enabled, detection_channel_id FROM guild_protection WHERE guild_id=?",
                (str(guild_id),),
            ).fetchone()
        if row:
            return {"enabled": bool(row[0]), "channel_ids": tuple(json.loads(row[1])),
                    "notifications_enabled": bool(row[2]),
                    "detection_channel_id": int(row[3]) if row[3] else None}
        return {"enabled": config.protection_enabled, "channel_ids": config.protected_channel_ids,
                "notifications_enabled": config.notifications_enabled,
                "detection_channel_id": config.detection_channel_id}

    def save_protection(self, guild_id, enabled, channel_ids, notifications_enabled, detection_channel_id):
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO guild_protection
                (guild_id, enabled, channel_ids, notifications_enabled, detection_channel_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled,
                channel_ids=excluded.channel_ids, notifications_enabled=excluded.notifications_enabled,
                detection_channel_id=excluded.detection_channel_id, updated_at=excluded.updated_at""",
                (str(guild_id), int(enabled), json.dumps(channel_ids), int(notifications_enabled),
                 str(detection_channel_id) if detection_channel_id else None,
                 datetime.now(timezone.utc).isoformat()),
            )

    def prune_enforcements(self, retention_days):
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        with self.connect() as connection:
            return connection.execute("DELETE FROM enforcement_events WHERE at < ?", (cutoff,)).rowcount

    def enforcement_summary(self):
        with self.connect() as connection:
            count, recent = connection.execute(
                "SELECT count(*), max(at) FROM enforcement_events WHERE deletion='succeeded'"
            ).fetchone()
            return {"audio_blocked": count, "recent_detection_at": recent}

    def reserve_enforcement(self, message, result, mode):
        author_name = getattr(message.author, "display_name", None)
        channel_name = getattr(message.channel, "name", None)
        guild_name = getattr(message.guild, "name", None)
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO enforcement_events
                (message_id, at, guild_id, channel_id, author_id, media_type, source, original_filename,
                 mode, deletion, notification, author_name, channel_name, guild_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'not_attempted', 'not_attempted', ?, ?, ?)""",
                (str(message.id), datetime.now(timezone.utc).isoformat(), str(message.guild.id),
                 str(message.channel.id), str(message.author.id), result.media_type, result.source,
                 result.filename[:255] if result.filename else None, mode,
                 author_name[:100] if author_name else None,
                 channel_name[:100] if channel_name else None,
                 guild_name[:100] if guild_name else None),
            )
            return cursor.rowcount == 1

    def set_outcome(self, message_id, *, deletion=None, notification=None):
        field, value = ("deletion", deletion) if deletion is not None else ("notification", notification)
        deleted_at = datetime.now(timezone.utc) if deletion == "succeeded" else None
        with self.connect() as connection:
            if deleted_at:
                connection.execute("UPDATE enforcement_events SET deletion=?, deleted_at=? WHERE message_id=?",
                                   (value, deleted_at.isoformat(), str(message_id)))
            else:
                connection.execute(f"UPDATE enforcement_events SET {field}=? WHERE message_id=?", (value, str(message_id)))
        return deleted_at

    def recent_enforcements(self, limit=50):
        with self.connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM enforcement_events ORDER BY at DESC, rowid DESC LIMIT ?",
                (max(0, min(limit, 200)),),
            ).fetchall()
            return [dict(row) for row in rows]
