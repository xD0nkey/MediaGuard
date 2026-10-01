import logging
import re
import subprocess
import sys
from types import SimpleNamespace

import discord
import pytest

from test_enforcement import Channel, Message, handle, setup
from test_inspection import MP3, attachment


def test_terminal_logging_has_local_millisecond_timestamp_and_level():
    script = ("import logging; from mediaguard.main import configure_logging; "
              "configure_logging(); configure_logging(); logging.info('ordinary runtime message'); "
              "logging.getLogger('uvicorn.error').info('server runtime message')")
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True)
    lines = result.stderr.splitlines()
    assert len(lines) == 2
    for line, message in zip(lines, ("ordinary runtime message", "server runtime message")):
        assert re.fullmatch(
            r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\] \[INFO\] " + message,
            line,
        )


@pytest.mark.parametrize("mode", ["auto_delete", "warn_only"])
def test_detection_send_failure_logs_safe_discord_details_and_keeps_activity(tmp_path, caplog, mode):
    runtime = setup(tmp_path)
    runtime.database.save_protection(1, True, [], True, 40, (), "allow", mode)
    channel = Channel(40)

    async def rejected(**_kwargs):
        response = SimpleNamespace(status=403, reason="Forbidden")
        raise discord.Forbidden(response, {"message": "Missing Permissions", "code": 50013})

    channel.send = rejected
    message = Message(attachment("PRIVATE-FILE.mp3", MP3), detection_channel=channel,
                      content="PRIVATE MESSAGE BODY")
    with caplog.at_level(logging.ERROR, logger="mediaguard.discord_service"):
        handle(runtime, message)
    assert "detection_notification_failed" in str(runtime.activity.recent())
    assert "detection_notification_failed" in caplog.text
    for value in ("guild_id=1", "configured_channel_id=40", "resolved_channel_id=40",
                  "resolved_channel=True", "exception=Forbidden", "status=403", "code=50013",
                  "message=Missing Permissions"):
        assert value in caplog.text
    for private in ("PRIVATE-FILE", "PRIVATE MESSAGE BODY", "DISCORD_BOT_TOKEN", "Authorization"):
        assert private not in caplog.text
    assert message.deletes == (1 if mode == "auto_delete" else 0)


@pytest.mark.parametrize("channel,reason,resolved", [
    (None, "channel_not_resolved", "False"),
    (Channel(40, visible=False), "missing_access", "True"),
    (Channel(40, send=False), "missing_permissions", "True"),
])
def test_notification_unavailable_logs_resolution_reason(tmp_path, caplog, channel, reason, resolved):
    runtime = setup(tmp_path, notifications=True, detection_channel_id=40)
    message = Message(attachment("song.mp3", MP3), detection_channel=channel)
    with caplog.at_level(logging.ERROR, logger="mediaguard.discord_service"):
        handle(runtime, message)
    assert "detection_notification_unavailable" in str(runtime.activity.recent())
    assert f"reason={reason}" in caplog.text
    assert f"resolved_channel={resolved}" in caplog.text
    assert "configured_channel_id=40" in caplog.text
    assert "detection_notification_failed" not in caplog.text


def test_unexpected_notification_exception_keeps_traceback_without_message_content(tmp_path, caplog):
    runtime = setup(tmp_path, notifications=True, detection_channel_id=40)
    channel = Channel(40)

    async def broken(**_kwargs):
        raise RuntimeError("PRIVATE MESSAGE BODY Authorization Bearer SECRET-TOKEN")

    channel.send = broken
    message = Message(attachment("PRIVATE-FILE.mp3", MP3), detection_channel=channel,
                      content="PRIVATE MESSAGE BODY")
    with caplog.at_level(logging.ERROR, logger="mediaguard.discord_service"):
        handle(runtime, message)
    assert "exception=RuntimeError" in caplog.text
    assert "traceback=discord_service.py:" in caplog.text
    assert "test_logging.py:" in caplog.text
    assert "message=omitted" in caplog.text
    for private in ("PRIVATE MESSAGE BODY", "PRIVATE-FILE", "SECRET-TOKEN", "Authorization Bearer"):
        assert private not in caplog.text
    assert "detection_notification_failed" in str(runtime.activity.recent())


