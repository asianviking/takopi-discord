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
bot_token = "..."
guild_id = 123456789  # optional, for single-guild mode
message_overflow = "trim"  # or "split"
session_mode = "stateless"  # or "chat"
```

## Setup

1. Create a Discord application at https://discord.com/developers/applications
2. Create a bot and copy the token
3. Enable "Message Content Intent" under Privileged Gateway Intents
4. Run `takopi setup` and follow the prompts
5. Invite the bot to your server using the generated URL

## Slash Commands

- `/status` - Show current channel context and status
- `/bind <project>` - Bind channel to a project
- `/unbind` - Remove project binding
- `/cancel` - Cancel running task

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

## License

MIT
