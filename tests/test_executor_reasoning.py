"""Tests for reasoning warning prelude in executor."""

from __future__ import annotations

import pytest

from takopi_discord.commands.executor import _reasoning_warning
from takopi.runners.run_options import EngineRunOptions


def test_reasoning_warning_returns_none_when_no_override() -> None:
    assert _reasoning_warning(engine="codex", run_options=None) is None


def test_reasoning_warning_returns_none_for_supported_engine() -> None:
    assert (
        _reasoning_warning(
            engine="codex", run_options=EngineRunOptions(reasoning="high")
        )
        is None
    )


def test_reasoning_warning_returns_event_for_unsupported_engine() -> None:
    evt = _reasoning_warning(
        engine="claude", run_options=EngineRunOptions(reasoning="high")
    )
    assert evt is not None
    assert "not supported" in evt.message
    assert evt.engine == "claude"
