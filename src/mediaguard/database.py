import sqlite3
from datetime import datetime, timezone
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

    def reserve_enforcement(self, message, result, mode):
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO enforcement_events
                (message_id, at, guild_id, channel_id, author_id, media_type, source, original_filename, mode, deletion, notification)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'not_attempted', 'not_attempted')""",
                (str(message.id), datetime.now(timezone.utc).isoformat(), str(message.guild.id),
                 str(message.channel.id), str(message.author.id), result.media_type, result.source,
                 result.filename[:255] if result.filename else None, mode),
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
