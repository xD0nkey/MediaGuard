import asyncio
import threading
from datetime import datetime, timezone
from discord import MessageReferenceType

from .activity import Activity
from .attachments import (
    DEFAULT_MAX_ATTACHMENT_BYTES,
    InspectionResult,
    Status,
    download_prefix,
    inspect_attachment,
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def make_client(service):
    import discord
    intents = discord.Intents.none()
    intents.guilds = True
    intents.messages = True
    intents.message_content = True

    class Client(discord.Client):
        async def on_ready(self):
            service._ready(len(self.guilds))

        async def on_disconnect(self):
            service._disconnected()

        async def on_resumed(self):
            service._resumed()

        async def on_message(self, message):
            try:
                await service.inspect_message(message, self.user.id if self.user else None)
            except Exception:
                service.activity.record("Error", "discord_intake_error")

    return Client(intents=intents)


class DiscordService:
    def __init__(
        self,
        activity: Activity,
        client_factory=make_client,
        *,
        max_attachment_bytes=DEFAULT_MAX_ATTACHMENT_BYTES,
        fetch_prefix=download_prefix,
    ):
        self.activity = activity
        self.client_factory = client_factory
        self.max_attachment_bytes = max_attachment_bytes
        self.fetch_prefix = fetch_prefix
        self._inspection_slots = asyncio.Semaphore(4)
        self._lock = threading.RLock()
        self._thread = None
        self._loop = None
        self._client = None
        self._stop = threading.Event()
        self._state = "unconfigured"
        self._gateway = "disconnected"
        self._guild_count = None
        self._ready_at = None
        self._reconnects = 0

    def snapshot(self):
        with self._lock:
            return {"state": self._state, "gateway": self._gateway, "guild_count": self._guild_count,
                    "ready_at": self._ready_at, "reconnect_count": self._reconnects}

    def _ready(self, guild_count):
        with self._lock:
            self._state, self._gateway = "ready", "connected"
            self._guild_count, self._ready_at = guild_count, _now()
        self.activity.record("Discord", "gateway_ready")

    def _disconnected(self):
        with self._lock:
            self._gateway = "disconnected"
            self._guild_count = None
        self.activity.record("Discord", "gateway_disconnected")

    def _resumed(self):
        with self._lock:
            self._gateway = "connected"
            self._reconnects += 1
        self.activity.record("Discord", "gateway_resumed")

    async def inspect_message(self, message, bot_user_id=None) -> tuple[InspectionResult, ...]:
        if message.guild is None or (bot_user_id is not None and message.author.id == bot_user_id):
            return ()

        attachments = [(attachment, "direct") for attachment in message.attachments]
        results = []
        reference = getattr(message, "reference", None)
        if reference is not None and reference.type is MessageReferenceType.forward:
            snapshots = message.message_snapshots
            if not snapshots:
                results.append(
                    InspectionResult(Status.UNAVAILABLE, "forward_snapshot_unavailable", "forward")
                )
            for snapshot in snapshots:
                attachments.extend((attachment, "forward") for attachment in snapshot.attachments)
                if snapshot.embeds:
                    results.append(
                        InspectionResult(Status.UNAVAILABLE, "forward_embeds_not_inspected", "forward")
                    )
                if not snapshot.attachments and not snapshot.embeds:
                    results.append(
                        InspectionResult(Status.UNAVAILABLE, "forward_media_metadata_unavailable", "forward")
                    )

        for attachment, source in attachments:
            async with self._inspection_slots:
                results.append(
                    await inspect_attachment(attachment, self.max_attachment_bytes, self.fetch_prefix, source)
                )

        if any(result.status is Status.MATCH for result in results):
            self.activity.record("Discord", "media_match_observed")
        if any(result.status is Status.UNAVAILABLE for result in results):
            self.activity.record("Error", "inspection_unavailable")
        return tuple(results)

    def start(self, token: str | None):
        if not token:
            self.activity.record("Discord", "token_missing")
            return False
        with self._lock:
            if self._thread and self._thread.is_alive():
                return True
            self._stop.clear()
            self._state = "starting"
            self._thread = threading.Thread(target=self._run, args=(token,), name="mediaguard-discord", daemon=True)
            self._thread.start()
        self.activity.record("Discord", "service_starting")
        return True

    def _run(self, token):
        async def runner():
            client = self.client_factory(self)
            with self._lock:
                self._loop = asyncio.get_running_loop()
                self._client = client
                self._gateway = "connecting"
            try:
                if not self._stop.is_set():
                    await client.start(token, reconnect=True)
            except Exception:
                with self._lock:
                    self._state, self._gateway = "error", "disconnected"
                self.activity.record("Error", "discord_connection_failed")
            finally:
                await client.close()
                with self._lock:
                    self._loop = None
                    self._client = None
                    self._gateway = "disconnected"
                    self._guild_count = None
                    if self._state != "error":
                        self._state = "stopped"
                self.activity.record("Discord", "service_stopped")
        asyncio.run(runner())

    def stop(self, timeout=15):
        self._stop.set()
        with self._lock:
            thread, loop, client = self._thread, self._loop, self._client
        if thread and thread.is_alive() and loop and client:
            future = asyncio.run_coroutine_threadsafe(client.close(), loop)
            future.result(timeout=timeout)
        if thread and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():
                raise RuntimeError("Discord service did not stop")
        with self._lock:
            self._thread = None
            if self._state != "error":
                self._state = "stopped"
