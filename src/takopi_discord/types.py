"""Type definitions for Discord transport."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class DiscordIncomingMessage:
    """Incoming message from Discord."""

    transport: str
    guild_id: int | None
    channel_id: int
    message_id: int
    content: str
    author_id: int
    author_name: str
    thread_id: int | None = None
    reply_to_message_id: int | None = None
    reply_to_content: str | None = None
    category_id: int | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class DiscordInteraction:
    """Interaction from Discord (slash commands, buttons)."""

    transport: str
    guild_id: int | None
    channel_id: int
    interaction_id: int
    interaction_token: str
    command_name: str | None
    custom_id: str | None
    user_id: int
    user_name: str
    options: dict[str, Any] | None = None
    message_id: int | None = None
    raw: Any | None = None


@dataclass(frozen=True, slots=True)
class DiscordChannelContext:
    """Context for a Discord channel mapped to a project/branch."""

    project: str
    branch: str


@dataclass(frozen=True, slots=True)
class DiscordChannelState:
    """State for a Discord channel."""

    context: DiscordChannelContext | None = None
    sessions: dict[str, str] | None = None  # engine_id -> resume_token
