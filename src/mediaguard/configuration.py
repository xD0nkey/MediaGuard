import sqlite3
import uuid

from .embed_phrases import normalize


PROTECTION_FIELDS = {"guild_id", "enabled", "channel_ids", "notifications_enabled",
                     "detection_channel_id", "exempt_role_ids", "unresolved_action", "moderation_mode"}
UNRESOLVED_ACTIONS = {"allow", "report"}
MODERATION_MODES = {"warn_only", "auto_delete"}


class ConfigurationError(ValueError):
    pass


def discord_id(value):
    if (not isinstance(value, str) or not value.isascii() or not value.isdecimal()
            or len(value) > 20 or not 0 < int(value) <= 2**64 - 1):
        raise ConfigurationError("Invalid Discord ID")
    return int(value)


def protection_data(guild_id, settings):
    return {"guild_id": str(guild_id), "enabled": settings["enabled"],
            "channel_ids": [str(value) for value in settings["channel_ids"]],
            "notifications_enabled": settings["notifications_enabled"],
            "detection_channel_id": str(settings["detection_channel_id"]) if settings["detection_channel_id"] else None,
            "exempt_role_ids": [str(value) for value in settings["exempt_role_ids"]],
            "unresolved_action": settings["unresolved_action"],
            "moderation_mode": settings["moderation_mode"]}


def validate_protection(guild, data):
    if not isinstance(data, dict) or set(data) != PROTECTION_FIELDS:
        raise ConfigurationError("Invalid configuration")
    guild_id = discord_id(data["guild_id"])
    if str(guild_id) != guild["id"]:
        raise ConfigurationError("Guild unavailable")
    if type(data["enabled"]) is not bool or type(data["notifications_enabled"]) is not bool:
        raise ConfigurationError("Invalid protection state")
    channel_ids = data["channel_ids"]
    if not isinstance(channel_ids, list) or len(channel_ids) > 500:
        raise ConfigurationError("Invalid protected channels")
    selected = [discord_id(value) for value in channel_ids]
    if len(selected) != len(set(selected)):
        raise ConfigurationError("Duplicate protected channel")
    if not isinstance(data["unresolved_action"], str) or data["unresolved_action"] not in UNRESOLVED_ACTIONS:
        raise ConfigurationError("Invalid unresolved action")
    if not isinstance(data["moderation_mode"], str) or data["moderation_mode"] not in MODERATION_MODES:
        raise ConfigurationError("Invalid moderation mode")
    role_ids = data["exempt_role_ids"]
    if not isinstance(role_ids, list) or len(role_ids) > 50:
        raise ConfigurationError("Invalid exempt roles")
    exempt_roles = [discord_id(value) for value in role_ids]
    if len(exempt_roles) != len(set(exempt_roles)):
        raise ConfigurationError("Duplicate exempt role")
    detection_id = discord_id(data["detection_channel_id"]) if data["detection_channel_id"] is not None else None
    if data["notifications_enabled"] and detection_id is None:
        raise ConfigurationError("Select a Detection channel")
    if data["enabled"] and data["moderation_mode"] == "warn_only" and not data["notifications_enabled"]:
        raise ConfigurationError("Warn / Log Only requires Detection notifications")
    protected = {int(channel["id"]) for channel in guild["channels"] if channel["can_protect"]}
    notification_channels = {int(channel["id"]) for channel in guild["channels"] if channel["can_notify"]}
    if not set(selected) <= protected or (data["enabled"] and not protected and not selected):
        raise ConfigurationError("Protected channel unavailable")
    if detection_id is not None and detection_id not in notification_channels:
        raise ConfigurationError("Detection channel unavailable")
    if not set(exempt_roles) <= {int(role["id"]) for role in guild["roles"]}:
        raise ConfigurationError("Exempt role unavailable")
    return guild_id, selected, detection_id, exempt_roles


def save_protection(database, config, guild, data):
    with database.mutation_lock:
        guild_id, selected, detection_id, exempt_roles = validate_protection(guild, data)
        database.save_protection(guild_id, data["enabled"], selected, data["notifications_enabled"],
                                 detection_id, exempt_roles, data["unresolved_action"], data["moderation_mode"])
        return database.protection_for(guild_id, config)


def change_protection(database, config, guild, *, transform=None, **changes):
    with database.mutation_lock:
        data = protection_data(guild["id"], database.protection_for(guild["id"], config))
        if transform is not None:
            changes.update(transform(data))
        if not changes or not set(changes) <= PROTECTION_FIELDS - {"guild_id"}:
            raise ConfigurationError("Invalid configuration")
        data.update(changes)
        return save_protection(database, config, guild, data)


def validate_phrase(name, phrase, enabled):
    if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 80
            or not isinstance(phrase, str) or not 1 <= len(phrase.strip()) <= 160
            or type(enabled) is not bool):
        raise ConfigurationError("Invalid rule")
    name, phrase = name.strip(), phrase.strip()
    normalized = normalize(phrase)
    if (not normalized or not any(char.isalnum() for char in normalized)
            or "http://" in normalized or "https://" in normalized):
        raise ConfigurationError("Invalid blocked phrase")
    return name, phrase, normalized


def save_phrase(database, guild_id, name, phrase, enabled, rule_id=None):
    name, phrase, normalized = validate_phrase(name, phrase, enabled)
    with database.mutation_lock:
        if rule_id is None:
            rule_id = uuid.uuid4().hex
            try:
                database.create_embed_rule(guild_id, rule_id, name, phrase, normalized, enabled)
            except sqlite3.IntegrityError:
                raise ConfigurationError("Blocked phrase already exists in this server") from None
            except ValueError as error:
                raise ConfigurationError(str(error)) from None
        else:
            existing = next((rule for rule in database.embed_rules(guild_id) if rule["rule_id"] == rule_id), None)
            if existing and existing["name"] == name and existing["phrase"] == phrase:
                set_phrase_enabled(database, guild_id, rule_id, enabled)
            else:
                try:
                    updated = database.update_embed_rule(guild_id, rule_id, name, phrase, normalized, enabled)
                except sqlite3.IntegrityError:
                    raise ConfigurationError("Blocked phrase already exists in this server") from None
                if not updated:
                    raise ConfigurationError("Rule unavailable")
        return next(rule for rule in database.embed_rules(guild_id) if rule["rule_id"] == rule_id)


def delete_phrase(database, guild_id, rule_id):
    with database.mutation_lock:
        if not database.delete_embed_rule(guild_id, rule_id):
            raise ConfigurationError("Rule unavailable")


def phrase_by_text(database, guild_id, phrase):
    if not isinstance(phrase, str):
        raise ConfigurationError("Rule unavailable")
    normalized = normalize(phrase)
    rule = next((item for item in database.embed_rules(guild_id)
                 if item["normalized_phrase"] == normalized), None)
    if rule is None:
        raise ConfigurationError("Rule unavailable")
    return rule


def set_phrase_enabled(database, guild_id, rule_id, enabled):
    with database.mutation_lock:
        if type(enabled) is not bool or not database.set_embed_rule_enabled(guild_id, rule_id, enabled):
            raise ConfigurationError("Rule unavailable")
