"""State management for Discord transport."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anyio
import msgspec

from .types import DiscordChannelContext, DiscordThreadContext

STATE_VERSION = 2


class DiscordChannelStateData(msgspec.Struct):
    """State data for a single channel or thread."""

    # For channels: {"project", "worktrees_dir", "default_engine", "worktree_base"}
    # For threads: {"project", "branch", "worktrees_dir", "default_engine"}
    context: dict[str, str] | None = None
    sessions: dict[str, str] | None = None  # engine_id -> resume_token
    # New fields for overrides
    model_overrides: dict[str, str] | None = None  # engine_id -> model
    reasoning_overrides: dict[str, str] | None = None  # engine_id -> level
    trigger_mode: str | None = None  # "all" | "mentions"
    default_engine: str | None = None  # default engine for this channel/thread


class DiscordState(msgspec.Struct):
    """Root state structure."""

    version: int = STATE_VERSION
    channels: dict[str, DiscordChannelStateData] = msgspec.field(default_factory=dict)


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically using a temp file."""
    tmp_path = path.with_suffix(".tmp")
    content = json.dumps(data, indent=2, ensure_ascii=False)
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


DEFAULT_STATE_PATH = Path.home() / ".takopi" / "discord_state.json"


class DiscordStateStore:
    """State store for Discord channel mappings and sessions."""

    def __init__(self, config_path: Path | None = None) -> None:
        if config_path is not None:
            self._path = config_path.parent / "discord_state.json"
        else:
            self._path = DEFAULT_STATE_PATH
        self._lock = anyio.Lock()
        self._loaded = False
        self._mtime_ns: int | None = None
        self._state = DiscordState()

    def _stat_mtime_ns(self) -> int | None:
        try:
            return self._path.stat().st_mtime_ns
        except FileNotFoundError:
            return None

    def _reload_if_needed(self) -> None:
        current = self._stat_mtime_ns()
        if self._loaded and current == self._mtime_ns:
            return
        self._load()

    def _load(self) -> None:
        self._loaded = True
        self._mtime_ns = self._stat_mtime_ns()
        if self._mtime_ns is None:
            self._state = DiscordState()
            return
        try:
            payload = msgspec.json.decode(self._path.read_bytes(), type=DiscordState)
        except Exception:  # noqa: BLE001
            self._state = DiscordState()
            return
        # Handle migration from version 1 to 2 (new fields have defaults)
        if payload.version < STATE_VERSION:
            payload = DiscordState(version=STATE_VERSION, channels=payload.channels)
            self._state = payload
            self._save()
            return
        self._state = payload

    def _save(self) -> None:
        payload = msgspec.to_builtins(self._state)
        _atomic_write_json(self._path, payload)
        self._mtime_ns = self._stat_mtime_ns()

    @staticmethod
    def _channel_key(guild_id: int | None, channel_id: int) -> str:
        if guild_id is not None:
            return f"{guild_id}:{channel_id}"
        return str(channel_id)

    async def get_context(
        self, guild_id: int | None, channel_id: int
    ) -> DiscordChannelContext | DiscordThreadContext | None:
        """Get the context for a channel or thread.

        Returns DiscordChannelContext for channels (no branch),
        or DiscordThreadContext for threads (with branch).
        """
        async with self._lock:
            self._reload_if_needed()
            key = self._channel_key(guild_id, channel_id)
            channel_data = self._state.channels.get(key)
            if channel_data is None or channel_data.context is None:
                return None
            ctx = channel_data.context
            project = ctx.get("project")
            if project is None:
                return None

            # Check if this is a thread context (has branch) or channel context
            branch = ctx.get("branch")
            if branch is not None:
                # Thread context
                return DiscordThreadContext(
                    project=project,
                    branch=branch,
                    worktrees_dir=ctx.get("worktrees_dir", ".worktrees"),
                    default_engine=ctx.get("default_engine", "claude"),
                )
            else:
                # Channel context
                return DiscordChannelContext(
                    project=project,
                    worktrees_dir=ctx.get("worktrees_dir", ".worktrees"),
                    default_engine=ctx.get("default_engine", "claude"),
                    worktree_base=ctx.get("worktree_base", "master"),
                )

    async def set_context(
        self,
        guild_id: int | None,
        channel_id: int,
        context: DiscordChannelContext | DiscordThreadContext | None,
    ) -> None:
        """Set the context for a channel or thread."""
        async with self._lock:
            self._reload_if_needed()
            key = self._channel_key(guild_id, channel_id)
            if key not in self._state.channels:
                self._state.channels[key] = DiscordChannelStateData()
            if context is None:
                self._state.channels[key].context = None
            elif isinstance(context, DiscordThreadContext):
                # Thread context (with branch)
                self._state.channels[key].context = {
                    "project": context.project,
                    "branch": context.branch,
                    "worktrees_dir": context.worktrees_dir,
                    "default_engine": context.default_engine,
                }
            else:
                # Channel context (no branch)
                self._state.channels[key].context = {
                    "project": context.project,
                    "worktrees_dir": context.worktrees_dir,
                    "default_engine": context.default_engine,
                    "worktree_base": context.worktree_base,
                }
            self._save()

    async def get_session(
        self, guild_id: int | None, channel_id: int, engine_id: str
    ) -> str | None:
        """Get the resume token for a session."""
        async with self._lock:
            self._reload_if_needed()
            key = self._channel_key(guild_id, channel_id)
            channel_data = self._state.channels.get(key)
            if channel_data is None or channel_data.sessions is None:
                return None
            return channel_data.sessions.get(engine_id)

    async def set_session(
        self,
        guild_id: int | None,
        channel_id: int,
        engine_id: str,
        resume_token: str | None,
    ) -> None:
        """Set or clear the resume token for a session."""
        async with self._lock:
            self._reload_if_needed()
            key = self._channel_key(guild_id, channel_id)
            if key not in self._state.channels:
                self._state.channels[key] = DiscordChannelStateData()
            if self._state.channels[key].sessions is None:
                self._state.channels[key].sessions = {}
            if resume_token is None:
                self._state.channels[key].sessions.pop(engine_id, None)
            else:
                self._state.channels[key].sessions[engine_id] = resume_token
            self._save()

    async def clear_channel(self, guild_id: int | None, channel_id: int) -> None:
        """Clear all state for a channel."""
        async with self._lock:
            self._reload_if_needed()
            key = self._channel_key(guild_id, channel_id)
            self._state.channels.pop(key, None)
            self._save()

    async def clear_sessions(self, guild_id: int | None, channel_id: int) -> None:
        """Clear all session tokens for a channel/thread."""
        async with self._lock:
            self._reload_if_needed()
            key = self._channel_key(guild_id, channel_id)
            channel_data = self._state.channels.get(key)
            if channel_data is not None:
                channel_data.sessions = None
                self._save()

    # Model override methods
    async def get_model_override(
        self, guild_id: int | None, channel_id: int, engine_id: str
    ) -> str | None:
        """Get model override for an engine."""
        async with self._lock:
            self._reload_if_needed()
            key = self._channel_key(guild_id, channel_id)
            channel_data = self._state.channels.get(key)
            if channel_data is None or channel_data.model_overrides is None:
                return None
            return channel_data.model_overrides.get(engine_id)

    async def set_model_override(
        self,
        guild_id: int | None,
        channel_id: int,
        engine_id: str,
        model: str | None,
    ) -> None:
        """Set or clear model override for an engine."""
        async with self._lock:
            self._reload_if_needed()
            key = self._channel_key(guild_id, channel_id)
            if key not in self._state.channels:
                self._state.channels[key] = DiscordChannelStateData()
            if self._state.channels[key].model_overrides is None:
                self._state.channels[key].model_overrides = {}
            if model is None:
                self._state.channels[key].model_overrides.pop(engine_id, None)
                if not self._state.channels[key].model_overrides:
                    self._state.channels[key].model_overrides = None
            else:
                self._state.channels[key].model_overrides[engine_id] = model
            self._save()

    async def clear_model_overrides(
        self, guild_id: int | None, channel_id: int
    ) -> None:
        """Clear all model overrides for a channel/thread."""
        async with self._lock:
            self._reload_if_needed()
            key = self._channel_key(guild_id, channel_id)
            channel_data = self._state.channels.get(key)
            if channel_data is not None:
                channel_data.model_overrides = None
                self._save()

    # Reasoning override methods
    async def get_reasoning_override(
        self, guild_id: int | None, channel_id: int, engine_id: str
    ) -> str | None:
        """Get reasoning level override for an engine."""
        async with self._lock:
            self._reload_if_needed()
            key = self._channel_key(guild_id, channel_id)
            channel_data = self._state.channels.get(key)
            if channel_data is None or channel_data.reasoning_overrides is None:
                return None
            return channel_data.reasoning_overrides.get(engine_id)

    async def set_reasoning_override(
        self,
        guild_id: int | None,
        channel_id: int,
        engine_id: str,
        level: str | None,
    ) -> None:
        """Set or clear reasoning level override for an engine."""
        async with self._lock:
            self._reload_if_needed()
            key = self._channel_key(guild_id, channel_id)
            if key not in self._state.channels:
                self._state.channels[key] = DiscordChannelStateData()
            if self._state.channels[key].reasoning_overrides is None:
                self._state.channels[key].reasoning_overrides = {}
            if level is None:
                self._state.channels[key].reasoning_overrides.pop(engine_id, None)
                if not self._state.channels[key].reasoning_overrides:
                    self._state.channels[key].reasoning_overrides = None
            else:
                self._state.channels[key].reasoning_overrides[engine_id] = level
            self._save()

    async def clear_reasoning_overrides(
        self, guild_id: int | None, channel_id: int
    ) -> None:
        """Clear all reasoning overrides for a channel/thread."""
        async with self._lock:
            self._reload_if_needed()
            key = self._channel_key(guild_id, channel_id)
            channel_data = self._state.channels.get(key)
            if channel_data is not None:
                channel_data.reasoning_overrides = None
                self._save()

    # Trigger mode methods
    async def get_trigger_mode(
        self, guild_id: int | None, channel_id: int
    ) -> str | None:
        """Get trigger mode for a channel/thread."""
        async with self._lock:
            self._reload_if_needed()
            key = self._channel_key(guild_id, channel_id)
            channel_data = self._state.channels.get(key)
            if channel_data is None:
                return None
            return channel_data.trigger_mode

    async def set_trigger_mode(
        self, guild_id: int | None, channel_id: int, mode: str | None
    ) -> None:
        """Set or clear trigger mode for a channel/thread."""
        async with self._lock:
            self._reload_if_needed()
            key = self._channel_key(guild_id, channel_id)
            if key not in self._state.channels:
                self._state.channels[key] = DiscordChannelStateData()
            self._state.channels[key].trigger_mode = mode
            self._save()

    # Default engine methods
    async def get_default_engine(
        self, guild_id: int | None, channel_id: int
    ) -> str | None:
        """Get default engine for a channel/thread."""
        async with self._lock:
            self._reload_if_needed()
            key = self._channel_key(guild_id, channel_id)
            channel_data = self._state.channels.get(key)
            if channel_data is None:
                return None
            return channel_data.default_engine

    async def set_default_engine(
        self, guild_id: int | None, channel_id: int, engine: str | None
    ) -> None:
        """Set or clear default engine for a channel/thread."""
        async with self._lock:
            self._reload_if_needed()
            key = self._channel_key(guild_id, channel_id)
            if key not in self._state.channels:
                self._state.channels[key] = DiscordChannelStateData()
            self._state.channels[key].default_engine = engine
            self._save()

    # Bulk getters for displaying all overrides
    async def get_all_overrides(
        self, guild_id: int | None, channel_id: int
    ) -> tuple[dict[str, str] | None, dict[str, str] | None, str | None, str | None]:
        """Get all overrides for a channel/thread.

        Returns: (model_overrides, reasoning_overrides, trigger_mode, default_engine)
        """
        async with self._lock:
            self._reload_if_needed()
            key = self._channel_key(guild_id, channel_id)
            channel_data = self._state.channels.get(key)
            if channel_data is None:
                return None, None, None, None
            return (
                channel_data.model_overrides,
                channel_data.reasoning_overrides,
                channel_data.trigger_mode,
                channel_data.default_engine,
            )
