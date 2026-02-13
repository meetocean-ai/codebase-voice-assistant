"""Tests for call manager (LiveKit + Twilio SIP integration)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.call.manager import CallManager, CallState


def make_call_manager(mock_livekit_api) -> CallManager:
    return CallManager(
        livekit_url="wss://test.livekit.cloud",
        livekit_api_key="lk_key",
        livekit_api_secret="lk_secret",
        twilio_account_sid="AC_test",
        twilio_auth_token="tw_token",
    )


class TestCallState:
    def test_default_state(self):
        state = CallState()
        assert state.state == "idle"
        assert state.room_name is None
        assert state.dial_in_number is None


class TestCallManagerInit:
    def test_creates_livekit_api(self, mock_livekit_api):
        cm = make_call_manager(mock_livekit_api)
        assert cm._livekit_api is not None


class TestJoinCall:
    @pytest.mark.asyncio
    async def test_join_creates_room_and_sip_participant(self, mock_livekit_api):
        cm = make_call_manager(mock_livekit_api)

        await cm.join(dial_in_number="+15551234567")

        # Room created
        mock_livekit_api.room.create_room.assert_called_once()

        # SIP participant created
        mock_livekit_api.sip.create_sip_participant.assert_called_once()
        call_args = mock_livekit_api.sip.create_sip_participant.call_args
        request = call_args.args[0]
        assert request.sip_call_to == "+15551234567"
        assert request.participant_name == "SIP Bridge"
        assert request.krisp_enabled is True

        # Bot participant connected to room
        mock_livekit_api._mock_room_participant.connect.assert_called_once()

        # State updated
        assert cm._call_state.state == "connected"
        assert cm._call_state.dial_in_number == "+15551234567"

    @pytest.mark.asyncio
    async def test_join_with_pin_sends_dtmf(self, mock_livekit_api):
        cm = make_call_manager(mock_livekit_api)

        await cm.join(dial_in_number="+15551234567", pin="12345#")

        call_args = mock_livekit_api.sip.create_sip_participant.call_args
        request = call_args.args[0]
        assert request.dtmf == "wwww12345#"

    @pytest.mark.asyncio
    async def test_join_without_pin_has_empty_dtmf(self, mock_livekit_api):
        cm = make_call_manager(mock_livekit_api)

        await cm.join(dial_in_number="+15551234567")

        call_args = mock_livekit_api.sip.create_sip_participant.call_args
        request = call_args.args[0]
        assert request.dtmf == ""

    @pytest.mark.asyncio
    async def test_join_uses_discovered_trunk(self, mock_livekit_api):
        cm = make_call_manager(mock_livekit_api)

        await cm.join(dial_in_number="+15551234567")

        call_args = mock_livekit_api.sip.create_sip_participant.call_args
        request = call_args.args[0]
        assert request.sip_trunk_id == "ST_test_trunk_123"

    @pytest.mark.asyncio
    async def test_join_uses_explicit_trunk(self, mock_livekit_api):
        cm = make_call_manager(mock_livekit_api)
        cm.sip_trunk_id = "ST_explicit_trunk"

        await cm.join(dial_in_number="+15551234567")

        call_args = mock_livekit_api.sip.create_sip_participant.call_args
        request = call_args.args[0]
        assert request.sip_trunk_id == "ST_explicit_trunk"

    @pytest.mark.asyncio
    async def test_join_fails_without_trunk(self, mock_livekit_api):
        mock_trunks = MagicMock()
        mock_trunks.items = []
        mock_livekit_api.sip.list_sip_outbound_trunk = AsyncMock(return_value=mock_trunks)

        cm = make_call_manager(mock_livekit_api)

        with pytest.raises(RuntimeError, match="No SIP trunk"):
            await cm.join(dial_in_number="+15551234567")


class TestLeaveCall:
    @pytest.mark.asyncio
    async def test_leave_removes_participant_and_deletes_room(self, mock_livekit_api):
        cm = make_call_manager(mock_livekit_api)
        await cm.join(dial_in_number="+15551234567")

        await cm.leave()

        # Bot participant disconnected
        mock_livekit_api._mock_room_participant.disconnect.assert_called_once()

        mock_livekit_api.room.remove_participant.assert_called_once()
        mock_livekit_api.room.delete_room.assert_called_once()
        assert cm._call_state.state == "idle"

    @pytest.mark.asyncio
    async def test_leave_when_idle_is_noop(self, mock_livekit_api):
        cm = make_call_manager(mock_livekit_api)
        await cm.leave()  # Should not raise
        mock_livekit_api.room.remove_participant.assert_not_called()


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_status_when_idle(self, mock_livekit_api):
        cm = make_call_manager(mock_livekit_api)
        assert cm.get_status() is None

    @pytest.mark.asyncio
    async def test_status_when_connected(self, mock_livekit_api):
        cm = make_call_manager(mock_livekit_api)
        await cm.join(dial_in_number="+15551234567")

        status = cm.get_status()
        assert status is not None
        assert status["state"] == "connected"
        assert status["dial_in_number"] == "+15551234567"
        assert status["duration_seconds"] is not None
        assert status["room_name"].startswith("cva-")
