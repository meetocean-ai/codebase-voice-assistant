"""Shared fixtures for the test suite."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import CONFIG_DIR, CONFIG_FILE


@pytest.fixture
def tmp_config_dir(tmp_path, monkeypatch):
    """Redirect config to a temporary directory so tests don't touch real config."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "config.json"

    monkeypatch.setattr("src.config.CONFIG_DIR", config_dir)
    monkeypatch.setattr("src.config.CONFIG_FILE", config_file)

    return config_dir, config_file


@pytest.fixture
def configured_config(tmp_config_dir):
    """A config with all keys set for a fully configured setup."""
    config_dir, config_file = tmp_config_dir
    config = {
        "deepgram_api_key": "dg_test_key_1234567890",
        "livekit_url": "wss://test.livekit.cloud",
        "livekit_api_key": "lk_api_test",
        "livekit_api_secret": "lk_secret_test",
        "twilio_account_sid": "AC_test_sid_12345",
        "twilio_auth_token": "tw_auth_test_token",
        "wake_word": "hey claude",
        "tts_voice": "aura-2-luna-en",
        "stt_language": "en-US",
        "stt_model": "nova-2",
    }
    config_file.write_text(json.dumps(config))
    return config


@pytest.fixture
def mock_pyaudio():
    """Mock pyaudio for tests that don't need real audio."""
    mock_pa = MagicMock()
    mock_stream = MagicMock()
    mock_pa.open.return_value = mock_stream
    mock_pa.get_device_count.return_value = 2
    mock_pa.get_device_info_by_index.side_effect = lambda i: {
        0: {
            "index": 0,
            "name": "Built-in Microphone",
            "maxInputChannels": 2,
            "maxOutputChannels": 0,
            "defaultSampleRate": 44100.0,
        },
        1: {
            "index": 1,
            "name": "BlackHole 2ch",
            "maxInputChannels": 2,
            "maxOutputChannels": 2,
            "defaultSampleRate": 48000.0,
        },
    }[i]
    mock_pa.get_default_input_device_info.return_value = {
        "index": 0,
        "name": "Built-in Microphone",
        "maxInputChannels": 2,
        "maxOutputChannels": 0,
        "defaultSampleRate": 44100.0,
    }
    mock_pa.get_default_output_device_info.return_value = {
        "index": 0,
        "name": "Built-in Output",
        "maxInputChannels": 0,
        "maxOutputChannels": 2,
        "defaultSampleRate": 44100.0,
    }

    with patch("pyaudio.PyAudio", return_value=mock_pa):
        yield mock_pa, mock_stream


@pytest.fixture
def mock_deepgram():
    """Mock Deepgram client for STT/TTS tests."""
    mock_client = MagicMock()

    # Mock listen.v1.connect() for STT
    mock_socket = MagicMock()
    mock_socket.send = MagicMock()
    mock_socket.close = MagicMock()
    mock_socket.poll = MagicMock(return_value=None)
    mock_client.listen.v1.connect.return_value = iter([mock_socket])

    # Mock speak.v1.audio.generate() for TTS
    mock_client.speak.v1.audio.generate.return_value = iter([b"\x00" * 4800])

    with patch("deepgram.DeepgramClient", return_value=mock_client):
        yield mock_client, mock_socket


@pytest.fixture
def mock_livekit_api():
    """Mock LiveKit API for call manager tests."""
    mock_api = MagicMock()

    # Mock room creation
    mock_api.room.create_room = AsyncMock()
    mock_api.room.delete_room = AsyncMock()
    mock_api.room.remove_participant = AsyncMock()

    # Mock SIP
    mock_participant = MagicMock()
    mock_participant.participant_identity = "codebase-voice-assistant"
    mock_api.sip.create_sip_participant = AsyncMock(return_value=mock_participant)

    mock_trunks = MagicMock()
    mock_trunk = MagicMock()
    mock_trunk.sip_trunk_id = "ST_test_trunk_123"
    mock_trunks.items = [mock_trunk]
    mock_api.sip.list_sip_outbound_trunk = AsyncMock(return_value=mock_trunks)

    # Mock RoomParticipant so CallManager.join doesn't need a real LiveKit connection
    mock_room_participant = MagicMock()
    mock_room_participant.connect = AsyncMock()
    mock_room_participant.disconnect = AsyncMock()
    mock_room_participant.publish_audio = AsyncMock()
    mock_room_participant.read_audio = AsyncMock(return_value=None)

    with patch("livekit.api.LiveKitAPI", return_value=mock_api), \
         patch("src.call.manager.RoomParticipant", return_value=mock_room_participant):
        mock_api._mock_room_participant = mock_room_participant
        yield mock_api
