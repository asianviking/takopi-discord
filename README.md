# takopi-discord

Discord transport plugin for [takopi](https://github.com/banteg/takopi) - "he just wants to help-pi... on Discord!"

## Concept

Maps Discord's structure to takopi's project/branch/session model:

| Discord | Takopi | Purpose |
|---------|--------|---------|
| Category | (organization) | Visual grouping |
| Channel | Project | Repository context (bound via `/bind`) |
| Thread | Branch / Session | Feature branch or session on base branch |
| Voice Channel | Voice Session | Talk to the agent with speech |

When you message in a channel, a thread is created. Use `@branch-name` prefix to work on a specific branch, otherwise it creates a session on the base branch (e.g., `master`).

Voice channels can be created with `/voice` and are linked to a thread's project/branch context. The bot joins, listens, and responds with speech.

## Structure Example

```
TAKOPI (category)
├── #main                 ← bound to ~/dev/takopi
│   ├── feat/voice        ← thread on branch: feat/voice
│   └── fix typo          ← session on master
├── #discord              ← bound to ~/dev/takopi-discord
└── 🔊 Voice: feat/voice  ← voice channel linked to feat/voice thread
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
message_overflow = "split"       # "split" (default) or "trim" for long messages
session_mode = "stateless"       # "stateless" (default) or "chat"
show_resume_line = true          # Show resume token in messages (default: true)
upload_dir = "~/uploads"         # Optional: enable /file commands with this root dir
```

State is automatically saved to `~/.takopi/discord_state.json`.

## Setup

1. Create a Discord application at https://discord.com/developers/applications
2. Create a bot and copy the token
3. Enable "Message Content Intent" under Privileged Gateway Intents
4. Run `takopi setup` and follow the prompts
5. Invite the bot to your server using the generated URL

## Slash Commands

### Core Commands

- `/bind <project> [worktrees_dir] [default_engine] [worktree_base]` - Bind channel to a project
- `/unbind` - Remove project binding
- `/status` - Show current channel/thread context and status
- `/ctx [show|clear]` - Show or clear context binding
- `/cancel` - Cancel running task
- `/new` - Clear conversation session (start fresh)

### Agent & Model Commands

- `/agent` - Show available agents and current defaults
- `/model [engine] [model]` - Show or set model override for an engine
- `/reasoning [engine] [level]` - Show or set reasoning level (minimal/low/medium/high/xhigh)
- `/trigger [all|mentions|clear]` - Set when bot responds (all messages or only @mentions)

### File Transfer

- `/file get <path>` - Download a file or directory (zipped) from the server
- `/file put <path>` - Upload a file (attach file, then reply with this command)

Requires `upload_dir` to be configured. Files in `.git`, `.env`, and credentials are blocked.

### Voice

- `/voice` or `/vc` - Create a voice channel for the current thread/channel

The voice channel is bound to the project context and auto-deletes when empty.

## Message Features

### @branch Prefix

Start a conversation on a specific branch by prefixing with `@branch-name`:

```
@feat/new-feature implement the login page
@issue-123 fix the bug
```

This creates a new thread bound to the specified branch. Without a prefix, threads work on the base branch (e.g., `master`).

### Thread Sessions

- Messages in channels automatically create threads
- Each thread maintains its own session with resume tokens
- Multiple sessions can run simultaneously across threads
- Cancel button appears on progress messages for task cancellation

### Trigger Modes

Control when the bot responds:
- **all** (default): Respond to all messages in bound channels/threads
- **mentions**: Only respond when @mentioned or replied to

Set per-channel or per-thread with `/trigger`.

## Discord Bot Permissions Required

**Text:**
- Read Messages / View Channels
- Send Messages
- Create Public Threads
- Send Messages in Threads
- Manage Threads
- Read Message History
- Add Reactions
- Attach Files
- Use Slash Commands

**Voice (optional, for `/voice` command):**
- Connect
- Speak
- Manage Channels (to create/delete voice channels)

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
