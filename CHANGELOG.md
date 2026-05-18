# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- `session_mode = "thread"` (new default): server-side resume scoped to Discord threads, channels stay reply-chain only. Reflects the Discord UX where a thread is one work item. Existing `"stateless"` keeps no server-side resume anywhere; legacy `"chat"` is accepted as an alias for `"thread"`.

### Fixed
- Replies inside a Discord thread now resume the saved session under the new default. Previously the `session_mode == "chat"` gate skipped the lookup, so each reply started fresh.

### Changed
- Inside a thread, the session resume key drops `author_id` so all thread participants share one session. Channel scope stays reply-chain only under canonical `session_mode = "thread"`.
- Discord thread/chat-mode messages suppress the visible resume-token line; the `ctx:` line remains visible for project/branch context.

## [0.5.1] - 2026-05-16

### Added
- `transports.discord.allowed_bot_user_ids` for explicitly trusted bot-authored Discord messages

### Fixed
- Allow trusted bot senders through the Discord message gate without also requiring them in `allowed_user_ids`

## [0.5.0] - 2026-02-25

### Added
- Per-user session isolation when `session_mode = "chat"`
- Resume token extraction from replies to bot progress messages
- Discord allowlist gating via `transports.discord.allowed_user_ids`
- `/ctx set` for rebinding channel/thread context
- `/agent set|clear` for per-channel/thread default agent overrides
- `/file put` for uploading attachments to explicit paths
- Voice message attachment transcription via `transports.discord.voice_messages`
- Configurable media group debounce via `transports.discord.media_group_debounce_s`

### Changed
- File transfer configuration is now under `transports.discord.files` (enable with `files.enabled = true`)

## [0.4.1] - 2026-02-23

### Added
- Configurable trigger mode fallback via `transports.discord.trigger_mode_default`

### Fixed
- Docs: fix uv tool install and onboarding command guidance

## [0.4.0] - 2026-02-21

### Added
- Resume queueing for replies to running tasks
- Buffer attachment bursts in threads
- Separate Discord prefs store (`discord_prefs.json`)

### Changed
- Default worktree base to `main`
- Ignore pre-startup messages to drain backlog

### Fixed
- Thread session continuity for `/engine` replies
- Engine slash commands threading
- Thread engine resolution for bound channels
- Seed plugin slash commands with starter message

## [0.3.0] - 2026-01-21

### Added
- **Auto File Upload**: Automatically upload Discord message attachments to the agent's incoming folder
- **Config Hot-Reload**: Watch config file for changes and reload settings without restart

### Fixed
- Allow messages with only attachments (no text) to be processed

## [0.2.1] - 2026-01-21

### Changed
- Updated README with v0.2.0 features documentation

## [0.2.0] - 2026-01-17

### Added
- **Voice Support**: Native voice channel integration using Pycord with local Whisper for speech-to-text
  - Push-to-talk support
  - Voice acknowledgment before processing
  - Reduced latency and prevented audio queueing
- **Plugin System**: Command plugin integration for extensibility
- **Dynamic Engine Commands**: Slash commands per engine (`/claude`, `/codex`, etc.)
- **Rate Limiting**: Rate limiting and outbox system for message operations
- **Thread Support**: Thread-bound worktrees with `@branch` prefix
- **Feature Parity**: Parity with takopi-telegram transport features

### Changed
- Migrated from discord.py to Pycord
- Changed `message_overflow` default from "trim" to "split"
- Improved context model with separate channel and thread contexts
- Suppress link embeds in bot responses

### Fixed
- Python 3.14 compatibility for slash command Option patterns
- Deferred interaction not completing after plugin command
- Cancel button to actually cancel running tasks
- Graceful shutdown handling
- Stale global commands cleared when syncing to a specific guild
- Session persistence improvements

## [0.1.0] - 2026-01-14

### Added
- Initial release
- Discord transport backend for takopi
- Basic slash commands and message handling
- Channel context and session management
