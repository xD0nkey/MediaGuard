from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from urllib.parse import urlsplit
from fastapi.staticfiles import StaticFiles
from .runtime import Runtime


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
        return await call_next(request)

    @app.get("/api/status")
    def status():
        return runtime.snapshot()

    @app.get("/api/activity")
    def activity():
        return runtime.activity.recent()

    @app.get("/api/protection")
    def protection():
        config = runtime.config
        return {"enabled": config.protection_enabled, "action": "DELETE",
                "channel_ids": [str(value) for value in config.protected_channel_ids],
                "notifications_enabled": config.notifications_enabled,
                "detection_channel_id": str(config.detection_channel_id) if config.detection_channel_id else None,
                "media_types": ["MP3", "WAV", "FLAC", "Ogg Opus", "Ogg Vorbis", "M4A"]}

    @app.get("/api/detections")
    def detections():
        return runtime.database.recent_enforcements()

    if web_dist and web_dist.exists():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

        @app.get("/{path:path}")
        def frontend(path: str):
            return FileResponse(web_dist / "index.html")
    return app
