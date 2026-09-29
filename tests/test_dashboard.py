import asyncio
import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient

from mediaguard.api import create_app
from mediaguard.config import Config
from mediaguard.database import Database, MIGRATIONS
from mediaguard.runtime import Runtime
from test_enforcement import Channel, Message, handle
from test_inspection import MP3, attachment


GUILDS = [
    {"id": "1", "name": "One", "channels": [
        {"id": "11", "name": "general", "can_protect": True, "can_notify": True},
        {"id": "12", "name": "uploads", "can_protect": True, "can_notify": False},
        {"id": "13", "name": "notice", "can_protect": False, "can_notify": True},
    ], "roles": [{"id": "70", "name": "Moderators"}, {"id": "71", "name": "DJs"}]},
    {"id": "2", "name": "Two", "channels": [
        {"id": "21", "name": "other", "can_protect": True, "can_notify": True},
    ], "roles": [{"id": "72", "name": "Elsewhere"}]},
]


def runtime(tmp_path, config=None):
    app = Runtime(config or Config(), tmp_path)
    app.start()
    app.discord.inventory = lambda: GUILDS
    return app


def payload(**changes):
    data = {"guild_id": "1", "enabled": True, "channel_ids": [],
            "notifications_enabled": False, "detection_channel_id": None, "exempt_role_ids": [],
            "unresolved_action": "allow"}
    data.update(changes)
    return data


def save(client, data):
    return client.post("/api/protection", json=data,
                       headers={"x-mediaguard-action": "save-protection"})


def test_inventory_uses_existing_guild_and_channel_permissions(tmp_path):
    app = runtime(tmp_path)
    channels = [
        SimpleNamespace(id=11, name="general", permissions_for=lambda _: SimpleNamespace(
            view_channel=True, manage_messages=True, send_messages=True)),
        SimpleNamespace(id=12, name="hidden", permissions_for=lambda _: SimpleNamespace(
            view_channel=False, manage_messages=True, send_messages=True)),
    ]
    forum = SimpleNamespace(id=14, name="clips", permissions_for=lambda _: SimpleNamespace(
        view_channel=True, manage_messages=True, send_messages=True))
    roles = [
        SimpleNamespace(id=1, name="@everyone", managed=False, is_default=lambda: True),
        SimpleNamespace(id=70, name="Moderators", managed=False, is_default=lambda: False),
        SimpleNamespace(id=73, name="Bot integration", managed=True, is_default=lambda: False),
    ]
    guild = SimpleNamespace(id=1, name="One", me=object(), text_channels=channels, forums=[forum], roles=roles)
    result = asyncio.run(app.discord._inventory(SimpleNamespace(guilds=[guild])))
    assert result[0]["channels"][0]["can_protect"]
    assert result[0]["channels"][0]["can_notify"]
    assert not result[0]["channels"][1]["can_protect"]
    assert not result[0]["channels"][1]["can_notify"]
    assert result[0]["channels"][2] == {"id": "14", "name": "clips", "can_protect": True, "can_notify": False}
    assert result[0]["roles"] == [{"id": "70", "name": "Moderators"}]


def test_protection_save_reload_and_guild_scope(tmp_path):
    app = runtime(tmp_path)
    with TestClient(create_app(app)) as client:
        assert client.get("/api/guilds").json() == GUILDS
        assert client.get("/api/protection", params={"guild_id": "1"}).json()["enabled"] is False
        assert save(client, payload(channel_ids=["11", "12"])).status_code == 200
        first = client.get("/api/protection", params={"guild_id": "1"}).json()
        assert first["enabled"] is True
        assert first["channel_ids"] == ["11", "12"]
        assert client.get("/api/protection", params={"guild_id": "2"}).json()["enabled"] is False
        assert save(client, payload(enabled=False, channel_ids=[])).json()["channel_ids"] == []
        assert save(client, payload(enabled=True, notifications_enabled=True,
                                    detection_channel_id="13")).json()["detection_channel_id"] == "13"
    restarted = runtime(tmp_path)
    with TestClient(create_app(restarted)) as client:
        saved = client.get("/api/protection", params={"guild_id": "1"}).json()
        assert saved["enabled"] is True
        assert saved["channel_ids"] == []
        assert saved["notifications_enabled"] is True
        assert saved["detection_channel_id"] == "13"
    assert app.database.protection_for(2, app.config)["enabled"] is False


