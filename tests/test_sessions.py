"""Tests for the session-scope predicate helpers."""

from __future__ import annotations

import pytest

from takopi_discord.resume import should_render_resume_line
from takopi_discord.sessions import (
    normalize_session_mode,
    session_author_id,
    should_resume_session,
)


class TestNormalizeSessionMode:
    def test_stateless_is_canonical(self) -> None:
        assert normalize_session_mode("stateless") == "stateless"

    @pytest.mark.parametrize("session_mode", ["thread", "chat"])
    def test_thread_and_legacy_chat_normalize_to_thread(
        self, session_mode: str
    ) -> None:
        assert normalize_session_mode(session_mode) == "thread"

    @pytest.mark.parametrize("session_mode", ["", "unknown", None])
    def test_invalid_values_fall_back_to_thread(self, session_mode: object) -> None:
        assert normalize_session_mode(session_mode) == "thread"


class TestShouldResumeSession:
    @pytest.mark.parametrize("thread_id", [None, 42])
    def test_stateless_never_resumes(self, thread_id: int | None) -> None:
        assert should_resume_session("stateless", thread_id=thread_id) is False

    def test_legacy_chat_mode_is_thread_scoped(self) -> None:
        assert should_resume_session("chat", thread_id=42) is True
        assert should_resume_session("chat", thread_id=None) is False

    def test_thread_mode_resumes_only_in_thread(self) -> None:
        assert should_resume_session("thread", thread_id=42) is True
        assert should_resume_session("thread", thread_id=None) is False


class TestShouldRenderResumeLine:
    @pytest.mark.parametrize("session_mode", ["thread", "chat"])
    def test_hides_resume_line_inside_thread_session(
        self, session_mode: str
    ) -> None:
        assert (
            should_render_resume_line(
                session_mode,
                thread_id=42,
                show_resume_line=True,
            )
            is False
        )

    def test_shows_resume_line_outside_thread_when_enabled(self) -> None:
        assert (
            should_render_resume_line(
                "thread",
                thread_id=None,
                show_resume_line=True,
            )
            is True
        )

    def test_respects_disabled_resume_line_outside_thread(self) -> None:
        assert (
            should_render_resume_line(
                "stateless",
                thread_id=None,
                show_resume_line=False,
            )
            is False
        )


class TestSessionAuthorId:
    def test_thread_drops_author(self) -> None:
        assert session_author_id(thread_id=42, author_id=99) is None

    def test_channel_keeps_author(self) -> None:
        assert session_author_id(thread_id=None, author_id=99) == 99

    def test_channel_with_no_author_is_none(self) -> None:
        assert session_author_id(thread_id=None, author_id=None) is None
