"""State management for Discord transport."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import anyio
import msgspec

from .types import DiscordChannelContext

STATE_VERSION = 1


class DiscordChannelStateData(msgspec.Struct):
    """State data for a single channel."""

    context: dict[str, str] | None = None  # {"project": ..., "branch": ...}
    sessions: dict[str, str] | None = None  # engine_id -> resume_token


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
        if payload.version != STATE_VERSION:
            self._state = DiscordState()
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
    ) -> DiscordChannelContext | None:
        """Get the context for a channel."""
        async with self._lock:
            self._reload_if_needed()
            key = self._channel_key(guild_id, channel_id)
            channel_data = self._state.channels.get(key)
            if channel_data is None or channel_data.context is None:
                return None
            ctx = channel_data.context
            project = ctx.get("project")
            branch = ctx.get("branch")
            if project is None or branch is None:
                return None
            return DiscordChannelContext(project=project, branch=branch)

    async def set_context(
        self,
        guild_id: int | None,
        channel_id: int,
        context: DiscordChannelContext | None,
    ) -> None:
        """Set the context for a channel."""
        async with self._lock:
            self._reload_if_needed()
            key = self._channel_key(guild_id, channel_id)
            if key not in self._state.channels:
                self._state.channels[key] = DiscordChannelStateData()
            if context is None:
                self._state.channels[key].context = None
            else:
                self._state.channels[key].context = {
                    "project": context.project,
                    "branch": context.branch,
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
