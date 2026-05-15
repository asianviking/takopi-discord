"""Tests for Discord backend config parsing of allowed bot senders."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import takopi_discord.backend as backend_module


def _runtime_stub(config_path: Path) -> MagicMock:
    runtime = MagicMock()
    runtime.available_engine_ids.return_value = ["codex"]
    runtime.missing_engine_ids.return_value = []
    runtime.engine_ids_with_status.return_value = []
    runtime.project_aliases.return_value = []
    runtime.default_engine = "codex"
    runtime.config_path = config_path
    runtime.watch_config = False
    return runtime


def test_build_and_run_parses_allowed_bot_user_ids(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_run_main_loop(cfg, **kwargs) -> None:
        captured["cfg"] = cfg
        captured["kwargs"] = kwargs

    def fake_anyio_run(fn) -> None:
        asyncio.run(fn())

    monkeypatch.setattr(backend_module, "run_main_loop", fake_run_main_loop)
    monkeypatch.setattr(backend_module.anyio, "run", fake_anyio_run)

    transport_config = {
        "bot_token": "secret",
        "allowed_bot_user_ids": ["123", 456],
        "files": {},
        "voice_messages": {},
    }

    backend_module.DiscordBackend().build_and_run(
        transport_config=transport_config,
        config_path=tmp_path / "config.yaml",
        runtime=_runtime_stub(tmp_path / "config.yaml"),
        final_notify=False,
        default_engine_override=None,
    )

    assert captured["cfg"].allowed_bot_user_ids == frozenset({123, 456})


def test_build_and_run_parses_max_download_bytes(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_run_main_loop(cfg, **kwargs) -> None:
        captured["cfg"] = cfg
        captured["kwargs"] = kwargs

    def fake_anyio_run(fn) -> None:
        asyncio.run(fn())

    monkeypatch.setattr(backend_module, "run_main_loop", fake_run_main_loop)
    monkeypatch.setattr(backend_module.anyio, "run", fake_anyio_run)

    transport_config = {
        "bot_token": "secret",
        "files": {"max_download_bytes": 10 * 1024 * 1024},
        "voice_messages": {},
    }

    backend_module.DiscordBackend().build_and_run(
        transport_config=transport_config,
        config_path=tmp_path / "config.yaml",
        runtime=_runtime_stub(tmp_path / "config.yaml"),
        final_notify=False,
        default_engine_override=None,
    )

    assert captured["cfg"].files.max_download_bytes == 10 * 1024 * 1024
