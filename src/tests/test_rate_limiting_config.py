"""
Tests for new rate limiting configuration options.
"""

from shared.config import Config


class TestRateLimitingConfig:
    """Test cases for rate limiting configuration."""

    def test_default_rate_limiting_config(self):
        """Test that rate limiting defaults are properly set."""
        config_data = {
            "llm_api_key": "test-key",
            "output": {
                "fade_ms": 3000,
                "min_ad_segement_separation_seconds": 60,
                "min_ad_segment_length_seconds": 14,
                "min_confidence": 0.8,
            },
            "processing": {
                "system_prompt_path": "config/system_prompt.txt",
                "user_prompt_template_path": "config/user_prompt.jinja",
                "num_segments_to_input_to_prompt": 30,
            },
        }

        config = Config(**config_data)

        # Test default values
        assert config.llm_max_concurrent_calls == 3
        assert config.llm_max_retry_attempts == 5
        assert config.llm_max_input_tokens_per_call is None
        assert config.llm_enable_token_rate_limiting is True
        assert config.llm_max_input_tokens_per_minute is None

    def test_custom_rate_limiting_config(self):
        """Test that custom rate limiting values are properly set."""
        config_data = {
            "llm_api_key": "test-key",
            "llm_max_concurrent_calls": 5,
            "llm_max_retry_attempts": 10,
            "llm_max_input_tokens_per_call": 50000,
            "llm_enable_token_rate_limiting": False,
            "llm_max_input_tokens_per_minute": 100000,
            "output": {
                "fade_ms": 3000,
                "min_ad_segement_separation_seconds": 60,
                "min_ad_segment_length_seconds": 14,
                "min_confidence": 0.8,
            },
            "processing": {
                "system_prompt_path": "config/system_prompt.txt",
                "user_prompt_template_path": "config/user_prompt.jinja",
                "num_segments_to_input_to_prompt": 30,
            },
        }

        config = Config(**config_data)

        # Test custom values
        assert config.llm_max_concurrent_calls == 5
        assert config.llm_max_retry_attempts == 10
        assert config.llm_max_input_tokens_per_call == 50000
        assert config.llm_enable_token_rate_limiting is False
        assert config.llm_max_input_tokens_per_minute == 100000

    def test_partial_rate_limiting_config(self):
        """Test that partial rate limiting config uses defaults for missing values."""
        config_data = {
            "llm_api_key": "test-key",
            "llm_max_retry_attempts": 7,  # Only override this one
            "output": {
                "fade_ms": 3000,
                "min_ad_segement_separation_seconds": 60,
                "min_ad_segment_length_seconds": 14,
                "min_confidence": 0.8,
            },
            "processing": {
                "system_prompt_path": "config/system_prompt.txt",
                "user_prompt_template_path": "config/user_prompt.jinja",
                "num_segments_to_input_to_prompt": 30,
            },
        }

        config = Config(**config_data)

        # Test that custom value is set
        assert config.llm_max_retry_attempts == 7

        # Test that defaults are used for other values
        assert config.llm_max_concurrent_calls == 3
        assert config.llm_max_input_tokens_per_call is None
        assert config.llm_enable_token_rate_limiting is True
        assert config.llm_max_input_tokens_per_minute is None

    def test_config_field_descriptions(self):
        """Test that config fields have proper descriptions."""
        # Test that the field definitions include helpful descriptions
        config_fields = Config.model_fields

        assert "llm_max_concurrent_calls" in config_fields
        assert (
            "Maximum concurrent LLM calls"
            in config_fields["llm_max_concurrent_calls"].description
        )

        assert "llm_max_retry_attempts" in config_fields
        assert (
            "Maximum retry attempts"
            in config_fields["llm_max_retry_attempts"].description
        )

        assert "llm_enable_token_rate_limiting" in config_fields
        assert (
            "client-side token-based rate limiting"
            in config_fields["llm_enable_token_rate_limiting"].description
        )
