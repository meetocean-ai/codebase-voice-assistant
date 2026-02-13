"""Text-to-Speech via Deepgram's Aura API.

Streams synthesized audio in chunks for low-latency playback.
Supports multiple voices.

Deepgram SDK v5 uses:
  client.speak.v1.audio.generate(text=..., model=..., encoding=...) → Iterator[bytes]
"""

from __future__ import annotations

import logging
import random
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

FILLER_PHRASES = [
    "Let me check.",
    "Looking into that.",
    "One moment.",
]


@dataclass
class TTSStream:
    """Text-to-speech using Deepgram Aura."""

    api_key: str
    voice: str = "aura-2-luna-en"
    _client: Any = field(default=None, init=False)

    def __post_init__(self):
        from deepgram import DeepgramClient
        self._client = DeepgramClient(api_key=self.api_key)

    async def synthesize(self, text: str) -> bytes:
        """Synthesize text to audio bytes (PCM linear16, 24kHz)."""
        if not text.strip():
            return b""

        import asyncio
        loop = asyncio.get_event_loop()

        def _generate() -> bytes:
            audio_data = b""
            for chunk in self._client.speak.v1.audio.generate(
                text=text,
                model=self.voice,
                encoding="linear16",
                sample_rate=24000,
            ):
                audio_data += chunk
            return audio_data

        result = await loop.run_in_executor(None, _generate)
        logger.debug(f"TTS synthesized {len(text)} chars -> {len(result)} bytes")
        return result

    async def synthesize_stream(self, text: str, chunk_size: int = 4096) -> AsyncIterator[bytes]:
        """Synthesize text and yield audio in chunks for streaming playback."""
        if not text.strip():
            return

        import asyncio
        loop = asyncio.get_event_loop()

        # Collect all audio first (Deepgram v5 returns sync iterator)
        audio = await self.synthesize(text)

        # Yield in smaller chunks for smoother streaming
        for i in range(0, len(audio), chunk_size):
            yield audio[i : i + chunk_size]

    async def speak_filler(self) -> bytes:
        """Generate a short filler phrase for perceived latency reduction."""
        return await self.synthesize(random.choice(FILLER_PHRASES))
