import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from mediaguard.api import create_app
from mediaguard.attachments import Status
from mediaguard.config import Config, load
from mediaguard.detection_notice import blocked_audio_embed
from mediaguard.runtime import Runtime
from mediaguard.discord_service import make_client

from test_inspection import MP3, WAV, attachment


class Channel:
    def __init__(self, channel_id, *, manage=True, send=True, visible=True, fail_send=False):
        self.id = channel_id
        self.permissions = SimpleNamespace(manage_messages=manage, send_messages=send, view_channel=visible)
        self.sent = []
        self.fail_send = fail_send

    def permissions_for(self, _member):
        return self.permissions

    async def send(self, **kwargs):
        if self.fail_send:
            raise OSError("private send failure")
        self.sent.append(kwargs)


class Message:
    def __init__(self, *items, channel=None, detection_channel=None, forward=False, fail_delete=False,
                 author_id=10, guild=True, message_id=30, content="private body"):
        self.id = message_id
        self.channel = channel or Channel(20)
        self.author = SimpleNamespace(id=author_id)
        self.guild = SimpleNamespace(id=1, me=object(), get_channel=lambda key: detection_channel if detection_channel and key == detection_channel.id else None) if guild else None
        self.attachments = list(items)
        self.reference = SimpleNamespace(type=__import__("discord").MessageReferenceType.forward) if forward else None
        self.message_snapshots = [SimpleNamespace(attachments=list(items), embeds=[])] if forward else []
        if forward:
            self.attachments = []
        self.content = content
        self.fail_delete = fail_delete
        self.deletes = 0

    async def delete(self):
        self.deletes += 1
        if self.fail_delete:
            raise OSError("private delete failure")


def setup(tmp_path, *, enabled=True, channels=(), notifications=False, detection_channel_id=None):
    config = Config(protection_enabled=enabled, protected_channel_ids=channels,
                    notifications_enabled=notifications, detection_channel_id=detection_channel_id)
    runtime = Runtime(config, tmp_path)
    runtime.start()

    async def fetch(item):
        if item.content is None:
            raise OSError("private download failure")
        return item.content

    runtime.discord.fetch_prefix = fetch
    return runtime


def handle(runtime, message, bot_id=99):
    return asyncio.run(runtime.discord.handle_message(message, bot_id))


def assert_no_history(runtime):
    with runtime.database.connect() as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='enforcement_events'"
        ).fetchone() is None


def test_duplicate_guard_is_bounded_and_expires(tmp_path, monkeypatch):
    app = setup(tmp_path)
    clock = [100.0]
    monkeypatch.setattr("mediaguard.discord_service.time.monotonic", lambda: clock[0])
    for message_id in range(4097):
        assert app.discord._reserve_attempt(message_id)
    assert len(app.discord._attempted_messages) == 4096
    assert not app.discord._reserve_attempt(4096)
    clock[0] += 301
    assert app.discord._reserve_attempt(4096)
    assert len(app.discord._attempted_messages) == 1


@pytest.mark.parametrize("items,expected,deletes", [
    ((attachment(),), [Status.SAFE], 0),
    ((attachment("song.mp3", MP3),), [Status.MATCH], 1),
    ((attachment("one.mp3", MP3), attachment("two.wav", WAV)), [Status.MATCH, Status.MATCH], 1),
    ((attachment(), attachment("song.mp3", MP3)), [Status.SAFE, Status.MATCH], 1),
    ((attachment(), attachment("song.mp3", None, size=100)), [Status.SAFE, Status.UNAVAILABLE], 0),
    ((attachment("song.mp3", MP3), attachment("bad.mp3", None, size=100)), [Status.MATCH, Status.UNAVAILABLE], 1),
])
def test_precedence_and_single_delete(tmp_path, items, expected, deletes):
    runtime = setup(tmp_path)
    message = Message(*items)
    assert [item.status for item in handle(runtime, message)] == expected
    assert message.deletes == deletes
    assert_no_history(runtime)


