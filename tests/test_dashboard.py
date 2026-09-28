import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from mediaguard.api import create_app
from mediaguard.attachments import InspectionResult, Status
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
    ]},
    {"id": "2", "name": "Two", "channels": [
        {"id": "21", "name": "other", "can_protect": True, "can_notify": True},
    ]},
]


def runtime(tmp_path, config=None):
    app = Runtime(config or Config(), tmp_path)
    app.start()
    app.discord.inventory = lambda: GUILDS
    return app


def payload(**changes):
    data = {"guild_id": "1", "enabled": True, "channel_ids": [],
            "notifications_enabled": False, "detection_channel_id": None}
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
    guild = SimpleNamespace(id=1, name="One", me=object(), text_channels=channels)
    result = asyncio.run(app.discord._inventory(SimpleNamespace(guilds=[guild])))
    assert result[0]["channels"][0]["can_protect"]
    assert result[0]["channels"][0]["can_notify"]
    assert not result[0]["channels"][1]["can_protect"]
    assert not result[0]["channels"][1]["can_notify"]


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


def test_detection_history_and_retention_stay_metadata_only(tmp_path):
    app = runtime(tmp_path, Config(detection_retention_days=90))
    app.database.save_protection(1, True, [11], False, None)
    message = SimpleNamespace(
        id=30, guild=SimpleNamespace(id=1, name="One"),
        channel=SimpleNamespace(id=11, name="general"),
        author=SimpleNamespace(id=10, display_name="Listener"),
        content="private message body",
    )
    result = InspectionResult(Status.MATCH, "audio_signature", "forward",
                              filename="sample.mp3", media_type="mp3")
    assert app.database.reserve_enforcement(message, result, "DELETE")
    deleted_at = app.database.set_outcome(30, deletion="succeeded")
    app.database.set_outcome(30, notification="failed")
    with TestClient(create_app(app)) as client:
        response = client.get("/api/detections")
        record = response.json()[0]
        assert record["author_name"] == "Listener"
        assert record["author_id"] == "10"
        assert record["channel_name"] == "general"
        assert record["guild_name"] == "One"
        assert record["source"] == "forward"
        assert record["deleted_at"] == deleted_at.isoformat()
        assert record["deletion"] == "succeeded"
        assert record["notification"] == "failed"
        assert "private message body" not in response.text
        assert "cdn.discordapp.com" not in response.text
        assert "https://" not in response.text
        assert "base64" not in response.text
    with app.database.connect() as connection:
        connection.execute("UPDATE enforcement_events SET at=? WHERE message_id='30'",
                           ((datetime.now(timezone.utc) - timedelta(days=91)).isoformat(),))
    assert app.database.prune_enforcements(90) == 1
    assert app.database.recent_enforcements() == []
    assert app.database.protection_for(1, app.config)["enabled"] is True


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
    assert [row["message_id"] for row in restarted.database.recent_enforcements()] == ["32"]


def test_rejects_oversized_discord_id_and_cross_origin_write(tmp_path):
    app = runtime(tmp_path)
    with TestClient(create_app(app)) as client:
        assert save(client, payload(guild_id="9" * 5000)).status_code == 422
        response = client.post(
            "/api/protection", json=payload(),
            headers={"x-mediaguard-action": "save-protection", "origin": "http://127.0.0.1:9000"},
        )
        assert response.status_code == 403


def test_existing_phase_1b_audit_survives_migration(tmp_path):
    path = tmp_path / "runtime" / "mediaguard.sqlite3"
    path.parent.mkdir()
    with sqlite3.connect(path) as connection:
        connection.execute(MIGRATIONS[0][1])
        connection.execute(MIGRATIONS[1][1])
        connection.executemany(
            "INSERT INTO schema_migrations VALUES (?, datetime('now'))", [(1,), (2,)]
        )
        connection.execute(
            """INSERT INTO enforcement_events VALUES
            ('30', '2026-09-28T00:00:00+00:00', '1', '11', '10', 'mp3', 'direct',
             'sample.mp3', 'DELETE', 'succeeded', '2026-09-28T00:00:01+00:00', 'not_attempted')"""
        )

    database = Database(path)
    database.migrate()
    database.migrate()
    record = database.recent_enforcements()[0]
    assert record["message_id"] == "30"
    assert record["deleted_at"] == "2026-09-28T00:00:01+00:00"
    assert record["author_name"] is None
    database.save_protection(1, True, [11], False, None)
    assert database.protection_for(1, Config())["channel_ids"] == (11,)
