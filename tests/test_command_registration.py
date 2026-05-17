"""Tests for plugin command registration helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from takopi.context import RunContext

from takopi_discord.commands.registration import (
    _format_plugin_starter_message,
    _format_plugin_thread_name,
    _handle_plugin_command,
)
from takopi_discord.types import DiscordChannelContext, DiscordThreadContext


class TestFormatPluginStarterMessage:
    def test_no_args(self) -> None:
        assert _format_plugin_starter_message("hello", "", max_chars=2000) == "/hello"

    def test_with_args(self) -> None:
        assert (
            _format_plugin_starter_message("hello", "world", max_chars=2000)
            == "/hello world"
        )

    def test_truncates_with_ellipsis(self) -> None:
        msg = _format_plugin_starter_message("hello", "x" * 100, max_chars=20)
        assert msg.startswith("/hello ")
        assert msg.endswith("…")
        assert len(msg) <= 20


class TestFormatPluginThreadName:
    def test_no_args(self) -> None:
        assert _format_plugin_thread_name("hello", "", max_chars=100) == "hello"

    def test_with_args(self) -> None:
        assert (
            _format_plugin_thread_name("hello", "world", max_chars=100)
            == "hello world"
        )

    def test_truncates_with_ellipsis(self) -> None:
        name = _format_plugin_thread_name("hello", "x" * 100, max_chars=20)
        assert name.startswith("hello ")
        assert name.endswith("…")
        assert len(name) <= 20


class DummyTextChannel:
    pass


class DummyThread:
    def __init__(self, *, parent_id: int | None) -> None:
        self.parent_id = parent_id


@pytest.mark.anyio
async def test_plugin_command_in_bound_channel_creates_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import takopi_discord.commands.registration as registration

    monkeypatch.setattr(registration.discord, "TextChannel", DummyTextChannel)
    monkeypatch.setattr(registration.discord, "Thread", DummyThread)

    created_coroutines = []

    def fake_create_task(coro, *, name=None):
        created_coroutines.append(coro)
        return MagicMock(name=name)

    dispatch = AsyncMock(return_value=True)
    monkeypatch.setattr(registration.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(registration, "dispatch_command", dispatch)

    ctx = MagicMock()
    ctx.guild = MagicMock()
    ctx.guild.id = 1
    ctx.author = MagicMock()
    ctx.author.id = 42
    ctx.channel_id = 20
    ctx.channel = DummyTextChannel()
    ctx.defer = AsyncMock()
    ctx.followup = MagicMock()
    ctx.followup.send = AsyncMock()

    cfg = MagicMock()
    cfg.allowed_user_ids = None
    cfg.show_resume_line = True
    cfg.session_mode = "chat"
    cfg.runtime = MagicMock()
    cfg.bot = MagicMock()
    cfg.bot.create_thread_without_message = AsyncMock(return_value=99)
    cfg.bot.send_message = AsyncMock(return_value=MagicMock(message_id=555))

    state_store = MagicMock()
    state_store.get_context = AsyncMock(
        return_value=DiscordChannelContext(
            project="takopi-discord",
            worktrees_dir=".worktrees",
            default_engine="claude",
            worktree_base="main",
        )
    )
    state_store.set_context = AsyncMock()

    prefs_store = MagicMock()

    await _handle_plugin_command(
        ctx,
        command_id="hello",
        args_text="world",
        cfg=cfg,
        running_tasks={},
        state_store=state_store,
        prefs_store=prefs_store,
        default_engine_override=None,
    )
    assert len(created_coroutines) == 1
    await created_coroutines[0]

    cfg.bot.create_thread_without_message.assert_awaited_once_with(
        channel_id=20,
        name="hello world",
    )
    state_store.set_context.assert_any_await(
        1,
        99,
        DiscordThreadContext(
            project="takopi-discord",
            branch="main",
            worktrees_dir=".worktrees",
            default_engine="claude",
        ),
    )
    cfg.bot.send_message.assert_awaited_once_with(
        channel_id=99,
        content="/hello world",
    )
    dispatch.assert_awaited_once()
    kwargs = dispatch.call_args.kwargs
    assert kwargs["channel_id"] == 99
    assert kwargs["thread_id"] == 99
    assert kwargs["default_context"] == RunContext(
        project="takopi-discord",
        branch="main",
    )
    ctx.followup.send.assert_awaited_once()
    assert "<#99>" in ctx.followup.send.call_args.args[0]
