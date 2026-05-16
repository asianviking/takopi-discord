"""Tests for reasoning engine support and level validation."""

from __future__ import annotations

import pytest

from takopi_discord.overrides import (
    REASONING_LEVELS,
    is_valid_reasoning_level,
    supports_reasoning,
)


@pytest.mark.parametrize(
    "engine_id,expected",
    [
        ("claude", True),
        ("codex", True),
        ("pi", True),
        ("gemini", False),
        ("openai", False),
        ("unknown", False),
    ],
)
def test_supports_reasoning(engine_id: str, expected: bool) -> None:
    assert supports_reasoning(engine_id) is expected


@pytest.mark.parametrize(
    "level,expected",
    [
        ("minimal", True),
        ("low", True),
        ("medium", True),
        ("high", True),
        ("xhigh", True),
        ("max", False),
        ("", False),
        ("LOW", False),
    ],
)
def test_is_valid_reasoning_level(level: str, expected: bool) -> None:
    assert is_valid_reasoning_level(level) is expected


def test_reasoning_levels_frozen_set_contents() -> None:
    assert REASONING_LEVELS == {"minimal", "low", "medium", "high", "xhigh"}
