"""Audio playback for TTS output.

Plays synthesized speech through:
1. The system default output (speakers/headphones) — for local testing
2. A virtual audio device that routes into the meeting — for live calls
3. LiveKit room — when the bot is a SIP participant
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum

import pyaudio

logger = logging.getLogger(__name__)

SAMPLE_RATE = 24000  # Deepgram TTS outputs 24kHz
CHANNELS = 1
FORMAT = pyaudio.paInt16


class PlaybackMode(str, Enum):
    LOCAL = "local"           # Play through speakers (testing)
    VIRTUAL_MIC = "virtual"   # Route through virtual audio device into meeting
    LIVEKIT = "livekit"       # Send to LiveKit room (SIP mode)


@dataclass
class AudioPlayback:
    """Plays TTS audio output."""

    mode: PlaybackMode = PlaybackMode.LOCAL
    device_index: int | None = None
    sample_rate: int = SAMPLE_RATE
    channels: int = CHANNELS
    _audio: pyaudio.PyAudio = field(default=None, init=False, repr=False)
    _stream: pyaudio.Stream | None = field(default=None, init=False, repr=False)

    def __post_init__(self):
        if self.mode in (PlaybackMode.LOCAL, PlaybackMode.VIRTUAL_MIC):
            self._audio = pyaudio.PyAudio()

    async def start(self) -> None:
        """Open the playback stream."""
        if self.mode == PlaybackMode.LIVEKIT:
            # Audio is sent directly to the LiveKit room via the agent SDK
            # No local playback needed
            logger.info("Playback mode: LiveKit (audio routed through SIP)")
            return

        device_index = self.device_index
        if device_index is None and self.mode == PlaybackMode.LOCAL:
            device_index = self._audio.get_default_output_device_info()["index"]

        self._stream = self._audio.open(
            format=FORMAT,
            channels=self.channels,
            rate=self.sample_rate,
            output=True,
            output_device_index=device_index,
        )
        logger.info(f"Audio playback started (mode={self.mode}, device={device_index})")

    async def play(self, audio_data: bytes) -> None:
        """Play a chunk of audio data."""
        if self.mode == PlaybackMode.LIVEKIT:
            # In LiveKit mode, audio is published to the room track
            # This is handled by CallManager, not here
            return

        if self._stream:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._stream.write, audio_data)

    async def play_stream(self, chunks: AsyncIterator[bytes]) -> None:
        """Play a stream of audio chunks (for streaming TTS)."""
        async for chunk in chunks:
            await self.play(chunk)

    async def stop(self) -> None:
        """Close the playback stream."""
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        logger.info("Audio playback stopped")

    def cleanup(self) -> None:
        if self._stream:
            self._stream.close()
        if self._audio:
            self._audio.terminate()

    def __del__(self):
        self.cleanup()
