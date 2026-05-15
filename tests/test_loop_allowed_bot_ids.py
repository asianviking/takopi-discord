"""Tests for allowed bot sender wiring in the Discord message loop."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import takopi_discord.loop as loop_module
from takopi_discord.bridge import (
    DiscordBridgeConfig,
    DiscordFilesSettings,
    DiscordVoiceMessageSettings,
)
from takopi_discord.loop import _is_message_author_allowed


class _StopLoop(RuntimeError):
    pass


@dataclass
class _DummyPrefsStore:
    async def ensure_loaded(self) -> None:
        return None


@dataclass
class _DummyStateStore:
    async def get_startup_channel(self, guild_id: int) -> int | None:
        return None


class _DummyBotClient:
    def __init__(self, message) -> None:
        self.user = SimpleNamespace(id=999, name="Takopi")
        self.bot = SimpleNamespace(
            event=lambda fn: fn,
            process_application_commands=AsyncMock(),
            sync_commands=AsyncMock(),
        )
        self._message = message
        self._handler = None
        self.closed = False

    def set_message_handler(self, handler) -> None:
        self._handler = handler

    async def start(self) -> None:
        assert self._handler is not None
        await self._handler(self._message)
        raise _StopLoop()

    async def close(self) -> None:
        self.closed = True


def _runtime_stub(config_path: Path) -> MagicMock:
    runtime = MagicMock()
    runtime.config_path = config_path
    runtime.allowlist = None
    runtime.default_engine = "codex"
    runtime.watch_config = False
    runtime.engine_ids = ["codex"]
    return runtime


def test_allowed_bot_user_ids_bypass_human_allowlist() -> None:
    assert _is_message_author_allowed(
        allowed_user_ids=frozenset({456}),
        allowed_bot_user_ids=frozenset({123}),
        author_id=123,
        author_is_bot=True,
    )


def test_untrusted_bot_sender_still_uses_human_allowlist() -> None:
    assert not _is_message_author_allowed(
        allowed_user_ids=frozenset({456}),
        allowed_bot_user_ids=frozenset({789}),
        author_id=123,
        author_is_bot=True,
    )


def test_human_sender_still_uses_human_allowlist() -> None:
    assert _is_message_author_allowed(
        allowed_user_ids=frozenset({456}),
        allowed_bot_user_ids=frozenset({123}),
        author_id=456,
        author_is_bot=False,
    )
    assert not _is_message_author_allowed(
        allowed_user_ids=frozenset({456}),
        allowed_bot_user_ids=frozenset({123}),
        author_id=123,
        author_is_bot=False,
    )


@pytest.mark.anyio
async def test_run_main_loop_passes_allowed_bot_user_ids_to_message_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    message = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        created_at=datetime.now(UTC) + timedelta(seconds=1),
        channel=SimpleNamespace(id=10),
        author=SimpleNamespace(id=123, bot=True, name="Hermes"),
        content="please continue",
        attachments=[],
    )
    bot = _DummyBotClient(message)

    monkeypatch.setattr(
        loop_module, "DiscordStateStore", lambda _path: _DummyStateStore()
    )
    monkeypatch.setattr(
        loop_module, "DiscordPrefsStore", lambda _path: _DummyPrefsStore()
    )
    monkeypatch.setattr(
        loop_module, "register_slash_commands", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        loop_module, "register_engine_commands", lambda *args, **kwargs: set()
    )
    monkeypatch.setattr(loop_module, "discover_command_ids", lambda _allowlist: set())

    def fake_should_process_message(
        message, bot_user, *, require_mention=False, allowed_bot_user_ids=None
    ):
        captured["allowed_bot_user_ids"] = allowed_bot_user_ids
        return False

    monkeypatch.setattr(
        loop_module, "should_process_message", fake_should_process_message
    )

    cfg = DiscordBridgeConfig(
        bot=bot,
        runtime=_runtime_stub(tmp_path / "config.toml"),
        guild_id=None,
        startup_msg="ready",
        exec_cfg=SimpleNamespace(transport=SimpleNamespace()),
        allowed_bot_user_ids=frozenset({123}),
        files=DiscordFilesSettings(),
        voice_messages=DiscordVoiceMessageSettings(),
    )

    with pytest.raises(BaseExceptionGroup):
        await loop_module.run_main_loop(cfg)

    assert captured["allowed_bot_user_ids"] == frozenset({123})
    assert bot.closed is True
