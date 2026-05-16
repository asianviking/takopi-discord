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

When you message in a channel, a thread is created. Use `@branch-name` prefix to work on a specific branch, otherwise it creates a session on the base branch (e.g., `main`).

Voice channels can be created with `/voice` and are linked to a thread's project/branch context. The bot joins, listens, and responds with speech.

## Structure Example

```
TAKOPI (category)
├── #main                 ← bound to ~/dev/takopi
│   ├── feat/voice        ← thread on branch: feat/voice
│   └── fix typo          ← session on main
├── #discord              ← bound to ~/dev/takopi-discord
└── 🔊 Voice: feat/voice  ← voice channel linked to feat/voice thread
```

## Installation

```bash
# Recommended: install into the takopi tool environment
uv tool install -U takopi --with takopi-discord

# If you're already inside a project virtual environment
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
trigger_mode_default = "all"     # "all" (default) or "mentions" for inherited trigger mode
# allowed_user_ids = [123456789012345678]      # Optional: restrict human bot usage (Discord user IDs)
# allowed_bot_user_ids = [987654321098765432]  # Optional: trusted bot senders allowed to trigger Takopi
media_group_debounce_s = 0.75     # Buffer bursts of attachments (seconds)

[transports.discord.files]
enabled = false                  # Enable /file + attachment auto-upload
# auto_put = true                # Auto-save attachments into `uploads_dir`
# auto_put_mode = "upload"       # "upload" (default) or "prompt"
uploads_dir = "incoming"         # Relative path in the repo
# max_upload_bytes = 20971520    # 20MB
# max_download_bytes = 10485760  # 10MB Discord base upload limit; raise for boosted/Nitro-capable servers
# deny_globs = [".git/**", ".env", ".envrc", "**/*.pem", "**/.ssh/**"]
# allowed_user_ids = [123456789012345678]  # Optional: restrict file transfers separately

[transports.discord.voice_messages]
enabled = false                  # Transcribe audio attachments with no text prompt
# max_bytes = 10485760           # 10MB
whisper_model = "base"
# voice_transcription_base_url = "http://localhost:8000/v1"  # Optional: local transcription server
# voice_transcription_api_key = "local"                      # Optional: key for transcription server
```

State is automatically saved to `~/.takopi/discord_state.json`. Chat preferences
(trigger mode, engine overrides) are stored in `~/.takopi/discord_prefs.json`.

## Setup

1. Create a Discord application at https://discord.com/developers/applications
2. Create a bot and copy the token
3. Enable "Message Content Intent" under Privileged Gateway Intents
4. Run `takopi --onboard --transport discord` and follow the prompts
5. Invite the bot to your server using the generated URL

## Troubleshooting

- `error: No virtual environment found; run uv venv to create an environment, or pass --system ...`
  - This happens when `uv pip install ...` is run outside a project venv.
  - If you installed Takopi with `uv tool install`, install this plugin with:
    - `uv tool install -U takopi --with takopi-discord`
- `Error: No such command 'setup'`
  - `takopi setup` is not a core command in current Takopi.
  - Use onboarding via:
    - `takopi --onboard --transport discord`
- Config changes without restarting
  - You can edit `~/.takopi/takopi.toml` directly, or use the CLI:
    - `takopi config set transports.discord.trigger_mode_default mentions`
    - `takopi config set transports.discord.voice_messages.enabled true`
  - Enable `watch_config = true` for hot reload of command registrations.

## Slash Commands

### Core Commands

- `/bind <project> [worktrees_dir] [default_engine] [worktree_base]` - Bind channel to a project
- `/unbind` - Remove project binding
- `/status` - Show current channel/thread context and status
- `/ctx [show|set|clear]` - Show or modify context binding
- `/cancel` - Cancel running task
- `/new` - Clear conversation session (start fresh)

### Engine Commands

Dynamic slash commands are registered for each configured engine:

- `/claude [prompt]` - Send a message to Claude
- `/codex [prompt]` - Send a message to Codex
- `/gemini [prompt]` - Send a message to Gemini
- etc.

These commands allow you to target a specific engine regardless of the channel's default.

### Agent & Model Commands

- `/agent [show|set|clear] [engine]` - Show or override the default agent for this channel/thread
- `/model [engine] [model]` - Show or set model override for an engine
- `/reasoning [engine] [level]` - Show or set reasoning level (minimal/low/medium/high/xhigh)
- `/trigger [all|mentions|clear]` - Set when bot responds (all messages or only @mentions)

### File Transfer

- `/file get <path>` - Download a file or directory (zipped) from the server
- `/file put <path>` - Upload a file (attach file, then reply with this command)

Enable with `[transports.discord.files] enabled = true`. Files in `.git`, `.env`, and credentials are blocked.

### Voice

- `/voice` or `/vc` - Create a voice channel for the current thread/channel

The voice channel is bound to the project context and auto-deletes when empty. Uses local Whisper for speech-to-text transcription.

To transcribe voice message attachments in text chat, enable `[transports.discord.voice_messages]` (requires `ffmpeg`).

### Plugins

Custom command plugins can extend the bot's functionality. Plugin commands are automatically registered as slash commands when loaded by takopi.

## Message Features

### @branch Prefix

Start a conversation on a specific branch by prefixing with `@branch-name`:

```
@feat/new-feature implement the login page
@issue-123 fix the bug
```

This creates a new thread bound to the specified branch. Without a prefix, threads work on the base branch (e.g., `main`).

### Thread Sessions

- Messages in channels automatically create threads
- Each thread maintains its own session with resume tokens
- Multiple sessions can run simultaneously across threads
- Progress messages include Discord buttons for cancellation, and queued replies
  can be steered into an active turn when the runner supports it
- Rate limiting prevents Discord API throttling during high activity

Discord uses native threads for the same project/branch workflow that Telegram
uses forum topics for. Start with `@branch-name` to create a branch-bound
thread, or use `/ctx set` inside an existing thread to rebind it.

### Trigger Modes

Control when the bot responds:
- **all** (default): Respond to all messages in bound channels/threads
- **mentions**: Only respond when @mentioned or replied to

Set per-channel or per-thread with `/trigger`.
Set the inherited fallback for new channels/threads with `trigger_mode_default` in
`[transports.discord]`.

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
