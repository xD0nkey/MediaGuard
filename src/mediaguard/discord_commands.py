import discord
from discord import app_commands

from .configuration import (ConfigurationError, change_protection, delete_phrase,
                            phrase_by_text, save_phrase, set_phrase_enabled)


async def _send(interaction, content, *, view=None):
    await interaction.response.send_message(
        content, ephemeral=True, view=view, allowed_mentions=discord.AllowedMentions.none()
    )


async def _authorized(interaction):
    if interaction.guild is None or interaction.guild_id != interaction.guild.id:
        await _send(interaction, "MediaGuard admin commands can only be used in a server.")
        return False
    if not getattr(interaction.permissions, "manage_guild", False):
        await _send(interaction, "You need Manage Server permission to use MediaGuard admin commands.")
        return False
    return True


def _inventory(service, guild):
    return service.guild_inventory(guild)


async def _change(interaction, service, confirmation, *, transform=None, **changes):
    if not await _authorized(interaction):
        return
    try:
        change_protection(service.database, service.config, _inventory(service, interaction.guild),
                          transform=transform, **changes)
    except ConfigurationError as error:
        await _send(interaction, str(error))
        return
    except Exception:
        service.activity.record("Error", "discord_command_failed")
        await _send(interaction, "Could not update MediaGuard settings.")
        return
    service.activity.record("Discord", "protection_configuration_saved")
    await _send(interaction, confirmation)


async def _settings(interaction, service):
    if not await _authorized(interaction):
        return None
    try:
        return service.database.protection_for(interaction.guild.id, service.config)
    except Exception:
        service.activity.record("Error", "discord_command_failed")
        await _send(interaction, "Could not load MediaGuard settings.")
        return None


def _add_id(data, field, value, label):
    if value in data[field]:
        raise ConfigurationError(f"That {label} is already configured.")
    return {field: [*data[field], value]}


def _remove_id(data, field, value, label):
    if value not in data[field]:
        raise ConfigurationError(f"That {label} is not configured.")
    remaining = [item for item in data[field] if item != value]
    if field == "channel_ids" and not remaining:
        raise ConfigurationError("The last selected channel cannot be removed. Use /protection-channels all instead.")
    return {field: remaining}


def _channel_text(guild, ids):
    if not ids:
        return "All relevant channels"
    channels = [guild.get_channel(int(value)) for value in ids]
    labels = [channel.mention if channel else "Unavailable channel" for channel in channels[:10]]
    if len(channels) > 10:
        labels.append(f"+{len(channels) - 10} more")
    return ", ".join(labels)


def _role_text(guild, ids):
    if not ids:
        return "None"
    roles = [guild.get_role(int(value)) for value in ids]
    labels = [role.mention if role else "Unavailable role" for role in roles[:10]]
    if len(roles) > 10:
        labels.append(f"+{len(roles) - 10} more")
    return ", ".join(labels)


def _status(guild, settings, rule_count):
    detection = guild.get_channel(settings["detection_channel_id"]) if settings["detection_channel_id"] else None
    return "\n".join((
        f"Protection: {'Enabled' if settings['enabled'] else 'Disabled'}",
        f"Protected channels: {_channel_text(guild, settings['channel_ids'])}",
        f"Moderation mode: {'Warn / Log Only' if settings['moderation_mode'] == 'warn_only' else 'Auto Delete'}",
        f"Detection notifications: {'Enabled' if settings['notifications_enabled'] else 'Disabled'}",
        f"Detection channel: {detection.mention if detection else 'Not configured or unavailable'}",
        f"Unconfirmed audio: {settings['unresolved_action'].title()}",
        f"Exempt roles (audio only): {_role_text(guild, settings['exempt_role_ids'])}",
        f"Blocked embed phrases: {rule_count}",
    ))[:1900]


class AutoDeleteConfirmation(discord.ui.View):
    def __init__(self, service, interaction):
        super().__init__(timeout=60)
        self.service = service
        self.initial_interaction = interaction
        self.user_id = interaction.user.id
        self.guild_id = interaction.guild_id

    async def interaction_check(self, interaction):
        if interaction.user.id != self.user_id:
            await _send(interaction, "Only the person who requested this change can confirm it.")
            return False
        return True

    @discord.ui.button(label="Enable Auto Delete", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, _button):
        if not await _authorized(interaction):
            return
        if interaction.guild_id != self.guild_id:
            await _send(interaction, "This confirmation belongs to another server.")
            return
        try:
            change_protection(self.service.database, self.service.config,
                              _inventory(self.service, interaction.guild), moderation_mode="auto_delete")
        except ConfigurationError as error:
            await _send(interaction, str(error))
            return
        except Exception:
            self.service.activity.record("Error", "discord_command_failed")
            await _send(interaction, "Could not update MediaGuard settings.")
            return
        self.service.activity.record("Discord", "protection_configuration_saved")
        self.stop()
        await interaction.response.edit_message(content="Moderation mode updated: Auto Delete.", view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, _button):
        self.stop()
        await interaction.response.edit_message(content="Auto Delete was not enabled.", view=None)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.initial_interaction.edit_original_response(view=self)
        except Exception:
            self.service.activity.record("Error", "discord_confirmation_expired")