def test_protection_rejects_unknown_cross_guild_and_inaccessible_ids(tmp_path):
    app = runtime(tmp_path)
    with TestClient(create_app(app)) as client:
        for data in (
            payload(guild_id="3"),
            payload(channel_ids=["21"]),
            payload(channel_ids=["13"]),
            payload(channel_ids=["abc"]),
            payload(channel_ids=["11", "11"]),
            payload(detection_channel_id="21"),
            payload(detection_channel_id="12"),
            payload(notifications_enabled=True),
            payload(enabled="true"),
            payload(guild_id=1),
        ):
            assert save(client, data).status_code == 422
        assert client.get("/api/protection", params={"guild_id": "1"}).json()["enabled"] is False
        assert save(client, payload(enabled=True, notifications_enabled=False,
                                    detection_channel_id=None)).status_code == 200
        assert client.post("/api/protection", json=payload()).status_code == 403
        assert save(client, {**payload(), "token": "synthetic"}).status_code == 422
        assert client.get("/api/protection", params={"guild_id": "999"}).status_code == 404


def test_detection_history_route_and_table_are_absent_on_new_install(tmp_path):
    app = runtime(tmp_path)
    with TestClient(create_app(app)) as client:
        assert client.get("/api/detections").status_code == 404
        assert "detections" not in client.get("/api/status").json()
    web_dist = tmp_path / "web" / "dist"
    (web_dist / "assets").mkdir(parents=True)
    (web_dist / "index.html").write_text("dashboard", encoding="utf-8")
    with TestClient(create_app(app, web_dist)) as client:
        assert client.get("/api/detections").status_code == 404
    with app.database.connect() as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert names == {"schema_migrations", "guild_protection", "blocked_embed_phrases"}


def test_legacy_global_config_is_default_until_guild_override(tmp_path):
    app = runtime(tmp_path, Config(protection_enabled=True,
                                  protected_channel_ids=(11,), notifications_enabled=False))
    with TestClient(create_app(app)) as client:
        assert client.get("/api/protection", params={"guild_id": "1"}).json()["channel_ids"] == ["11"]
        assert save(client, payload(enabled=False)).status_code == 200
        assert client.get("/api/protection", params={"guild_id": "1"}).json()["enabled"] is False
        assert client.get("/api/protection", params={"guild_id": "2"}).json()["enabled"] is True


def test_saved_channel_scope_controls_enforcement_after_restart(tmp_path):
    app = runtime(tmp_path)
    with TestClient(create_app(app)) as client:
        assert save(client, payload(channel_ids=["11"])).status_code == 200
    restarted = runtime(tmp_path)

    async def fetch(item):
        return item.content

    restarted.discord.fetch_prefix = fetch
    skipped = Message(attachment("song.mp3", MP3), channel=Channel(12), message_id=31)
    matched = Message(attachment("song.mp3", MP3), channel=Channel(11), message_id=32)
    other_guild = Message(attachment("song.mp3", MP3), channel=Channel(11), message_id=33)
    other_guild.guild.id = 2

    assert handle(restarted, skipped) == ()
    assert skipped.deletes == 0
    assert handle(restarted, matched)[0].media_type == "mp3"
    assert matched.deletes == 1
    handle(restarted, other_guild)
    assert other_guild.deletes == 0
    with restarted.database.connect() as connection:
        assert connection.execute("SELECT count(*) FROM guild_protection").fetchone()[0] == 1


