"""Tests for message header parsing helpers in the loop module."""

from __future__ import annotations

from takopi.context import RunContext
from takopi.model import ResumeToken
from takopi.transport_runtime import ResolvedMessage
from takopi_discord.loop import _apply_resolved_message, _extract_engine_id_from_header


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
