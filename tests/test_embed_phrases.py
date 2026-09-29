import asyncio
from types import SimpleNamespace

import discord
import pytest
from fastapi.testclient import TestClient

from mediaguard.api import create_app
from mediaguard.attachments import Status
from mediaguard.embed_phrases import match_embeds, normalize
from mediaguard.discord_service import make_client
from test_dashboard import runtime as dashboard_runtime
from test_enforcement import Channel, Message, assert_no_history, handle, setup
from test_inspection import MP3, attachment


def embed(*, title=None, description=None, fields=(), url=None):
    value = discord.Embed(title=title, description=description, url=url)
    for name, text in fields:
        value.add_field(name=name, value=text)
    return value


def rule(name="Opalite leak", phrase="the fate of opalite", rule_id="a", enabled=True):
    return {"rule_id": rule_id, "name": name, "phrase": phrase,
            "normalized_phrase": normalize(phrase), "enabled": enabled}


def message_with_embed(value, *, bot=False, webhook=False, message_id=30, forward=False):
    message = Message(channel=Channel(20), message_id=message_id, forward=forward)
    message.author.bot = bot
    message.webhook_id = 444 if webhook else None
    message.embeds = [] if forward else [value]
    if forward:
        message.message_snapshots = [SimpleNamespace(attachments=[], embeds=[value])]
    return message


def add_rule(runtime, *, guild_id=1, rule_id="a", name="Opalite leak",
             phrase="the fate of opalite", enabled=True):
    runtime.database.create_embed_rule(guild_id, rule_id, name, phrase, normalize(phrase), enabled)


@pytest.mark.parametrize("surface", [
    embed(title="Now playing: The Fate of Opalite"),
    embed(description="Now playing: The Fate of Opalite"),
    embed(fields=[("Song", "The Fate of Opalite")]),
    embed(fields=[("Other", "none"), ("Track", "The Fate of Opalite")]),
])
def test_selected_text_surfaces_match(surface):
    result = match_embeds([surface], [], [rule()])
    assert result.status is Status.MATCH
    assert result.source == "embed"
    assert result.rule_id == "a"


@pytest.mark.parametrize("surface", [
    embed(fields=[("The Fate of Opalite", "unrelated")]),
    embed(title="The Fate of OpaliteExtended"),
    embed(title="other", url="https://example.invalid/the-fate-of-opalite"),
    embed(description="https://example.invalid/the-fate-of-opalite"),
    embed(description="[other](https://example.invalid/the-fate-of-opalite)"),
    embed(description="The Fate of https://example.invalid/secret Opalite"),
    embed(description="unrelated"),
])
def test_excluded_surfaces_and_partial_words_do_not_match(surface):
    assert match_embeds([surface], [], [rule()]) is None


def test_unicode_whitespace_punctuation_and_boundaries():
    configured = rule(phrase="Café  in   Paris")
    assert match_embeds([embed(description="Now playing: CAFE\u0301\nin Paris!")], [], [configured])
    assert match_embeds([embed(description="(Café in Paris)")], [], [configured])
    assert match_embeds([embed(description="Café in Parises")], [], [configured]) is None
    assert match_embeds([embed(description="opalite")], [], [rule(phrase="opal")]) is None
    assert match_embeds([embed(description="opal, now playing")], [], [rule(phrase="opal")])


def test_multiple_embeds_rules_and_bounds():
    rules = [rule("First", "tenderness", "a"), rule("Second", "opalite", "b")]
    result = match_embeds([embed(title="Opalite"), embed(fields=[("Track", "Tenderness")])], [], rules)
    assert result.rule_id == "a"
    assert match_embeds([embed(description="x" * 4097)], [], rules) is None
    assert match_embeds([embed(fields=[("A", "x")] * 26)], [], rules) is None
    assert match_embeds([embed()] * 11, [], rules) is None
    assert match_embeds([embed()] * 6, [embed(title="Opalite")] * 5, rules) is None
    assert match_embeds([embed(description="x" * 3500)],
                        [embed(description="x" * 2500, title="Opalite")], rules) is None
    assert match_embeds([embed(fields=[("A", None)])], [], rules) is None


