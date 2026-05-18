"""Session-scope helpers for Discord transport.

``session_mode`` decides where the server-side resume store applies. Discord
thread sessions store resume tokens server-side, so visible resume lines are
only needed for reply-chain scopes outside those stored sessions.

- ``stateless`` — no server-side resume anywhere. Persistence lives in the
  chat history (replies). Matches upstream Telegram semantics.
- ``thread`` (default for Discord) — server-side resume inside threads only.
  Channels and DMs stay reply-chain only. Reflects Discord's native UX where a
  thread is a session/work item.

``chat`` is accepted as a legacy alias for ``thread``.
"""

from __future__ import annotations

from typing import Literal

SessionMode = Literal["stateless", "thread"]


def normalize_session_mode(session_mode: object) -> SessionMode:
    """Normalize config/session values into the canonical runtime modes."""
    if isinstance(session_mode, str):
        value = session_mode.strip().lower()
        if value == "stateless":
            return "stateless"
        if value in {"thread", "chat"}:
            return "thread"
    return "thread"


def should_resume_session(session_mode: str, *, thread_id: int | None) -> bool:
    """Whether to restore a saved resume token at the current scope."""
    return normalize_session_mode(session_mode) == "thread" and thread_id is not None


def session_author_id(*, thread_id: int | None, author_id: int | None) -> int | None:
    """Per-author isolation only applies to channel scope.

    A thread is a shared work item; all participants contribute to the same
    session. Channel callers keep the author id for compatibility with older
    state paths, although canonical thread mode does not persist channel
    sessions.
    """
    return None if thread_id is not None else author_id
