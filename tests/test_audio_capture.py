"""Tests for audio capture module."""

from __future__ import annotations

import struct
from unittest.mock import MagicMock, patch

import pytest

from src.audio.capture import AudioCapture, AudioDevice, SAMPLE_RATE


class TestListDevices:
    def test_lists_input_devices(self, mock_pyaudio):
        devices = AudioCapture.list_devices()
        assert len(devices) == 2
        assert devices[0].name == "Built-in Microphone"
        assert devices[1].name == "BlackHole 2ch"

    def test_device_properties(self, mock_pyaudio):
        devices = AudioCapture.list_devices()
        mic = devices[0]
        assert mic.index == 0
        assert mic.max_input_channels == 2
        assert mic.default_sample_rate == 44100.0


class TestFindVirtualDevice:
    def test_finds_blackhole_on_macos(self, mock_pyaudio):
        with patch("platform.system", return_value="Darwin"):
            index = AudioCapture.find_virtual_audio_device()
            assert index == 1  # BlackHole device

    def test_returns_none_when_no_virtual_device(self):
        mock_pa = MagicMock()
        mock_pa.get_device_count.return_value = 1
        mock_pa.get_device_info_by_index.return_value = {
            "index": 0,
            "name": "Built-in Microphone",
            "maxInputChannels": 2,
            "maxOutputChannels": 0,
            "defaultSampleRate": 44100.0,
        }

        with patch("pyaudio.PyAudio", return_value=mock_pa), \
             patch("platform.system", return_value="Darwin"):
            index = AudioCapture.find_virtual_audio_device()
            assert index is None


class TestAudioCaptureLifecycle:
    @pytest.mark.asyncio
    async def test_start_opens_stream(self, mock_pyaudio):
        mock_pa, mock_stream = mock_pyaudio
        capture = AudioCapture()

        await capture.start()
        assert capture._running is True
        mock_pa.open.assert_called_once()

        await capture.stop()
        assert capture._running is False
        mock_stream.stop_stream.assert_called_once()
        mock_stream.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_uses_specified_device(self, mock_pyaudio):
        mock_pa, _ = mock_pyaudio
        capture = AudioCapture(device_index=1)

        await capture.start()
        call_kwargs = mock_pa.open.call_args
        assert call_kwargs.kwargs.get("input_device_index") == 1 or \
               (len(call_kwargs.args) > 0 or call_kwargs[1].get("input_device_index") == 1)

        await capture.stop()

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self, mock_pyaudio):
        mock_pa, _ = mock_pyaudio
        capture = AudioCapture()

        await capture.start()
        await capture.start()  # Should not open a second stream
        assert mock_pa.open.call_count == 1

        await capture.stop()


class TestGetRms:
    def test_rms_of_silence(self, mock_pyaudio):
        capture = AudioCapture()
        # 16-bit silence (all zeros)
        data = struct.pack("<4h", 0, 0, 0, 0)
        assert capture.get_rms(data) == 0.0

    def test_rms_of_signal(self, mock_pyaudio):
        capture = AudioCapture()
        # 16-bit samples with known values
        data = struct.pack("<4h", 100, -100, 100, -100)
        rms = capture.get_rms(data)
        assert rms == pytest.approx(100.0)

    def test_rms_of_empty(self, mock_pyaudio):
        capture = AudioCapture()
        assert capture.get_rms(b"") == 0.0

    def test_rms_of_max_amplitude(self, mock_pyaudio):
        capture = AudioCapture()
        data = struct.pack("<2h", 32767, -32767)
        rms = capture.get_rms(data)
        assert rms > 32000


class TestReadChunks:
    @pytest.mark.asyncio
    async def test_read_raises_without_start(self, mock_pyaudio):
        capture = AudioCapture()
        with pytest.raises(RuntimeError, match="not started"):
            async for _ in capture.read_chunks():
                pass

    @pytest.mark.asyncio
    async def test_read_yields_chunks(self, mock_pyaudio):
        _, mock_stream = mock_pyaudio
        # Return 3 chunks then raise to break loop
        audio_data = b"\x00" * 2048
        call_count = 0

        def mock_read(size, overflow):
            nonlocal call_count
            call_count += 1
            if call_count > 3:
                raise OSError("stream closed")
            return audio_data

        mock_stream.read.side_effect = mock_read

        capture = AudioCapture()
        await capture.start()

        chunks = []
        async for chunk in capture.read_chunks():
            chunks.append(chunk)
            if len(chunks) >= 3:
                break

        assert len(chunks) == 3
        assert all(c == audio_data for c in chunks)
        await capture.stop()