def test_bot_webhook_self_and_forwarded_enforcement(tmp_path, monkeypatch):
    runtime = setup(tmp_path)
    add_rule(runtime)

    def no_http(*_args, **_kwargs):
        raise AssertionError("embed detection made an HTTP request")

    monkeypatch.setattr("aiohttp.ClientSession", no_http)
    human = message_with_embed(embed(fields=[("Song", "The Fate of Opalite")]), message_id=30)
    bot = message_with_embed(embed(description="The Fate of Opalite"), bot=True, message_id=31)
    safe_bot = message_with_embed(embed(description="Unrelated song"), bot=True, message_id=32)
    webhook = message_with_embed(embed(title="The Fate of Opalite"), webhook=True, message_id=33)
    own = message_with_embed(embed(title="The Fate of Opalite"), bot=True, message_id=34)
    own.author.id = 99
    forwarded = message_with_embed(embed(fields=[("Track", "The Fate of Opalite")]),
                                   forward=True, message_id=35)
    missing = message_with_embed(embed(), forward=True, message_id=36)
    missing.message_snapshots = [SimpleNamespace(attachments=[], embeds=[])]

    for message in (human, bot, webhook, forwarded):
        assert handle(runtime, message)[0].status is Status.MATCH
        assert message.deletes == 1
    for message in (safe_bot, own, missing):
        handle(runtime, message)
        assert message.deletes == 0
    assert_no_history(runtime)


def test_bot_embed_added_after_message_creation(tmp_path):
    destination = Channel(40)
    runtime = setup(tmp_path, channels=(20,), notifications=True, detection_channel_id=40)
    add_rule(runtime, phrase="opalite")
    message = Message(channel=Channel(20), detection_channel=destination, message_id=60)
    message.author.bot = True
    message.embeds = []
    message.content = ""
    client = make_client(runtime.discord)
    client._connection.user = SimpleNamespace(id=99)

    async def run():
        try:
            await client.on_message(message)
            assert message.deletes == 0
            message.embeds = [embed(fields=[("Artist", "Taylor Swift"), ("Track", "Opalite")])]
            await client.on_message_edit(message, message)
            await client.on_message_edit(message, message)

            other = message_with_embed(embed(fields=[("Track", "Another song")]),
                                       bot=True, message_id=61)
            await client.on_message(other)
            assert other.deletes == 0

            own = message_with_embed(embed(fields=[("Track", "Opalite")]),
                                     bot=True, message_id=62)
            own.author.id = 99
            await client.on_message_edit(own, own)
            assert own.deletes == 0

            plain = Message(channel=Channel(20), message_id=63, content="opalite")
            plain.embeds = []
            await client.on_message(plain)
            assert plain.deletes == 0
        finally:
            await client.close()

    asyncio.run(run())
    assert message.deletes == 1
    assert len(destination.sent) == 1
    assert destination.sent[0]["embed"].title == "Blocked embed phrase"
    assert_no_history(runtime)


def test_rule_update_applies_without_restart(tmp_path):
    runtime = setup(tmp_path, channels=(20,))
    add_rule(runtime, phrase="opalite", enabled=False)
    first = message_with_embed(embed(fields=[("Track", "Opalite")]), bot=True, message_id=64)
    handle(runtime, first)
    assert first.deletes == 0

    runtime.database.update_embed_rule(1, "a", "Opalite leak", "opalite", normalize("opalite"), True)
    second = message_with_embed(embed(fields=[("Track", "OPALITE")]), bot=True, message_id=65)
    handle(runtime, second)
    assert second.deletes == 1

    out_of_scope = message_with_embed(embed(fields=[("Track", "Opalite")]),
                                      bot=True, message_id=66)
    out_of_scope.channel = Channel(21)
    handle(runtime, out_of_scope)
    assert out_of_scope.deletes == 0


