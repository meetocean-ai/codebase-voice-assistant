"""System audio capture for macOS and Linux.

Captures audio from the system output (what the user hears from their meeting)
and from the microphone (for local-mode where the bot speaks through the user's mic).

On macOS: Uses CoreAudio via pyaudio, requires a virtual audio device (BlackHole)
          for system audio capture.
On Linux: Uses PulseAudio monitor source for system audio capture.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import struct
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import pyaudio

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # 16kHz for STT
CHANNELS = 1  # Mono
CHUNK_SIZE = 1024  # Samples per buffer
FORMAT = pyaudio.paInt16


@dataclass
class AudioDevice:
    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: float


@dataclass
class AudioCapture:
    """Captures audio from a system audio source or microphone."""

    device_index: int | None = None
    sample_rate: int = SAMPLE_RATE
    channels: int = CHANNELS
    chunk_size: int = CHUNK_SIZE
    _audio: pyaudio.PyAudio = field(default=None, init=False, repr=False)
    _stream: pyaudio.Stream | None = field(default=None, init=False, repr=False)
    _running: bool = field(default=False, init=False)

    def __post_init__(self):
        self._audio = pyaudio.PyAudio()

    @staticmethod
    def list_devices() -> list[AudioDevice]:
        """List available audio input devices."""
        audio = pyaudio.PyAudio()
        devices = []
        for i in range(audio.get_device_count()):
            info = audio.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                devices.append(AudioDevice(
                    index=i,
                    name=info["name"],
                    max_input_channels=info["maxInputChannels"],
                    max_output_channels=info["maxOutputChannels"],
                    default_sample_rate=info["defaultSampleRate"],
                ))
        audio.terminate()
        return devices

    @staticmethod
    def find_virtual_audio_device() -> int | None:
        """Find a virtual audio device (BlackHole, PulseAudio monitor) for system audio capture."""
        system = platform.system()
        devices = AudioCapture.list_devices()

        # Look for common virtual audio devices
        virtual_names = []
        if system == "Darwin":
            virtual_names = ["BlackHole", "Loopback", "Soundflower"]
        elif system == "Linux":
            virtual_names = ["Monitor of", "pulse"]

        for device in devices:
            for vname in virtual_names:
                if vname.lower() in device.name.lower():
                    logger.info(f"Found virtual audio device: {device.name} (index={device.index})")
                    return device.index

        logger.warning(
            "No virtual audio device found. "
            "On macOS, install BlackHole: brew install blackhole-2ch"
        )
        return None

    async def start(self) -> None:
        """Open the audio stream."""
        if self._running:
            return

        device_index = self.device_index
        if device_index is None:
            # Default to the system default input device (microphone)
            device_index = self._audio.get_default_input_device_info()["index"]

        self._stream = self._audio.open(
            format=FORMAT,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            input_device_index=device_index,
            frames_per_buffer=self.chunk_size,
        )
        self._running = True
        logger.info(f"Audio capture started (device={device_index}, rate={self.sample_rate})")

    async def stop(self) -> None:
        """Close the audio stream."""
        self._running = False
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
            self._stream = None
        logger.info("Audio capture stopped")

    async def read_chunks(self) -> AsyncIterator[bytes]:
        """Yield audio chunks as raw PCM bytes."""
        if not self._stream:
            raise RuntimeError("Audio capture not started. Call start() first.")

        loop = asyncio.get_event_loop()
        while self._running:
            try:
                data = await loop.run_in_executor(
                    None, self._stream.read, self.chunk_size, False
                )
                yield data
            except OSError as e:
                if self._running:
                    logger.error(f"Audio read error: {e}")
                    await asyncio.sleep(0.01)
                break

    def get_rms(self, data: bytes) -> float:
        """Calculate RMS volume level of an audio chunk."""
        if not data:
            return 0.0
        count = len(data) // 2  # 16-bit samples
        samples = struct.unpack(f"<{count}h", data)
        sum_sq = sum(s * s for s in samples)
        return (sum_sq / count) ** 0.5

    def cleanup(self) -> None:
        """Release audio resources."""
        if self._stream:
            self._stream.close()
        if self._audio:
            self._audio.terminate()

    def __del__(self):
        self.cleanup()
