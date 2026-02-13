"""Configuration management for the codebase voice assistant.

Stores user settings in ~/.config/codebase-voice-assistant/config.json.
API keys are stored separately in the OS keychain when available,
falling back to the config file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".config" / "codebase-voice-assistant"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "wake_word": "hey claude",
    "tts_voice": "aura-2-en-US-luna",
    "stt_language": "en-US",
    "stt_model": "nova-2",
    "silence_threshold_ms": 1500,
    "filler_phrases": ["Let me check...", "Looking into that...", "One moment..."],
}

# Keys that should be masked when displayed
SENSITIVE_KEYS = {
    "deepgram_api_key",
    "livekit_api_key",
    "livekit_api_secret",
    "twilio_account_sid",
    "twilio_auth_token",
}


def _ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    _ensure_config_dir()
    if CONFIG_FILE.exists():
        return {**DEFAULTS, **json.loads(CONFIG_FILE.read_text())}
    return {**DEFAULTS}


def save_config(config: dict[str, Any]) -> None:
    _ensure_config_dir()
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def get_config_value(key: str) -> Any:
    config = load_config()
    return config.get(key)


def set_config_value(key: str, value: Any) -> None:
    config = load_config()
    config[key] = value
    save_config(config)


def mask_sensitive(key: str, value: str) -> str:
    if key in SENSITIVE_KEYS and value:
        return f"****{value[-4:]}" if len(value) > 4 else "****"
    return value


def get_display_config() -> dict[str, str]:
    """Return config with sensitive values masked for display."""
    config = load_config()
    return {k: mask_sensitive(k, str(v)) for k, v in config.items()}


def is_configured() -> bool:
    """Check if minimum required configuration is present."""
    config = load_config()
    return bool(config.get("deepgram_api_key"))


def has_telephony_config() -> bool:
    """Check if SIP dial-in configuration is present (LiveKit + Twilio)."""
    config = load_config()
    return all(
        config.get(k)
        for k in ["livekit_url", "livekit_api_key", "livekit_api_secret",
                   "twilio_account_sid", "twilio_auth_token"]
    )
