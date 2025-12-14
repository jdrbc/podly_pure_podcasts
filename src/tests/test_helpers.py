"""
Shared test utilities for rate limiting tests.
"""

from typing import Any

from shared.config import Config


def create_test_config(**overrides: Any) -> Config:
    """Create a test configuration with rate limiting enabled."""
    config_data: dict[str, Any] = {
        "llm_model": "anthropic/claude-3-5-sonnet-20240620",
        "llm_api_key": "test-key",
        "llm_enable_token_rate_limiting": True,
        "llm_max_retry_attempts": 3,
        "llm_max_concurrent_calls": 2,
        "openai_timeout": 300,
        "openai_max_tokens": 4096,
        "output": {
            "fade_ms": 3000,
            "min_ad_segement_separation_seconds": 60,
            "min_ad_segment_length_seconds": 14,
            "min_confidence": 0.8,
        },
        "processing": {
            "num_segments_to_input_to_prompt": 30,
        },
    }
    config_data.update(overrides)
    return Config(**config_data)