def test_disabled_states_audio_precedence_and_duplicate(tmp_path):
    runtime = setup(tmp_path)
    add_rule(runtime, enabled=False)
    disabled_rule = message_with_embed(embed(title="The Fate of Opalite"), message_id=40)
    handle(runtime, disabled_rule)
    assert disabled_rule.deletes == 0
    runtime.database.update_embed_rule(1, "a", "Opalite leak", "the fate of opalite",
                                       normalize("the fate of opalite"), True)
    runtime.database.create_embed_rule(1, "b", "Second", "opalite", normalize("opalite"), True)
    both = message_with_embed(embed(title="The Fate of Opalite"), message_id=41)
    both.attachments = [attachment("song.mp3", MP3)]
    result = handle(runtime, both)
    assert [item.status for item in result] == [Status.MATCH]
    assert both.deletes == 1
    handle(runtime, both)
    assert both.deletes == 1
    assert result[0].media_type == "mp3"
    assert_no_history(runtime)

    off = setup(tmp_path / "off", enabled=False)
    add_rule(off)
    message = message_with_embed(embed(title="The Fate of Opalite"))
    handle(off, message)
    assert message.deletes == 0

    no_identity = message_with_embed(embed(title="The Fate of Opalite"), message_id=42)
    handle(runtime, no_identity, bot_id=None)
    assert no_identity.deletes == 0


def test_multiple_matching_embeds_still_delete_once(tmp_path):
    runtime = setup(tmp_path)
    add_rule(runtime)
    message = message_with_embed(embed(title="The Fate of Opalite"))
    message.embeds.append(embed(description="Now playing: The Fate of Opalite"))
    result = handle(runtime, message)
    assert [item.status for item in result] == [Status.MATCH]
    assert message.deletes == 1
    assert_no_history(runtime)


def test_embed_deletion_and_notification_outcomes_and_privacy(tmp_path):
    runtime = setup(tmp_path, notifications=True, detection_channel_id=40)
    add_rule(runtime, name="Opalite leak")
    destination = Channel(40)
    value = embed(description="The Fate of Opalite · private embed sentence",
                  url="https://example.invalid/secret",
                  fields=[("Other", "private field")])
    failed = message_with_embed(value, message_id=50)
    failed.fail_delete = True
    assert handle(runtime, failed)[0].status is Status.MATCH
    assert destination.sent == []

    success = message_with_embed(value, message_id=51)
    success.guild.get_channel = lambda key: destination if key == 40 else None
    handle(runtime, success)
    assert success.deletes == 1
    assert len(destination.sent) == 1
    notice = destination.sent[0]["embed"].to_dict()
    serialized = str(notice)
    assert "Opalite leak" in serialized
    assert next(field["value"] for field in notice["fields"] if field["name"] == "User") == "<@10>"
    assert all(field["name"] != "Discord user ID" for field in notice["fields"])
    assert next(field["value"] for field in notice["fields"] if field["name"] == "Deleted at").startswith("<t:")
    assert destination.sent[0]["allowed_mentions"].users is False
    assert "Forwarded embed" not in serialized
    assert "private embed sentence" not in serialized
    assert "private field" not in serialized
    assert "example.invalid" not in serialized
    assert_no_history(runtime)
    with TestClient(create_app(runtime)) as client:
        assert client.get("/api/detections").status_code == 404

    destination.fail_send = True
    notification_failed = message_with_embed(value, message_id=52)
    notification_failed.guild.get_channel = lambda key: destination if key == 40 else None
    handle(runtime, notification_failed)
    assert notification_failed.deletes == 1
    assert "detection_notification_failed" in str(runtime.activity.recent())
    assert_no_history(runtime)


