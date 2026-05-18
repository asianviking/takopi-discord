"""Tests for message header parsing helpers in the loop module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from takopi.context import RunContext
from takopi.model import ResumeToken
from takopi.transport_runtime import ResolvedMessage
from takopi_discord.loop import (
    _apply_resolved_message,
    _build_new_thread_context,
    _dispatch_plugin_component_interaction,
    _extract_engine_id_from_header,
    _maybe_update_thread_context_from_directives,
    _parse_plugin_component_custom_id,
)
from takopi_discord.types import DiscordChannelContext, DiscordThreadContext


class FakeRuntime:
    def __init__(self) -> None:
        self.resolved: list[RunContext] = []

    def resolve_run_cwd(self, context: RunContext) -> Path:
        self.resolved.append(context)
        return Path("/repo/.worktrees") / (context.branch or "main")


class DummyThread:
    def __init__(self, *, parent_id: int | None) -> None:
        self.parent_id = parent_id


class TestExtractEngineIdFromHeader:
    def test_none(self) -> None:
        assert _extract_engine_id_from_header(None) is None

    def test_empty(self) -> None:
        assert _extract_engine_id_from_header("") is None

    def test_standard_header(self) -> None:
        assert _extract_engine_id_from_header("done · codex · 10s") == "codex"

    def test_header_with_step(self) -> None:
        assert _extract_engine_id_from_header("done · codex · 10s · step 2") == "codex"

    def test_header_without_spaces(self) -> None:
        assert _extract_engine_id_from_header("done·codex·10s") == "codex"

    def test_engine_wrapped_in_backticks(self) -> None:
        assert _extract_engine_id_from_header("done · `codex` · 10s") == "codex"

    def test_no_separator(self) -> None:
        assert _extract_engine_id_from_header("not a status line") is None


def test_apply_resolved_message_uses_directive_prompt_engine_and_context() -> None:
    context = RunContext(project="takopi-discord", branch="feat/discord")
    prompt, engine_id, run_context, resume_token = _apply_resolved_message(
        prompt="/claude @feat/discord ship it",
        engine_id="codex",
        run_context=None,
        resume_token=None,
        resolved_msg=ResolvedMessage(
            prompt="ship it",
            resume_token=None,
            engine_override="claude",
            context=context,
            context_source="directives",
        ),
        is_voice_transcribed=False,
    )

    assert prompt == "ship it"
    assert engine_id == "claude"
    assert run_context == context
    assert resume_token is None


def test_apply_resolved_message_resume_token_wins_over_engine_directive() -> None:
    token = ResumeToken(engine="pi", value="resume-123")
    prompt, engine_id, _run_context, resume_token = _apply_resolved_message(
        prompt="/claude continue",
        engine_id="codex",
        run_context=None,
        resume_token=None,
        resolved_msg=ResolvedMessage(
            prompt="continue",
            resume_token=token,
            engine_override="claude",
            context=None,
        ),
        is_voice_transcribed=False,
    )

    assert prompt == "continue"
    assert engine_id == "pi"
    assert resume_token == token


def test_apply_resolved_message_annotates_voice_after_directives_are_removed() -> None:
    prompt, _engine_id, _run_context, _resume_token = _apply_resolved_message(
        prompt="/claude fix it",
        engine_id="codex",
        run_context=None,
        resume_token=None,
        resolved_msg=ResolvedMessage(
            prompt="fix it",
            resume_token=None,
            engine_override="claude",
            context=None,
        ),
        is_voice_transcribed=True,
    )

    assert prompt == "(voice transcribed) fix it"


def test_build_new_thread_context_uses_first_turn_engine() -> None:
    context = _build_new_thread_context(
        run_context=RunContext(project="dakopi", branch="main"),
        channel_context=DiscordChannelContext(
            project="dakopi",
            worktrees_dir=".worktrees",
            default_engine="claude",
            worktree_base="main",
        ),
        engine_id="codex",
    )

    assert context == DiscordThreadContext(
        project="dakopi",
        branch="main",
        worktrees_dir=".worktrees",
        default_engine="codex",
    )


def test_build_new_thread_context_requires_project_and_branch() -> None:
    assert (
        _build_new_thread_context(
            run_context=RunContext(project="dakopi", branch=None),
            channel_context=None,
            engine_id="codex",
        )
        is None
    )


def test_parse_plugin_component_custom_id_supports_telegram_shape() -> None:
    assert _parse_plugin_component_custom_id("hello:world") == ("hello", "world")
    assert _parse_plugin_component_custom_id("hello") == ("hello", "")


def test_parse_plugin_component_custom_id_supports_discord_prefix() -> None:
    assert _parse_plugin_component_custom_id("takopi-discord:command:hello:world") == (
        "hello",
        "world",
    )


def test_parse_plugin_component_custom_id_skips_reserved_ids() -> None:
    assert _parse_plugin_component_custom_id("takopi-discord:cancel") is None
    assert _parse_plugin_component_custom_id("takopi-discord:steer") is None
    assert _parse_plugin_component_custom_id("takopi-discord:other") is None


@pytest.mark.anyio
async def test_thread_directive_rebind_keeps_parent_project_and_renames() -> None:
    state_store = MagicMock()
    state_store.set_context = AsyncMock()
    thread = MagicMock()
    thread.edit = AsyncMock()
    runtime = FakeRuntime()

    result = await _maybe_update_thread_context_from_directives(
        resolved_msg=ResolvedMessage(
            prompt="ship it",
            resume_token=None,
            engine_override=None,
            context=RunContext(project="other-project", branch="feat/new"),
            context_source="directives",
        ),
        state_store=state_store,
        guild_id=1,
        thread_id=10,
        thread_channel=thread,
        channel_context=DiscordChannelContext(
            project="takopi-discord",
            worktrees_dir=".worktrees",
            default_engine="claude",
            worktree_base="main",
        ),
        thread_context=DiscordThreadContext(
            project="takopi-discord",
            branch="main",
            worktrees_dir=".worktrees",
            default_engine="codex",
        ),
        runtime=runtime,
    )

    expected_context = RunContext(project="takopi-discord", branch="feat/new")
    assert result == expected_context
    assert runtime.resolved == [expected_context]
    state_store.set_context.assert_awaited_once_with(
        1,
        10,
        DiscordThreadContext(
            project="takopi-discord",
            branch="feat/new",
            worktrees_dir=".worktrees",
            default_engine="codex",
        ),
    )
    thread.edit.assert_awaited_once_with(name="feat/new")


@pytest.mark.anyio
async def test_thread_project_only_directive_keeps_existing_branch() -> None:
    state_store = MagicMock()
    state_store.set_context = AsyncMock()
    thread = MagicMock()
    thread.edit = AsyncMock()
    runtime = FakeRuntime()

    result = await _maybe_update_thread_context_from_directives(
        resolved_msg=ResolvedMessage(
            prompt="ship it",
            resume_token=None,
            engine_override=None,
            context=RunContext(project="other-project", branch=None),
            context_source="directives",
        ),
        state_store=state_store,
        guild_id=1,
        thread_id=10,
        thread_channel=thread,
        channel_context=DiscordChannelContext(
            project="takopi-discord",
            worktrees_dir=".worktrees",
            default_engine="claude",
            worktree_base="main",
        ),
        thread_context=DiscordThreadContext(
            project="takopi-discord",
            branch="existing",
            worktrees_dir=".worktrees",
            default_engine="codex",
        ),
        runtime=runtime,
    )

    assert result == RunContext(project="takopi-discord", branch="existing")
    assert runtime.resolved == []
    state_store.set_context.assert_not_awaited()
    thread.edit.assert_not_awaited()


@pytest.mark.anyio
async def test_plugin_component_dispatch_uses_thread_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import takopi_discord.loop as loop

    monkeypatch.setattr(loop.discord, "Thread", DummyThread)

    created_coroutines = []

    def fake_create_task(coro, *, name=None):
        created_coroutines.append(coro)
        return MagicMock(name=name)

    dispatch = AsyncMock(return_value=True)
    monkeypatch.setattr(loop.asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(loop, "dispatch_command", dispatch)

    interaction = MagicMock()
    interaction.guild = MagicMock()
    interaction.guild.id = 1
    interaction.channel_id = 99
    interaction.channel = DummyThread(parent_id=20)
    interaction.message = MagicMock()
    interaction.message.id = 555
    interaction.user = MagicMock()
    interaction.user.id = 42
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()

    state_store = MagicMock()

    async def get_context(_guild_id: int, channel_id: int):
        if channel_id == 99:
            return DiscordThreadContext(
                project="takopi-discord",
                branch="feat/plugin",
                worktrees_dir=".worktrees",
                default_engine="codex",
            )
        if channel_id == 20:
            return DiscordChannelContext(
                project="takopi-discord",
                worktrees_dir=".worktrees",
                default_engine="claude",
                worktree_base="main",
            )
        return None

    state_store.get_context = AsyncMock(side_effect=get_context)
    prefs_store = MagicMock()
    cfg = MagicMock()
    cfg.allowed_user_ids = None

    handled = await _dispatch_plugin_component_interaction(
        interaction=interaction,
        custom_id="hello:world",
        cfg=cfg,
        state_store=state_store,
        prefs_store=prefs_store,
        running_tasks={},
        current_command_ids={"hello"},
        refresh_commands=MagicMock(return_value={"hello"}),
        default_engine_override=None,
    )

    assert handled is True
    interaction.response.defer.assert_awaited_once()
    assert len(created_coroutines) == 1
    await created_coroutines[0]

    dispatch.assert_awaited_once()
    kwargs = dispatch.call_args.kwargs
    assert kwargs["command_id"] == "hello"
    assert kwargs["args_text"] == "world"
    assert kwargs["full_text"] == "hello:world"
    assert kwargs["channel_id"] == 99
    assert kwargs["thread_id"] == 99
    assert kwargs["sender_id"] == 42
    assert kwargs["default_context"] == RunContext(
        project="takopi-discord",
        branch="feat/plugin",
    )


@pytest.mark.anyio
async def test_plugin_component_dispatch_defers_unknown_command() -> None:
    interaction = MagicMock()
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()

    handled = await _dispatch_plugin_component_interaction(
        interaction=interaction,
        custom_id="missing:world",
        cfg=MagicMock(),
        state_store=MagicMock(),
        prefs_store=MagicMock(),
        running_tasks={},
        current_command_ids=set(),
        refresh_commands=MagicMock(return_value=set()),
        default_engine_override=None,
    )

    assert handled is True
    interaction.response.defer.assert_awaited_once()
