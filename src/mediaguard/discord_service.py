import asyncio
import logging
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from discord import AllowedMentions, HTTPException, MessageReferenceType

from .activity import Activity
from .detection_notice import detection_embed, unresolved_embed
from .embed_phrases import match_embeds
from .attachments import (
    InspectionResult,
    Status,
    download_prefix,
    inspect_attachment,
)


logger = logging.getLogger(__name__)
SAFE_DISCORD_ERRORS = {"Missing Permissions", "Missing Access", "Unknown Channel", "Unknown Message"}
NOTIFICATION_PERMISSIONS = (
    "view_channel", "send_messages", "embed_links", "attach_files", "read_message_history",
    "add_reactions", "send_messages_in_threads", "create_public_threads", "create_private_threads",
    "manage_messages", "manage_threads", "mention_everyone",
)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _is_protected_channel(channel, protected_ids):
    return channel.id in protected_ids or getattr(channel, "parent_id", None) in protected_ids


def _has_exempt_role(author, exempt_role_ids):
    roles = getattr(author, "roles", None)
    return bool(exempt_role_ids and roles and any(role.id in exempt_role_ids for role in roles))


def make_client(service):
    import discord
    from discord import app_commands
    from .discord_commands import register_commands
    intents = discord.Intents.none()
    intents.guilds = True
    intents.messages = True
    intents.message_content = True

    class Client(discord.Client):
        def __init__(self):
            super().__init__(intents=intents)
            self.tree = app_commands.CommandTree(self)
            register_commands(self.tree, service)

        async def setup_hook(self):
            try:
                await self.tree.sync()
            except Exception:
                service.activity.record("Error", "discord_command_sync_failed")

        async def on_ready(self):
            service._ready(len(self.guilds))

        async def on_disconnect(self):
            service._disconnected()

        async def on_resumed(self):
            service._resumed()

        async def on_message(self, message):
            try:
                await service.handle_message(message, self.user.id if self.user else None)
            except Exception:
                service.activity.record("Error", "discord_intake_error")

        async def on_message_edit(self, _before, after):
            if not after.embeds:
                return
            try:
                await service.handle_message(after, self.user.id if self.user else None, embed_only=True)
            except Exception:
                service.activity.record("Error", "discord_intake_error")

    return Client()


