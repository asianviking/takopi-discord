# Changelog

All notable changes to this project will be documented in this file.

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
