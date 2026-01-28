"""
Tests for configuration error handling and validation.
"""

import importlib
from typing import Any

import pytest

from shared.config import Config, OutputConfig, ProcessingConfig

app_module = importlib.import_module("app.__init__")


class TestConfigurationErrorHandling:
    """Test configuration validation and error handling."""

    def test_config_with_none_values(self) -> None:
        """Test that optional fields can be None."""
        config = Config(
            llm_api_key="test-key",
            llm_max_input_tokens_per_call=None,  # Should be valid
            llm_max_input_tokens_per_minute=None,  # Should be valid
            output=OutputConfig(
                fade_ms=3000,
                min_ad_segement_separation_seconds=60,
                min_ad_segment_length_seconds=14,
                min_confidence=0.8,
            ),
            processing=ProcessingConfig(
                num_segments_to_input_to_prompt=30,
            ),
        )

        assert config.llm_max_input_tokens_per_call is None
        assert config.llm_max_input_tokens_per_minute is None

    def test_zero_values(self) -> None:
        """Test configuration with zero values where appropriate."""
        # Zero concurrent calls might be problematic in practice but should validate
        config = Config(
            llm_api_key="test-key",
            llm_max_concurrent_calls=0,
            llm_max_retry_attempts=0,
            output=OutputConfig(
                fade_ms=3000,
                min_ad_segement_separation_seconds=60,
                min_ad_segment_length_seconds=14,
                min_confidence=0.8,
            ),
            processing=ProcessingConfig(
                num_segments_to_input_to_prompt=30,
            ),
        )

        assert config.llm_max_concurrent_calls == 0
        assert config.llm_max_retry_attempts == 0

    def test_very_large_values(self) -> None:
        """Test configuration with very large values."""
        config = Config(
            llm_api_key="test-key",
            llm_max_concurrent_calls=999999,
            llm_max_retry_attempts=999999,
            llm_max_input_tokens_per_call=999999999,
            llm_max_input_tokens_per_minute=999999999,
            output=OutputConfig(
                fade_ms=3000,
                min_ad_segement_separation_seconds=60,
                min_ad_segment_length_seconds=14,
                min_confidence=0.8,
            ),
            processing=ProcessingConfig(
                num_segments_to_input_to_prompt=30,
            ),
        )

        assert config.llm_max_concurrent_calls == 999999
        assert config.llm_max_retry_attempts == 999999
        assert config.llm_max_input_tokens_per_call == 999999999
        assert config.llm_max_input_tokens_per_minute == 999999999

    def test_boolean_field_validation(self) -> None:
        """Test boolean field validation."""
        # Test valid boolean values
        config = Config(
            llm_api_key="test-key",
            llm_enable_token_rate_limiting=True,
            output=OutputConfig(
                fade_ms=3000,
                min_ad_segement_separation_seconds=60,
                min_ad_segment_length_seconds=14,
                min_confidence=0.8,
            ),
            processing=ProcessingConfig(
                num_segments_to_input_to_prompt=30,
            ),
        )
        assert config.llm_enable_token_rate_limiting is True

        config = Config(
            llm_api_key="test-key",
            llm_enable_token_rate_limiting=False,
            output=OutputConfig(
                fade_ms=3000,
                min_ad_segement_separation_seconds=60,
                min_ad_segment_length_seconds=14,
                min_confidence=0.8,
            ),
            processing=ProcessingConfig(
                num_segments_to_input_to_prompt=30,
            ),
        )
        assert config.llm_enable_token_rate_limiting is False


class TestEnvKeyValidation:
    """Tests for environment-based API key validation."""

    def test_llm_and_groq_conflict_raises(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("LLM_API_KEY", "llm-value")
        monkeypatch.setenv("GROQ_API_KEY", "groq-value")
        monkeypatch.setenv("LLM_MODEL", "groq/openai/gpt-oss-120b")
        monkeypatch.delenv("WHISPER_REMOTE_API_KEY", raising=False)

        with pytest.raises(SystemExit):
            app_module._validate_env_key_conflicts()

    def test_non_groq_llm_allows_different_groq_key(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("LLM_API_KEY", "llm-value")
        monkeypatch.setenv("GROQ_API_KEY", "groq-value")
        monkeypatch.setenv("LLM_MODEL", "google/gemini-1.5-pro")
        monkeypatch.delenv("WHISPER_REMOTE_API_KEY", raising=False)

        app_module._validate_env_key_conflicts()

    def test_whisper_remote_allows_different_key(self, monkeypatch: Any) -> None:
        monkeypatch.setenv("LLM_API_KEY", "llm-value")
        monkeypatch.setenv("WHISPER_REMOTE_API_KEY", "remote-value")
        monkeypatch.delenv("GROQ_API_KEY", raising=False)

        app_module._validate_env_key_conflicts()
