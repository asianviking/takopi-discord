"""Tests for message and interaction deduplication."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from takopi.model import ResumeToken
from takopi.scheduler import ThreadJob
from takopi.transport import RenderedMessage
from takopi_discord.bridge import DiscordPresenter
from takopi_discord.loop import (
    _BoundedDeduper,
    _edit_queued_progress,
    _send_queued_progress,
)


class _FakeFormatter:
    def render_progress_parts(self, state, *, elapsed_s, label):
        return SimpleNamespace(header=f"{label} · test", body="", footer="")


class _FakeState:
    pass


class _FakeTransport:
    def __init__(self) -> None:
        self.sent: list[RenderedMessage] = []
        self.edited: list[RenderedMessage] = []

    async def send(self, *, channel_id, message, options=None):
        self.sent.append(message)
        return SimpleNamespace(channel_id=channel_id, message_id=len(self.sent))

    async def edit(self, *, ref, message, wait=True):
        self.edited.append(message)
        return ref


class _FakeProgressPresenter:
    def render_progress(self, state, *, elapsed_s, label):
        return RenderedMessage(
            text=label,
            extra={
                "show_cancel": label not in {"cancelled", "steered"},
                "show_steer": label == "queued",
            },
        )


class _FakeRuntime:
    def format_context_line(self, context):
        return None


def test_presenter_queued_shows_steer_and_cancel() -> None:
    presenter = DiscordPresenter(formatter=_FakeFormatter())
    rendered = presenter.render_progress(_FakeState(), elapsed_s=0.0, label="queued")
    assert rendered.extra["show_cancel"] is True
    assert rendered.extra["show_steer"] is True


def test_presenter_working_shows_only_cancel() -> None:
    presenter = DiscordPresenter(formatter=_FakeFormatter())
    rendered = presenter.render_progress(_FakeState(), elapsed_s=0.0, label="working")
    assert rendered.extra["show_cancel"] is True
    assert rendered.extra["show_steer"] is False


def test_presenter_cancelled_shows_neither() -> None:
    presenter = DiscordPresenter(formatter=_FakeFormatter())
    rendered = presenter.render_progress(
        _FakeState(), elapsed_s=0.0, label="`cancelled`"
    )
    assert rendered.extra["show_cancel"] is False
    assert rendered.extra["show_steer"] is False


def test_presenter_steered_shows_neither() -> None:
    presenter = DiscordPresenter(formatter=_FakeFormatter())
    rendered = presenter.render_progress(_FakeState(), elapsed_s=0.0, label="steered")
    assert rendered.extra["show_cancel"] is False
    assert rendered.extra["show_steer"] is False


def test_bounded_deduper_rejects_duplicates_and_evicts_oldest() -> None:
    deduper = _BoundedDeduper(limit=2)

    assert deduper.add(("guild", 1)) is True
    assert deduper.add(("guild", 1)) is False
    assert deduper.add(("guild", 2)) is True
    assert deduper.add(("guild", 3)) is True
    assert deduper.add(("guild", 1)) is True


@pytest.mark.anyio
async def test_send_queued_progress_only_marks_steerable_when_busy() -> None:
    transport = _FakeTransport()
    cfg = SimpleNamespace(
        runtime=_FakeRuntime(),
        exec_cfg=SimpleNamespace(
            presenter=_FakeProgressPresenter(),
            transport=transport,
        ),
        show_resume_line=False,
        session_mode="chat",
    )
    resume = ResumeToken(engine="codex", value="resume-token")

    await _send_queued_progress(
        cfg,
        channel_id=1,
        user_msg_id=2,
        thread_id=None,
        resume_token=resume,
        context=None,
        steerable=False,
    )
    await _send_queued_progress(
        cfg,
        channel_id=1,
        user_msg_id=3,
        thread_id=None,
        resume_token=resume,
        context=None,
        steerable=True,
    )

    assert transport.sent[0].text == "starting"
    assert transport.sent[0].extra["show_steer"] is False
    assert transport.sent[1].text == "queued"
    assert transport.sent[1].extra["show_steer"] is True


@pytest.mark.anyio
async def test_edit_queued_progress_clears_buttons_when_cancelled() -> None:
    transport = _FakeTransport()
    cfg = SimpleNamespace(
        runtime=_FakeRuntime(),
        exec_cfg=SimpleNamespace(
            presenter=_FakeProgressPresenter(),
            transport=transport,
        ),
        show_resume_line=False,
        session_mode="chat",
    )
    job = ThreadJob(
        chat_id=1,
        user_msg_id=2,
        text="queued prompt",
        resume_token=ResumeToken(engine="codex", value="resume-token"),
    )

    await _edit_queued_progress(
        cfg,
        channel_id=1,
        message_id=10,
        job=job,
        label="cancelled",
    )

    assert transport.edited[0].text == "cancelled"
    assert transport.edited[0].extra["show_cancel"] is False
    assert transport.edited[0].extra["show_steer"] is False


@pytest.mark.anyio
async def test_discover_command_ids_filters_reserved() -> None:
    from takopi_discord.commands.registration import discover_command_ids

    ids = discover_command_ids(allowlist=None)
    assert "cancel" not in ids
    assert "file" not in ids
    assert "new" not in ids
    assert "agent" not in ids
    assert "model" not in ids
    assert "reasoning" not in ids
    assert "trigger" not in ids
    assert "topic" not in ids
    assert "ctx" not in ids