def register_commands(tree, service):
    permissions = discord.Permissions(manage_guild=True)

    def group(name, description):
        command_group = app_commands.Group(name=name, description=description,
                                           guild_only=True, default_permissions=permissions)
        tree.add_command(command_group)
        return command_group

    protection = group("protection", "Configure MediaGuard message protection")

    @protection.command(name="status", description="Show this server's MediaGuard settings")
    async def protection_status(interaction: discord.Interaction):
        settings = await _settings(interaction, service)
        if settings is None:
            return
        try:
            count = len(service.database.embed_rules(interaction.guild.id))
            await _send(interaction, _status(interaction.guild, settings, count))
        except Exception:
            service.activity.record("Error", "discord_command_failed")
            await _send(interaction, "Could not load MediaGuard settings.")

    @protection.command(name="enable", description="Enable message protection")
    async def protection_enable(interaction: discord.Interaction):
        await _change(interaction, service, "Protection enabled.", enabled=True)

    @protection.command(name="disable", description="Disable message protection")
    async def protection_disable(interaction: discord.Interaction):
        await _change(interaction, service, "Protection disabled.", enabled=False)

    channels = group("protection-channels", "Choose channels MediaGuard protects")

    @channels.command(name="all", description="Protect all relevant channels")
    async def channels_all(interaction: discord.Interaction):
        await _change(interaction, service, "All relevant channels are protected.", channel_ids=[])

    @channels.command(name="add", description="Add a protected text or forum channel")
    async def channels_add(interaction: discord.Interaction, channel: discord.TextChannel | discord.ForumChannel):
        if not await _authorized(interaction):
            return
        if getattr(channel.guild, "id", None) != interaction.guild_id:
            await _send(interaction, "That channel belongs to another server.")
            return
        await _change(interaction, service, "Protected channel added.",
                      transform=lambda data: _add_id(data, "channel_ids", str(channel.id), "channel"))

    @channels.command(name="remove", description="Remove a selected protected channel")
    async def channels_remove(interaction: discord.Interaction, channel: discord.TextChannel | discord.ForumChannel):
        if not await _authorized(interaction):
            return
        if getattr(channel.guild, "id", None) != interaction.guild_id:
            await _send(interaction, "That channel belongs to another server.")
            return
        await _change(interaction, service, "Protected channel removed.",
                      transform=lambda data: _remove_id(data, "channel_ids", str(channel.id), "channel"))

    @channels.command(name="list", description="Show protected channels")
    async def channels_list(interaction: discord.Interaction):
        settings = await _settings(interaction, service)
        if settings is not None:
            await _send(interaction, f"Protected channels: {_channel_text(interaction.guild, settings['channel_ids'])}"[:1900])

    roles = group("exempt-role", "Configure audio exemption roles")

    @roles.command(name="add", description="Exempt a role from audio enforcement")
    async def roles_add(interaction: discord.Interaction, role: discord.Role):
        if not await _authorized(interaction):
            return
        if getattr(role.guild, "id", None) != interaction.guild_id:
            await _send(interaction, "That role belongs to another server.")
            return
        await _change(interaction, service, "Exempt role added.",
                      transform=lambda data: _add_id(data, "exempt_role_ids", str(role.id), "role"))

    @roles.command(name="remove", description="Remove an audio exemption role")
    async def roles_remove(interaction: discord.Interaction, role: discord.Role):
        if not await _authorized(interaction):
            return
        if getattr(role.guild, "id", None) != interaction.guild_id:
            await _send(interaction, "That role belongs to another server.")
            return
        await _change(interaction, service, "Exempt role removed.",
                      transform=lambda data: _remove_id(data, "exempt_role_ids", str(role.id), "role"))

    @roles.command(name="list", description="Show audio exemption roles")
    async def roles_list(interaction: discord.Interaction):
        settings = await _settings(interaction, service)
        if settings is not None:
            await _send(interaction, f"Exempt roles (audio only): {_role_text(interaction.guild, settings['exempt_role_ids'])}"[:1900])

    modes = group("moderation-mode", "Choose how MediaGuard handles matches")

    @modes.command(name="warn-only", description="Report matches without deleting messages")
    async def mode_warn(interaction: discord.Interaction):
        await _change(interaction, service,
                      "Moderation mode updated: Warn / Log Only. Matches will be reported without automatic deletion.",
                      moderation_mode="warn_only")

    @modes.command(name="auto-delete", description="Enable automatic deletion after confirmation")
    async def mode_auto(interaction: discord.Interaction):
        settings = await _settings(interaction, service)
        if settings is None:
            return
        if settings["moderation_mode"] == "auto_delete":
            await _send(interaction, "Auto Delete is already enabled.")
            return
        view = AutoDeleteConfirmation(service, interaction)
        await _send(interaction,
                    "Enable Auto Delete? MediaGuard will automatically delete messages containing media that matches the configured moderation policy.",
                    view=view)

    notifications = group("detection-notifications", "Configure Detection channel reports")

    @notifications.command(name="enable", description="Enable Detection channel reports")
    async def notifications_enable(interaction: discord.Interaction):
        await _change(interaction, service, "Detection notifications enabled.", notifications_enabled=True)

    @notifications.command(name="disable", description="Disable Detection channel reports")
    async def notifications_disable(interaction: discord.Interaction):
        await _change(interaction, service, "Detection notifications disabled.",
                      notifications_enabled=False, detection_channel_id=None)

    detection = group("detection-channel", "Choose the Detection notification channel")

    @detection.command(name="set", description="Set a Detection text channel")
    async def detection_set(interaction: discord.Interaction, channel: discord.TextChannel):
        if not await _authorized(interaction):
            return
        if getattr(channel.guild, "id", None) != interaction.guild_id:
            await _send(interaction, "That channel belongs to another server.")
            return
        await _change(interaction, service, "Detection channel updated.", detection_channel_id=str(channel.id))

    @detection.command(name="clear", description="Clear the Detection channel when notifications are off")
    async def detection_clear(interaction: discord.Interaction):
        await _change(interaction, service, "Detection channel cleared.", detection_channel_id=None)

    unconfirmed = group("unconfirmed", "Choose how inconclusive audio is handled")

    @unconfirmed.command(name="allow", description="Allow inconclusive audio without a report")
    async def unconfirmed_allow(interaction: discord.Interaction):
        await _change(interaction, service, "Unconfirmed audio will be allowed.", unresolved_action="allow")

    @unconfirmed.command(name="report", description="Report inconclusive audio to Detection")
    async def unconfirmed_report(interaction: discord.Interaction):
        await _change(interaction, service, "Unconfirmed audio will be reported.", unresolved_action="report")

    phrases = group("blocked-phrase", "Configure blocked embed phrases")

    async def phrase_action(interaction, action, phrase):
        if not await _authorized(interaction):
            return
        try:
            if action == "add":
                save_phrase(service.database, interaction.guild_id, phrase.strip()[:80], phrase, True)
                confirmation = "Blocked phrase added."
            else:
                with service.database.mutation_lock:
                    rule = phrase_by_text(service.database, interaction.guild_id, phrase)
                    if action == "remove":
                        delete_phrase(service.database, interaction.guild_id, rule["rule_id"])
                        confirmation = "Blocked phrase removed."
                    else:
                        set_phrase_enabled(service.database, interaction.guild_id, rule["rule_id"], action == "enable")
                        confirmation = f"Blocked phrase {'enabled' if action == 'enable' else 'disabled'}."
        except ConfigurationError as error:
            await _send(interaction, str(error))
            return
        except Exception:
            service.activity.record("Error", "discord_command_failed")
            await _send(interaction, "Could not update blocked phrases.")
            return
        service.activity.record("Discord", "embed_rule_saved")
        await _send(interaction, confirmation)

    @phrases.command(name="add", description="Block a phrase in embed text")
    async def phrases_add(interaction: discord.Interaction, phrase: str):
        await phrase_action(interaction, "add", phrase)

    @phrases.command(name="remove", description="Remove a blocked embed phrase")
    async def phrases_remove(interaction: discord.Interaction, phrase: str):
        await phrase_action(interaction, "remove", phrase)

    @phrases.command(name="enable", description="Enable an existing blocked phrase")
    async def phrases_enable(interaction: discord.Interaction, phrase: str):
        await phrase_action(interaction, "enable", phrase)

    @phrases.command(name="disable", description="Disable an existing blocked phrase")
    async def phrases_disable(interaction: discord.Interaction, phrase: str):
        await phrase_action(interaction, "disable", phrase)

    @phrases.command(name="list", description="Show blocked embed phrases")
    async def phrases_list(interaction: discord.Interaction):
        if not await _authorized(interaction):
            return
        try:
            rules = service.database.embed_rules(interaction.guild_id)
            lines = [f"{index}. {rule['phrase']} ({'enabled' if rule['enabled'] else 'disabled'})"
                     for index, rule in enumerate(rules, 1)]
            output = "Blocked embed phrases:\n" + ("\n".join(lines) if lines else "None")
            await _send(interaction, output[:1900])
        except Exception:
            service.activity.record("Error", "discord_command_failed")
            await _send(interaction, "Could not load blocked phrases.")
