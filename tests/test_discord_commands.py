import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from mediaguard.api import create_app
from mediaguard.config import Config
from mediaguard.discord_service import make_client
from mediaguard.runtime import Runtime
from test_dashboard import GUILDS, payload, save


class Response:
    def __init__(self):
        self.messages = []
        self.edits = []

    async def send_message(self, content, **kwargs):
        self.messages.append((content, kwargs))

    async def edit_message(self, **kwargs):
        self.edits.append(kwargs)


class Interaction:
    def __init__(self, guild, *, permitted=True, user_id=100):
        self.guild = guild
        self.guild_id = guild.id if guild else None
        self.user = SimpleNamespace(id=user_id)
        self.permissions = SimpleNamespace(manage_guild=permitted)
        self.response = Response()
        self.original_edits = []

    async def edit_original_response(self, **kwargs):
        self.original_edits.append(kwargs)


@pytest.fixture
def command_app(tmp_path):
    app = Runtime(Config(), tmp_path)
    app.start()
    app.discord.inventory = lambda: GUILDS
    app.discord.guild_inventory = lambda guild: next(item for item in GUILDS if item["id"] == str(guild.id))
    channels = {int(item["id"]): SimpleNamespace(id=int(item["id"]),
                                                 mention=f"<#{item['id']}>") for item in GUILDS[0]["channels"]}
    roles = {int(item["id"]): SimpleNamespace(id=int(item["id"]),
                                              mention=f"<@&{item['id']}>") for item in GUILDS[0]["roles"]}
    guild = SimpleNamespace(id=1, get_channel=channels.get, get_role=roles.get)
    client = make_client(app.discord)
    yield app, client, guild
    asyncio.run(client.close())


def invoke(client, group, command, interaction, **options):
    callback = client.tree.get_command(group).get_command(command).callback
    asyncio.run(callback(interaction, **options))
    if interaction.response.messages:
        assert interaction.response.messages[-1][1]["ephemeral"] is True


def press(view, label, interaction):
    async def dispatch():
        if await view.interaction_check(interaction):
            button = next(item for item in view.children if item.label == label)
            await button.callback(interaction)
    asyncio.run(dispatch())


def settings(app):
    return app.database.protection_for(1, app.config)


def test_tree_declares_manage_guild_and_guild_only(command_app):
    _, client, _ = command_app
    assert {group.name for group in client.tree.get_commands()} == {
        "protection", "protection-channels", "exempt-role", "moderation-mode",
        "detection-notifications", "detection-channel", "unconfirmed", "blocked-phrase",
    }
    assert all(group.default_permissions.manage_guild and group.guild_only
               for group in client.tree.get_commands())
    assert all(group.to_dict(client.tree)["default_member_permissions"] == 32
               for group in client.tree.get_commands())
    assert client.intents.message_content
    assert not client.intents.members
    assert not client.intents.presences


def test_command_tree_syncs_during_client_setup(command_app):
    _, client, _ = command_app
    client.tree.sync = AsyncMock(return_value=[])
    asyncio.run(client.setup_hook())
    client.tree.sync.assert_awaited_once_with()


def test_unauthorized_and_dm_commands_cannot_read_or_mutate(command_app):
    app, client, guild = command_app
    denied = Interaction(guild, permitted=False)
    invoke(client, "protection", "enable", denied)
    assert settings(app)["enabled"] is False
    assert "Manage Server" in denied.response.messages[-1][0]
    denied_status = Interaction(guild, permitted=False)
    invoke(client, "protection", "status", denied_status)
    assert "Manage Server" in denied_status.response.messages[-1][0]
    dm = Interaction(None)
    invoke(client, "protection", "enable", dm)
    assert "server" in dm.response.messages[-1][0]
    assert settings(app)["enabled"] is False


def test_protection_and_dashboard_share_settings(command_app):
    app, client, guild = command_app
    invoke(client, "protection", "enable", Interaction(guild))
    with TestClient(create_app(app)) as web:
        assert web.get("/api/protection", params={"guild_id": "1"}).json()["enabled"] is True
        assert save(web, payload(enabled=False)).status_code == 200
    status = Interaction(guild)
    invoke(client, "protection", "status", status)
    assert "Protection: Disabled" in status.response.messages[-1][0]
    invoke(client, "protection", "enable", Interaction(guild))
    invoke(client, "protection", "disable", Interaction(guild))
    assert settings(app)["enabled"] is False


