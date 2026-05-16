"""Tests for voice message transcription helpers."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import takopi_discord.voice_messages as voice_messages


def test_is_audio_attachment_detects_by_content_type() -> None:
    attachment = MagicMock()
    attachment.content_type = "audio/ogg"
    attachment.filename = "voice.ogg"
    assert voice_messages.is_audio_attachment(attachment) is True


def test_is_audio_attachment_detects_by_extension() -> None:
    attachment = MagicMock()
    attachment.content_type = None
    attachment.filename = "clip.MP3"
    assert voice_messages.is_audio_attachment(attachment) is True


def test_is_audio_attachment_rejects_unknown() -> None:
    attachment = MagicMock()
    attachment.content_type = "image/png"
    attachment.filename = "image.png"
    assert voice_messages.is_audio_attachment(attachment) is False


@dataclass(frozen=True, slots=True)
class _Seg:
    text: str


@pytest.mark.anyio
async def test_transcriber_cleans_whisper_artifacts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], *, capture_output: bool):
        calls.append(cmd)

        class Result:
            returncode = 0
            stderr = b""

        return Result()

    class DummyModel:
        def __init__(self, model_name: str) -> None:
            self.model_name = model_name

        def transcribe(self, _path: str):
            return [
                _Seg(text="[Silence]"),
                _Seg(text=" hello "),
                _Seg(text="(Music)"),
                _Seg(text="world"),
            ]

    monkeypatch.setattr(voice_messages, "WhisperModel", DummyModel)
    monkeypatch.setattr(voice_messages.subprocess, "run", fake_run)

    transcriber = voice_messages.WhisperAttachmentTranscriber("base")
    text = await transcriber.transcribe_bytes(b"123", suffix=".ogg")

    assert text == "hello world"
    assert calls
    assert "ffmpeg" in calls[0][0]


@pytest.mark.anyio
async def test_transcriber_uses_remote_client_when_base_url_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class DummyTranscriptions:
        async def create(self, *, model: str, file):
            captured["model"] = model
            captured["filename"] = file[0]
            captured["payload"] = file[1].read()
            return SimpleNamespace(text=" hello from server ")

    class DummyClient:
        def __init__(self, *, api_key: str, base_url: str) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.audio = SimpleNamespace(transcriptions=DummyTranscriptions())

    monkeypatch.setattr(voice_messages, "AsyncOpenAI", DummyClient)

    transcriber = voice_messages.WhisperAttachmentTranscriber(
        "whisper-large-v3",
        base_url="http://localhost:8000/v1",
        api_key="local-key",
    )
    text = await transcriber.transcribe_bytes(b"audio", suffix=".ogg")

    assert text == "hello from server"
    assert captured == {
        "api_key": "local-key",
        "base_url": "http://localhost:8000/v1",
        "model": "whisper-large-v3",
        "filename": "voice.ogg",
        "payload": b"audio",
    }
