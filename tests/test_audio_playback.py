"""Tests for audio playback module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.audio.playback import AudioPlayback, PlaybackMode


class TestPlaybackModes:
    def test_local_mode_initializes_pyaudio(self, mock_pyaudio):
        playback = AudioPlayback(mode=PlaybackMode.LOCAL)
        assert playback._audio is not None

    def test_livekit_mode_skips_pyaudio(self):
        with patch("pyaudio.PyAudio") as mock_cls:
            playback = AudioPlayback(mode=PlaybackMode.LIVEKIT)
            mock_cls.assert_not_called()


class TestPlaybackLifecycle:
    @pytest.mark.asyncio
    async def test_start_opens_output_stream(self, mock_pyaudio):
        mock_pa, _ = mock_pyaudio
        playback = AudioPlayback(mode=PlaybackMode.LOCAL)

        await playback.start()
        mock_pa.open.assert_called_once()
        call_kwargs = mock_pa.open.call_args
        assert call_kwargs.kwargs.get("output") is True or \
               (len(call_kwargs) > 1 and call_kwargs[1].get("output") is True)

        await playback.stop()

    @pytest.mark.asyncio
    async def test_livekit_start_is_noop(self):
        with patch("pyaudio.PyAudio"):
            playback = AudioPlayback(mode=PlaybackMode.LIVEKIT)
            await playback.start()  # Should not raise
            await playback.stop()

    @pytest.mark.asyncio
    async def test_stop_closes_stream(self, mock_pyaudio):
        _, mock_stream = mock_pyaudio
        playback = AudioPlayback(mode=PlaybackMode.LOCAL)

        await playback.start()
        await playback.stop()

        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()


class TestPlay:
    @pytest.mark.asyncio
    async def test_play_writes_to_stream(self, mock_pyaudio):
        _, mock_stream = mock_pyaudio
        playback = AudioPlayback(mode=PlaybackMode.LOCAL)
        await playback.start()

        audio_data = b"\x00" * 4800
        await playback.play(audio_data)

        mock_stream.write.assert_called_once_with(audio_data)
        await playback.stop()

    @pytest.mark.asyncio
    async def test_play_livekit_is_noop(self):
        with patch("pyaudio.PyAudio"):
            playback = AudioPlayback(mode=PlaybackMode.LIVEKIT)
            await playback.start()
            await playback.play(b"\x00" * 4800)  # Should not raise
            await playback.stop()

    @pytest.mark.asyncio
    async def test_play_stream_plays_all_chunks(self, mock_pyaudio):
        _, mock_stream = mock_pyaudio
        playback = AudioPlayback(mode=PlaybackMode.LOCAL)
        await playback.start()

        async def chunks():
            yield b"\x00" * 100
            yield b"\x01" * 100
            yield b"\x02" * 100

        await playback.play_stream(chunks())
        assert mock_stream.write.call_count == 3
        await playback.stop()
