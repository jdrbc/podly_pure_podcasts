"""
Runtime configuration module - isolated to prevent circular imports.
Initializes the global config object that is used throughout the application.
"""

import os
import sys

from shared import defaults as DEFAULTS
from shared.config import Config as RuntimeConfig
from shared.config import LocalWhisperConfig, OutputConfig, ProcessingConfig

is_test = "pytest" in sys.modules

# For tests, use in-memory config for deterministic behavior. For runtime,
# initialize with sensible defaults; DB-backed settings will hydrate immediately after migrations.
if is_test:
    from shared.test_utils import create_standard_test_config

    config = create_standard_test_config()
else:
    config = RuntimeConfig(
        llm_api_key=None,
        llm_model=DEFAULTS.LLM_DEFAULT_MODEL,
        openai_base_url=None,
        openai_max_tokens=DEFAULTS.OPENAI_DEFAULT_MAX_TOKENS,
        openai_timeout=DEFAULTS.OPENAI_DEFAULT_TIMEOUT_SEC,
        output=OutputConfig(
            fade_ms=DEFAULTS.OUTPUT_FADE_MS,
            min_ad_segement_separation_seconds=DEFAULTS.OUTPUT_MIN_AD_SEGMENT_SEPARATION_SECONDS,
            min_ad_segment_length_seconds=DEFAULTS.OUTPUT_MIN_AD_SEGMENT_LENGTH_SECONDS,
            min_confidence=DEFAULTS.OUTPUT_MIN_CONFIDENCE,
        ),
        processing=ProcessingConfig(
            num_segments_to_input_to_prompt=DEFAULTS.PROCESSING_NUM_SEGMENTS_TO_INPUT_TO_PROMPT,
            max_overlap_segments=DEFAULTS.PROCESSING_MAX_OVERLAP_SEGMENTS,
        ),
        background_update_interval_minute=DEFAULTS.APP_BACKGROUND_UPDATE_INTERVAL_MINUTE,
        post_cleanup_retention_days=DEFAULTS.APP_POST_CLEANUP_RETENTION_DAYS,
        llm_max_concurrent_calls=DEFAULTS.LLM_DEFAULT_MAX_CONCURRENT_CALLS,
        llm_max_retry_attempts=DEFAULTS.LLM_DEFAULT_MAX_RETRY_ATTEMPTS,
        llm_enable_token_rate_limiting=DEFAULTS.LLM_ENABLE_TOKEN_RATE_LIMITING,
        llm_max_input_tokens_per_call=DEFAULTS.LLM_MAX_INPUT_TOKENS_PER_CALL,
        llm_max_input_tokens_per_minute=DEFAULTS.LLM_MAX_INPUT_TOKENS_PER_MINUTE,
        automatically_whitelist_new_episodes=DEFAULTS.APP_AUTOMATICALLY_WHITELIST_NEW_EPISODES,
        number_of_episodes_to_whitelist_from_archive_of_new_feed=DEFAULTS.APP_NUM_EPISODES_TO_WHITELIST_FROM_ARCHIVE_OF_NEW_FEED,
        whisper=LocalWhisperConfig(model=DEFAULTS.WHISPER_LOCAL_MODEL),
        enable_public_landing_page=DEFAULTS.APP_ENABLE_PUBLIC_LANDING_PAGE,
        developer_mode=os.environ.get("DEVELOPER_MODE", "false").lower() == "true",
    )
