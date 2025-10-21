"""
Shared configuration helpers to avoid code duplication.
"""

from .config import Config, OutputConfig, ProcessingConfig


def create_standard_test_config(
    llm_api_key: str = "test-key",
    llm_max_input_tokens_per_call: int | None = None,
    num_segments_to_input_to_prompt: int = 400,
    max_overlap_segments: int = 6,
) -> Config:
    """
    Create a standardized configuration for testing and demos.

    Args:
        llm_api_key: API key for testing
        llm_max_input_tokens_per_call: Optional token limit
        num_segments_to_input_to_prompt: Number of segments per prompt
        max_overlap_segments: Maximum number of previously identified segments to carry forward

    Returns:
        Configured Config object for testing
    """
    return Config(
        llm_api_key=llm_api_key,
        llm_max_input_tokens_per_call=llm_max_input_tokens_per_call,
        output=OutputConfig(
            fade_ms=2000,
            min_ad_segement_separation_seconds=60,
            min_ad_segment_length_seconds=14,
            min_confidence=0.7,
        ),
        processing=ProcessingConfig(
            num_segments_to_input_to_prompt=num_segments_to_input_to_prompt,
            max_overlap_segments=max_overlap_segments,
        ),
    )
