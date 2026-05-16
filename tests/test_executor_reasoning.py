"""Tests for reasoning warning prelude in executor."""

from __future__ import annotations

from takopi.runners.run_options import EngineRunOptions
from takopi_discord.commands.executor import _reasoning_warning
from takopi_discord.overrides import allowed_reasoning_levels, is_valid_reasoning_level


def test_reasoning_warning_returns_none_when_no_override() -> None:
    assert _reasoning_warning(engine="codex", run_options=None) is None


def test_reasoning_warning_returns_none_for_codex() -> None:
    assert (
        _reasoning_warning(
            engine="codex", run_options=EngineRunOptions(reasoning="high")
        )
        is None
    )


def test_reasoning_warning_returns_none_for_claude() -> None:
    assert (
        _reasoning_warning(
            engine="claude", run_options=EngineRunOptions(reasoning="high")
        )
        is None
    )


def test_reasoning_warning_returns_none_for_pi() -> None:
    assert (
        _reasoning_warning(engine="pi", run_options=EngineRunOptions(reasoning="high"))
        is None
    )


def test_reasoning_warning_returns_event_for_unsupported_engine() -> None:
    evt = _reasoning_warning(
        engine="opencode", run_options=EngineRunOptions(reasoning="high")
    )
    assert evt is not None
    assert "not supported" in evt.message
    assert evt.engine == "opencode"


def test_reasoning_levels_are_engine_specific() -> None:
    assert allowed_reasoning_levels("claude") == (
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    )
    assert is_valid_reasoning_level("claude", "max")
    assert not is_valid_reasoning_level("codex", "max")
    assert is_valid_reasoning_level("pi", "minimal")
    assert not is_valid_reasoning_level("opencode", "high")