def test_status_and_channel_selection(command_app):
    app, client, guild = command_app
    selected = SimpleNamespace(id=11, guild=guild)
    invoke(client, "protection-channels", "add", Interaction(guild), channel=selected)
    assert settings(app)["channel_ids"] == (11,)
    listed = Interaction(guild)
    invoke(client, "protection-channels", "list", listed)
    assert "<#11>" in listed.response.messages[-1][0]
    duplicate = Interaction(guild)
    invoke(client, "protection-channels", "add", duplicate, channel=selected)
    assert "already" in duplicate.response.messages[-1][0]
    last = Interaction(guild)
    invoke(client, "protection-channels", "remove", last, channel=selected)
    assert "last selected" in last.response.messages[-1][0]
    invoke(client, "protection-channels", "add", Interaction(guild),
           channel=SimpleNamespace(id=12, guild=guild))
    invoke(client, "protection-channels", "remove", Interaction(guild), channel=selected)
    assert settings(app)["channel_ids"] == (12,)
    invoke(client, "protection-channels", "all", Interaction(guild))
    assert settings(app)["channel_ids"] == ()
    foreign = Interaction(guild)
    invoke(client, "protection-channels", "add", foreign,
           channel=SimpleNamespace(id=21, guild=SimpleNamespace(id=2)))
    assert "another server" in foreign.response.messages[-1][0]


def test_exempt_roles_and_cross_guild_role(command_app):
    app, client, guild = command_app
    role = SimpleNamespace(id=70, guild=guild)
    invoke(client, "exempt-role", "add", Interaction(guild), role=role)
    assert settings(app)["exempt_role_ids"] == (70,)
    listed = Interaction(guild)
    invoke(client, "exempt-role", "list", listed)
    assert "<@&70>" in listed.response.messages[-1][0]
    foreign = Interaction(guild)
    invoke(client, "exempt-role", "add", foreign,
           role=SimpleNamespace(id=72, guild=SimpleNamespace(id=2)))
    assert "another server" in foreign.response.messages[-1][0]
    invoke(client, "exempt-role", "remove", Interaction(guild), role=role)
    assert settings(app)["exempt_role_ids"] == ()


def test_warn_only_validation_and_notifications(command_app):
    app, client, guild = command_app
    invoke(client, "protection", "enable", Interaction(guild))
    rejected = Interaction(guild)
    invoke(client, "moderation-mode", "warn-only", rejected)
    assert "requires Detection notifications" in rejected.response.messages[-1][0]
    assert settings(app)["moderation_mode"] == "auto_delete"
    missing = Interaction(guild)
    invoke(client, "detection-notifications", "enable", missing)
    assert "Select a Detection channel" in missing.response.messages[-1][0]
    invoke(client, "detection-channel", "set", Interaction(guild),
           channel=SimpleNamespace(id=13, guild=guild))
    invoke(client, "detection-notifications", "enable", Interaction(guild))
    invoke(client, "moderation-mode", "warn-only", Interaction(guild))
    assert settings(app)["moderation_mode"] == "warn_only"
    blocked = Interaction(guild)
    invoke(client, "detection-notifications", "disable", blocked)
    assert "requires Detection notifications" in blocked.response.messages[-1][0]
    assert settings(app)["notifications_enabled"] is True


def test_detection_channel_ownership_and_clearing(command_app):
    app, client, guild = command_app
    foreign = Interaction(guild)
    invoke(client, "detection-channel", "set", foreign,
           channel=SimpleNamespace(id=21, guild=SimpleNamespace(id=2)))
    assert "another server" in foreign.response.messages[-1][0]
    unavailable = Interaction(guild)
    invoke(client, "detection-channel", "set", unavailable,
           channel=SimpleNamespace(id=12, guild=guild))
    assert "unavailable" in unavailable.response.messages[-1][0]
    invoke(client, "detection-channel", "set", Interaction(guild),
           channel=SimpleNamespace(id=13, guild=guild))
    assert settings(app)["detection_channel_id"] == 13
    invoke(client, "detection-channel", "clear", Interaction(guild))
    assert settings(app)["detection_channel_id"] is None


def test_unconfirmed_actions(command_app):
    app, client, guild = command_app
    invoke(client, "unconfirmed", "report", Interaction(guild))
    assert settings(app)["unresolved_action"] == "report"
    invoke(client, "unconfirmed", "allow", Interaction(guild))
    assert settings(app)["unresolved_action"] == "allow"


