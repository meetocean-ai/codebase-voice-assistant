"""Tests for wake word detection and question capture."""

from __future__ import annotations

import time

import pytest

from src.voice.stt import TranscriptResult
from src.voice.wake_word import CapturedQuestion, DetectorState, WakeWordDetector


def make_transcript(
    text: str,
    is_final: bool = True,
    confidence: float = 0.95,
    speech_final: bool = False,
) -> TranscriptResult:
    return TranscriptResult(
        text=text,
        is_final=is_final,
        confidence=confidence,
        speech_final=speech_final,
    )


class TestWakeWordDetection:
    def test_initial_state_is_listening(self):
        detector = WakeWordDetector()
        assert detector.state == DetectorState.LISTENING

    def test_detects_default_wake_word(self):
        detector = WakeWordDetector()
        result = detector.process_transcript(make_transcript("hey claude what is this"))
        # Should transition to capturing
        assert detector.state in (DetectorState.CAPTURING, DetectorState.PROCESSING)

    def test_detects_wake_word_case_insensitive(self):
        detector = WakeWordDetector()
        result = detector.process_transcript(make_transcript("Hey Claude what is this"))
        assert detector.state in (DetectorState.CAPTURING, DetectorState.PROCESSING)

    def test_detects_wake_word_with_comma(self):
        detector = WakeWordDetector()
        result = detector.process_transcript(make_transcript("Hey, Claude what is this"))
        assert detector.state in (DetectorState.CAPTURING, DetectorState.PROCESSING)

    def test_ignores_text_without_wake_word(self):
        detector = WakeWordDetector()
        result = detector.process_transcript(make_transcript("what does this function do"))
        assert result is None
        assert detector.state == DetectorState.LISTENING

    def test_custom_wake_word(self):
        detector = WakeWordDetector(wake_word="ok assistant")
        result = detector.process_transcript(make_transcript("ok assistant tell me about auth"))
        assert detector.state in (DetectorState.CAPTURING, DetectorState.PROCESSING)

    def test_wake_word_at_start_of_utterance(self):
        detector = WakeWordDetector()
        result = detector.process_transcript(make_transcript("hey claude"))
        # Just wake word, no question yet — should be capturing
        assert detector.state == DetectorState.CAPTURING


class TestQuestionCapture:
    def test_captures_question_on_speech_final(self):
        detector = WakeWordDetector()

        # Wake word detected with partial question
        detector.process_transcript(make_transcript("hey claude what does", is_final=False))

        # Full question arrives with speech_final
        result = detector.process_transcript(
            make_transcript("hey claude what does the auth module do?", is_final=True, speech_final=True)
        )

        assert result is not None
        assert "auth module" in result.text
        assert result.wake_word_used == "hey claude"

    def test_captures_inline_question_ending_with_question_mark(self):
        detector = WakeWordDetector()
        result = detector.process_transcript(
            make_transcript("hey claude what is the main entry point?")
        )
        # Complete question detected inline (ends with ?)
        assert result is not None
        assert "main entry point" in result.text

    def test_multi_turn_capture(self):
        detector = WakeWordDetector()

        # Wake word
        detector.process_transcript(make_transcript("hey claude", is_final=True))
        assert detector.state == DetectorState.CAPTURING

        # Question part 1
        detector.process_transcript(make_transcript("what does the", is_final=False))

        # Question part 2 (final, speech_final)
        result = detector.process_transcript(
            make_transcript("what does the auth module do", is_final=True, speech_final=True)
        )

        assert result is not None
        assert "auth module" in result.text

    def test_timeout_captures_question(self):
        detector = WakeWordDetector(silence_timeout_ms=100)

        # Wake word + start of question
        detector.process_transcript(make_transcript("hey claude what is auth"))
        assert detector.state == DetectorState.CAPTURING

        # Need a final transcript to add to buffer
        detector.process_transcript(
            make_transcript("what is auth", is_final=True)
        )

        # Simulate time passing
        detector._last_speech_at = time.time() - 0.5  # 500ms ago

        result = detector.check_timeout()
        assert result is not None
        assert "auth" in result.text

    def test_no_timeout_without_buffer(self):
        detector = WakeWordDetector(silence_timeout_ms=100)
        result = detector.check_timeout()
        assert result is None

    def test_no_timeout_while_listening(self):
        detector = WakeWordDetector(silence_timeout_ms=100)
        detector._last_speech_at = time.time() - 1.0
        result = detector.check_timeout()
        assert result is None


class TestLeaveCommand:
    def test_detects_leave_command(self):
        detector = WakeWordDetector()
        result = detector.process_transcript(make_transcript("Claude, leave"))
        assert result is not None
        assert result.text == "__LEAVE__"

    def test_detects_leave_case_insensitive(self):
        detector = WakeWordDetector()
        result = detector.process_transcript(make_transcript("claude leave"))
        assert result is not None
        assert result.text == "__LEAVE__"


class TestReset:
    def test_reset_returns_to_listening(self):
        detector = WakeWordDetector()
        detector.process_transcript(make_transcript("hey claude what is this?"))
        detector.reset()
        assert detector.state == DetectorState.LISTENING
        assert len(detector._buffer) == 0

    def test_can_detect_after_reset(self):
        detector = WakeWordDetector()

        # First question
        detector.process_transcript(make_transcript("hey claude what is auth?"))
        detector.reset()

        # Second question
        result = detector.process_transcript(make_transcript("hey claude what is the db schema?"))
        assert result is not None
        assert "db schema" in result.text
