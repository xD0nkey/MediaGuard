from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from urllib.parse import urlsplit
from fastapi.staticfiles import StaticFiles
from .runtime import Runtime
from .configuration import (ConfigurationError, delete_phrase, discord_id,
                            save_phrase, save_protection as save_guild_protection)


MEDIA_TYPES = ["MP3", "WAV", "FLAC", "Ogg Opus", "Ogg Vorbis", "M4A"]
def _id(value):
    try:
        return discord_id(value)
    except ConfigurationError as error:
        raise HTTPException(422, str(error)) from None


def _protection_payload(settings):
    return {"enabled": settings["enabled"], "action": "DELETE",
            "channel_ids": [str(value) for value in settings["channel_ids"]],
            "notifications_enabled": settings["notifications_enabled"],
            "detection_channel_id": str(settings["detection_channel_id"]) if settings["detection_channel_id"] else None,
            "exempt_role_ids": [str(value) for value in settings["exempt_role_ids"]],
            "unresolved_action": settings["unresolved_action"],
            "moderation_mode": settings["moderation_mode"],
            "media_types": MEDIA_TYPES}


def _rule_payload(rule):
    payload = {key: rule[key] for key in ("rule_id", "guild_id", "name", "phrase", "created_at", "updated_at")}
    payload["enabled"] = bool(rule["enabled"])
    return payload


def _rule_id(value):
    if len(value) != 32 or any(char not in "0123456789abcdef" for char in value):
        raise HTTPException(422, "Invalid rule ID")
    return value


def create_app(runtime: Runtime, web_dist: Path | None = None):
    app = FastAPI(title="MediaGuard", docs_url=None, redoc_url=None, openapi_url=None)

    def connected_guild(guild_id):
        guild_id = str(_id(guild_id))
        try:
            guild = next((item for item in runtime.discord.inventory() if item["id"] == guild_id), None)
        except Exception:
            raise HTTPException(503, "Discord channel list unavailable") from None
        if guild is None:
            raise HTTPException(404, "Guild unavailable")
        return guild

    async def rule_request(request, action):
        if request.headers.get("x-mediaguard-action") != action:
            raise HTTPException(403, "Explicit action required")
        if not request.headers.get("content-type", "").startswith("application/json"):
            raise HTTPException(415, "JSON required")
        try:
            data = await request.json()
        except ValueError:
            raise HTTPException(422, "Invalid rule") from None
        if not isinstance(data, dict) or set(data) != {"guild_id", "name", "phrase", "enabled"}:
            raise HTTPException(422, "Invalid rule")
        guild = connected_guild(data["guild_id"])
        return guild["id"], data["name"], data["phrase"], data["enabled"]

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
            settings = runtime.database.protection_for(connected_guild(guild_id)["id"], runtime.config)
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
        if not isinstance(data, dict) or "guild_id" not in data:
            raise HTTPException(422, "Invalid configuration")
        guild_id = _id(data["guild_id"])
        try:
            guild = next((item for item in runtime.discord.inventory() if item["id"] == str(guild_id)), None)
        except Exception:
            raise HTTPException(503, "Discord channel list unavailable") from None
        if guild is None:
            raise HTTPException(422, "Guild unavailable")
        try:
            settings = save_guild_protection(runtime.database, runtime.config, guild, data)
        except ConfigurationError as error:
            raise HTTPException(422, str(error)) from None
        runtime.activity.record("System", "protection_configuration_saved")
        return _protection_payload(settings)

    @app.get("/api/embed-rules")
    def embed_rules(guild_id: str):
        guild = connected_guild(guild_id)
        return [_rule_payload(rule) for rule in runtime.database.embed_rules(guild["id"])]

    @app.post("/api/embed-rules")
    async def create_embed_rule(request: Request):
        guild_id, name, phrase, enabled = await rule_request(request, "save-embed-rule")
        try:
            rule = save_phrase(runtime.database, guild_id, name, phrase, enabled)
        except ConfigurationError as error:
            raise HTTPException(422, str(error)) from None
        runtime.activity.record("System", "embed_rule_saved")
        return _rule_payload(rule)

    @app.put("/api/embed-rules/{rule_id}")
    async def update_embed_rule(rule_id: str, request: Request):
        rule_id = _rule_id(rule_id)
        guild_id, name, phrase, enabled = await rule_request(request, "save-embed-rule")
        try:
            rule = save_phrase(runtime.database, guild_id, name, phrase, enabled, rule_id)
        except ConfigurationError as error:
            raise HTTPException(404 if str(error) == "Rule unavailable" else 422, str(error)) from None
        runtime.activity.record("System", "embed_rule_saved")
        return _rule_payload(rule)

    @app.delete("/api/embed-rules/{rule_id}")
    def delete_embed_rule(rule_id: str, guild_id: str, request: Request):
        if request.headers.get("x-mediaguard-action") != "delete-embed-rule":
            raise HTTPException(403, "Explicit action required")
        guild_id = connected_guild(guild_id)["id"]
        try:
            delete_phrase(runtime.database, guild_id, _rule_id(rule_id))
        except ConfigurationError as error:
            raise HTTPException(404, str(error)) from None
        runtime.activity.record("System", "embed_rule_deleted")
        return {"deleted": True}

    if web_dist and web_dist.exists():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

        @app.get("/{path:path}")
        def frontend(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "Not found")
            return FileResponse(web_dist / "index.html")
    return app
