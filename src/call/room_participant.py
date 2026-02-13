"""LiveKit room participant — the bot's presence in the conference call.

Connects to a LiveKit room as a participant that:
1. Subscribes to the SIP participant's audio track → feeds to STT
2. Publishes its own audio track → TTS output heard by all attendees

This bridges the LiveKit room (conference call audio) with our voice pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass, field

import numpy as np
from livekit import api, rtc

logger = logging.getLogger(__name__)

# STT expects 16kHz mono, LiveKit default is 48kHz
STT_SAMPLE_RATE = 16000
# TTS outputs 24kHz mono
TTS_SAMPLE_RATE = 24000
NUM_CHANNELS = 1


@dataclass
class RoomParticipant:
    """Bot participant that listens and speaks in a LiveKit room."""

    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    room_name: str
    participant_identity: str = "codebase-voice-bot"
    participant_name: str = "Claude (Codebase Assistant)"

    _room: rtc.Room | None = field(default=None, init=False)
    _audio_source: rtc.AudioSource | None = field(default=None, init=False)
    _audio_track: rtc.LocalAudioTrack | None = field(default=None, init=False)
    _audio_streams: list[rtc.AudioStream] = field(default_factory=list, init=False)
    _on_audio_data: asyncio.Queue[bytes] | None = field(default=None, init=False)
    _running: bool = field(default=False, init=False)
    _tasks: list[asyncio.Task] = field(default_factory=list, init=False)

    async def connect(self) -> None:
        """Connect to the LiveKit room and set up audio tracks."""
        # Generate access token for the bot participant
        token = (
            api.AccessToken(self.livekit_api_key, self.livekit_api_secret)
            .with_identity(self.participant_identity)
            .with_name(self.participant_name)
            .with_grants(api.VideoGrants(
                room_join=True,
                room=self.room_name,
                can_publish=True,
                can_subscribe=True,
            ))
            .to_jwt()
        )

        # Create room and connect
        self._room = rtc.Room()
        self._on_audio_data = asyncio.Queue()
        self._running = True

        # Set up event handlers before connecting
        self._room.on("track_subscribed", self._on_track_subscribed)

        await self._room.connect(self.livekit_url, token)
        logger.info(f"Connected to room {self.room_name} as {self.participant_identity}")

        # Create and publish our audio track for TTS output
        self._audio_source = rtc.AudioSource(TTS_SAMPLE_RATE, NUM_CHANNELS)
        self._audio_track = rtc.LocalAudioTrack.create_audio_track(
            "assistant-voice", self._audio_source
        )
        await self._room.local_participant.publish_track(self._audio_track)
        logger.info("Published audio track for TTS output")

    def _on_track_subscribed(
        self,
        track: rtc.RemoteTrack,
        publication: rtc.RemoteTrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        """Called when a remote participant's track is subscribed."""
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return

        logger.info(
            f"Subscribed to audio from {participant.identity} "
            f"(track: {track.name})"
        )

        # Create an audio stream from this track, resampled to STT rate
        audio_stream = rtc.AudioStream.from_track(
            track=track,
            sample_rate=STT_SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
        )
        self._audio_streams.append(audio_stream)

        # Start forwarding audio frames to the queue
        task = asyncio.create_task(
            self._forward_audio(audio_stream, participant.identity)
        )
        self._tasks.append(task)

    async def _forward_audio(
        self, stream: rtc.AudioStream, participant_id: str
    ) -> None:
        """Forward audio frames from a remote participant to the STT pipeline."""
        try:
            async for event in stream:
                if not self._running:
                    break
                frame: rtc.AudioFrame = event.frame
                # Convert to raw PCM bytes (int16) for our STT pipeline
                pcm_data = bytes(frame.data)
                if self._on_audio_data:
                    await self._on_audio_data.put(pcm_data)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Audio forwarding error from {participant_id}: {e}")

    async def read_audio(self) -> bytes | None:
        """Read the next chunk of audio from conference participants.

        Returns PCM audio at 16kHz mono int16, or None if disconnected.
        Used by the voice pipeline as an alternative to mic capture.
        """
        if not self._on_audio_data:
            return None
        try:
            return await asyncio.wait_for(self._on_audio_data.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return None

    async def publish_audio(self, pcm_data: bytes) -> None:
        """Publish TTS audio to the room so conference attendees hear it.

        Args:
            pcm_data: Raw PCM audio at 24kHz mono int16
        """
        if not self._audio_source or not self._running:
            return

        # Convert raw bytes to AudioFrame
        samples_per_channel = len(pcm_data) // 2  # 16-bit = 2 bytes per sample
        frame = rtc.AudioFrame.create(TTS_SAMPLE_RATE, NUM_CHANNELS, samples_per_channel)
        # Copy PCM data into frame
        frame_data = frame.data
        frame_data[:len(pcm_data)] = pcm_data
        await self._audio_source.capture_frame(frame)

    async def disconnect(self) -> None:
        """Disconnect from the room and clean up."""
        self._running = False

        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        for stream in self._audio_streams:
            await stream.aclose()
        self._audio_streams.clear()

        if self._room:
            await self._room.disconnect()
            self._room = None

        self._audio_source = None
        self._audio_track = None
        self._on_audio_data = None

        logger.info(f"Disconnected from room {self.room_name}")
