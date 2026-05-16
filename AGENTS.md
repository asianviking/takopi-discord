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
- Telegram forum topic combines project, branch, and session/work-item scope in
  one object.
- Discord splits that responsibility across two objects:
  - Bound channel: project container.
  - Auto-created thread: branch/session/work-item container inside the project
    channel.

Guidance:
- Preserve Discord UX. Do not copy Telegram topic behavior directly into
  Discord threads.
- If upstream changes topic-scoped project context, defaults, overrides,
  bindings, or onboarding, first consider whether the Discord equivalent belongs
  at bound-channel scope.
- If upstream changes topic-scoped branch, session, continuation, or work-item
  behavior, first consider whether the Discord equivalent belongs in threads.
- A new message in a bound Discord project channel should usually create a new
  thread/work item.
- A message inside a Discord thread should continue that thread's
  branch/session context.
- `/topic` parity usually means improving channel/project binding or onboarding,
  not adding a literal `/topic` command.