def test_channel_resolution_exception_is_logged_and_still_propagates(tmp_path, caplog):
    runtime = setup(tmp_path, notifications=True, detection_channel_id=40)
    message = Message(attachment("song.mp3", MP3))

    def broken(_channel_id):
        raise RuntimeError("PRIVATE CHANNEL CONTENT")

    message.guild.get_channel = broken
    with caplog.at_level(logging.ERROR, logger="mediaguard.discord_service"):
        with pytest.raises(RuntimeError):
            handle(runtime, message)
    assert "operation=resolve" in caplog.text
    assert "exception=RuntimeError" in caplog.text
    assert "PRIVATE CHANNEL CONTENT" not in caplog.text


def test_failed_send_logs_effective_permissions_without_discord_requests(tmp_path, caplog):
    runtime = setup(tmp_path, notifications=True, detection_channel_id=40)
    channel = Channel(40)
    channel.type = SimpleNamespace(name="text")
    channel.category_id = 77
    channel.name = "PRIVATE CHANNEL NAME"
    channel.permissions = SimpleNamespace(**{
        "view_channel": True, "send_messages": True, "embed_links": False,
        "attach_files": False, "read_message_history": True, "add_reactions": True,
        "send_messages_in_threads": False, "create_public_threads": False,
        "create_private_threads": False, "manage_messages": False,
        "manage_threads": False, "mention_everyone": False,
    })
    message = Message(attachment("PRIVATE-FILE.mp3", MP3), detection_channel=channel,
                      content="PRIVATE MESSAGE BODY")
    member = message.guild.me
    calls = []

    def permissions_for(candidate):
        assert candidate is member
        calls.append(candidate)
        return channel.permissions

    async def rejected(**_kwargs):
        response = SimpleNamespace(status=403, reason="Forbidden")
        raise discord.Forbidden(response, {"message": "Missing Permissions", "code": 50013})

    def unexpected_request(*_args, **_kwargs):
        raise AssertionError("unexpected Discord request")

    channel.permissions_for = permissions_for
    channel.send = rejected
    message.guild.fetch_member = unexpected_request
    message.guild.fetch_channel = unexpected_request
    channel.fetch = unexpected_request
    with caplog.at_level(logging.ERROR, logger="mediaguard.discord_service"):
        handle(runtime, message)
    assert "detection_notification_failed" in str(runtime.activity.recent())
    assert "detection_notification_failed operation=send" in caplog.text
    assert "detection_notification_permissions guild_id=1 channel_id=40 channel_type=text category_id=77" in caplog.text
    assert len(calls) == 2
    for name, value in vars(channel.permissions).items():
        assert f"{name}={value}" in caplog.text
    for private in ("PRIVATE CHANNEL NAME", "PRIVATE-FILE", "PRIVATE MESSAGE BODY", "Authorization", "SECRET-TOKEN"):
        assert private not in caplog.text


def test_missing_bot_member_does_not_mask_send_failure(tmp_path, caplog):
    runtime = setup(tmp_path, notifications=True, detection_channel_id=40)
    channel = Channel(40)
    message = Message(attachment("song.mp3", MP3), detection_channel=channel)

    async def rejected(**_kwargs):
        message.guild.me = None
        response = SimpleNamespace(status=403, reason="Forbidden")
        raise discord.Forbidden(response, {"message": "Missing Permissions", "code": 50013})

    channel.send = rejected
    with caplog.at_level(logging.ERROR, logger="mediaguard.discord_service"):
        handle(runtime, message)
    assert "detection_notification_failed" in str(runtime.activity.recent())
    assert "detection_notification_failed operation=send" in caplog.text
    assert "detection_notification_permissions guild_id=1 channel_id=40 unavailable=ValueError" in caplog.text


def test_permission_snapshot_error_does_not_mask_send_failure(tmp_path, caplog):
    runtime = setup(tmp_path, notifications=True, detection_channel_id=40)
    channel = Channel(40)
    message = Message(attachment("song.mp3", MP3), detection_channel=channel)
    original_permissions_for = channel.permissions_for
    calls = 0

    def permissions_for(member):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("PRIVATE PERMISSION DETAILS")
        return original_permissions_for(member)

    async def rejected(**_kwargs):
        response = SimpleNamespace(status=403, reason="Forbidden")
        raise discord.Forbidden(response, {"message": "Missing Permissions", "code": 50013})

    channel.permissions_for = permissions_for
    channel.send = rejected
    with caplog.at_level(logging.ERROR, logger="mediaguard.discord_service"):
        handle(runtime, message)
    assert "detection_notification_failed" in str(runtime.activity.recent())
    assert "detection_notification_failed operation=send" in caplog.text
    assert "detection_notification_permissions guild_id=1 channel_id=40 unavailable=RuntimeError" in caplog.text
    assert "PRIVATE PERMISSION DETAILS" not in caplog.text
