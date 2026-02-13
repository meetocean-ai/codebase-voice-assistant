"""Tests for the MCP server tool handlers."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.server import call_tool, list_tools, server


def _reset_server_state():
    """Reset global server state between tests."""
    import src.server as srv
    srv.session_active = False
    srv.session_mode = None
    srv.voice_pipeline = None
    srv.call_manager = None


class TestListTools:
    @pytest.mark.asyncio
    async def test_returns_all_tools(self):
        tools = await list_tools()
        tool_names = {t.name for t in tools}
        assert tool_names == {
            "start_local_session",
            "start_call_session",
            "poll_question",
            "provide_answer",
            "stop_session",
            "get_status",
            "get_config",
            "set_config",
        }

    @pytest.mark.asyncio
    async def test_tools_have_descriptions(self):
        tools = await list_tools()
        for tool in tools:
            assert tool.description, f"Tool {tool.name} has no description"

    @pytest.mark.asyncio
    async def test_tools_have_input_schemas(self):
        tools = await list_tools()
        for tool in tools:
            assert tool.inputSchema is not None
            assert tool.inputSchema["type"] == "object"

    @pytest.mark.asyncio
    async def test_call_session_marked_as_pro(self):
        tools = await list_tools()
        call_tool_def = next(t for t in tools if t.name == "start_call_session")
        assert "[Pro]" in call_tool_def.description

    @pytest.mark.asyncio
    async def test_local_session_is_free(self):
        tools = await list_tools()
        local_tool = next(t for t in tools if t.name == "start_local_session")
        assert "free" in local_tool.description.lower()


class TestGetConfig:
    @pytest.mark.asyncio
    async def test_returns_config_display(self, tmp_config_dir):
        result = await call_tool("get_config", {})
        assert len(result) == 1
        text = result[0].text
        assert "Configuration" in text
        assert "/voice-start" in text
        assert "/voice-join" in text

    @pytest.mark.asyncio
    async def test_shows_not_configured(self, tmp_config_dir):
        result = await call_tool("get_config", {})
        text = result[0].text
        assert "No" in text

    @pytest.mark.asyncio
    async def test_shows_configured(self, configured_config):
        result = await call_tool("get_config", {})
        text = result[0].text
        assert "Yes" in text

    @pytest.mark.asyncio
    async def test_shows_pro_status(self, configured_config):
        result = await call_tool("get_config", {})
        text = result[0].text
        # Fully configured = both voice-start and voice-join should be ready
        assert "/voice-start ready: Yes" in text
        assert "/voice-join ready: Yes" in text


class TestSetConfig:
    @pytest.mark.asyncio
    async def test_sets_value(self, tmp_config_dir):
        result = await call_tool("set_config", {"key": "deepgram_api_key", "value": "new_key"})
        assert "successfully" in result[0].text.lower()

        from src.config import get_config_value
        assert get_config_value("deepgram_api_key") == "new_key"

    @pytest.mark.asyncio
    async def test_sets_wake_word(self, tmp_config_dir):
        await call_tool("set_config", {"key": "wake_word", "value": "yo ai"})
        from src.config import get_config_value
        assert get_config_value("wake_word") == "yo ai"


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_idle_status(self, tmp_config_dir):
        _reset_server_state()
        result = await call_tool("get_status", {})
        text = result[0].text
        assert "idle" in text.lower()
        assert "/voice-start" in text
        assert "/voice-join" in text

    @pytest.mark.asyncio
    async def test_active_local_status(self, configured_config, mock_pyaudio, mock_deepgram):
        _reset_server_state()
        await call_tool("start_local_session", {"project_path": "/test"})

        result = await call_tool("get_status", {})
        text = result[0].text
        assert "local" in text.lower()
        assert "active" in text.lower()

        await call_tool("stop_session", {})

    @pytest.mark.asyncio
    async def test_active_call_status(self, configured_config, mock_pyaudio, mock_deepgram, mock_livekit_api):
        _reset_server_state()
        await call_tool("start_call_session", {
            "project_path": "/test",
            "dial_in_number": "+15551234567",
        })

        result = await call_tool("get_status", {})
        text = result[0].text
        assert "call" in text.lower()
        assert "active" in text.lower()

        await call_tool("stop_session", {})


class TestStartLocalSession:
    @pytest.mark.asyncio
    async def test_requires_config(self, tmp_config_dir):
        _reset_server_state()
        result = await call_tool("start_local_session", {"project_path": "/test"})
        text = result[0].text
        assert "voice-config" in text.lower() or "not configured" in text.lower()

    @pytest.mark.asyncio
    async def test_starts_local_session(self, configured_config, mock_pyaudio, mock_deepgram):
        _reset_server_state()
        result = await call_tool("start_local_session", {
            "project_path": "/test/project",
            "codebase_summary": "A Python web app",
        })

        import src.server as srv
        text = result[0].text
        assert "local voice session started" in text.lower()
        assert "microphone" in text.lower()
        assert srv.session_active is True
        assert srv.session_mode == "local"
        assert srv.voice_pipeline is not None

        await call_tool("stop_session", {})

    @pytest.mark.asyncio
    async def test_rejects_double_start(self, configured_config, mock_pyaudio, mock_deepgram):
        _reset_server_state()
        await call_tool("start_local_session", {"project_path": "/test"})
        result = await call_tool("start_local_session", {"project_path": "/test2"})

        text = result[0].text
        assert "already active" in text.lower()

        await call_tool("stop_session", {})

    @pytest.mark.asyncio
    async def test_includes_wake_word_in_response(self, configured_config, mock_pyaudio, mock_deepgram):
        _reset_server_state()
        result = await call_tool("start_local_session", {"project_path": "/test"})
        text = result[0].text
        assert "hey claude" in text.lower()

        await call_tool("stop_session", {})


class TestStartCallSession:
    @pytest.mark.asyncio
    async def test_requires_config(self, tmp_config_dir):
        _reset_server_state()
        result = await call_tool("start_call_session", {
            "project_path": "/test",
            "dial_in_number": "+15551234567",
        })
        text = result[0].text
        assert "not configured" in text.lower()

    @pytest.mark.asyncio
    async def test_requires_telephony_config(self, tmp_config_dir):
        _reset_server_state()
        from src.config import set_config_value
        set_config_value("deepgram_api_key", "dg_key")

        result = await call_tool("start_call_session", {
            "project_path": "/test",
            "dial_in_number": "+15551234567",
        })
        text = result[0].text
        assert "pro" in text.lower() or "livekit" in text.lower()
        assert "/voice-start" in text  # Suggests free alternative

    @pytest.mark.asyncio
    async def test_starts_call_session(self, configured_config, mock_pyaudio, mock_deepgram, mock_livekit_api):
        _reset_server_state()
        result = await call_tool("start_call_session", {
            "project_path": "/test/project",
            "dial_in_number": "+15551234567",
            "pin": "12345#",
        })

        import src.server as srv
        text = result[0].text
        assert "joined" in text.lower() or "+15551234567" in text
        assert "12345#" in text
        assert srv.session_active is True
        assert srv.session_mode == "call"
        assert srv.voice_pipeline is not None
        assert srv.call_manager is not None

        await call_tool("stop_session", {})

    @pytest.mark.asyncio
    async def test_call_session_without_pin(self, configured_config, mock_pyaudio, mock_deepgram, mock_livekit_api):
        _reset_server_state()
        result = await call_tool("start_call_session", {
            "project_path": "/test",
            "dial_in_number": "+15551234567",
        })

        text = result[0].text
        assert "+15551234567" in text

        await call_tool("stop_session", {})


class TestStopSession:
    @pytest.mark.asyncio
    async def test_stops_local_session(self, configured_config, mock_pyaudio, mock_deepgram):
        _reset_server_state()
        await call_tool("start_local_session", {"project_path": "/test"})
        result = await call_tool("stop_session", {})

        import src.server as srv
        assert "stopped" in result[0].text.lower()
        assert srv.session_active is False
        assert srv.session_mode is None

    @pytest.mark.asyncio
    async def test_stops_call_session(self, configured_config, mock_pyaudio, mock_deepgram, mock_livekit_api):
        _reset_server_state()
        await call_tool("start_call_session", {
            "project_path": "/test",
            "dial_in_number": "+15551234567",
        })
        result = await call_tool("stop_session", {})

        text = result[0].text
        assert "left" in text.lower() or "stopped" in text.lower()

    @pytest.mark.asyncio
    async def test_stop_when_idle_is_safe(self, tmp_config_dir):
        _reset_server_state()
        result = await call_tool("stop_session", {})
        assert "stopped" in result[0].text.lower()


class TestPollQuestion:
    @pytest.mark.asyncio
    async def test_poll_no_session(self, tmp_config_dir):
        _reset_server_state()
        result = await call_tool("poll_question", {})
        assert "no active session" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_poll_returns_no_question_on_timeout(self, configured_config, mock_pyaudio, mock_deepgram):
        _reset_server_state()
        await call_tool("start_local_session", {"project_path": "/test"})

        result = await call_tool("poll_question", {"timeout_ms": 100})
        assert result[0].text == "__NO_QUESTION__"

        await call_tool("stop_session", {})

    @pytest.mark.asyncio
    async def test_poll_returns_question(self, configured_config, mock_pyaudio, mock_deepgram):
        _reset_server_state()
        await call_tool("start_local_session", {"project_path": "/test"})

        import src.server as srv
        await srv.voice_pipeline._question_queue.put("what does the auth module do?")

        result = await call_tool("poll_question", {"timeout_ms": 1000})
        assert result[0].text == "what does the auth module do?"

        await call_tool("stop_session", {})

    @pytest.mark.asyncio
    async def test_poll_returns_leave_signal(self, configured_config, mock_pyaudio, mock_deepgram):
        _reset_server_state()
        await call_tool("start_local_session", {"project_path": "/test"})

        import src.server as srv
        await srv.voice_pipeline._question_queue.put("__LEAVE__")

        result = await call_tool("poll_question", {"timeout_ms": 1000})
        assert result[0].text == "__LEAVE__"

        await call_tool("stop_session", {})

    @pytest.mark.asyncio
    async def test_poll_default_timeout(self, configured_config, mock_pyaudio, mock_deepgram):
        _reset_server_state()
        await call_tool("start_local_session", {"project_path": "/test"})

        # Default timeout is 2000ms, use a short one to not slow tests
        result = await call_tool("poll_question", {"timeout_ms": 50})
        assert result[0].text == "__NO_QUESTION__"

        await call_tool("stop_session", {})


class TestProvideAnswer:
    @pytest.mark.asyncio
    async def test_provide_answer_no_session(self, tmp_config_dir):
        _reset_server_state()
        result = await call_tool("provide_answer", {"answer": "test"})
        assert "no active session" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_provide_answer_speaks(self, configured_config, mock_pyaudio, mock_deepgram):
        mock_client, _ = mock_deepgram
        _reset_server_state()
        await call_tool("start_local_session", {"project_path": "/test"})

        # Add a pending question so provide_answer has something to record
        import src.server as srv
        import time
        from src.voice.pipeline import QuestionRecord
        srv.voice_pipeline._questions.append(
            QuestionRecord("what is auth", None, time.time(), None, None)
        )

        result = await call_tool("provide_answer", {"answer": "Auth is in src/auth.py using JWT"})
        assert "spoken" in result[0].text.lower()

        # Verify TTS was called
        mock_client.speak.v1.audio.generate.assert_called()

        await call_tool("stop_session", {})

    @pytest.mark.asyncio
    async def test_provide_answer_records_latency(self, configured_config, mock_pyaudio, mock_deepgram):
        _reset_server_state()
        await call_tool("start_local_session", {"project_path": "/test"})

        # Simulate a question via poll (which now creates the QuestionRecord)
        import src.server as srv
        await srv.voice_pipeline._question_queue.put("what is the db")
        await call_tool("poll_question", {"timeout_ms": 1000})

        # Backdate the asked_at to verify latency calculation
        srv.voice_pipeline._questions[-1].asked_at -= 1.5

        await call_tool("provide_answer", {"answer": "PostgreSQL with SQLAlchemy ORM"})

        record = srv.voice_pipeline._questions[-1]
        assert record.answer == "PostgreSQL with SQLAlchemy ORM"
        assert record.latency_ms is not None
        assert record.latency_ms >= 1400  # At least 1.4 seconds

        await call_tool("stop_session", {})


class TestFullLoop:
    """Integration test: start session → poll → answer → stop."""

    @pytest.mark.asyncio
    async def test_full_local_loop(self, configured_config, mock_pyaudio, mock_deepgram):
        _reset_server_state()

        # Start
        result = await call_tool("start_local_session", {"project_path": "/test"})
        assert "started" in result[0].text.lower()

        # Simulate a voice question arriving
        import src.server as srv
        await srv.voice_pipeline._question_queue.put("how does the API handle auth?")

        # Poll picks it up
        result = await call_tool("poll_question", {"timeout_ms": 1000})
        assert "auth" in result[0].text.lower()

        # Provide answer
        result = await call_tool("provide_answer", {
            "answer": "The API uses JWT tokens in src/auth/middleware.py"
        })
        assert "spoken" in result[0].text.lower()

        # Status shows the answered question
        result = await call_tool("get_status", {})
        assert "1" in result[0].text  # 1 question answered

        # Stop
        result = await call_tool("stop_session", {})
        assert "stopped" in result[0].text.lower()

    @pytest.mark.asyncio
    async def test_leave_command_loop(self, configured_config, mock_pyaudio, mock_deepgram):
        _reset_server_state()

        await call_tool("start_local_session", {"project_path": "/test"})

        import src.server as srv
        await srv.voice_pipeline._question_queue.put("__LEAVE__")

        result = await call_tool("poll_question", {"timeout_ms": 1000})
        assert result[0].text == "__LEAVE__"

        # Skill should call stop_session on __LEAVE__
        result = await call_tool("stop_session", {})
        assert "stopped" in result[0].text.lower()


class TestUnknownTool:
    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, tmp_config_dir):
        result = await call_tool("nonexistent_tool", {})
        assert "unknown" in result[0].text.lower()