def test_auto_delete_confirmation_binding_cancel_and_stale_config(command_app):
    app, client, guild = command_app
    app.database.save_protection(1, True, [], True, 13, (), "allow", "warn_only")
    initial = Interaction(guild)
    invoke(client, "moderation-mode", "auto-delete", initial)
    view = initial.response.messages[-1][1]["view"]
    assert view.timeout == 60
    assert settings(app)["moderation_mode"] == "warn_only"
    wrong = Interaction(guild, user_id=101)
    press(view, "Enable Auto Delete", wrong)
    assert "Only the person" in wrong.response.messages[-1][0]
    assert settings(app)["moderation_mode"] == "warn_only"
    foreign_guild = Interaction(SimpleNamespace(id=2), user_id=100)
    press(view, "Enable Auto Delete", foreign_guild)
    assert "another server" in foreign_guild.response.messages[-1][0]
    assert settings(app)["moderation_mode"] == "warn_only"
    lost = Interaction(guild, permitted=False)
    press(view, "Enable Auto Delete", lost)
    assert "Manage Server" in lost.response.messages[-1][0]
    assert settings(app)["moderation_mode"] == "warn_only"
    app.database.save_protection(1, False, [11], True, 13, (70,), "report", "warn_only")
    confirmed = Interaction(guild)
    press(view, "Enable Auto Delete", confirmed)
    assert confirmed.response.edits[-1]["view"] is None
    assert settings(app) == {"enabled": False, "channel_ids": (11,), "notifications_enabled": True,
                             "detection_channel_id": 13, "exempt_role_ids": (70,),
                             "unresolved_action": "report", "moderation_mode": "auto_delete"}
    app.database.save_protection(1, False, [11], True, 13, (70,), "report", "warn_only")
    second = Interaction(guild)
    invoke(client, "moderation-mode", "auto-delete", second)
    cancelled = Interaction(guild)
    press(second.response.messages[-1][1]["view"], "Cancel", cancelled)
    assert settings(app)["moderation_mode"] == "warn_only"
    timed_out = Interaction(guild)
    invoke(client, "moderation-mode", "auto-delete", timed_out)
    expired_view = timed_out.response.messages[-1][1]["view"]
    asyncio.run(expired_view.on_timeout())
    assert all(button.disabled for button in expired_view.children)
    assert settings(app)["moderation_mode"] == "warn_only"


def test_blocked_phrase_commands_and_api_parity(command_app):
    app, client, guild = command_app
    invoke(client, "blocked-phrase", "add", Interaction(guild), phrase=" Opalite ")
    rules = app.database.embed_rules(1)
    assert rules[0]["normalized_phrase"] == "opalite"
    duplicate = Interaction(guild)
    invoke(client, "blocked-phrase", "add", duplicate, phrase="opalite")
    assert "already exists" in duplicate.response.messages[-1][0]
    invalid = Interaction(guild)
    invoke(client, "blocked-phrase", "add", invalid, phrase="https://example.com")
    assert "Invalid blocked phrase" in invalid.response.messages[-1][0]
    listed = Interaction(guild)
    invoke(client, "blocked-phrase", "list", listed)
    assert "Opalite" in listed.response.messages[-1][0]
    invoke(client, "blocked-phrase", "disable", Interaction(guild), phrase="opalite")
    assert not app.database.embed_rules(1)[0]["enabled"]
    invoke(client, "blocked-phrase", "enable", Interaction(guild), phrase="opalite")
    assert app.database.embed_rules(1)[0]["enabled"]
    with TestClient(create_app(app)) as web:
        assert web.get("/api/embed-rules", params={"guild_id": "1"}).json()[0]["phrase"] == "Opalite"
        added = web.post("/api/embed-rules", json={"guild_id": "1", "name": "Second",
                                                      "phrase": "second phrase", "enabled": True},
                         headers={"x-mediaguard-action": "save-embed-rule"})
        assert added.status_code == 200
    listed_again = Interaction(guild)
    invoke(client, "blocked-phrase", "list", listed_again)
    assert "second phrase" in listed_again.response.messages[-1][0]
    status = Interaction(guild)
    invoke(client, "protection", "status", status)
    assert "Blocked embed phrases: 2" in status.response.messages[-1][0]
    invoke(client, "blocked-phrase", "remove", Interaction(guild), phrase="opalite")
    assert [rule["phrase"] for rule in app.database.embed_rules(1)] == ["second phrase"]


def test_command_validation_cannot_bypass_dashboard_rules(command_app):
    app, client, guild = command_app
    app.database.save_protection(1, True, [], False, None)
    rejected = Interaction(guild)
    invoke(client, "moderation-mode", "warn-only", rejected)
    assert "requires Detection notifications" in rejected.response.messages[-1][0]
    assert settings(app)["moderation_mode"] == "auto_delete"
