"""Tests for STT streaming module."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.voice.stt import STTStream, TranscriptResult


class TestTranscriptResult:
    def test_dataclass_fields(self):
        result = TranscriptResult(
            text="hello world",
            is_final=True,
            confidence=0.98,
            speech_final=True,
        )
        assert result.text == "hello world"
        assert result.is_final is True
        assert result.confidence == 0.98
        assert result.speech_final is True


class TestSTTStreamInit:
    def test_default_values(self):
        stt = STTStream(api_key="test_key")
        assert stt.model == "nova-2"
        assert stt.language == "en-US"
        assert stt._running is False

    def test_custom_values(self):
        stt = STTStream(api_key="key", model="nova-3", language="es")
        assert stt.model == "nova-3"
        assert stt.language == "es"


class TestSTTStreamLifecycle:
    @pytest.mark.asyncio
    async def test_start_connects_to_deepgram(self, mock_deepgram):
        mock_client, mock_socket = mock_deepgram
        stt = STTStream(api_key="test_key")

        await stt.start()

        assert stt._running is True
        assert stt._socket is mock_socket
        mock_client.listen.v1.connect.assert_called_once()

        await stt.stop()
        assert stt._running is False

    @pytest.mark.asyncio
    async def test_stop_closes_socket(self, mock_deepgram):
        _, mock_socket = mock_deepgram
        stt = STTStream(api_key="test_key")

        await stt.start()
        await stt.stop()

        mock_socket.close.assert_called_once()
        assert stt._socket is None

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self):
        stt = STTStream(api_key="test_key")
        await stt.stop()  # Should not raise


class TestSTTSendAudio:
    @pytest.mark.asyncio
    async def test_send_audio_forwards_to_socket(self, mock_deepgram):
        _, mock_socket = mock_deepgram
        stt = STTStream(api_key="test_key")
        await stt.start()

        audio = b"\x00" * 1024
        await stt.send_audio(audio)

        mock_socket.send.assert_called_once_with(audio)
        await stt.stop()

    @pytest.mark.asyncio
    async def test_send_audio_noop_when_not_running(self):
        stt = STTStream(api_key="test_key")
        await stt.send_audio(b"\x00" * 1024)  # Should not raise


class TestSTTProcessEvent:
    def test_extracts_transcript_from_event(self, mock_deepgram):
        _, mock_socket = mock_deepgram
        stt = STTStream(api_key="test_key")
        stt._transcript_queue = asyncio.Queue()

        # Build a mock event matching Deepgram's structure
        mock_alt = MagicMock()
        mock_alt.transcript = "hello world"
        mock_alt.confidence = 0.95

        mock_channel = MagicMock()
        mock_channel.alternatives = [mock_alt]

        mock_event = MagicMock()
        mock_event.channel = mock_channel
        mock_event.is_final = True
        mock_event.speech_final = False

        stt._process_event(mock_event)

        assert not stt._transcript_queue.empty()
        result = stt._transcript_queue.get_nowait()
        assert result.text == "hello world"
        assert result.confidence == 0.95
        assert result.is_final is True

    def test_ignores_empty_transcript(self, mock_deepgram):
        _, _ = mock_deepgram
        stt = STTStream(api_key="test_key")
        stt._transcript_queue = asyncio.Queue()

        mock_alt = MagicMock()
        mock_alt.transcript = ""
        mock_channel = MagicMock()
        mock_channel.alternatives = [mock_alt]
        mock_event = MagicMock()
        mock_event.channel = mock_channel

        stt._process_event(mock_event)
        assert stt._transcript_queue.empty()

    def test_handles_malformed_event(self, mock_deepgram):
        _, _ = mock_deepgram
        stt = STTStream(api_key="test_key")
        stt._transcript_queue = asyncio.Queue()

        # Event with no channel attribute
        mock_event = MagicMock(spec=[])
        stt._process_event(mock_event)  # Should not raise
        assert stt._transcript_queue.empty()


class TestSTTTranscripts:
    @pytest.mark.asyncio
    async def test_yields_queued_results(self, mock_deepgram):
        _, _ = mock_deepgram
        stt = STTStream(api_key="test_key")
        stt._running = True

        # Pre-fill the queue
        result1 = TranscriptResult("hello", True, 0.9, False)
        result2 = TranscriptResult("world", True, 0.95, True)
        await stt._transcript_queue.put(result1)
        await stt._transcript_queue.put(result2)

        results = []
        count = 0
        async for r in stt.transcripts():
            results.append(r)
            count += 1
            if count >= 2:
                stt._running = False

        assert len(results) == 2
        assert results[0].text == "hello"
        assert results[1].text == "world"
