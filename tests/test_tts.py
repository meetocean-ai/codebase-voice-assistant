"""Tests for TTS streaming module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.voice.tts import FILLER_PHRASES, TTSStream


class TestTTSInit:
    def test_default_voice(self, mock_deepgram):
        tts = TTSStream(api_key="test_key")
        assert tts.voice == "aura-2-luna-en"

    def test_custom_voice(self, mock_deepgram):
        tts = TTSStream(api_key="test_key", voice="aura-2-orion-en")
        assert tts.voice == "aura-2-orion-en"


class TestSynthesize:
    @pytest.mark.asyncio
    async def test_synthesize_returns_audio_bytes(self, mock_deepgram):
        mock_client, _ = mock_deepgram
        tts = TTSStream(api_key="test_key")

        result = await tts.synthesize("Hello world")

        assert isinstance(result, bytes)
        assert len(result) > 0
        mock_client.speak.v1.audio.generate.assert_called_once_with(
            text="Hello world",
            model="aura-2-luna-en",
            encoding="linear16",
            sample_rate=24000,
        )

    @pytest.mark.asyncio
    async def test_synthesize_empty_string(self, mock_deepgram):
        tts = TTSStream(api_key="test_key")
        result = await tts.synthesize("")
        assert result == b""

    @pytest.mark.asyncio
    async def test_synthesize_whitespace_only(self, mock_deepgram):
        tts = TTSStream(api_key="test_key")
        result = await tts.synthesize("   ")
        assert result == b""


class TestSynthesizeStream:
    @pytest.mark.asyncio
    async def test_yields_chunks(self, mock_deepgram):
        mock_client, _ = mock_deepgram
        # Return enough data to get multiple chunks
        mock_client.speak.v1.audio.generate.return_value = iter([b"\x00" * 10000])

        tts = TTSStream(api_key="test_key")

        chunks = []
        async for chunk in tts.synthesize_stream("Hello world", chunk_size=4096):
            chunks.append(chunk)

        assert len(chunks) >= 2  # 10000 / 4096 = 2+ chunks
        total_size = sum(len(c) for c in chunks)
        assert total_size == 10000

    @pytest.mark.asyncio
    async def test_stream_empty_string(self, mock_deepgram):
        tts = TTSStream(api_key="test_key")
        chunks = []
        async for chunk in tts.synthesize_stream(""):
            chunks.append(chunk)
        assert len(chunks) == 0


class TestSpeakFiller:
    @pytest.mark.asyncio
    async def test_speak_filler_returns_audio(self, mock_deepgram):
        mock_client, _ = mock_deepgram
        tts = TTSStream(api_key="test_key")

        result = await tts.speak_filler()
        assert isinstance(result, bytes)
        assert len(result) > 0

        # Verify it was called with one of the filler phrases
        call_args = mock_client.speak.v1.audio.generate.call_args
        text_used = call_args.kwargs["text"]
        assert text_used in FILLER_PHRASES
