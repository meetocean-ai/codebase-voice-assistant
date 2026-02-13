"""MCP server for the codebase voice assistant.

Exposes tools to Claude Code for:
- Local voice sessions (free — mic + speakers, no telephony)
- Conference call sessions (pro — SIP dial-in via LiveKit + Twilio)
- Configuration management
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.call.manager import CallManager
from src.config import (
    get_config_value,
    get_display_config,
    has_telephony_config,
    is_configured,
    load_config,
    set_config_value,
)
from src.voice.pipeline import VoicePipeline

logger = logging.getLogger(__name__)

server = Server("codebase-voice")

# Global state
voice_pipeline: VoicePipeline | None = None
call_manager: CallManager | None = None
session_active = False
session_mode: str | None = None  # "local" or "call"


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        # ── Free: Local Voice ──────────────────────────────────────────
        Tool(
            name="start_local_session",
            description=(
                "Start a free local voice session. Uses your microphone and speakers "
                "to talk with Claude about your codebase. No telephony required — "
                "just a Deepgram API key (free tier: 12,000 min/month)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Absolute path to the project/repo root",
                    },
                    "codebase_summary": {
                        "type": "string",
                        "description": (
                            "A brief summary of the codebase structure, key files, "
                            "and tech stack. This context is available to the voice "
                            "agent when answering questions."
                        ),
                    },
                },
                "required": ["project_path"],
            },
        ),
        # ── Pro: Conference Call ───────────────────────────────────────
        Tool(
            name="start_call_session",
            description=(
                "[Pro] Join a conference call as a voice AI assistant. Dials into "
                "the meeting via SIP so the bot appears as its own participant. "
                "Everyone on the call can ask codebase questions. "
                "Requires LiveKit + Twilio configuration."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Absolute path to the project/repo root",
                    },
                    "codebase_summary": {
                        "type": "string",
                        "description": "Brief summary of codebase structure and tech stack.",
                    },
                    "dial_in_number": {
                        "type": "string",
                        "description": "Conference dial-in phone number in E.164 format (e.g., +15551234567)",
                    },
                    "pin": {
                        "type": "string",
                        "description": "Meeting PIN or access code (e.g., '12345#'). Include # if needed.",
                    },
                },
                "required": ["project_path", "dial_in_number"],
            },
        ),
        # ── Question/Answer Loop ──────────────────────────────────────
        Tool(
            name="poll_question",
            description=(
                "Poll for the next voice question captured by the wake word detector. "
                "Returns the question text if someone said the wake word followed by a "
                "question, or null if no question is pending. Call this in a loop during "
                "an active session. Timeout is 2 seconds per poll."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "timeout_ms": {
                        "type": "integer",
                        "description": "How long to wait for a question in milliseconds (default: 2000)",
                        "default": 2000,
                    },
                },
            },
        ),
        Tool(
            name="provide_answer",
            description=(
                "Provide an answer to the most recent voice question. The answer will "
                "be spoken aloud via TTS. Call this after poll_question returns a question "
                "and you've searched the codebase for the answer."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "string",
                        "description": "The answer to speak aloud. Keep it concise (1-3 sentences) for natural conversation.",
                    },
                },
                "required": ["answer"],
            },
        ),
        # ── Shared ─────────────────────────────────────────────────────
        Tool(
            name="stop_session",
            description="Stop the voice assistant session and disconnect from any active call.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_status",
            description="Get the current status of the voice assistant (session mode, call info, questions asked).",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_config",
            description="Get the current configuration (API keys masked, preferences shown).",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="set_config",
            description="Set a configuration value (API key or preference).",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Configuration key to set",
                        "enum": [
                            "deepgram_api_key",
                            "livekit_url",
                            "livekit_api_key",
                            "livekit_api_secret",
                            "twilio_account_sid",
                            "twilio_auth_token",
                            "wake_word",
                            "tts_voice",
                            "stt_language",
                        ],
                    },
                    "value": {
                        "type": "string",
                        "description": "Value to set",
                    },
                },
                "required": ["key", "value"],
            },
        ),
    ]


def _create_pipeline(config: dict, project_path: str, codebase_summary: str) -> VoicePipeline:
    return VoicePipeline(
        deepgram_api_key=config["deepgram_api_key"],
        wake_word=config.get("wake_word", "hey claude"),
        tts_voice=config.get("tts_voice", "aura-2-en-US-luna"),
        stt_model=config.get("stt_model", "nova-2"),
        stt_language=config.get("stt_language", "en-US"),
        project_path=project_path,
        codebase_summary=codebase_summary,
    )


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    global voice_pipeline, call_manager, session_active, session_mode

    # ── get_config ─────────────────────────────────────────────────
    if name == "get_config":
        display = get_display_config()
        configured = is_configured()
        telephony = has_telephony_config()
        lines = ["## Current Configuration", ""]
        for k, v in sorted(display.items()):
            lines.append(f"- **{k}**: `{v}`")
        lines.append("")
        lines.append(f"/voice-start ready: {'Yes' if configured else 'No — need deepgram_api_key'}")
        lines.append(f"/voice-join ready: {'Yes' if telephony else 'No — need LiveKit + Twilio keys (Pro)'}")
        return [TextContent(type="text", text="\n".join(lines))]

    # ── set_config ─────────────────────────────────────────────────
    if name == "set_config":
        key = arguments["key"]
        value = arguments["value"]
        set_config_value(key, value)
        return [TextContent(type="text", text=f"Set `{key}` successfully.")]

    # ── get_status ─────────────────────────────────────────────────
    if name == "get_status":
        if not session_active:
            return [TextContent(
                type="text",
                text=(
                    "Voice assistant is **idle**.\n\n"
                    "- `/voice-start` — talk to Claude through your mic (free)\n"
                    "- `/voice-join` — join a conference call (pro)"
                ),
            )]

        lines = ["## Voice Assistant Status", ""]
        lines.append(f"- Mode: **{session_mode}**")
        lines.append(f"- Session: **active**")

        if voice_pipeline:
            vp = voice_pipeline.get_status()
            lines.append(f"- STT: **{vp.get('stt_state', 'unknown')}**")
            lines.append(f"- TTS: **{vp.get('tts_state', 'unknown')}**")
            lines.append(f"- Wake word: **{get_config_value('wake_word') or 'hey claude'}**")
            lines.append(f"- Questions answered: **{vp.get('questions_answered', 0)}**")
            if vp.get("avg_latency_ms"):
                lines.append(f"- Avg response time: **{vp['avg_latency_ms']}ms**")

        if call_manager:
            c = call_manager.get_status()
            if c:
                lines.append(f"- Call: **{c.get('state', 'unknown')}**")
                lines.append(f"- Dial-in: `{c.get('dial_in_number', 'N/A')}`")
                lines.append(f"- Duration: {c.get('duration_seconds', 0)}s")

        return [TextContent(type="text", text="\n".join(lines))]

    # ── start_local_session (FREE) ─────────────────────────────────
    if name == "start_local_session":
        if session_active:
            return [TextContent(type="text", text="Session already active. Use `stop_session` first to restart.")]

        if not is_configured():
            return [TextContent(
                type="text",
                text="Not configured. Run `/voice-config` to set your Deepgram API key first.",
            )]

        config = load_config()
        project_path = arguments["project_path"]
        codebase_summary = arguments.get("codebase_summary", "")

        voice_pipeline = _create_pipeline(config, project_path, codebase_summary)
        await voice_pipeline.start()
        session_active = True
        session_mode = "local"

        wake = config.get("wake_word", "hey claude")
        return [TextContent(
            type="text",
            text=(
                f"Local voice session started for `{project_path}`.\n\n"
                f"Listening on your microphone for wake word: **\"{wake}\"**\n"
                f"Answers play through your speakers.\n\n"
                f"Say **\"{wake}\"** followed by your question. "
                f"Say **\"Claude, leave\"** to stop."
            ),
        )]

    # ── start_call_session (PRO) ───────────────────────────────────
    if name == "start_call_session":
        if session_active:
            return [TextContent(type="text", text="Session already active. Use `stop_session` first to restart.")]

        if not is_configured():
            return [TextContent(
                type="text",
                text="Not configured. Run `/voice-config` to set your Deepgram API key first.",
            )]

        if not has_telephony_config():
            return [TextContent(
                type="text",
                text=(
                    "**[Pro]** Conference call joining requires LiveKit and Twilio.\n\n"
                    "Run `/voice-config` to set up:\n"
                    "- LiveKit Cloud (free tier: 50GB/month) — livekit_url, livekit_api_key, livekit_api_secret\n"
                    "- Twilio (trial: $15 credit) — twilio_account_sid, twilio_auth_token\n\n"
                    "Or use `/voice-start` for free local voice mode."
                ),
            )]

        config = load_config()
        project_path = arguments["project_path"]
        codebase_summary = arguments.get("codebase_summary", "")
        dial_in_number = arguments["dial_in_number"]
        pin = arguments.get("pin")

        # Start voice pipeline
        voice_pipeline = _create_pipeline(config, project_path, codebase_summary)
        await voice_pipeline.start()

        # Join the call
        call_manager = CallManager(
            livekit_url=config["livekit_url"],
            livekit_api_key=config["livekit_api_key"],
            livekit_api_secret=config["livekit_api_secret"],
            twilio_account_sid=config["twilio_account_sid"],
            twilio_auth_token=config["twilio_auth_token"],
            voice_pipeline=voice_pipeline,
        )
        await call_manager.join(dial_in_number=dial_in_number, pin=pin)

        session_active = True
        session_mode = "call"

        msg = f"Joined conference call: `{dial_in_number}`"
        if pin:
            msg += f" (PIN: `{pin}`)"
        wake = config.get("wake_word", "hey claude")
        msg += (
            f"\n\nThe assistant is now a participant on the call.\n"
            f"Anyone can say **\"{wake}\"** followed by a codebase question.\n"
            f"Say **\"Claude, leave\"** to disconnect."
        )
        return [TextContent(type="text", text=msg)]

    # ── poll_question ─────────────────────────────────────────────
    if name == "poll_question":
        if not session_active or not voice_pipeline:
            return [TextContent(type="text", text="No active session.")]

        timeout_ms = arguments.get("timeout_ms", 2000)
        timeout_s = timeout_ms / 1000.0

        try:
            question = await asyncio.wait_for(
                voice_pipeline._question_queue.get(),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            # Check if session was stopped while waiting
            if not session_active:
                return [TextContent(type="text", text="__SESSION_ENDED__")]
            return [TextContent(type="text", text="__NO_QUESTION__")]

        if question == "__LEAVE__":
            return [TextContent(type="text", text="__LEAVE__")]

        # Track the question so provide_answer can record latency
        import time
        from src.voice.pipeline import QuestionRecord
        voice_pipeline._questions.append(
            QuestionRecord(
                question=question,
                answer=None,
                asked_at=time.time(),
                answered_at=None,
                latency_ms=None,
            )
        )

        return [TextContent(type="text", text=question)]

    # ── provide_answer ─────────────────────────────────────────────
    if name == "provide_answer":
        if not session_active or not voice_pipeline:
            return [TextContent(type="text", text="No active session.")]

        answer = arguments["answer"]
        await voice_pipeline.provide_answer(answer)
        return [TextContent(type="text", text="Answer spoken.")]

    # ── stop_session ───────────────────────────────────────────────
    if name == "stop_session":
        mode = session_mode
        if voice_pipeline:
            await voice_pipeline.stop()
            voice_pipeline = None
        if call_manager:
            await call_manager.leave()
            call_manager = None
        session_active = False
        session_mode = None

        if mode == "call":
            return [TextContent(type="text", text="Left the conference call. Voice session stopped.")]
        return [TextContent(type="text", text="Voice session stopped.")]

    return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
