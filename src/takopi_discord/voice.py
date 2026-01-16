"""Voice chat support for Discord transport using Pycord's native recording."""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import struct
import tempfile
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import discord

if TYPE_CHECKING:
    from openai import AsyncOpenAI

    from .client import DiscordBotClient

logger = logging.getLogger("takopi.discord.voice")

# Audio processing constants
SILENCE_THRESHOLD_MS = 1500  # Time of silence before processing
MIN_AUDIO_DURATION_MS = 500  # Minimum audio duration to process
SAMPLE_RATE = 48000  # Discord uses 48kHz
CHANNELS = 2  # Stereo
SAMPLE_WIDTH = 2  # 16-bit PCM


@dataclass
class VoiceSession:
    """Tracks an active voice session."""

    guild_id: int
    voice_channel_id: int
    text_channel_id: int
    voice_client: discord.VoiceClient
    project: str
    branch: str
    delete_on_leave: bool = True  # Delete the voice channel when leaving


@dataclass
class AudioBuffer:
    """Buffers audio chunks and detects speech pauses."""

    user_id: int
    chunks: list[bytes] = field(default_factory=list)
    last_voice_time: float = 0.0
    silence_threshold_ms: int = SILENCE_THRESHOLD_MS

    def add_chunk(self, chunk: bytes) -> None:
        """Add an audio chunk to the buffer."""
        self.chunks.append(chunk)
        self.last_voice_time = time.monotonic()

    def is_silence_detected(self) -> bool:
        """Check if enough silence has passed to trigger processing."""
        if not self.chunks:
            return False
        elapsed_ms = (time.monotonic() - self.last_voice_time) * 1000
        return elapsed_ms >= self.silence_threshold_ms

    def get_audio_and_clear(self) -> bytes:
        """Get all buffered audio and clear the buffer."""
        audio = b"".join(self.chunks)
        self.chunks.clear()
        return audio

    def duration_ms(self) -> float:
        """Calculate approximate duration of buffered audio in ms."""
        total_bytes = sum(len(c) for c in self.chunks)
        # PCM: bytes / (sample_rate * channels * sample_width) * 1000
        return (total_bytes / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)) * 1000


VoiceMessageHandler = Callable[
    [
        int,
        int,
        str,
        str,
        str,
        str,
    ],  # guild_id, text_channel_id, transcript, user_name, project, branch
    Coroutine[Any, Any, str | None],  # Returns response text or None
]


class StreamingSink(discord.sinks.Sink):
    """Custom sink that captures audio per-user for real-time processing."""

    def __init__(self, callback: Callable[[int, bytes], None]) -> None:
        super().__init__()
        self._callback = callback

    def write(self, data: bytes, user: int) -> None:
        """Called when audio data is received from a user."""
        self._callback(user, data)

    def cleanup(self) -> None:
        """Clean up resources."""
        pass


