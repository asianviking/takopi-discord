"""Tests for upstream v0.19.0 adaptations in the Discord message loop."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest

import takopi_discord.loop as loop_module
from takopi.model import ResumeToken
from takopi.scheduler import ThreadScheduler
from takopi.transport import MessageRef

from takopi_discord.bridge import (
    DiscordBridgeConfig,
    DiscordFilesSettings,
    DiscordVoiceMessageSettings,
)


class _StopLoop(RuntimeError):
    pass


@dataclass
class _DummyPrefsStore:
    async def ensure_loaded(self) -> None:
        return None

    async def get_trigger_mode(self, guild_id: int, channel_id: int) -> str | None:
        return None

    async def get_model_override(
        self, guild_id: int, channel_id: int, engine_id: str
    ) -> str | None:
        return None

    async def get_reasoning_override(
        self, guild_id: int, channel_id: int, engine_id: str
    ) -> str | None:
        return None

    async def get_default_engine(self, guild_id: int, channel_id: int) -> str | None:
        return None


@dataclass
class _DummyStateStore:
    async def get_startup_channel(self, guild_id: int) -> int | None:
        return None

    async def set_startup_channel(self, guild_id: int, channel_id: int) -> None:
        return None

    async def get_context(self, guild_id: int, channel_id: int):
        return SimpleNamespace(
            project="proj",
            worktrees_dir=".worktrees",
            default_engine="claude",
            worktree_base="main",
        )


class _DummyBotClient:
    def __init__(self, message=None) -> None:
        self.user = SimpleNamespace(id=999, name="Takopi")
        self._message = message
        self._handler = None
        self._handlers: dict[str, callable] = {}
        self.bot = SimpleNamespace(
            event=self._event,
            process_application_commands=AsyncMock(),
            sync_commands=AsyncMock(),
        )
        self.closed = False
        self.create_thread = AsyncMock(return_value=None)
        self.send_message = AsyncMock(return_value=None)

    def _event(self, fn: callable) -> callable:
        self._handlers[fn.__name__] = fn
        return fn

    def set_message_handler(self, handler) -> None:
        self._handler = handler

    async def start(self) -> None:
        if self._message is not None and self._handler is not None:
            await self._handler(self._message)
        raise _StopLoop()

    async def close(self) -> None:
        self.closed = True


def _runtime_stub(config_path: Path) -> MagicMock:
    runtime = MagicMock()
    runtime.config_path = config_path
    runtime.allowlist = None
    runtime.default_engine = "claude"
    runtime.watch_config = False
    runtime.engine_ids = ["claude"]
    runtime.format_context_line.return_value = ""
    runtime.is_resume_line = lambda line: False
    runtime.resolve_runner.return_value = SimpleNamespace(
        available=True,
        runner=SimpleNamespace(
            engine="claude",
            is_resume_line=lambda line: False,
            format_resume=lambda token: "",
            extract_resume=lambda text: None,
            run=lambda prompt, resume: None,
        ),
        issue=None,
    )
    runtime.resolve_run_cwd.return_value = config_path.parent
    runtime.resolve_message.return_value = None
    return runtime


@pytest.mark.anyio
async def test_handle_cancel_interaction_cancels_queued_job() -> None:
    from takopi_discord.loop import _handle_cancel_interaction

    interaction = SimpleNamespace(
        type=loop_module.discord.InteractionType.component,
        data={"custom_id": loop_module.CANCEL_BUTTON_ID},
        channel_id=123,
        message=SimpleNamespace(id=456),
        user=SimpleNamespace(id=1),
        response=SimpleNamespace(defer=AsyncMock()),
    )

    cfg = MagicMock()
    cfg.allowed_user_ids = None
    cfg.runtime.format_context_line.return_value = ""
    cfg.exec_cfg.presenter.render_progress = MagicMock(return_value=MagicMock())
    cfg.exec_cfg.transport.edit = AsyncMock(return_value=MagicMock())

    cancel_task_called = False

    async def cancel_task(channel_id: int) -> None:
        nonlocal cancel_task_called
        cancel_task_called = True

    async with anyio.create_task_group() as tg:
        scheduler = ThreadScheduler(task_group=tg, run_job=lambda job: None)
        progress_ref = MessageRef(channel_id=123, message_id=456)
        resume = ResumeToken(engine="claude", value="abc")
        await scheduler.enqueue_resume(
            chat_id=123,
            user_msg_id=10,
            text="hello",
            resume_token=resume,
            progress_ref=progress_ref,
        )

        await _handle_cancel_interaction(
            interaction,
            cfg,
            scheduler,
            cancel_task,
        )

        # Queued job should be gone
        assert await scheduler.cancel_queued(123, 456) is None
        # Fallback running-task cancel should not have been invoked
        assert not cancel_task_called

        cfg.exec_cfg.presenter.render_progress.assert_called_once()
        cfg.exec_cfg.transport.edit.assert_awaited_once()
        interaction.response.defer.assert_awaited_once()

        tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_voice_attachment_gets_transcribed_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio_attachment = SimpleNamespace(
        id=1,
        filename="voice.ogg",
        content_type="audio/ogg",
        size=100,
        read=AsyncMock(return_value=b"audio_data"),
    )
    message = SimpleNamespace(
        id=100,
        guild=SimpleNamespace(id=1),
        created_at=datetime.now(UTC) + timedelta(seconds=1),
        channel=SimpleNamespace(id=10),
        author=SimpleNamespace(id=123, bot=False, name="User"),
        content="",
        attachments=[audio_attachment],
        reference=None,
        mentions=[],
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
    monkeypatch.setattr(loop_module, "is_audio_attachment", lambda att: True)

    class FakeTranscriber:
        def __init__(self, model_name: str) -> None:
            pass

        async def transcribe_bytes(self, payload: bytes, *, suffix: str) -> str:
            return "hello world"

    monkeypatch.setattr(loop_module, "WhisperAttachmentTranscriber", FakeTranscriber)

    cfg = DiscordBridgeConfig(
        bot=bot,
        runtime=_runtime_stub(tmp_path / "config.toml"),
        guild_id=None,
        startup_msg="ready",
        exec_cfg=SimpleNamespace(
            transport=MagicMock(),
            presenter=MagicMock(),
        ),
        allowed_user_ids=None,
        files=DiscordFilesSettings(),
        voice_messages=DiscordVoiceMessageSettings(enabled=True),
    )

    captured_prompts: list[str] = []

    async def fake_takopi_handle_message(_cfg, *, incoming, **kwargs):
        captured_prompts.append(incoming.text)

    monkeypatch.setattr(
        "takopi.runner_bridge.handle_message", fake_takopi_handle_message
    )

    with pytest.raises(BaseExceptionGroup):
        await loop_module.run_main_loop(cfg)

    assert len(captured_prompts) == 1
    assert captured_prompts[0] == "(voice transcribed) hello world"
