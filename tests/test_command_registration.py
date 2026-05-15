"""Tests for plugin command registration helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from takopi.ids import RESERVED_CHAT_COMMANDS
from takopi_discord.commands.registration import (
    _format_plugin_starter_message,
    register_plugin_commands,
)


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


class TestRegisterPluginCommandsReservedFiltering:
    def test_reserved_ids_are_not_registered(self) -> None:
        bot = MagicMock()
        bot.bot = MagicMock()
        bot.bot.slash_command = MagicMock(return_value=lambda fn: fn)
        cfg = MagicMock()
        cfg.runtime.allowlist = None

        with patch("takopi_discord.commands.registration.get_command") as mock_get:
            mock_backend = MagicMock()
            mock_backend.description = "a plugin"
            mock_get.return_value = mock_backend

            command_ids = {"new", "agent", "ctx", "cancel", "file", "topic", "myplugin"}
            register_plugin_commands(
                bot,
                cfg,
                command_ids=command_ids,
                running_tasks={},
                state_store=MagicMock(),
                prefs_store=MagicMock(),
                default_engine_override=None,
            )

            registered_names = {
                call.kwargs.get("name")
                for call in bot.bot.slash_command.call_args_list
            }
            assert "myplugin" in registered_names
            for reserved in RESERVED_CHAT_COMMANDS:
                assert reserved not in registered_names