def test_forward_and_duplicate_within_runtime(tmp_path):
    runtime = setup(tmp_path)
    message = Message(attachment("song.mp3", MP3), forward=True)
    assert handle(runtime, message)[0].source == "forward"
    assert message.deletes == 1
    handle(runtime, message)
    assert message.deletes == 1
    assert_no_history(runtime)


def test_discord_hook_enforces_without_network(tmp_path):
    runtime = setup(tmp_path)
    message = Message(attachment("song.mp3", MP3))

    async def run():
        client = make_client(runtime.discord)
        try:
            await client.on_message(message)
        finally:
            await client.close()

    asyncio.run(run())
    assert message.deletes == 1


def test_forward_notification_and_multiple_matches(tmp_path):
    channel = Channel(40)
    runtime = setup(tmp_path, notifications=True, detection_channel_id=40)
    message = Message(attachment("first.mp3", MP3), attachment("second.wav", WAV),
                      forward=True, detection_channel=channel)
    handle(runtime, message)
    assert message.deletes == 1
    assert len(channel.sent) == 1
    embed = channel.sent[0]["embed"]
    assert embed.fields[4].value == "Forwarded message"
    assert embed.fields[5].value == "Message deleted"
    assert embed.fields[0].value == "<@10>"
    assert embed.fields[6].value.startswith("<t:")
    assert embed.fields[6].value.endswith(":F>")
    assert channel.sent[0]["allowed_mentions"].users is False
    assert "second.wav" not in str(embed.to_dict())


def test_notification_without_filename_avatar_or_emoji(tmp_path):
    channel = Channel(40)
    runtime = setup(tmp_path, notifications=True, detection_channel_id=40)
    message = Message(attachment("song.mp3", MP3), detection_channel=channel)
    message.author.display_name = "Listener 🎵"
    message.author.display_avatar = None
    runtime.discord.fetch_prefix = lambda _: asyncio.sleep(0, result=MP3)
    message.attachments[0].filename = None
    message.attachments[0].content_type = "audio/mpeg"
    message.attachments[0].size = len(MP3)
    handle(runtime, message)
    embed = channel.sent[0]["embed"]
    assert embed.author.name == "Listener"
    assert embed.author.icon_url is None
    assert all(field.name != "File" for field in embed.fields)
    rendered = str(embed.to_dict())
    assert "🎵" not in rendered
    assert "https://cdn.discordapp.com" not in rendered
    assert "private body" not in rendered
    assert not channel.sent[0].get("file")
    audit = b"".join(path.read_bytes() for path in (tmp_path / "runtime").glob("mediaguard.sqlite3*"))
    assert MP3 not in audit
    assert b"cdn.discordapp.com" not in audit
    assert b"base64" not in audit
    assert b"private body" not in audit
    assert b"AppData" not in audit
    assert all(path.name.startswith("mediaguard.sqlite3") for path in (tmp_path / "runtime").iterdir())


def test_embed_bounds_long_names_and_uses_known_avatar():
    from datetime import datetime, timezone
    from mediaguard.attachments import InspectionResult

    message = Message()
    message.author.display_name = "A" * 500 + "🎵"
    message.author.display_avatar = SimpleNamespace(url="https://cdn.discordapp.com/avatars/synthetic.png")
    result = InspectionResult(Status.MATCH, "audio_signature", "direct", filename="B" * 500 + "🎵.mp3", media_type="mp3")
    embed = blocked_audio_embed(message, result, datetime(2026, 9, 28, 20, 47, 31, tzinfo=timezone.utc))
    assert len(embed.author.name) <= 200
    assert len(embed.fields[2].value) <= 200
    assert embed.author.icon_url.endswith("synthetic.png")
    assert embed.fields[6].value == "<t:1790628451:F>"
    assert " UTC" not in embed.fields[6].value
    assert "🎵" not in str(embed.to_dict())
    emoji_filename = InspectionResult(Status.MATCH, "audio_signature", "direct", filename="song🎵.mp3", media_type="mp3")
    assert "🎵" not in str(blocked_audio_embed(message, emoji_filename,
                                               datetime(2026, 9, 28, tzinfo=timezone.utc)).to_dict())


