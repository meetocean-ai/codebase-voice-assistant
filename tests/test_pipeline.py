"""Tests for the voice pipeline orchestrator."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.voice.pipeline import QuestionRecord, VoicePipeline
from src.voice.stt import TranscriptResult
from src.voice.wake_word import CapturedQuestion


class TestQuestionRecord:
    def test_dataclass_fields(self):
        record = QuestionRecord(
            question="what is auth",
            answer="auth module handles login",
            asked_at=1000.0,
            answered_at=1002.5,
            latency_ms=2500,
        )
        assert record.question == "what is auth"
        assert record.latency_ms == 2500


class TestVoicePipelineInit:
    def test_default_values(self):
        vp = VoicePipeline(deepgram_api_key="test")
        assert vp.wake_word == "hey claude"
        assert vp.tts_voice == "aura-2-en-US-luna"
        assert vp.stt_model == "nova-2"
        assert vp._running is False

    def test_custom_values(self):
        vp = VoicePipeline(
            deepgram_api_key="test",
            wake_word="yo ai",
            tts_voice="aura-2-orion-en",
            project_path="/my/project",
        )
        assert vp.wake_word == "yo ai"
        assert vp.project_path == "/my/project"


class TestVoicePipelineLifecycle:
    @pytest.mark.asyncio
    async def test_start_initializes_components(self, mock_pyaudio, mock_deepgram):
        vp = VoicePipeline(deepgram_api_key="test")

        await vp.start()

        assert vp._running is True
        assert vp._stt is not None
        assert vp._tts is not None
        assert vp._detector is not None
        assert vp._capture is not None
        assert vp._playback is not None
        assert len(vp._tasks) == 3  # audio_to_stt, stt_to_detector, timeout_check

        await vp.stop()
        assert vp._running is False

    @pytest.mark.asyncio
    async def test_stop_cancels_background_tasks(self, mock_pyaudio, mock_deepgram):
        vp = VoicePipeline(deepgram_api_key="test")
        await vp.start()

        tasks_before = list(vp._tasks)
        await vp.stop()

        assert len(vp._tasks) == 0
        for task in tasks_before:
            assert task.cancelled() or task.done()


class TestVoicePipelineStatus:
    def test_status_when_not_started(self):
        vp = VoicePipeline(deepgram_api_key="test")
        status = vp.get_status()
        assert status["stt_state"] == "disconnected"
        assert status["questions_answered"] == 0

    @pytest.mark.asyncio
    async def test_status_when_running(self, mock_pyaudio, mock_deepgram):
        vp = VoicePipeline(deepgram_api_key="test")
        await vp.start()

        status = vp.get_status()
        assert status["stt_state"] == "connected"
        assert status["tts_state"] == "ready"
        assert status["questions_answered"] == 0

        await vp.stop()

    def test_status_with_questions(self):
        vp = VoicePipeline(deepgram_api_key="test")
        vp._questions = [
            QuestionRecord("q1", "a1", 1000.0, 1002.0, 2000),
            QuestionRecord("q2", None, 1005.0, None, None),
        ]

        status = vp.get_status()
        assert status["questions_answered"] == 1
        assert status["questions_pending"] == 1
        assert status["last_question"] == "q2"
        assert status["avg_latency_ms"] == 2000


class TestVoicePipelineProvideAnswer:
    @pytest.mark.asyncio
    async def test_provide_answer_records_and_speaks(self, mock_pyaudio, mock_deepgram):
        mock_client, _ = mock_deepgram
        vp = VoicePipeline(deepgram_api_key="test")
        await vp.start()

        # Simulate a pending question
        import time
        vp._questions.append(
            QuestionRecord("what is auth", None, time.time(), None, None)
        )

        await vp.provide_answer("The auth module handles user login")

        # Verify the answer was recorded
        assert vp._questions[-1].answer == "The auth module handles user login"
        assert vp._questions[-1].latency_ms is not None

        # Verify TTS was called
        mock_client.speak.v1.audio.generate.assert_called()

        await vp.stop()


class TestVoicePipelineQuestionQueue:
    @pytest.mark.asyncio
    async def test_get_next_question_returns_none_when_empty(self):
        vp = VoicePipeline(deepgram_api_key="test")
        result = await vp.get_next_question()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_next_question_returns_queued_question(self):
        vp = VoicePipeline(deepgram_api_key="test")
        await vp._question_queue.put("what is the main entry point?")

        result = await vp.get_next_question()
        assert result == "what is the main entry point?"


class TestVoicePipelineSwitchToLivekit:
    def test_switch_changes_playback_mode(self, mock_pyaudio):
        from src.audio.playback import PlaybackMode

        vp = VoicePipeline(deepgram_api_key="test")
        vp._playback = MagicMock()
        vp._playback.mode = PlaybackMode.LOCAL

        vp.switch_to_livekit(None)

        assert vp._playback.mode == PlaybackMode.LIVEKIT
