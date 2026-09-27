import sqlite3
from pathlib import Path
from .paths import database_path


MIGRATIONS = [
    (1, "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"),
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