def test_disabled_notifications_and_unavailable_never_send(tmp_path):
    channel = Channel(40)
    runtime = setup(tmp_path, detection_channel_id=40)
    handle(runtime, Message(attachment("song.mp3", MP3), detection_channel=channel))
    assert channel.sent == []
    assert_no_history(runtime)
    enabled = setup(tmp_path / "enabled", notifications=True, detection_channel_id=40)
    uncertain = Message(attachment("song.mp3", None, size=100), detection_channel=channel)
    assert handle(enabled, uncertain)[0].status is Status.UNAVAILABLE
    assert uncertain.deletes == 0
    assert channel.sent == []


def test_detection_notification_success_and_failure(tmp_path):
    detection_channel = Channel(40)
    runtime = setup(tmp_path, notifications=True, detection_channel_id=40)
    message = Message(attachment("secret-song.mp3", MP3), detection_channel=detection_channel,
                      author_id=123456789012345678)
    message.author.display_name = "Fixture Listener"
    handle(runtime, message)
    assert_no_history(runtime)
    assert len(detection_channel.sent) == 1
    assert "private body" not in str(detection_channel.sent)
    embed = detection_channel.sent[0]["embed"]
    assert embed.color.value == 0xD94A4A
    assert embed.title == "Audio file blocked"
    assert embed.fields[2].name == "File"
    assert embed.fields[2].value == "secret-song.mp3"
    assert embed.fields[4].value == "Direct attachment"
    assert embed.fields[0].value == "<@123456789012345678>"
    assert "Fixture Listener" not in embed.fields[0].value
    assert embed.fields[1].value == "<#20>"
    assert embed.fields[6].name == "Deleted at"
    assert embed.timestamp.utcoffset().total_seconds() == 0
    assert embed.fields[6].value == f"<t:{int(embed.timestamp.timestamp())}:F>"
    assert " UTC" not in embed.fields[6].value
    allowed = detection_channel.sent[0]["allowed_mentions"]
    assert allowed.users is False
    assert allowed.everyone is False
    assert allowed.roles is False

    detection_channel.fail_send = True
    second = Message(attachment("song.mp3", MP3), detection_channel=detection_channel, message_id=31)
    handle(runtime, second)
    assert second.deletes == 1
    assert "detection_notification_failed" in str(runtime.activity.recent())
    assert_no_history(runtime)


def test_failed_delete_and_missing_permissions(tmp_path):
    detection_channel = Channel(40)
    runtime = setup(tmp_path, notifications=True, detection_channel_id=40)
    failed = Message(attachment("song.mp3", MP3), fail_delete=True, detection_channel=detection_channel)
    handle(runtime, failed)
    assert "delete_failed" in str(runtime.activity.recent())
    assert detection_channel.sent == []
    handle(runtime, failed)
    assert failed.deletes == 1
    denied = Message(attachment("song.mp3", MP3), channel=Channel(20, manage=False), message_id=31)
    handle(runtime, denied)
    assert denied.deletes == 0
    assert "delete_permission_missing" in str(runtime.activity.recent())
    assert_no_history(runtime)


@pytest.mark.parametrize("detection_channel,detection_channel_id", [(None, None), (Channel(40, send=False), 40)])
def test_notification_preflight(tmp_path, detection_channel, detection_channel_id):
    runtime = setup(tmp_path, notifications=True, detection_channel_id=detection_channel_id)
    message = Message(attachment("song.mp3", MP3), detection_channel=detection_channel)
    handle(runtime, message)
    assert message.deletes == 1
    assert "detection_notification_unavailable" in str(runtime.activity.recent())
    assert_no_history(runtime)


