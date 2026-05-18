# Agent Notes

## Transport Parity: Telegram vs Discord

When adapting upstream Takopi or Telegram transport behavior to takopi-discord,
map concepts before porting UI.

Track capability parity in `docs/transport-parity.md`. `AGENTS.md` should stay
as the short conceptual guide; the parity doc is the living ledger for status,
intentional UX differences, and follow-up work.

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
  thread/work item on the channel's base branch unless a branch is specified.
- A message inside a Discord thread should continue that thread's
  branch/session context.
- Thread-level `/ctx set` should only set the branch/worktree for that thread.
  The project stays inherited from the bound parent channel.
- When a thread is rebound to a branch, prepare or reuse the Takopi worktree and
  rename the Discord thread to match the branch.
- `/topic` parity usually means improving channel/project binding or onboarding,
  not adding a literal `/topic` command.
