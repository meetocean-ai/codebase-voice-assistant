# Codebase Voice Assistant

Claude Code plugin for voice-based codebase Q&A. Two modes: local mic/speakers (free) and conference call dial-in (pro).

## Architecture

MCP server (`src/server.py`) exposes tools to Claude Code. Skills (`skills/`) define user-facing commands. Voice pipeline captures audio → STT → wake word detection → question queue → Claude Code answers → TTS → audio output.

### Key modules

- `src/server.py` — MCP tool handlers (start/stop session, poll/answer loop, config)
- `src/voice/pipeline.py` — Orchestrator connecting audio capture → STT → wake word → TTS
- `src/voice/stt.py` — Deepgram STT streaming (nova-2)
- `src/voice/tts.py` — Deepgram TTS (aura-2)
- `src/voice/wake_word.py` — State machine: LISTENING → CAPTURING → PROCESSING
- `src/audio/capture.py` — PyAudio mic capture (16kHz mono)
- `src/audio/playback.py` — PyAudio speaker output (24kHz mono)
- `src/call/manager.py` — LiveKit room + SIP participant lifecycle
- `src/call/room_participant.py` — Bot participant in LiveKit room (audio I/O)
- `src/config.py` — Config stored at `~/.config/codebase-voice-assistant/config.json`

## Commands

```bash
# Run tests
.venv/bin/python -m pytest tests/ -q

# Run a single test file
.venv/bin/python -m pytest tests/test_server.py -q

# Lint
.venv/bin/ruff check src/ tests/

# Run MCP server locally
.venv/bin/python -m src
```

## Conventions

- Python 3.11+, async/await throughout
- Dataclasses over Pydantic for internal types
- Tests use pytest-asyncio with mocked PyAudio, Deepgram, and LiveKit
- Deepgram SDK v5 API: `listen.v1.connect()` for STT, `speak.v1.audio.generate()` for TTS
- Config keys: snake_case, stored as flat JSON
- MCP tools return `list[TextContent]`

## Testing

All external APIs (Deepgram, LiveKit, PyAudio) are mocked in `tests/conftest.py`. Tests run without any API keys or audio devices. Run `pytest tests/ -q` before committing.
