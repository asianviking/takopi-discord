"""Tests for message and interaction deduplication."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from takopi_discord.bridge import DiscordPresenter


class _FakeFormatter:
    def render_progress_parts(self, state, *, elapsed_s, label):
        return SimpleNamespace(header=f"{label} · test", body="", footer="")


class _FakeState:
    pass


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