def test_rejects_oversized_discord_id_and_cross_origin_write(tmp_path):
    app = runtime(tmp_path)
    with TestClient(create_app(app)) as client:
        assert save(client, payload(guild_id="9" * 5000)).status_code == 422
        response = client.post(
            "/api/protection", json=payload(),
            headers={"x-mediaguard-action": "save-protection", "origin": "http://127.0.0.1:9000"},
        )
        assert response.status_code == 403


def test_existing_history_is_left_untouched_during_config_migration(tmp_path):
    path = tmp_path / "runtime" / "mediaguard.sqlite3"
    path.parent.mkdir()
    with sqlite3.connect(path) as connection:
        connection.execute(MIGRATIONS[0][1])
        connection.execute("CREATE TABLE enforcement_events (message_id TEXT PRIMARY KEY, original_filename TEXT)")
        connection.executemany(
            "INSERT INTO schema_migrations VALUES (?, datetime('now'))", [(1,), (2,)]
        )
        connection.execute("INSERT INTO enforcement_events VALUES ('30', 'legacy.mp3')")

    database = Database(path)
    database.migrate()
    database.migrate()
    with database.connect() as connection:
        assert connection.execute("SELECT * FROM enforcement_events").fetchall() == [("30", "legacy.mp3")]
    database.save_protection(1, True, [11], False, None)
    assert database.protection_for(1, Config())["channel_ids"] == (11,)

    app = Runtime(Config(protection_enabled=True), tmp_path)
    app.start()

    async def fetch(item):
        return item.content

    app.discord.fetch_prefix = fetch
    message = Message(attachment("new.mp3", MP3), channel=Channel(11), message_id=31)
    handle(app, message)
    assert message.deletes == 1
    with database.connect() as connection:
        assert connection.execute("SELECT * FROM enforcement_events").fetchall() == [("30", "legacy.mp3")]


def test_exempt_roles_are_saved_and_validated(tmp_path):
    app = runtime(tmp_path)
    with TestClient(create_app(app)) as client:
        for roles in (["72"], ["999"], ["70", "70"], ["abc"], "70", [str(n) for n in range(100, 151)]):
            assert save(client, payload(exempt_role_ids=roles)).status_code == 422
        assert client.get("/api/protection", params={"guild_id": "1"}).json()["exempt_role_ids"] == []
        assert save(client, payload(exempt_role_ids=["70", "71"])).json()["exempt_role_ids"] == ["70", "71"]
    assert runtime(tmp_path).database.protection_for(1, Config())["exempt_role_ids"] == (70, 71)


def test_unresolved_action_is_saved_and_validated(tmp_path):
    app = runtime(tmp_path)
    with TestClient(create_app(app)) as client:
        assert client.get("/api/protection", params={"guild_id": "1"}).json()["unresolved_action"] == "allow"
        for action in ("delete", "REPORT", "", None, True, ["report"]):
            assert save(client, payload(unresolved_action=action)).status_code == 422
        missing = payload()
        del missing["unresolved_action"]
        assert save(client, missing).status_code == 422
        assert save(client, payload(unresolved_action="report")).json()["unresolved_action"] == "report"
    assert runtime(tmp_path).database.protection_for(1, Config())["unresolved_action"] == "report"


def test_unresolved_action_migration_defaults_existing_rows_to_allow(tmp_path):
    path = tmp_path / "runtime" / "mediaguard.sqlite3"
    database = Database(path)
    with database.connect() as connection:
        connection.execute(MIGRATIONS[0][1])
        for version, sql in MIGRATIONS[1:-1]:
            connection.execute(sql)
            connection.execute("INSERT INTO schema_migrations VALUES (?, datetime('now'))", (version,))
        connection.execute("INSERT INTO guild_protection (guild_id, enabled, channel_ids, notifications_enabled, "
                           "detection_channel_id, updated_at) VALUES ('1', 1, '[]', 0, NULL, 'x')")
    database.migrate()
    assert database.protection_for(1, Config())["unresolved_action"] == "allow"
