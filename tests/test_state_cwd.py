"""Tests for DiscordStateStore cwd-change session clearing."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from takopi_discord.state import DiscordStateStore, STATE_VERSION


@pytest.mark.anyio
async def test_state_clears_sessions_on_cwd_change(tmp_path: Path) -> None:
    store = DiscordStateStore(config_path=tmp_path / "config.toml")
    # Manually seed state with old cwd and a session
    old_cwd = "/old/project"
    payload = {
        "version": STATE_VERSION,
        "cwd": old_cwd,
        "channels": {
            "1:10": {
                "context": None,
                "sessions": {"claude": "resume-token-123"},
            }
        },
        "guilds": {},
    }
    state_path = tmp_path / "discord_state.json"
    state_path.write_text(json.dumps(payload), encoding="utf-8")

    # Load should detect cwd change and clear sessions
    await store.get_context(1, 10)
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["cwd"] == os.getcwd()
    assert data["channels"]["1:10"]["sessions"] is None


@pytest.mark.anyio
async def test_state_preserves_sessions_when_cwd_unchanged(tmp_path: Path) -> None:
    store = DiscordStateStore(config_path=tmp_path / "config.toml")
    current_cwd = os.getcwd()
    payload = {
        "version": STATE_VERSION,
        "cwd": current_cwd,
        "channels": {
            "1:10": {
                "context": None,
                "sessions": {"claude": "resume-token-123"},
            }
        },
        "guilds": {},
    }
    state_path = tmp_path / "discord_state.json"
    state_path.write_text(json.dumps(payload), encoding="utf-8")

    await store.get_context(1, 10)
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["channels"]["1:10"]["sessions"] == {"claude": "resume-token-123"}