class DiscordService:
    def __init__(
        self,
        activity: Activity,
        client_factory=make_client,
        *,
        fetch_prefix=download_prefix,
        config=None,
        database=None,
    ):
        self.activity = activity
        self.client_factory = client_factory
        self.fetch_prefix = fetch_prefix
        self.config = config
        self.database = database
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
        self._attempted_messages = {}

    def _reserve_attempt(self, message_id):
        now = time.monotonic()
        with self._lock:
            self._attempted_messages = {
                key: expires for key, expires in self._attempted_messages.items() if expires > now
            }
            if message_id in self._attempted_messages:
                return False
            if len(self._attempted_messages) >= 4096:
                self._attempted_messages.pop(next(iter(self._attempted_messages)))
            self._attempted_messages[message_id] = now + 300
            return True

    def snapshot(self):
        with self._lock:
            return {"state": self._state, "gateway": self._gateway, "guild_count": self._guild_count,
                    "ready_at": self._ready_at, "reconnect_count": self._reconnects}

    def guild_inventory(self, guild):
        channels = []
        forum_ids = {forum.id for forum in guild.forums}
        for channel in [*guild.text_channels, *guild.forums]:
            permissions = channel.permissions_for(guild.me) if guild.me else None
            visible = bool(permissions and permissions.view_channel)
            channels.append({"id": str(channel.id), "name": channel.name,
                             "can_protect": visible and bool(permissions.manage_messages),
                             "can_notify": visible and bool(permissions.send_messages)
                             and channel.id not in forum_ids})
        roles = [{"id": str(role.id), "name": role.name} for role in guild.roles
                 if not role.is_default() and not role.managed]
        return {"id": str(guild.id), "name": guild.name, "channels": channels, "roles": roles}

    async def _inventory(self, client):
        return [self.guild_inventory(guild) for guild in client.guilds]

    def inventory(self):
        with self._lock:
            loop, client = self._loop, self._client
        if not loop or not client or not loop.is_running():
            return []
        return asyncio.run_coroutine_threadsafe(self._inventory(client), loop).result(timeout=3)

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

    async def inspect_message(
        self, message, bot_user_id=None, embed_rules=(), embed_only=False, inspect_audio=True
    ) -> tuple[InspectionResult, ...]:
        if message.guild is None or (bot_user_id is not None and message.author.id == bot_user_id):
            return ()

        skip_attachments = embed_only or not inspect_audio
        attachments = [] if skip_attachments else [(attachment, "direct") for attachment in message.attachments]
        results = []
        forwarded_embeds = []
        reference = getattr(message, "reference", None)
        if reference is not None and reference.type is MessageReferenceType.forward:
            snapshots = message.message_snapshots
            if not snapshots and (not skip_attachments or embed_rules):
                results.append(
                    InspectionResult(Status.UNAVAILABLE, "forward_snapshot_unavailable", "forward")
                )
            for snapshot in snapshots:
                if not skip_attachments:
                    attachments.extend((attachment, "forward") for attachment in snapshot.attachments)
                forwarded_embeds.extend(snapshot.embeds)
                if not skip_attachments and not snapshot.attachments and not snapshot.embeds:
                    results.append(
                        InspectionResult(Status.UNAVAILABLE, "forward_media_metadata_unavailable", "forward")
                    )

        for attachment, source in attachments:
            async with self._inspection_slots:
                results.append(
                    await inspect_attachment(attachment, self.fetch_prefix, source)
                )

        if embed_rules:
            if not any(result.status is Status.MATCH for result in results):
                embed_match = match_embeds(message.embeds, forwarded_embeds, embed_rules)
                if embed_match:
                    results.append(embed_match)
        elif forwarded_embeds:
            results.append(InspectionResult(Status.UNAVAILABLE, "forward_embeds_not_inspected", "forward"))

        if any(result.status is Status.UNAVAILABLE for result in results):
            self.activity.record("Error", "inspection_unavailable")
        return tuple(results)

    async def handle_message(self, message, bot_user_id=None, *, embed_only=False):
        if message.guild is None or (bot_user_id is not None and message.author.id == bot_user_id):
            return ()
        settings = self.database.protection_for(message.guild.id, self.config) if self.config and self.database else None
        if settings and settings["channel_ids"] and not _is_protected_channel(message.channel, settings["channel_ids"]):
            return ()
        rules = self.database.embed_rules(message.guild.id, enabled_only=True) if settings and settings["enabled"] and bot_user_id is not None else ()
        exempt = bool(settings) and _has_exempt_role(message.author, settings["exempt_role_ids"])
        results = await self.inspect_message(message, bot_user_id, rules, embed_only, not exempt)
        if not settings or not settings["enabled"]:
            return results
        match = next((result for result in results if result.status is Status.MATCH), None)
        if match is None:
            await self._report_unresolved(message, results, settings)
            return results

        settings = self.database.protection_for(message.guild.id, self.config)
        if not settings["enabled"]:
            return results
        if not self._reserve_attempt(message.id):
            return results

        mode = settings["moderation_mode"]
        if mode == "warn_only":
            detection_channel = self._detection_channel(message, settings)
            if detection_channel is None:
                self.activity.record("Error", "detection_notification_unavailable")
                self._log_notification_unavailable(message, settings)
                return results
            try:
                await detection_channel.send(
                    embed=detection_embed(message, match, datetime.now(timezone.utc), mode),
                    allowed_mentions=AllowedMentions.none(),
                )
            except Exception as error:
                self.activity.record("Error", "detection_notification_failed")
                self._log_notification_failure(message, settings, detection_channel, error)
                self._log_notification_permissions(message, detection_channel)
            return results
        if mode != "auto_delete":
            self.activity.record("Error", "invalid_moderation_mode")
            return results

        member = message.guild.me
        permissions = message.channel.permissions_for(member) if member else None
        if not permissions or not permissions.view_channel or not permissions.manage_messages:
            self.activity.record("Error", "delete_permission_missing")
            return results

        detection_channel = self._detection_channel(message, settings) if settings["notifications_enabled"] else None
        can_notify = detection_channel is not None

        try:
            await message.delete()
        except Exception:
            self.activity.record("Error", "delete_failed")
            return results
        deleted_at = datetime.now(timezone.utc)

        if settings["notifications_enabled"]:
            if not can_notify:
                self.activity.record("Error", "detection_notification_unavailable")
                self._log_notification_unavailable(message, settings)
                return results
            try:
                await detection_channel.send(embed=detection_embed(message, match, deleted_at), allowed_mentions=AllowedMentions.none())
            except Exception as error:
                self.activity.record("Error", "detection_notification_failed")
                self._log_notification_failure(message, settings, detection_channel, error)
                self._log_notification_permissions(message, detection_channel)
        return results

    def _detection_channel(self, message, settings):
        member = message.guild.me
        channel = None
        try:
            channel = message.guild.get_channel(settings["detection_channel_id"]) if settings["detection_channel_id"] else None
            permissions = channel.permissions_for(member) if channel and member else None
            if permissions and permissions.view_channel and permissions.send_messages:
                return channel
            return None
        except Exception as error:
            self._log_notification_failure(message, settings, channel, error, operation="resolve")
            raise

    def _log_notification_failure(self, message, settings, channel, error, *, operation="send"):
        fields = (message.guild.id, settings["detection_channel_id"],
                  channel.id if channel else None, channel is not None, type(error).__name__)
        if isinstance(error, HTTPException):
            detail = error.text if error.text in SAFE_DISCORD_ERRORS else "omitted"
            logger.error(
                "detection_notification_failed operation=%s guild_id=%s configured_channel_id=%s "
                "resolved_channel_id=%s resolved_channel=%s exception=%s status=%s code=%s message=%s",
                operation, *fields, error.status, error.code, detail,
            )
        else:
            frames = " -> ".join(
                f"{Path(frame.filename).name}:{frame.lineno}:{frame.name}"
                for frame in traceback.extract_tb(error.__traceback__)
            )
            logger.error(
                "detection_notification_failed operation=%s guild_id=%s configured_channel_id=%s "
                "resolved_channel_id=%s resolved_channel=%s exception=%s message=omitted traceback=%s",
                operation, *fields, frames,
            )

    def _log_notification_unavailable(self, message, settings):
        configured = settings["detection_channel_id"]
        channel = None
        try:
            if configured is None:
                reason = "channel_not_configured"
            else:
                channel = message.guild.get_channel(configured)
                if channel is None:
                    reason = "channel_not_resolved"
                elif message.guild.me is None:
                    reason = "bot_member_unavailable"
                else:
                    permissions = channel.permissions_for(message.guild.me)
                    if not permissions.view_channel:
                        reason = "missing_access"
                    elif not permissions.send_messages:
                        reason = "missing_permissions"
                    else:
                        reason = "resolution_changed"
            logger.error(
                "detection_notification_unavailable guild_id=%s configured_channel_id=%s "
                "resolved_channel_id=%s resolved_channel=%s reason=%s",
                message.guild.id, configured, channel.id if channel else None, channel is not None, reason,
            )
        except Exception as error:
            self._log_notification_failure(message, settings, channel, error)

    def _log_notification_permissions(self, message, channel):
        try:
            member = message.guild.me
            if member is None:
                raise ValueError("bot_member_unavailable")
            permissions = channel.permissions_for(member)
            channel_type = getattr(channel, "type", None)
            fields = " ".join(
                f"{name}={getattr(permissions, name, 'unavailable')}" for name in NOTIFICATION_PERMISSIONS
            )
            logger.error(
                "detection_notification_permissions guild_id=%s channel_id=%s channel_type=%s "
                "category_id=%s %s",
                message.guild.id, channel.id, getattr(channel_type, "name", type(channel).__name__),
                getattr(channel, "category_id", None), fields,
            )
        except Exception as error:
            logger.error(
                "detection_notification_permissions guild_id=%s channel_id=%s unavailable=%s",
                getattr(message.guild, "id", None), getattr(channel, "id", None), type(error).__name__,
            )

    async def _report_unresolved(self, message, results, settings):
        unresolved = next((result for result in results if result.status is Status.UNAVAILABLE), None)
        if unresolved is None or settings["unresolved_action"] != "report" or not settings["notifications_enabled"]:
            return
        if not self._reserve_attempt(("unresolved", message.id)):
            return
        detection_channel = self._detection_channel(message, settings)
        if detection_channel is None:
            self.activity.record("Error", "unresolved_notification_unavailable")
            return
        try:
            await detection_channel.send(embed=unresolved_embed(message, unresolved, datetime.now(timezone.utc)),
                                         allowed_mentions=AllowedMentions.none())
        except Exception:
            self.activity.record("Error", "unresolved_notification_failed")

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
