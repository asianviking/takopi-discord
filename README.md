# takopi-discord

Discord transport plugin for [takopi](https://github.com/banteg/takopi) - "he just wants to help-pi... on Discord!"

## Concept

Maps Discord's structure to takopi's project/branch/session model:

| Discord | Takopi | Purpose |
|---------|--------|---------|
| Category | Project | Repository context |
| Channel | Branch | Feature branch / worktree |
| Thread | Session | Conversation with agent |

## Structure Example

```
FURTHERMORE (category)
├── #main
├── #issue-764-remove-ybgt
├── #issue-840-vault-search
└── Voice: furthermore-vc

TAKOPI (category)
├── #main
├── #feat
└── Voice: takopi-vc
```

## Installation

```bash
# Install takopi-discord
pip install takopi-discord

# Or with uv
uv pip install takopi-discord

# Verify the transport is loaded
takopi plugins --load
```

## Configuration

```toml
# takopi.toml
transport = "discord"

[transports.discord]
bot_token = "..."                # Required: Discord bot token
guild_id = 123456789             # Optional: restrict bot to single server
message_overflow = "trim"        # "trim" (default) or "split" for long messages
session_mode = "stateless"       # "stateless" (default) or "chat"
show_resume_line = true          # Show resume token in messages (default: true)
```

State is automatically saved to `~/.takopi/discord_state.json`.

## Setup

1. Create a Discord application at https://discord.com/developers/applications
2. Create a bot and copy the token
3. Enable "Message Content Intent" under Privileged Gateway Intents
4. Run `takopi setup` and follow the prompts
5. Invite the bot to your server using the generated URL

## Slash Commands

- `/status` - Show current channel context and status
- `/bind <project> [branch]` - Bind channel to a project and optional branch
- `/unbind` - Remove project binding
- `/cancel` - Cancel running task

## Message Features

### @branch Prefix

Override the branch for a single message by prefixing with `@branch-name`:

```
@feat/new-feature implement the login page
@issue-123 fix the bug
```

This creates a new thread bound to the specified branch. Only works in channels, not existing threads.

### Automatic Channel Mapping

Channel names are automatically mapped to branches:
- `#main` or `#master` → main/master branch
- `#issue-123` or `#issue-123-description` → corresponding branch
- `#feat-name` → feat-name branch
- Other channels use their name as the branch

### Thread Sessions

- Messages automatically create threads for conversations
- Each thread maintains its own session with resume tokens
- Multiple sessions can run simultaneously across channels/threads
- Cancel button appears on progress messages for task cancellation

## Discord Bot Permissions Required

- Read Messages / View Channels
- Send Messages
- Create Public Threads
- Send Messages in Threads
- Manage Threads
- Read Message History
- Add Reactions
- Attach Files
- Use Slash Commands

## Development

```bash
# Clone the repo
git clone https://github.com/asianviking/takopi-discord.git
cd takopi-discord

# Install in development mode
uv pip install -e .

# Run tests
pytest
```

Requires Python ≥ 3.14.

## License

MIT
