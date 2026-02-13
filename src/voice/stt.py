"""Speech-to-Text via Deepgram streaming API.

Uses Deepgram's nova-2 model with:
- Interim results (for low-latency wake word detection)
- Smart formatting (punctuation, capitalization)
- Endpointing (silence detection to know when user stops speaking)

Deepgram SDK v5 uses a new API:
  client.listen.v1.connect(...) → yields V1SocketClient
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TranscriptResult:
    text: str
    is_final: bool
    confidence: float
    speech_final: bool  # True when endpoint detected (user stopped speaking)


@dataclass
class STTStream:
    """Streaming speech-to-text using Deepgram.

    The Deepgram v5 SDK uses a synchronous websocket API (listen.v1.connect).
    We run the blocking socket operations in a thread executor to keep
    the async pipeline non-blocking.
    """

    api_key: str
    model: str = "nova-2"
    language: str = "en-US"
    _client: Any = field(default=None, init=False)
    _socket: Any = field(default=None, init=False)
    _transcript_queue: asyncio.Queue = field(default_factory=asyncio.Queue, init=False)
    _running: bool = field(default=False, init=False)
    _reader_task: asyncio.Task | None = field(default=None, init=False)

    async def start(self) -> None:
        """Connect to Deepgram's streaming API."""
        from deepgram import DeepgramClient

        self._client = DeepgramClient(api_key=self.api_key)

        # v5 SDK: listen.v1.connect() returns an iterator of V1SocketClient
        # We call it in a thread since it's synchronous
        loop = asyncio.get_event_loop()
        socket_iter = await loop.run_in_executor(
            None,
            lambda: self._client.listen.v1.connect(
                model=self.model,
                language=self.language,
                smart_format="true",
                interim_results="true",
                endpointing="300",
                vad_events="true",
                encoding="linear16",
                sample_rate="16000",
            ),
        )

        # The iterator yields a socket client
        self._socket = next(socket_iter)
        self._running = True

        # Start reading transcripts in background
        self._reader_task = asyncio.create_task(self._read_loop())

        logger.info(f"STT started (model={self.model}, language={self.language})")

    async def _read_loop(self) -> None:
        """Read transcript events from the socket in a background thread."""
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                event = await loop.run_in_executor(None, self._socket.poll)
                if event is None:
                    continue
                # Parse the event and put transcript results in the queue
                self._process_event(event)
            except StopIteration:
                break
            except Exception as e:
                if self._running:
                    logger.error(f"STT read error: {e}")
                break

    def _process_event(self, event: Any) -> None:
        """Extract transcript from a Deepgram websocket event."""
        # The event structure varies; we handle the common transcript result
        try:
            channel = event.channel
            alt = channel.alternatives[0]
            if not alt.transcript:
                return
            result = TranscriptResult(
                text=alt.transcript,
                is_final=getattr(event, "is_final", True),
                confidence=getattr(alt, "confidence", 0.0),
                speech_final=getattr(event, "speech_final", False),
            )
            self._transcript_queue.put_nowait(result)
        except (AttributeError, IndexError):
            pass

    async def send_audio(self, audio_data: bytes) -> None:
        """Send raw PCM audio data to Deepgram for transcription."""
        if self._socket and self._running:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._socket.send, audio_data)

    async def transcripts(self) -> AsyncIterator[TranscriptResult]:
        """Yield transcription results as they arrive."""
        while self._running:
            try:
                result = await asyncio.wait_for(self._transcript_queue.get(), timeout=0.1)
                yield result
            except asyncio.TimeoutError:
                continue

    async def stop(self) -> None:
        """Disconnect from Deepgram."""
        self._running = False
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._socket:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._socket.close)
            except Exception:
                pass
            self._socket = None
        logger.info("STT stopped")
