import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from .paths import database_path


MIGRATIONS = [
    (1, "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"),
    (6, """CREATE TABLE guild_protection (
        guild_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL,
        channel_ids TEXT NOT NULL, notifications_enabled INTEGER NOT NULL,
        detection_channel_id TEXT, updated_at TEXT NOT NULL
    )"""),
    (7, """CREATE TABLE blocked_embed_phrases (
        rule_id TEXT PRIMARY KEY, guild_id TEXT NOT NULL, name TEXT NOT NULL,
        phrase TEXT NOT NULL, normalized_phrase TEXT NOT NULL, enabled INTEGER NOT NULL,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(guild_id, normalized_phrase)
    )"""),
    (8, "ALTER TABLE guild_protection ADD COLUMN exempt_role_ids TEXT NOT NULL DEFAULT '[]'"),
    (9, "ALTER TABLE guild_protection ADD COLUMN unresolved_action TEXT NOT NULL DEFAULT 'allow'"),
    (10, "ALTER TABLE guild_protection ADD COLUMN moderation_mode TEXT NOT NULL DEFAULT 'auto_delete'"),
]


class Database:
    def __init__(self, path: Path | None = None):
        self.path = path or database_path()
        self.mutation_lock = threading.RLock()

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
            columns = {row[1] for row in connection.execute("PRAGMA table_info(guild_protection)")}
            for version, column in ((8, "exempt_role_ids"), (9, "unresolved_action"), (10, "moderation_mode")):
                if column not in columns:
                    connection.execute(next(sql for migration, sql in MIGRATIONS if migration == version))

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
                "SELECT enabled, channel_ids, notifications_enabled, detection_channel_id, exempt_role_ids, "
                "unresolved_action, moderation_mode FROM guild_protection WHERE guild_id=?",
                (str(guild_id),),
            ).fetchone()
        if row:
            return {"enabled": bool(row[0]), "channel_ids": tuple(json.loads(row[1])),
                    "notifications_enabled": bool(row[2]),
                    "detection_channel_id": int(row[3]) if row[3] else None,
                    "exempt_role_ids": tuple(json.loads(row[4])), "unresolved_action": row[5],
                    "moderation_mode": row[6]}
        return {"enabled": config.protection_enabled, "channel_ids": config.protected_channel_ids,
                "notifications_enabled": config.notifications_enabled,
                "detection_channel_id": config.detection_channel_id, "exempt_role_ids": (),
                "unresolved_action": "allow", "moderation_mode": config.moderation_mode}

    def save_protection(self, guild_id, enabled, channel_ids, notifications_enabled, detection_channel_id,
                        exempt_role_ids=(), unresolved_action="allow", moderation_mode="auto_delete"):
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO guild_protection
                (guild_id, enabled, channel_ids, notifications_enabled, detection_channel_id,
                exempt_role_ids, unresolved_action, moderation_mode, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled,
                channel_ids=excluded.channel_ids, notifications_enabled=excluded.notifications_enabled,
                detection_channel_id=excluded.detection_channel_id,
                exempt_role_ids=excluded.exempt_role_ids, unresolved_action=excluded.unresolved_action,
                moderation_mode=excluded.moderation_mode,
                updated_at=excluded.updated_at""",
                (str(guild_id), int(enabled), json.dumps(channel_ids), int(notifications_enabled),
                 str(detection_channel_id) if detection_channel_id else None, json.dumps(list(exempt_role_ids)),
                 unresolved_action, moderation_mode,
                 datetime.now(timezone.utc).isoformat()),
            )

    def embed_rules(self, guild_id, *, enabled_only=False):
        with self.connect() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM blocked_embed_phrases WHERE guild_id=? "
                + ("AND enabled=1 " if enabled_only else "")
                + "ORDER BY created_at, rule_id", (str(guild_id),),
            ).fetchall()
            return [dict(row) for row in rows]

    def create_embed_rule(self, guild_id, rule_id, name, phrase, normalized_phrase, enabled):
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            if connection.execute("SELECT count(*) FROM blocked_embed_phrases WHERE guild_id=?",
                                  (str(guild_id),)).fetchone()[0] >= 50:
                raise ValueError("Rule limit reached")
            connection.execute(
                """INSERT INTO blocked_embed_phrases
                (rule_id, guild_id, name, phrase, normalized_phrase, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (rule_id, str(guild_id), name, phrase, normalized_phrase, int(enabled), now, now),
            )

    def update_embed_rule(self, guild_id, rule_id, name, phrase, normalized_phrase, enabled):
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE blocked_embed_phrases SET name=?, phrase=?, normalized_phrase=?,
                enabled=?, updated_at=? WHERE guild_id=? AND rule_id=?""",
                (name, phrase, normalized_phrase, int(enabled), datetime.now(timezone.utc).isoformat(),
                 str(guild_id), rule_id),
            )
            return cursor.rowcount == 1

    def delete_embed_rule(self, guild_id, rule_id):
        with self.connect() as connection:
            return connection.execute(
                "DELETE FROM blocked_embed_phrases WHERE guild_id=? AND rule_id=?",
                (str(guild_id), rule_id),
            ).rowcount == 1

    def set_embed_rule_enabled(self, guild_id, rule_id, enabled):
        with self.connect() as connection:
            return connection.execute(
                "UPDATE blocked_embed_phrases SET enabled=?, updated_at=? WHERE guild_id=? AND rule_id=?",
                (int(enabled), datetime.now(timezone.utc).isoformat(), str(guild_id), rule_id),
            ).rowcount == 1
