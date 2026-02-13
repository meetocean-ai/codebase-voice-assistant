"""Voice pipeline — the core orchestrator.

Connects audio capture → STT → wake word detection → question answering → TTS → audio playback.

This is the main loop that runs during an active voice session:
1. Capture audio from system/mic
2. Stream to Deepgram STT
3. Monitor transcripts for wake word ("Hey Claude")
4. On wake word + question: send codebase context + question to Claude (via callback)
5. Stream Claude's answer through TTS
6. Play audio response

The question-answering itself is delegated back to Claude Code via the MCP tool response,
so Claude Code's built-in Read/Grep/Glob tools handle the codebase search.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.audio.capture import AudioCapture
from src.audio.playback import AudioPlayback, PlaybackMode
from src.voice.stt import STTStream
from src.voice.tts import TTSStream
from src.voice.wake_word import CapturedQuestion, DetectorState, WakeWordDetector

logger = logging.getLogger(__name__)


@dataclass
class QuestionRecord:
    question: str
    answer: str | None
    asked_at: float
    answered_at: float | None
    latency_ms: int | None


@dataclass
class VoicePipeline:
    """Orchestrates the full voice pipeline: audio → STT → wake word → answer → TTS → audio."""

    deepgram_api_key: str
    wake_word: str = "hey claude"
    tts_voice: str = "aura-2-en-US-luna"
    stt_model: str = "nova-2"
    stt_language: str = "en-US"
    project_path: str = ""
    codebase_summary: str = ""

    # Callback for when a question is captured — set by the caller
    on_question: Callable[[str], Any] | None = None

    _stt: STTStream | None = field(default=None, init=False)
    _tts: TTSStream | None = field(default=None, init=False)
    _capture: AudioCapture | None = field(default=None, init=False)
    _playback: AudioPlayback | None = field(default=None, init=False)
    _detector: WakeWordDetector | None = field(default=None, init=False)
    _running: bool = field(default=False, init=False)
    _questions: list[QuestionRecord] = field(default_factory=list, init=False)
    _tasks: list[asyncio.Task] = field(default_factory=list, init=False)
    _question_queue: asyncio.Queue = field(default_factory=asyncio.Queue, init=False)
    _room_participant: object | None = field(default=None, init=False)  # RoomParticipant for call mode

    async def start(self) -> None:
        """Initialize and start all pipeline components."""
        logger.info(f"Starting voice pipeline (project={self.project_path})")

        # Initialize components
        self._stt = STTStream(
            api_key=self.deepgram_api_key,
            model=self.stt_model,
            language=self.stt_language,
        )
        self._tts = TTSStream(
            api_key=self.deepgram_api_key,
            voice=self.tts_voice,
        )
        self._detector = WakeWordDetector(
            wake_word=self.wake_word,
        )
        self._capture = AudioCapture()
        self._playback = AudioPlayback(mode=PlaybackMode.LOCAL)

        # Start components
        await self._stt.start()
        await self._capture.start()
        await self._playback.start()

        self._running = True

        # Launch background tasks
        self._tasks = [
            asyncio.create_task(self._audio_to_stt_loop(), name="audio_to_stt"),
            asyncio.create_task(self._stt_to_detector_loop(), name="stt_to_detector"),
            asyncio.create_task(self._timeout_check_loop(), name="timeout_check"),
        ]

        logger.info("Voice pipeline started")

    async def stop(self) -> None:
        """Stop all pipeline components and clean up."""
        self._running = False

        for task in self._tasks:
            task.cancel()

        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        if self._stt:
            await self._stt.stop()
        if self._capture:
            await self._capture.stop()
        if self._playback:
            await self._playback.stop()

        logger.info(
            f"Voice pipeline stopped. Questions answered: {len(self._questions)}"
        )

    async def _audio_to_stt_loop(self) -> None:
        """Continuously send captured audio to STT."""
        try:
            if self._room_participant:
                # In call mode: read audio from LiveKit room participants
                while self._running:
                    chunk = await self._room_participant.read_audio()
                    if chunk:
                        await self._stt.send_audio(chunk)
            else:
                # In local mode: read from microphone
                async for chunk in self._capture.read_chunks():
                    if not self._running:
                        break
                    await self._stt.send_audio(chunk)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Audio→STT loop error: {e}")

    async def _stt_to_detector_loop(self) -> None:
        """Process STT results through wake word detector."""
        try:
            async for result in self._stt.transcripts():
                if not self._running:
                    break

                question = self._detector.process_transcript(result)
                if question:
                    await self._handle_question(question)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"STT→Detector loop error: {e}")

    async def _timeout_check_loop(self) -> None:
        """Periodically check for silence timeout during question capture."""
        try:
            while self._running:
                question = self._detector.check_timeout()
                if question:
                    await self._handle_question(question)
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

    async def _handle_question(self, question: CapturedQuestion) -> None:
        """Handle a captured question: get answer and speak it."""
        if question.text == "__LEAVE__":
            logger.info("Leave command received")
            await self._speak("Goodbye!")
            await self.stop()
            return

        logger.info(f"Processing question: '{question.text}'")

        # Speak filler while processing
        filler_audio = await self._tts.speak_filler()
        if self._room_participant:
            await self._room_participant.publish_audio(filler_audio)
        else:
            await self._playback.play(filler_audio)

        # Put question in queue for the MCP server to pick up.
        # The server creates the QuestionRecord when it polls this question,
        # so we don't track it here to avoid duplicates.
        await self._question_queue.put(question.text)

    async def provide_answer(self, answer: str) -> None:
        """Called when Claude Code provides an answer to speak."""
        if self._questions:
            record = self._questions[-1]
            record.answer = answer
            record.answered_at = time.time()
            record.latency_ms = int((record.answered_at - record.asked_at) * 1000)
            logger.info(f"Answer received ({record.latency_ms}ms): '{answer[:100]}...'")

        await self._speak(answer)
        self._detector.reset()

    async def _speak(self, text: str) -> None:
        """Synthesize and play text as speech."""
        async for chunk in self._tts.synthesize_stream(text):
            if not self._running:
                break
            if self._room_participant:
                # In call mode: publish to LiveKit room
                await self._room_participant.publish_audio(chunk)
            else:
                # In local mode: play through speakers
                await self._playback.play(chunk)

    async def get_next_question(self) -> str | None:
        """Get the next captured question (used by MCP server)."""
        try:
            return await asyncio.wait_for(self._question_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return None

    def get_status(self) -> dict:
        return {
            "stt_state": "connected" if self._stt and self._running else "disconnected",
            "tts_state": "ready" if self._tts else "not initialized",
            "detector_state": self._detector.state.value if self._detector else "not initialized",
            "questions_answered": len([q for q in self._questions if q.answer]),
            "questions_pending": len([q for q in self._questions if not q.answer]),
            "last_question": self._questions[-1].question if self._questions else None,
            "avg_latency_ms": (
                int(sum(q.latency_ms for q in self._questions if q.latency_ms) / len([q for q in self._questions if q.latency_ms]))
                if any(q.latency_ms for q in self._questions)
                else None
            ),
        }

    def switch_to_livekit(self, room_participant) -> None:
        """Switch audio I/O to a LiveKit room (for conference call mode).

        Called by CallManager when the bot joins a conference call.
        Audio input comes from the room participant (conference attendees)
        instead of the local mic, and TTS output is published to the room.
        """
        self._room_participant = room_participant
        if self._playback:
            self._playback.mode = PlaybackMode.LIVEKIT
        logger.info("Voice pipeline switched to LiveKit audio I/O")
