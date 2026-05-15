"""Tests for plugin command dispatch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from takopi.transport import MessageRef
from takopi_discord.commands.dispatch import dispatch_command


@pytest.mark.anyio
async def test_dispatch_command_populates_sender_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MessageRef passed to CommandContext should carry sender_id."""
    cfg = MagicMock()
    cfg.runtime = MagicMock()
    cfg.runtime.allowlist = None
    cfg.runtime.plugin_config.return_value = {}
    cfg.show_resume_line = True
    cfg.exec_cfg = MagicMock()

    backend = MagicMock()
    backend.handle = AsyncMock(return_value=None)

    with patch("takopi_discord.commands.dispatch.get_command", return_value=backend):
        handled = await dispatch_command(
            cfg,
            command_id="hello",
            args_text="world",
            full_text="/hello world",
            channel_id=123,
            message_id=456,
            guild_id=789,
            thread_id=None,
            sender_id=4242,
            reply_ref=None,
            reply_text=None,
            running_tasks={},
            on_thread_known=None,
            default_engine_override=None,
            engine_overrides_resolver=None,
        )

    assert handled is True
    ctx = backend.handle.call_args.args[0]
    assert isinstance(ctx.message, MessageRef)
    assert ctx.message.sender_id == 4242


@pytest.mark.anyio
async def test_dispatch_command_sender_id_defaults_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MessageRef.sender_id should default to None when not provided."""
    cfg = MagicMock()
    cfg.runtime = MagicMock()
    cfg.runtime.allowlist = None
    cfg.runtime.plugin_config.return_value = {}
    cfg.show_resume_line = True
    cfg.exec_cfg = MagicMock()

    backend = MagicMock()
    backend.handle = AsyncMock(return_value=None)

    with patch("takopi_discord.commands.dispatch.get_command", return_value=backend):
        handled = await dispatch_command(
            cfg,
            command_id="hello",
            args_text="world",
            full_text="/hello world",
            channel_id=123,
            message_id=456,
            guild_id=789,
            thread_id=None,
            reply_ref=None,
            reply_text=None,
            running_tasks={},
            on_thread_known=None,
            default_engine_override=None,
            engine_overrides_resolver=None,
        )

    assert handled is True
    ctx = backend.handle.call_args.args[0]
    assert isinstance(ctx.message, MessageRef)
    assert ctx.message.sender_id is None
