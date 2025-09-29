"""
Tests for configuration error handling and validation.
"""

from shared.config import Config


class TestConfigurationErrorHandling:
    """Test configuration validation and error handling."""

    def test_config_with_none_values(self):
        """Test that optional fields can be None."""
        config = Config(
            llm_api_key="test-key",
            llm_max_input_tokens_per_call=None,  # Should be valid
            llm_max_input_tokens_per_minute=None,  # Should be valid
            output={
                "fade_ms": 3000,
                "min_ad_segement_separation_seconds": 60,
                "min_ad_segment_length_seconds": 14,
                "min_confidence": 0.8,
            },
            processing={
                "num_segments_to_input_to_prompt": 30,
            },
        )

        assert config.llm_max_input_tokens_per_call is None
        assert config.llm_max_input_tokens_per_minute is None

    def test_zero_values(self):
        """Test configuration with zero values where appropriate."""
        # Zero concurrent calls might be problematic in practice but should validate
        config = Config(
            llm_api_key="test-key",
            llm_max_concurrent_calls=0,
            llm_max_retry_attempts=0,
            output={
                "fade_ms": 3000,
                "min_ad_segement_separation_seconds": 60,
                "min_ad_segment_length_seconds": 14,
                "min_confidence": 0.8,
            },
            processing={
                "num_segments_to_input_to_prompt": 30,
            },
        )

        assert config.llm_max_concurrent_calls == 0
        assert config.llm_max_retry_attempts == 0

    def test_very_large_values(self):
        """Test configuration with very large values."""
        config = Config(
            llm_api_key="test-key",
            llm_max_concurrent_calls=999999,
            llm_max_retry_attempts=999999,
            llm_max_input_tokens_per_call=999999999,
            llm_max_input_tokens_per_minute=999999999,
            output={
                "fade_ms": 3000,
                "min_ad_segement_separation_seconds": 60,
                "min_ad_segment_length_seconds": 14,
                "min_confidence": 0.8,
            },
            processing={
                "num_segments_to_input_to_prompt": 30,
            },
        )

        assert config.llm_max_concurrent_calls == 999999
        assert config.llm_max_retry_attempts == 999999
        assert config.llm_max_input_tokens_per_call == 999999999
        assert config.llm_max_input_tokens_per_minute == 999999999

    def test_boolean_field_validation(self):
        """Test boolean field validation."""
        # Test valid boolean values
        config = Config(
            llm_api_key="test-key",
            llm_enable_token_rate_limiting=True,
            output={
                "fade_ms": 3000,
                "min_ad_segement_separation_seconds": 60,
                "min_ad_segment_length_seconds": 14,
                "min_confidence": 0.8,
            },
            processing={
                "system_prompt_path": "config/system_prompt.txt",
                "user_prompt_template_path": "config/user_prompt.jinja",
                "num_segments_to_input_to_prompt": 30,
            },
        )
        assert config.llm_enable_token_rate_limiting is True

        config = Config(
            llm_api_key="test-key",
            llm_enable_token_rate_limiting=False,
            output={
                "fade_ms": 3000,
                "min_ad_segement_separation_seconds": 60,
                "min_ad_segment_length_seconds": 14,
                "min_confidence": 0.8,
            },
            processing={
                "num_segments_to_input_to_prompt": 30,
            },
        )
        assert config.llm_enable_token_rate_limiting is False