def test_filter_disabled_own_dm_and_privacy(tmp_path):
    runtime = setup(tmp_path, channels=(21,))
    outside = Message(attachment("song.mp3", MP3))
    assert handle(runtime, outside) == ()
    own = Message(attachment("song.mp3", MP3), channel=Channel(21), author_id=99)
    dm = Message(attachment("song.mp3", MP3), channel=Channel(21), guild=False)
    assert handle(runtime, own) == ()
    assert handle(runtime, dm) == ()
    assert_no_history(runtime)
    enabled = Message(attachment("private-name.mp3", MP3), channel=Channel(21), content="private body")
    handle(runtime, enabled)
    data = b"".join(path.read_bytes() for path in (tmp_path / "runtime").glob("mediaguard.sqlite3*"))
    assert b"private body" not in data
    assert b"private-name.mp3" not in data
    assert b"cdn.discordapp.com" not in data
    assert MP3 not in data
    disabled = setup(tmp_path / "disabled", enabled=False)
    message = Message(attachment("song.mp3", MP3))
    handle(disabled, message)
    assert message.deletes == 0


def thread(thread_id, parent_id):
    channel = Channel(thread_id)
    channel.parent_id = parent_id
    return channel


def test_thread_under_protected_channel_is_handled(tmp_path):
    runtime = setup(tmp_path, channels=(21,))
    message = Message(attachment("song.mp3", MP3), channel=thread(50, 21))
    assert handle(runtime, message)[0].status is Status.MATCH
    assert message.deletes == 1


def test_thread_under_unprotected_channel_is_ignored(tmp_path):
    runtime = setup(tmp_path, channels=(21,))
    message = Message(attachment("song.mp3", MP3), channel=thread(50, 22))
    assert handle(runtime, message) == ()
    assert message.deletes == 0


def test_forum_post_under_protected_forum_is_handled(tmp_path):
    runtime = setup(tmp_path, channels=(60,))
    message = Message(attachment("song.mp3", MP3), channel=thread(61, 60))
    assert handle(runtime, message)[0].status is Status.MATCH
    assert message.deletes == 1


def test_thread_delete_permission_uses_thread(tmp_path):
    runtime = setup(tmp_path, channels=(21,))
    denied = thread(50, 21)
    denied.permissions.manage_messages = False
    message = Message(attachment("song.mp3", MP3), channel=denied)
    handle(runtime, message)
    assert message.deletes == 0
    assert "delete_permission_missing" in str(runtime.activity.recent())


def test_config_and_read_only_api(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"protection": {"enabled": True, "channel_ids": [20], "notifications_enabled": True, "detection_channel_id": 40}}), encoding="utf-8")
    config = load(tmp_path)
    assert load(tmp_path) == config
    runtime = Runtime(config, tmp_path)
    runtime.start()
    with TestClient(create_app(runtime)) as client:
        assert client.get("/api/protection").json()["channel_ids"] == ["20"]
        assert client.get("/api/detections").status_code == 404
    path.write_text(json.dumps({"protection": {"notifications_enabled": "INVALID"}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load(tmp_path)


def test_inspection_never_writes_media_files(tmp_path):
    cases = (
        ("safe", attachment(), False, False),
        ("match", attachment("song.mp3", MP3), False, False),
        ("delete-failed", attachment("song.mp3", MP3), True, False),
        ("notify-failed", attachment("song.mp3", MP3), False, True),
    )
    for name, item, fail_delete, fail_send in cases:
        root = tmp_path / name
        destination = Channel(40, fail_send=fail_send)
        app = setup(root, notifications=True, detection_channel_id=40)
        source = Message(item, detection_channel=destination, fail_delete=fail_delete)
        handle(app, source)
        assert_no_history(app)
        assert all(path.name.startswith("mediaguard.sqlite3") for path in (root / "runtime").iterdir())

    root = tmp_path / "exception"
    app = setup(root)

    async def broken_fetch(_):
        raise RuntimeError("inspection failed")

    app.discord.fetch_prefix = broken_fetch
    with pytest.raises(RuntimeError):
        handle(app, Message(attachment("song.mp3", MP3)))
    assert_no_history(app)
    assert all(path.name.startswith("mediaguard.sqlite3") for path in (root / "runtime").iterdir())
