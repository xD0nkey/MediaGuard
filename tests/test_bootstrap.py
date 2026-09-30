import asyncio
import importlib
import pkgutil
import sqlite3
import threading
import time
from pathlib import Path
from fastapi.testclient import TestClient
from mediaguard.activity import Activity
from mediaguard.api import create_app
from mediaguard.config import Config, load
from mediaguard.database import Database
from mediaguard.discord_service import DiscordService
from mediaguard.runtime import Runtime


def test_independent_imports_and_paths(tmp_path):
    import mediaguard
    for module in pkgutil.walk_packages(mediaguard.__path__, "mediaguard."):
        importlib.import_module(module.name)
    assert "MediaGuard" in str(mediaguard.paths.project_root())
    assert mediaguard.paths.project_root().name == "MediaGuard"
    assert load(tmp_path) == Config()
    assert not (tmp_path / "secrets.env").exists()


def test_migration_idempotent(tmp_path):
    db = Database(tmp_path / "runtime" / "test.sqlite3")
    db.migrate()
    db.migrate()
    with db.connect() as connection:
        assert connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 6


def test_legacy_attachment_size_setting_is_ignored(tmp_path):
    import json

    path = tmp_path / "config.json"
    for value in (1024, 0, "invalid"):
        path.write_text(json.dumps({"discord": {"enabled": True, "max_attachment_bytes": value}}), encoding="utf-8")
        assert load(tmp_path).discord_enabled is True
        assert not hasattr(load(tmp_path), "max_attachment_bytes")


def test_legacy_retention_setting_is_ignored(tmp_path):
    import json

    (tmp_path / "config.json").write_text(
        json.dumps({"detection_retention_days": 90, "protection": {"enabled": True}}),
        encoding="utf-8",
    )
    assert load(tmp_path).protection_enabled is True
    assert not hasattr(load(tmp_path), "detection_retention_days")


def test_legacy_global_protection_defaults_to_auto_delete(tmp_path):
    import json

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"protection": {"enabled": True}}), encoding="utf-8")
    assert load(tmp_path).moderation_mode == "auto_delete"
    path.write_text(json.dumps({"protection": {"moderation_mode": "warn_only"}}), encoding="utf-8")
    assert load(tmp_path).moderation_mode == "warn_only"
    path.write_text(json.dumps({"protection": {"enabled": True, "moderation_mode": "warn_only"}}), encoding="utf-8")
    import pytest
    with pytest.raises(ValueError):
        load(tmp_path)
    path.write_text(json.dumps({"protection": {"enabled": True, "moderation_mode": "warn_only",
                                               "notifications_enabled": True, "detection_channel_id": 40}}), encoding="utf-8")
    assert load(tmp_path).moderation_mode == "warn_only"
    path.write_text(json.dumps({"protection": {"moderation_mode": "delete"}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load(tmp_path)


class FakeClient:
    def __init__(self, service):
        self.service = service
        self.closed = asyncio.Event()
        self.started = threading.Event()

    async def start(self, token, reconnect=True):
        assert token == "fake-test-token"
        assert reconnect
        self.service._ready(2)
        self.started.set()
        await self.closed.wait()

    async def close(self):
        self.closed.set()


def test_discord_lifecycle_no_network():
    activity = Activity()
    holder = {}
    created = threading.Event()
    def factory(service):
        holder["client"] = FakeClient(service)
        created.set()
        return holder["client"]
    service = DiscordService(activity, factory)
    assert service.start(None) is False
    assert service.start("fake-test-token")
    assert created.wait(2)
    assert holder["client"].started.wait(2)
    assert service.snapshot()["guild_count"] == 2
    service.stop(timeout=2)
    assert service.snapshot()["state"] == "stopped"
    assert not service._thread


def test_runtime_and_backend(tmp_path):
    runtime = Runtime(Config(), tmp_path)
    runtime.start()
    with TestClient(create_app(runtime)) as client:
        status = client.get("/api/status")
        assert status.status_code == 200
        assert status.json()["database"] == "ready"
        assert status.json()["discord"]["state"] == "unconfigured"
        assert client.get("/api/activity").json()[0]["code"] == "runtime_started"
        assert client.get("/api/cases").status_code == 404
        assert client.get("/api/rules").status_code == 404
        assert client.get("/api/status", headers={"host": "evil.example"}).status_code == 403
        assert client.get("/api/status", headers={"origin": "http://localhost.evil.example"}).status_code == 403
    runtime.stop()


def test_runtime_imports_only_package_or_declared_dependencies():
    import ast
    root = Path(__file__).resolve().parents[1] / "src" / "mediaguard"
    allowed = {"asyncio", "threading", "datetime", "pathlib", "collections", "json", "os", "sqlite3", "time", "fastapi", "uvicorn", "discord", "dataclasses", "urllib", "enum", "aiohttp", "unicodedata", "re", "uuid"}
    for path in root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(name.name.split(".")[0] in allowed for name in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                assert node.module.split(".")[0] in allowed
