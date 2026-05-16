# Agent Notes

## Transport Parity: Telegram vs Discord

When adapting upstream Takopi or Telegram transport behavior to takopi-discord,
map concepts before porting UI.

Core Takopi concepts:
- Project: configured repo/workspace alias.
- Branch: git branch/worktree context.
- Session: resumable agent conversation.
- Scope: where context, defaults, overrides, and sessions are stored.

Transport mapping:
- Telegram chat roughly maps to the Discord guild/channel environment.
- Telegram forum topic maps closest to a Discord project channel.
- Discord thread is Discord-specific UX for branch/session isolation inside a
  project channel.

Guidance:
- Preserve Discord UX. Do not copy Telegram topic behavior directly into
  Discord threads.
- If upstream changes topic-scoped context, defaults, overrides, or sessions,
  first consider whether the Discord equivalent belongs at channel scope.
- If upstream changes branch/session continuation inside a topic, consider
  whether it belongs in Discord threads.
- `/topic` parity usually means improving channel creation, binding, or
  onboarding, not adding a literal `/topic` command.
