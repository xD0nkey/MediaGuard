# Architecture

## Bootstrap boundary

`Runtime` owns startup and shutdown. `DiscordService` owns a single `discord.py` client and an asyncio loop on a dedicated thread. `Database` owns a SQLite file under this project's `runtime/` directory and applies numbered, idempotent migrations. `Activity` keeps bounded, sanitized lifecycle events in memory. FastAPI exposes read-only status and activity endpoints to the local dashboard. No moderation listener, classifier, rules, enforcement, or case records exist yet.

The dashboard shows actual runtime state. Cases and Rules are explicit placeholders.

## Future boundaries

The next phase should add modules for Discord message intake, attachment and forward inspection, deterministic rules, enforcement, moderator cases, and persistent audit records. Cases and audit events must be written transactionally with enforcement intent and outcome. Inspection failure must have its own outcome, distinct from a safe result. Each moderator action must store moderator ID; each rule match must store its exact reason and rule version. Case records should never be deleted silently. These are future design constraints, not implemented features.

## Discord intents

The current client requests `guilds`, `messages`, and privileged `message_content`. Message content is needed for future attachments, embeds, forwards, and links. Guild intent supplies guild identity and connected guild count. Channel and author IDs arrive with message events. Interactions arrive through Discord's interaction gateway handling and do not require a separate privileged intent. `members` and `presences` are not requested; member identity and roles should be resolved only when an authorized moderation action requires them. Enable Message Content Intent for MediaGuard's own application in the Discord developer portal before expecting inspection to work. This bootstrap registers no commands and handles no messages.

## Operator access

The backend binds to loopback only. Host and Origin are checked. Endpoints are read-only and expose no message bodies, notes, or secrets. Remote deployment requires a separately designed authentication layer.