def api_payload(**changes):
    value = {"guild_id": "1", "name": "Opalite leak", "phrase": "The Fate of Opalite", "enabled": True}
    value.update(changes)
    return value


def write(client, method, path, data):
    return client.request(method, path, json=data,
                          headers={"x-mediaguard-action": "save-embed-rule"})


def test_rule_api_lifecycle_scope_validation_and_retention(tmp_path):
    app = dashboard_runtime(tmp_path)
    with TestClient(create_app(app)) as client:
        assert client.get("/api/embed-rules", params={"guild_id": "1"}).json() == []
        created = write(client, "POST", "/api/embed-rules", api_payload())
        assert created.status_code == 200
        item = created.json()
        rule_id = item["rule_id"]
        assert len(rule_id) == 32
        assert "normalized_phrase" not in item
        assert client.get("/api/embed-rules", params={"guild_id": "1"}).json()[0]["phrase"] == "The Fate of Opalite"
        assert write(client, "POST", "/api/embed-rules", api_payload(phrase=" the  fate of opalite ")).status_code == 422
        assert write(client, "POST", "/api/embed-rules", api_payload(guild_id="2")).status_code == 200
        assert write(client, "POST", "/api/embed-rules", api_payload(guild_id="3")).status_code == 404
        assert write(client, "PUT", f"/api/embed-rules/{rule_id}", api_payload(guild_id="2")).status_code == 404
        for invalid in (api_payload(name=""), api_payload(name="x" * 81),
                        api_payload(phrase=" \n "), api_payload(phrase="!!!"),
                        api_payload(phrase="x" * 161),
                        api_payload(enabled="true"), api_payload(phrase="https://example.invalid"),
                        {**api_payload(), "message_body": "private"}):
            assert write(client, "POST", "/api/embed-rules", invalid).status_code == 422
        disabled = write(client, "PUT", f"/api/embed-rules/{rule_id}", api_payload(enabled=False))
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] is False
        updated = write(client, "PUT", f"/api/embed-rules/{rule_id}", api_payload(name="Renamed", phrase="Tenderness"))
        assert updated.json()["name"] == "Renamed"
        assert client.post("/api/embed-rules", json=api_payload()).status_code == 403
        assert client.delete(f"/api/embed-rules/{rule_id}", params={"guild_id": "2"},
                             headers={"x-mediaguard-action": "delete-embed-rule"}).status_code == 404

    restarted = dashboard_runtime(tmp_path)
    with TestClient(create_app(restarted)) as client:
        assert client.get("/api/embed-rules", params={"guild_id": "1"}).json()[0]["name"] == "Renamed"
        assert client.delete(f"/api/embed-rules/{rule_id}", params={"guild_id": "1"},
                             headers={"x-mediaguard-action": "delete-embed-rule"}).json() == {"deleted": True}
        assert client.get("/api/embed-rules", params={"guild_id": "1"}).json() == []


def test_event_is_forgotten_while_rule_configuration_persists(tmp_path):
    runtime = setup(tmp_path)
    add_rule(runtime)
    add_rule(runtime, rule_id="b", name="Retained rule", phrase="another song")
    source = message_with_embed(embed(description="The Fate of Opalite · hidden source content"))
    handle(runtime, source)
    assert source.deletes == 1
    assert_no_history(runtime)
    restarted = setup(tmp_path)
    assert {rule["name"] for rule in restarted.database.embed_rules(1)} == {
        "Opalite leak", "Retained rule"
    }


def test_no_external_http_for_embeds(tmp_path, monkeypatch):
    runtime = setup(tmp_path)
    add_rule(runtime)
    monkeypatch.setattr("aiohttp.ClientSession", lambda *_a, **_k: pytest.fail("unexpected HTTP"))
    message = message_with_embed(embed(description="The Fate of Opalite"))
    handle(runtime, message)
    assert message.deletes == 1
