from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from urllib.parse import urlsplit
from fastapi.staticfiles import StaticFiles
from .runtime import Runtime


MEDIA_TYPES = ["MP3", "WAV", "FLAC", "Ogg Opus", "Ogg Vorbis", "M4A"]


def _id(value):
    if (not isinstance(value, str) or not value.isascii() or not value.isdecimal()
            or len(value) > 20 or not 0 < int(value) <= 2**64 - 1):
        raise HTTPException(422, "Invalid Discord ID")
    return int(value)


def _protection_payload(settings):
    return {"enabled": settings["enabled"], "action": "DELETE",
            "channel_ids": [str(value) for value in settings["channel_ids"]],
            "notifications_enabled": settings["notifications_enabled"],
            "detection_channel_id": str(settings["detection_channel_id"]) if settings["detection_channel_id"] else None,
            "media_types": MEDIA_TYPES}


def create_app(runtime: Runtime, web_dist: Path | None = None):
    app = FastAPI(title="MediaGuard", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.url.hostname
        if host not in {"localhost", "127.0.0.1", "::1", "testserver"}:
            return JSONResponse({"detail": "Local operator access only"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and (urlsplit(origin).scheme != "http" or urlsplit(origin).hostname not in {"localhost", "127.0.0.1", "::1"}):
            return JSONResponse({"detail": "Untrusted origin"}, status_code=403)
        if request.method not in {"GET", "HEAD"} and origin and urlsplit(origin).netloc != request.url.netloc:
            return JSONResponse({"detail": "Untrusted origin"}, status_code=403)
        return await call_next(request)

    @app.get("/api/status")
    def status():
        return runtime.snapshot()

    @app.get("/api/activity")
    def activity():
        return runtime.activity.recent()

    @app.get("/api/protection")
    def protection(guild_id: str | None = None):
        if guild_id is not None:
            guild_id = str(_id(guild_id))
            try:
                guild = next((item for item in runtime.discord.inventory() if item["id"] == guild_id), None)
            except Exception:
                raise HTTPException(503, "Discord channel list unavailable") from None
            if guild is None:
                raise HTTPException(404, "Guild unavailable")
            settings = runtime.database.protection_for(_id(guild_id), runtime.config)
        else:
            settings = runtime.database.protection_for("0", runtime.config)
        return _protection_payload(settings)

    @app.get("/api/guilds")
    def guilds():
        try:
            return runtime.discord.inventory()
        except Exception:
            raise HTTPException(503, "Discord channel list unavailable") from None

    @app.post("/api/protection")
    async def save_protection(request: Request):
        if request.headers.get("x-mediaguard-action") != "save-protection":
            raise HTTPException(403, "Explicit save required")
        if not request.headers.get("content-type", "").startswith("application/json"):
            raise HTTPException(415, "JSON required")
        try:
            data = await request.json()
        except ValueError:
            raise HTTPException(422, "Invalid configuration") from None
        if not isinstance(data, dict) or set(data) != {"guild_id", "enabled", "channel_ids", "notifications_enabled", "detection_channel_id"}:
            raise HTTPException(422, "Invalid configuration")
        guild_id = _id(data["guild_id"])
        if type(data["enabled"]) is not bool or type(data["notifications_enabled"]) is not bool:
            raise HTTPException(422, "Invalid protection state")
        channel_ids = data["channel_ids"]
        if not isinstance(channel_ids, list) or len(channel_ids) > 500:
            raise HTTPException(422, "Invalid protected channels")
        selected = [_id(value) for value in channel_ids]
        if len(selected) != len(set(selected)):
            raise HTTPException(422, "Duplicate protected channel")
        detection_id = _id(data["detection_channel_id"]) if data["detection_channel_id"] is not None else None
        if data["notifications_enabled"] and detection_id is None:
            raise HTTPException(422, "Select a Detection channel")
        try:
            guild = next((item for item in runtime.discord.inventory() if item["id"] == str(guild_id)), None)
        except Exception:
            raise HTTPException(503, "Discord channel list unavailable") from None
        if guild is None:
            raise HTTPException(422, "Guild unavailable")
        protected = {int(channel["id"]) for channel in guild["channels"] if channel["can_protect"]}
        notification_channels = {int(channel["id"]) for channel in guild["channels"] if channel["can_notify"]}
        if not set(selected) <= protected or (data["enabled"] and not protected and not selected):
            raise HTTPException(422, "Protected channel unavailable")
        if detection_id is not None and detection_id not in notification_channels:
            raise HTTPException(422, "Detection channel unavailable")
        runtime.database.save_protection(guild_id, data["enabled"], selected,
                                         data["notifications_enabled"], detection_id)
        runtime.activity.record("System", "protection_configuration_saved")
        return _protection_payload(runtime.database.protection_for(guild_id, runtime.config))

    @app.get("/api/detections")
    def detections():
        return runtime.database.recent_enforcements()

    if web_dist and web_dist.exists():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

        @app.get("/{path:path}")
        def frontend(path: str):
            return FileResponse(web_dist / "index.html")
    return app
