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
    _extract_engine_id_from_header,
    _maybe_update_thread_context_from_directives,
)
from takopi_discord.types import DiscordChannelContext, DiscordThreadContext


class FakeRuntime:
    def __init__(self) -> None:
        self.resolved: list[RunContext] = []

    def resolve_run_cwd(self, context: RunContext) -> Path:
        self.resolved.append(context)
        return Path("/repo/.worktrees") / (context.branch or "main")


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
