"""Tests for configuration management."""

from __future__ import annotations

import json

import pytest

from src.config import (
    DEFAULTS,
    SENSITIVE_KEYS,
    get_config_value,
    get_display_config,
    has_telephony_config,
    is_configured,
    load_config,
    mask_sensitive,
    save_config,
    set_config_value,
)


class TestLoadConfig:
    def test_returns_defaults_when_no_file(self, tmp_config_dir):
        config = load_config()
        assert config["wake_word"] == "hey claude"
        assert config["tts_voice"] == "aura-2-en-US-luna"
        assert config["stt_language"] == "en-US"

    def test_loads_existing_config(self, tmp_config_dir):
        _, config_file = tmp_config_dir
        config_file.write_text(json.dumps({"deepgram_api_key": "test_key"}))

        config = load_config()
        assert config["deepgram_api_key"] == "test_key"
        # Defaults should still be present
        assert config["wake_word"] == "hey claude"

    def test_user_values_override_defaults(self, tmp_config_dir):
        _, config_file = tmp_config_dir
        config_file.write_text(json.dumps({"wake_word": "yo claude"}))

        config = load_config()
        assert config["wake_word"] == "yo claude"

    def test_creates_config_dir_if_missing(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "nonexistent" / "config"
        monkeypatch.setattr("src.config.CONFIG_DIR", config_dir)
        monkeypatch.setattr("src.config.CONFIG_FILE", config_dir / "config.json")

        config = load_config()
        assert config_dir.exists()
        assert config == DEFAULTS


class TestSaveConfig:
    def test_saves_and_loads(self, tmp_config_dir):
        _, config_file = tmp_config_dir
        save_config({"deepgram_api_key": "saved_key", "wake_word": "hi claude"})

        raw = json.loads(config_file.read_text())
        assert raw["deepgram_api_key"] == "saved_key"
        assert raw["wake_word"] == "hi claude"

    def test_set_config_value(self, tmp_config_dir):
        set_config_value("deepgram_api_key", "new_key")
        assert get_config_value("deepgram_api_key") == "new_key"

    def test_set_preserves_existing(self, tmp_config_dir):
        set_config_value("deepgram_api_key", "key1")
        set_config_value("wake_word", "yo claude")

        assert get_config_value("deepgram_api_key") == "key1"
        assert get_config_value("wake_word") == "yo claude"


class TestMaskSensitive:
    def test_masks_api_keys(self):
        assert mask_sensitive("deepgram_api_key", "dg_test_key_1234567890") == "****7890"

    def test_masks_short_values(self):
        assert mask_sensitive("twilio_auth_token", "abc") == "****"

    def test_does_not_mask_non_sensitive(self):
        assert mask_sensitive("wake_word", "hey claude") == "hey claude"

    def test_masks_all_sensitive_keys(self):
        for key in SENSITIVE_KEYS:
            result = mask_sensitive(key, "some_secret_value")
            assert result.startswith("****")

    def test_handles_empty_value(self):
        assert mask_sensitive("deepgram_api_key", "") == ""


class TestDisplayConfig:
    def test_masks_sensitive_values(self, configured_config):
        display = get_display_config()
        assert display["deepgram_api_key"] == "****7890"
        assert display["twilio_account_sid"] == "****2345"
        assert display["wake_word"] == "hey claude"  # Not masked


class TestIsConfigured:
    def test_not_configured_by_default(self, tmp_config_dir):
        assert is_configured() is False

    def test_configured_with_deepgram_key(self, tmp_config_dir):
        set_config_value("deepgram_api_key", "test_key")
        assert is_configured() is True


class TestHasTelephonyConfig:
    def test_not_configured_by_default(self, tmp_config_dir):
        assert has_telephony_config() is False

    def test_partial_config_is_not_enough(self, tmp_config_dir):
        set_config_value("livekit_url", "wss://test")
        set_config_value("livekit_api_key", "key")
        assert has_telephony_config() is False

    def test_fully_configured(self, configured_config):
        assert has_telephony_config() is True
