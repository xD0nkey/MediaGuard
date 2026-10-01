# MediaGuard Discord Permissions

Grant MediaGuard only the permissions needed in the channels it monitors and uses for Detection notifications. Channel and category overrides can change the bot's effective permissions.

## Required bot permissions

| Permission | Why MediaGuard needs it |
| --- | --- |
| View Channels | Receive messages in monitored channels and access the configured Detection channel. |
| Send Messages | Send Detection notifications to the configured channel. |
| Embed Links | Send Detection notifications as rich Discord embeds. |
| Manage Messages | Delete prohibited source messages in Auto Delete mode. |

These permissions must be effective in the relevant channels. MediaGuard does not require Administrator. Its current notification path does not upload files, add reactions, reply to messages, or read message history.

## Detection channel

In the configured Detection channel, MediaGuard needs effective **View Channel**, **Send Messages**, and **Embed Links** permissions. Detection notifications contain one rich embed and no uploaded file.

In a production incident, Discord rejected Detection notifications with **403 / 50013 Missing Permissions** while View Channel and Send Messages were effective. Granting Embed Links in that channel allowed delivery.

## Source and protected channels

MediaGuard needs View Channel to monitor messages in protected channels. **Auto Delete** also requires effective **Manage Messages** in the source channel to delete a prohibited message.

**Warn / Log Only** leaves the source message in place, so it does not use Manage Messages for deletion. Its Detection notification still requires the Detection channel permissions above.

## Slash commands

Administrative slash commands require the **invoking user** to have **Manage Server** (Manage Guild). MediaGuard checks this permission when each command runs. This is not a Manage Server permission requirement for the bot.

## Gateway intents

MediaGuard enables the Guilds and Guild Messages intents and requires **Message Content** to inspect message content and attachments. Enable Message Content Intent for the bot in the Discord Developer Portal. Server Members and Presence intents are not enabled or required.

Gateway intents are separate from channel permissions.

## Troubleshooting

### Detection notification fails with 403 / 50013

Check MediaGuard's **effective** View Channel, Send Messages, and Embed Links permissions in the configured Detection channel. When a send fails, local diagnostic logging reports the bot's effective channel permission snapshot.
