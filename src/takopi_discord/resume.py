"""Helpers for Discord resume-token rendering."""

from __future__ import annotations

from dataclasses import dataclass

from takopi.model import ResumeToken
from takopi.runner import Runner

from .sessions import should_resume_session


def should_render_resume_line(
    session_mode: str,
    *,
    thread_id: int | None,
    show_resume_line: bool,
) -> bool:
    """Whether a visible resume line should be included in Discord output."""
    return show_resume_line and not should_resume_session(
        session_mode, thread_id=thread_id
    )


@dataclass(slots=True)
class ResumeLineProxy:
    """Proxy runner that suppresses visible resume line output."""

    runner: Runner

    @property
    def engine(self) -> str:
        return self.runner.engine

    def is_resume_line(self, line: str) -> bool:
        return self.runner.is_resume_line(line)

    def format_resume(self, _: ResumeToken) -> str:
        return ""

    def extract_resume(self, text: str | None) -> ResumeToken | None:
        return self.runner.extract_resume(text)

    def run(self, prompt: str, resume: ResumeToken | None):
        return self.runner.run(prompt, resume)