class VoiceManager:
    """Manages voice connections and audio processing."""

    def __init__(
        self,
        bot: DiscordBotClient,
        openai_client: AsyncOpenAI,
        *,
        tts_voice: str = "nova",
        tts_model: str = "tts-1",
    ) -> None:
        self._bot = bot
        self._openai = openai_client
        self._tts_voice = tts_voice
        self._tts_model = tts_model
        self._sessions: dict[int, VoiceSession] = {}  # guild_id -> session
        self._audio_buffers: dict[
            tuple[int, int], AudioBuffer
        ] = {}  # (guild_id, user_id) -> buffer
        self._processing_lock = asyncio.Lock()
        self._silence_check_task: asyncio.Task[None] | None = None
        self._message_handler: VoiceMessageHandler | None = None

    def set_message_handler(self, handler: VoiceMessageHandler) -> None:
        """Set the handler for processing transcribed voice messages."""
        self._message_handler = handler

    @property
    def sessions(self) -> dict[int, VoiceSession]:
        """Get active voice sessions."""
        return self._sessions

    def is_connected(self, guild_id: int) -> bool:
        """Check if the bot is connected to a voice channel in the guild."""
        session = self._sessions.get(guild_id)
        return session is not None and session.voice_client.is_connected()

    def get_session(self, guild_id: int) -> VoiceSession | None:
        """Get the voice session for a guild."""
        return self._sessions.get(guild_id)

    def _receive_audio(self, guild_id: int, user_id: int, data: bytes) -> None:
        """Receive audio data from a user (called from sink)."""
        key = (guild_id, user_id)
        if key not in self._audio_buffers:
            self._audio_buffers[key] = AudioBuffer(user_id=user_id)
            logger.info("Started receiving audio from user %s in guild %s", user_id, guild_id)
        self._audio_buffers[key].add_chunk(data)

    async def join_channel(
        self,
        voice_channel: discord.VoiceChannel,
        text_channel_id: int,
        project: str,
        branch: str,
    ) -> VoiceSession:
        """Join a voice channel and start listening."""
        guild_id = voice_channel.guild.id

        # Disconnect from existing session if any
        if guild_id in self._sessions:
            await self.leave_channel(guild_id)

        # Connect to the voice channel
        voice_client = await voice_channel.connect()
        logger.info("Connected to voice channel %s", voice_channel.id)

        # Create session
        session = VoiceSession(
            guild_id=guild_id,
            voice_channel_id=voice_channel.id,
            text_channel_id=text_channel_id,
            voice_client=voice_client,
            project=project,
            branch=branch,
        )
        self._sessions[guild_id] = session

        # Create a sink that forwards audio to our buffer
        def on_audio(user_id: int, data: bytes) -> None:
            self._receive_audio(guild_id, user_id, data)

        sink = StreamingSink(on_audio)

        # Callback when recording stops
        async def on_recording_stop(sink: discord.sinks.Sink, *args: Any) -> None:
            logger.info("Recording stopped for guild %s", guild_id)

        # Start recording
        voice_client.start_recording(sink, on_recording_stop)
        logger.info("Started recording on voice channel %s", voice_channel.id)

        # Start silence detection task if not running
        if self._silence_check_task is None or self._silence_check_task.done():
            self._silence_check_task = asyncio.create_task(self._silence_check_loop())

        logger.info(
            "Joined voice channel %s in guild %s, linked to text channel %s",
            voice_channel.id,
            guild_id,
            text_channel_id,
        )
        return session

    async def leave_channel(self, guild_id: int) -> None:
        """Leave the voice channel in a guild and optionally delete it."""
        session = self._sessions.pop(guild_id, None)
        if session is None:
            return

        voice_channel_id = session.voice_channel_id
        should_delete = session.delete_on_leave

        # Stop recording if active
        if session.voice_client.recording:
            session.voice_client.stop_recording()

        # Disconnect
        await session.voice_client.disconnect()

        # Clear audio buffers for this guild
        keys_to_remove = [k for k in self._audio_buffers if k[0] == guild_id]
        for key in keys_to_remove:
            del self._audio_buffers[key]

        # Delete the voice channel if it was bot-created
        if should_delete:
            voice_channel = self._bot.bot.get_channel(voice_channel_id)
            if voice_channel is not None:
                with contextlib.suppress(discord.HTTPException):
                    await voice_channel.delete(reason="Voice session ended")
                    logger.info(
                        "Deleted voice channel %s in guild %s",
                        voice_channel_id,
                        guild_id,
                    )

        logger.info("Left voice channel in guild %s", guild_id)

    async def _silence_check_loop(self) -> None:
        """Periodically check for silence and process audio."""
        while self._sessions:
            await asyncio.sleep(0.1)  # Check every 100ms

            buffers_to_process: list[tuple[int, int, AudioBuffer]] = []

            for (guild_id, user_id), buffer in list(self._audio_buffers.items()):
                if (
                    buffer.is_silence_detected()
                    and buffer.duration_ms() >= MIN_AUDIO_DURATION_MS
                ):
                    buffers_to_process.append((guild_id, user_id, buffer))

            for guild_id, user_id, buffer in buffers_to_process:
                audio = buffer.get_audio_and_clear()
                logger.info("Processing audio from user %s: %d bytes", user_id, len(audio))
                asyncio.create_task(self._process_audio(guild_id, user_id, audio))

    async def _process_audio(self, guild_id: int, user_id: int, audio: bytes) -> None:
        """Process captured audio: transcribe and handle."""
        session = self._sessions.get(guild_id)
        if session is None:
            return

        async with self._processing_lock:
            try:
                # Get user info
                guild = self._bot.bot.get_guild(guild_id)
                member = guild.get_member(user_id) if guild else None
                user_name = member.display_name if member else f"User {user_id}"

                # Transcribe audio
                transcript = await self.transcribe(audio)
                if not transcript or not transcript.strip():
                    logger.debug("Empty transcript, skipping")
                    return

                logger.info("Transcribed from %s: %s", user_name, transcript)

                # Call the message handler
                if self._message_handler is not None:
                    response = await self._message_handler(
                        guild_id,
                        session.text_channel_id,
                        transcript,
                        user_name,
                        session.project,
                        session.branch,
                    )

                    # Synthesize and play response if we got one
                    if response:
                        await self.speak(guild_id, response)

            except Exception:
                logger.exception("Error processing voice audio")

    async def transcribe(self, audio: bytes) -> str:
        """Transcribe audio bytes to text using OpenAI Whisper."""
        # Convert raw PCM to WAV format for Whisper
        wav_bytes = self._pcm_to_wav(audio)

        # Create a file-like object
        audio_file = io.BytesIO(wav_bytes)
        audio_file.name = "audio.wav"

        try:
            response = await self._openai.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="en",
            )
            return response.text
        except Exception:
            logger.exception("Error transcribing audio")
            return ""

    async def synthesize(self, text: str) -> bytes:
        """Synthesize text to speech using OpenAI TTS."""
        try:
            response = await self._openai.audio.speech.create(
                model=self._tts_model,
                voice=self._tts_voice,
                input=text,
                response_format="opus",
            )
            return response.content
        except Exception:
            logger.exception("Error synthesizing speech")
            return b""

    async def speak(self, guild_id: int, text: str) -> None:
        """Synthesize and play text in the voice channel."""
        session = self._sessions.get(guild_id)
        if session is None or not session.voice_client.is_connected():
            return

        # Synthesize speech
        audio = await self.synthesize(text)
        if not audio:
            return

        # Write to temp file for FFmpeg
        with tempfile.NamedTemporaryFile(suffix=".opus", delete=False) as f:
            f.write(audio)
            temp_path = Path(f.name)

        try:
            # Wait if already playing
            while session.voice_client.is_playing():
                await asyncio.sleep(0.1)

            # Play the audio
            source = discord.FFmpegOpusAudio(str(temp_path))
            session.voice_client.play(source)

            # Wait for playback to finish
            while session.voice_client.is_playing():
                await asyncio.sleep(0.1)

        finally:
            # Clean up temp file
            with contextlib.suppress(OSError):
                temp_path.unlink()

    def _pcm_to_wav(self, pcm_data: bytes) -> bytes:
        """Convert raw PCM data to WAV format."""
        # WAV header
        data_size = len(pcm_data)
        file_size = data_size + 36

        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            file_size,
            b"WAVE",
            b"fmt ",
            16,  # Subchunk1Size (PCM)
            1,  # AudioFormat (PCM)
            CHANNELS,
            SAMPLE_RATE,
            SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH,  # ByteRate
            CHANNELS * SAMPLE_WIDTH,  # BlockAlign
            SAMPLE_WIDTH * 8,  # BitsPerSample
            b"data",
            data_size,
        )

        return header + pcm_data

    async def handle_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        """Handle voice state updates (users joining/leaving)."""
        guild_id = member.guild.id
        session = self._sessions.get(guild_id)
        if session is None:
            return

        # Check if the bot was disconnected
        bot_user = self._bot.user
        bot_user_id = bot_user.id if bot_user else None
        if (
            member.id == bot_user_id
            and after.channel is None
            and before.channel is not None
        ):
            # Bot was disconnected
            logger.info("Bot was disconnected from voice in guild %s", guild_id)
            self._sessions.pop(guild_id, None)
            return

        # Check if we should leave (channel is empty except for bot)
        if before.channel and before.channel.id == session.voice_channel_id:
            # Someone left our channel, check if it's empty
            voice_channel = self._bot.bot.get_channel(session.voice_channel_id)
            if isinstance(voice_channel, discord.VoiceChannel):
                # Count non-bot members
                human_members = [m for m in voice_channel.members if not m.bot]
                if not human_members:
                    logger.info("Voice channel empty, leaving guild %s", guild_id)
                    await self.leave_channel(guild_id)
