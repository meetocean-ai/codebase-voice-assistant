"""Tests for LiveKit room participant (bot audio I/O in conference calls)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.call.room_participant import RoomParticipant


def mock_livekit_rtc():
    """Create mocks for livekit.rtc components."""
    mock_room = MagicMock()
    mock_room.connect = AsyncMock()
    mock_room.disconnect = AsyncMock()

    mock_local_participant = MagicMock()
    mock_local_participant.publish_track = AsyncMock()
    mock_room.local_participant = mock_local_participant

    # Track event registration
    handlers = {}

    def on_handler(event_name, handler):
        handlers[event_name] = handler

    mock_room.on = on_handler
    mock_room._handlers = handlers

    mock_audio_source = MagicMock()
    mock_audio_source.capture_frame = AsyncMock()

    mock_audio_track = MagicMock()

    mock_audio_frame = MagicMock()
    mock_audio_frame.data = bytearray(b"\x00" * 1024)

    return {
        "room": mock_room,
        "audio_source": mock_audio_source,
        "audio_track": mock_audio_track,
        "audio_frame": mock_audio_frame,
        "local_participant": mock_local_participant,
    }


@pytest.fixture
def livekit_mocks():
    mocks = mock_livekit_rtc()

    with patch("src.call.room_participant.rtc") as mock_rtc, \
         patch("src.call.room_participant.api") as mock_api:
        mock_rtc.Room.return_value = mocks["room"]
        mock_rtc.AudioSource.return_value = mocks["audio_source"]
        mock_rtc.LocalAudioTrack.create_audio_track.return_value = mocks["audio_track"]
        mock_rtc.AudioFrame.create.return_value = mocks["audio_frame"]
        mock_rtc.TrackKind.KIND_AUDIO = "audio"
        mock_rtc.AudioStream.from_track.return_value = AsyncMock()

        mock_token = MagicMock()
        mock_token.with_identity.return_value = mock_token
        mock_token.with_name.return_value = mock_token
        mock_token.with_grants.return_value = mock_token
        mock_token.to_jwt.return_value = "test_jwt_token"
        mock_api.AccessToken.return_value = mock_token

        mocks["rtc"] = mock_rtc
        mocks["api"] = mock_api
        yield mocks


def make_participant() -> RoomParticipant:
    return RoomParticipant(
        livekit_url="wss://test.livekit.cloud",
        livekit_api_key="lk_key",
        livekit_api_secret="lk_secret",
        room_name="cva-test-room",
    )


class TestRoomParticipantConnect:
    @pytest.mark.asyncio
    async def test_connects_to_room(self, livekit_mocks):
        rp = make_participant()
        await rp.connect()

        livekit_mocks["room"].connect.assert_called_once_with(
            "wss://test.livekit.cloud", "test_jwt_token"
        )

    @pytest.mark.asyncio
    async def test_generates_access_token(self, livekit_mocks):
        rp = make_participant()
        await rp.connect()

        livekit_mocks["api"].AccessToken.assert_called_once_with("lk_key", "lk_secret")

    @pytest.mark.asyncio
    async def test_publishes_audio_track(self, livekit_mocks):
        rp = make_participant()
        await rp.connect()

        livekit_mocks["rtc"].LocalAudioTrack.create_audio_track.assert_called_once()
        livekit_mocks["local_participant"].publish_track.assert_called_once()

    @pytest.mark.asyncio
    async def test_registers_track_subscribed_handler(self, livekit_mocks):
        rp = make_participant()
        await rp.connect()

        assert "track_subscribed" in livekit_mocks["room"]._handlers

    @pytest.mark.asyncio
    async def test_sets_running_state(self, livekit_mocks):
        rp = make_participant()
        assert rp._running is False

        await rp.connect()
        assert rp._running is True


class TestRoomParticipantDisconnect:
    @pytest.mark.asyncio
    async def test_disconnects_from_room(self, livekit_mocks):
        rp = make_participant()
        await rp.connect()
        await rp.disconnect()

        livekit_mocks["room"].disconnect.assert_called_once()
        assert rp._running is False
        assert rp._room is None

    @pytest.mark.asyncio
    async def test_disconnect_cleans_up_state(self, livekit_mocks):
        rp = make_participant()
        await rp.connect()
        await rp.disconnect()

        assert rp._audio_source is None
        assert rp._audio_track is None
        assert rp._on_audio_data is None


class TestPublishAudio:
    @pytest.mark.asyncio
    async def test_publish_audio_captures_frame(self, livekit_mocks):
        rp = make_participant()
        await rp.connect()

        pcm_data = b"\x00" * 960  # 20ms at 24kHz mono int16
        await rp.publish_audio(pcm_data)

        livekit_mocks["rtc"].AudioFrame.create.assert_called_once_with(24000, 1, 480)
        livekit_mocks["audio_source"].capture_frame.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_audio_noop_when_not_connected(self, livekit_mocks):
        rp = make_participant()
        await rp.publish_audio(b"\x00" * 960)

        livekit_mocks["audio_source"].capture_frame.assert_not_called()


class TestReadAudio:
    @pytest.mark.asyncio
    async def test_read_audio_returns_none_when_empty(self, livekit_mocks):
        rp = make_participant()
        await rp.connect()

        result = await rp.read_audio()
        assert result is None

    @pytest.mark.asyncio
    async def test_read_audio_returns_queued_data(self, livekit_mocks):
        rp = make_participant()
        await rp.connect()

        await rp._on_audio_data.put(b"\x01\x02\x03")
        result = await rp.read_audio()
        assert result == b"\x01\x02\x03"

    @pytest.mark.asyncio
    async def test_read_audio_returns_none_when_not_connected(self, livekit_mocks):
        rp = make_participant()
        result = await rp.read_audio()
        assert result is None


class TestTrackSubscription:
    @pytest.mark.asyncio
    async def test_ignores_non_audio_tracks(self, livekit_mocks):
        rp = make_participant()
        await rp.connect()

        mock_track = MagicMock()
        mock_track.kind = "video"
        mock_pub = MagicMock()
        mock_participant = MagicMock()
        mock_participant.identity = "test-user"

        handler = livekit_mocks["room"]._handlers["track_subscribed"]
        handler(mock_track, mock_pub, mock_participant)

        # No audio stream created
        livekit_mocks["rtc"].AudioStream.from_track.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_audio_stream_for_audio_tracks(self, livekit_mocks):
        rp = make_participant()
        await rp.connect()

        mock_track = MagicMock()
        mock_track.kind = "audio"
        mock_track.name = "microphone"
        mock_pub = MagicMock()
        mock_participant = MagicMock()
        mock_participant.identity = "sip-participant"

        handler = livekit_mocks["room"]._handlers["track_subscribed"]
        handler(mock_track, mock_pub, mock_participant)

        livekit_mocks["rtc"].AudioStream.from_track.assert_called_once_with(
            track=mock_track,
            sample_rate=16000,
            num_channels=1,
        )
