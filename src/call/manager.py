"""Call manager — handles joining and leaving conference calls via SIP.

Uses LiveKit rooms + Twilio SIP trunks to join a conference call.
The flow:
1. Create a LiveKit room
2. Create a SIP participant that dials the conference number
3. Connect our bot participant to the room for audio I/O
4. Route audio between the conference call and the voice pipeline
5. On leave: remove participant, delete room
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from livekit import api

from src.call.room_participant import RoomParticipant

logger = logging.getLogger(__name__)


@dataclass
class CallState:
    room_name: str | None = None
    dial_in_number: str | None = None
    pin: str | None = None
    state: str = "idle"  # idle, connecting, connected, disconnected
    connected_at: float | None = None
    sip_participant_id: str | None = None


@dataclass
class CallManager:
    """Manages conference call joining via LiveKit + Twilio SIP."""

    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str
    twilio_account_sid: str
    twilio_auth_token: str
    voice_pipeline: object = None  # VoicePipeline, avoid circular import
    sip_trunk_id: str | None = None  # LiveKit SIP trunk ID (configured in LiveKit dashboard)

    _livekit_api: api.LiveKitAPI | None = field(default=None, init=False)
    _call_state: CallState = field(default_factory=CallState, init=False)
    _room_participant: RoomParticipant | None = field(default=None, init=False)

    def __post_init__(self):
        self._livekit_api = api.LiveKitAPI(
            url=self.livekit_url,
            api_key=self.livekit_api_key,
            api_secret=self.livekit_api_secret,
        )

    async def join(self, dial_in_number: str, pin: str | None = None) -> None:
        """Join a conference call by dialing in via SIP.

        Args:
            dial_in_number: Conference dial-in number in E.164 format
            pin: Optional meeting PIN/access code (include # if needed)
        """
        room_name = f"cva-{int(time.time())}"
        self._call_state = CallState(
            room_name=room_name,
            dial_in_number=dial_in_number,
            pin=pin,
            state="connecting",
        )

        logger.info(f"Creating LiveKit room: {room_name}")

        # Create the room
        await self._livekit_api.room.create_room(
            api.CreateRoomRequest(name=room_name)
        )

        # Determine SIP trunk to use
        trunk_id = self.sip_trunk_id
        if not trunk_id:
            # List available trunks and use the first one
            trunks = await self._livekit_api.sip.list_sip_outbound_trunk(
                api.ListSIPOutboundTrunkRequest()
            )
            if trunks.items:
                trunk_id = trunks.items[0].sip_trunk_id
                logger.info(f"Using SIP trunk: {trunk_id}")
            else:
                raise RuntimeError(
                    "No SIP trunk configured in LiveKit. "
                    "Create one in your LiveKit dashboard linked to your Twilio account."
                )

        # Build DTMF string for PIN entry
        # Wait 3 seconds after connect, then send PIN digits
        dtmf = ""
        if pin:
            dtmf = f"wwww{pin}"  # Each 'w' is a 0.5s pause

        # Create SIP participant that dials into the conference
        logger.info(f"Dialing {dial_in_number} via SIP trunk {trunk_id}")

        participant = await self._livekit_api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                room_name=room_name,
                sip_trunk_id=trunk_id,
                sip_call_to=dial_in_number,
                participant_identity="codebase-voice-sip",
                participant_name="SIP Bridge",
                dtmf=dtmf,
                play_dialtone=False,
                krisp_enabled=True,
            )
        )

        self._call_state.sip_participant_id = participant.participant_identity
        self._call_state.state = "connected"
        self._call_state.connected_at = time.time()

        logger.info(f"SIP participant connected in room {room_name}")

        # Connect our bot participant to the room for audio I/O
        self._room_participant = RoomParticipant(
            livekit_url=self.livekit_url,
            livekit_api_key=self.livekit_api_key,
            livekit_api_secret=self.livekit_api_secret,
            room_name=room_name,
        )
        await self._room_participant.connect()

        # Switch voice pipeline to route audio through LiveKit
        if self.voice_pipeline and hasattr(self.voice_pipeline, "switch_to_livekit"):
            self.voice_pipeline.switch_to_livekit(self._room_participant)

        logger.info(f"Connected to conference call in room {room_name}")

    async def leave(self) -> None:
        """Leave the conference call and clean up."""
        if self._call_state.state == "idle":
            return

        room_name = self._call_state.room_name

        # Disconnect our bot participant first
        if self._room_participant:
            await self._room_participant.disconnect()
            self._room_participant = None

        if room_name and self._livekit_api:
            try:
                # Remove the SIP participant
                if self._call_state.sip_participant_id:
                    await self._livekit_api.room.remove_participant(
                        api.RoomParticipantIdentity(
                            room=room_name,
                            identity=self._call_state.sip_participant_id,
                        )
                    )

                # Delete the room
                await self._livekit_api.room.delete_room(
                    api.DeleteRoomRequest(room=room_name)
                )
                logger.info(f"Left conference call, room {room_name} deleted")
            except Exception as e:
                logger.error(f"Error leaving call: {e}")

        self._call_state = CallState()

    def get_status(self) -> dict | None:
        if self._call_state.state == "idle":
            return None

        duration = None
        if self._call_state.connected_at:
            duration = int(time.time() - self._call_state.connected_at)

        return {
            "state": self._call_state.state,
            "room_name": self._call_state.room_name,
            "dial_in_number": self._call_state.dial_in_number,
            "duration_seconds": duration,
        }
