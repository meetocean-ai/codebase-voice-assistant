"""Wake word detection for triggering the voice assistant.

Monitors the STT transcript stream for the configured wake word
(default: "hey claude"). When detected, captures the following
utterance as the question to answer.

States:
  LISTENING  -> Monitoring for wake word
  CAPTURING  -> Wake word detected, capturing the question
  PROCESSING -> Question captured, waiting for answer
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum

from src.voice.stt import TranscriptResult

logger = logging.getLogger(__name__)


class DetectorState(str, Enum):
    LISTENING = "listening"    # Waiting for wake word
    CAPTURING = "capturing"    # Recording the question after wake word
    PROCESSING = "processing"  # Question sent for processing


@dataclass
class CapturedQuestion:
    text: str
    captured_at: float
    wake_word_used: str


@dataclass
class WakeWordDetector:
    """Detects wake word and captures the following question."""

    wake_word: str = "hey claude"
    silence_timeout_ms: int = 1500  # How long to wait after speech stops to finalize question
    _state: DetectorState = field(default=DetectorState.LISTENING, init=False)
    _buffer: list[str] = field(default_factory=list, init=False)
    _last_speech_at: float = field(default=0.0, init=False)
    _wake_word_pattern: re.Pattern = field(default=None, init=False)
    _leave_pattern: re.Pattern = field(default=None, init=False)

    def __post_init__(self):
        # Build flexible regex pattern for the wake word
        # "hey claude" matches "hey claude", "hey, claude", "hey Claude", etc.
        words = self.wake_word.lower().split()
        pattern = r"\b" + r"[,\s]+".join(re.escape(w) for w in words) + r"\b"
        self._wake_word_pattern = re.compile(pattern, re.IGNORECASE)
        self._leave_pattern = re.compile(r"\bclaude[,\s]+leave\b", re.IGNORECASE)

    @property
    def state(self) -> DetectorState:
        return self._state

    def process_transcript(self, result: TranscriptResult) -> CapturedQuestion | None:
        """Process a transcript result and return a question if one is fully captured.

        Returns:
            CapturedQuestion if a complete question was captured, None otherwise.
        """
        text = result.text.strip()
        if not text:
            return None

        now = time.time()

        if self._state == DetectorState.LISTENING:
            return self._handle_listening(text, now)
        elif self._state == DetectorState.CAPTURING:
            return self._handle_capturing(text, result, now)

        return None

    def _handle_listening(self, text: str, now: float) -> CapturedQuestion | None:
        # Check for leave command
        if self._leave_pattern.search(text):
            logger.info("Leave command detected")
            return CapturedQuestion(text="__LEAVE__", captured_at=now, wake_word_used="leave")

        # Check for wake word
        match = self._wake_word_pattern.search(text)
        if match:
            # Extract any text after the wake word as the start of the question
            after_wake = text[match.end():].strip()
            if after_wake:
                self._buffer.append(after_wake)

            self._state = DetectorState.CAPTURING
            self._last_speech_at = now
            logger.info(f"Wake word detected: '{self.wake_word}'")

            # If this was a final result with speech_final, the question might be complete
            # in the same utterance: "Hey Claude, what does the auth module do?"
            if after_wake and self._is_complete_question(after_wake):
                return self._finalize_question(now)

        return None

    def _handle_capturing(
        self, text: str, result: TranscriptResult, now: float
    ) -> CapturedQuestion | None:
        self._last_speech_at = now

        if result.is_final:
            # Remove wake word if it appears in the final transcript too
            cleaned = self._wake_word_pattern.sub("", text).strip()
            if cleaned:
                self._buffer.append(cleaned)

            # If speech_final (endpoint detected), the question is complete
            if result.speech_final:
                return self._finalize_question(now)

        return None

    def check_timeout(self) -> CapturedQuestion | None:
        """Check if the question capture has timed out (silence after speaking).

        Call this periodically (e.g., every 100ms) to detect end-of-question by silence.
        """
        if self._state != DetectorState.CAPTURING:
            return None

        if not self._buffer:
            return None

        now = time.time()
        elapsed_ms = (now - self._last_speech_at) * 1000

        if elapsed_ms > self.silence_timeout_ms:
            return self._finalize_question(now)

        return None

    def _is_complete_question(self, text: str) -> bool:
        """Heuristic: is this likely a complete question?"""
        return text.endswith("?") or text.endswith(".")

    def _finalize_question(self, now: float) -> CapturedQuestion:
        question_text = " ".join(self._buffer).strip()
        self._buffer.clear()
        self._state = DetectorState.PROCESSING
        logger.info(f"Question captured: '{question_text}'")
        return CapturedQuestion(
            text=question_text,
            captured_at=now,
            wake_word_used=self.wake_word,
        )

    def reset(self) -> None:
        """Reset to listening state (call after question is answered)."""
        self._state = DetectorState.LISTENING
        self._buffer.clear()
        self._last_speech_at = 0.0
