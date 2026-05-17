# Transport Parity Ledger

Track capability parity with upstream Takopi and its Telegram transport here.
The goal is not a direct UI port. The goal is that a Discord user can accomplish
the same Takopi capability through native-feeling Discord UX.

Last reviewed against upstream `banteg/takopi` `v0.23.3`
(`38c9f8a7520fbda775eaf77e6c4ccfd8dc0d67db`).

## Status Vocabulary

- Done: Discord has a native equivalent and tests or docs cover the behavior.
- Partial: Discord has some equivalent behavior, but the mapping is incomplete.
- Missing: upstream has a capability with no Discord equivalent yet.
- Intentional difference: Discord should differ because the native UX is better.
- Not applicable: the upstream behavior is transport-specific and does not need a
  Discord equivalent.
- Needs mapping: upstream changed, but the Discord UX decision is still open.

## Scope Mapping

| Takopi capability scope | Telegram UX | Discord UX mapping | Notes |
| --- | --- | --- | --- |
| Project | Forum topic can carry project/worktree context | Bound text channel | Project-level defaults, onboarding, and bindings should usually live at channel scope. |
| Branch/work item | Forum topic can also carry branch/session scope | Auto-created thread inside a bound channel | A message in a bound channel usually starts a new thread/work item on the channel's base branch. |
| Session continuation | Continue in the same topic | Continue in the same thread | Thread sessions keep resume tokens and active-turn context. |
| Per-scope preferences | Topic/chat-level settings | Thread override, then channel override, then config default | Preserve the cascade so thread-specific work can override project defaults. |

## Capability Matrix

| Upstream capability | Telegram UX | Discord UX mapping | Status | Notes/tests |
| --- | --- | --- | --- | --- |
| Project binding | Bind a topic/chat to a project | `/bind` binds the current Discord channel to a project alias | Done | Channel is the project container; see README "Core Commands". |
| Project context display/editing | Show or change topic context | `/ctx show/set/clear` works in channels and threads | Done | Thread context can override channel context for branch-specific work. |
| New work item | Start or use a topic for a branch/task | Send a message in a bound project channel; the bot creates a thread | Done | Discord-specific UX. Do not replace with literal topic creation. |
| Branch targeting | Topic or command-level branch context | Prefix a channel message with `@branch-name`, or use `/ctx set @branch-name` in a thread | Done | Thread-level `/ctx set` is branch-only, prepares/reuses the Takopi worktree, and renames the Discord thread to the branch. |
| Session continuation | Continue in the same topic | Continue in the same Discord thread | Done | Resume tokens are keyed by thread when present. |
| Clear conversation | `/new` or equivalent reset | `/new` clears the channel/thread session | Done | Applies to current Discord scope. |
| Cancel active task | Telegram cancel action/command | `/cancel` and Discord cancel controls | Done | Keep Discord buttons when they fit the surface. |
| Engine selection | Engine-specific commands or directives | Dynamic slash commands like `/claude`, `/codex`, `/gemini` | Done | Slash commands should run in the current channel/thread scope. |
| Default agent/engine | Topic/chat default engine | `/agent` stores channel or thread default | Done | Thread override wins over channel default. |
| Model override | Topic/chat model setting | `/model` stores channel or thread model override per engine | Done | Thread override wins over channel default. |
| Reasoning override | Topic/chat reasoning setting | `/reasoning` stores channel or thread reasoning override per engine | Done | Reasoning support is engine-specific. |
| Trigger mode | Topic/chat response mode | `/trigger` stores channel or thread trigger mode | Done | `trigger_mode_default` config is inherited fallback. |
| File upload/download | Telegram document upload/download | `/file put`, `/file get`, and attachment auto-upload | Done | Discord limits differ; keep Discord file-size configuration explicit. |
| Voice input | Telegram voice/audio messages | Optional voice message attachment transcription | Intentional difference | Discord also has live voice channels, which are Discord-only UX. |
| Live voice session | Not a direct Telegram topic equivalent | `/voice` creates a linked Discord voice channel | Intentional difference | Keep as Discord-native extension, not upstream parity debt. |
| Plugin commands | Upstream plugin command surface | Register plugin commands as Discord slash commands | Done | Channel-level plugin invocations create a thread in bound project channels; thread-level invocations stay in the current thread. |
| Plugin callback actions | Telegram callback data can dispatch to command plugins | Discord component interactions need a custom-id mapping to command plugins | Needs mapping | Current Discord component handling is reserved for Takopi cancel/steer buttons only. Decide whether plugin-owned Discord buttons/selects are part of transport parity. |
| Directive-driven context update | Directives inside a topic can update topic binding and rename the topic | Existing Discord threads update branch binding and rename the thread when directives resolve a new branch | Done | Parent channel remains the project owner; thread directives can only rebind the thread branch/worktree. |
| Project alias command invocation | `/project-alias ...` can act as an explicit project invocation in Telegram | Bound Discord channels are the primary project selector | Intentional difference | Revisit only if users need ad hoc project selection outside bound channels. |
| Forwarded message coalescing | Telegram coalesces comment-plus-forward bursts | No direct Discord equivalent | Not applicable | Discord attachment grouping is handled separately through media buffering. |
| Onboarding/setup | Telegram setup flow | Discord onboarding validates bot token and config | Done | Transport-specific by nature. |

## Open Parity Gaps

These are the current items that look unaddressed or still need a Discord UX
decision after comparing against Telegram `v0.23.3`.

| Gap | Status | Suggested Discord mapping | Notes |
| --- | --- | --- | --- |
| Plugin component/callback routing | Needs mapping | Define a Discord custom-id convention for plugin-owned components, then route allowed component interactions through `CommandContext` like Telegram callback data. | Current Discord component interactions only handle built-in cancel and steer buttons. |
| Project alias slash commands | Intentional difference | Keep `/bind` + project channels as the project selection UX unless we want ad hoc project commands. | Telegram registers project aliases in the command menu; Discord project selection is channel-scoped by design. |
| Forward/comment coalescing | Not applicable | No action unless Discord gains a comparable native forwarded-message burst that users expect to prompt with. | Telegram-specific behavior for forwarded message batches. |

## Review Workflow

When upstream Takopi or Telegram changes:

1. Identify the capability independent of Telegram UI.
2. Decide whether the Discord equivalent belongs at channel scope, thread scope,
   both, or neither.
3. Update the capability matrix with one of the status values above.
4. If the status is Partial, Missing, or Needs mapping, open or update an
   `upstream-parity` issue.
5. If Discord intentionally differs, mark it as Intentional difference and state
   the UX reason in the notes.
6. Add or update tests for behavior that affects runtime scope, session
   continuation, preferences, file handling, or command dispatch.

Suggested labels for parity issues and PRs:

- `upstream-parity`
- `discord-ux`
- `intentional-difference`
- `needs-mapping`
- `missing-tests`

## Issue Prompt Template

Use this shape when the upstream workflow creates a tracking issue:

```md
## Upstream Capability

Describe the feature independent of Telegram UI.

## Telegram Behavior

How upstream exposes it in Telegram.

## Discord Mapping

Where it should live in takopi-discord:
- Channel scope:
- Thread scope:
- Discord-only UX considerations:

## Parity Status

Done | Partial | Missing | Intentional difference | Not applicable | Needs mapping

## Tests / Acceptance

List the behavior that should prove parity.
```
