import pytest

from shared.config import (
    Config,
    LocalWhisperConfig,
    OutputConfig,
    ProcessingConfig,
    get_config,
    get_config_from_str,
)


def test_broken_config() -> None:
    # config is invalid because missing some required fields
    invalid_config = """
openai_api_key: asdfasdf
    """

    with pytest.raises(ValueError):
        get_config_from_str(invalid_config)


def test_example_config() -> None:
    # this way if we add some new fields to the config we'll be forced to also
    # update the example.

    expected_config = Config(
        llm_api_key="sk-proj-XXXXXXXXXXXXXXXXXXXXXXXX",
        processing=ProcessingConfig(
            system_prompt_path="config/system_prompt.txt",
            user_prompt_template_path="config/user_prompt.jinja",
            num_segments_to_input_to_prompt=30,
        ),
        podcasts=None,
        output=OutputConfig(
            fade_ms=3000,
            min_ad_segement_separation_seconds=60,
            min_ad_segment_length_seconds=14,
            min_confidence=0.8,
        ),
        openai_base_url=None,
        whisper=LocalWhisperConfig(model="base"),
        remote_whisper=None,
        whisper_model=None,
        automatically_whitelist_new_episodes=True,
        number_of_episodes_to_whitelist_from_archive_of_new_feed=1,
        host="0.0.0.0",
        port=5001,
        server=None,
        threads=1,
    )

    assert get_config("config/config.yml.example") == expected_config


def test_backwards_compatibility_openai_to_llm() -> None:
    """Test that older configs using openai_api_key and openai_model are translated correctly."""
    old_config = """
openai_api_key: sk-old-api-key-123456
openai_model: gpt-3.5-turbo
processing:
  system_prompt_path: config/system_prompt.txt
  user_prompt_template_path: config/user_prompt.jinja
  num_segments_to_input_to_prompt: 30
output:
  fade_ms: 3000
  min_ad_segement_separation_seconds: 60
  min_ad_segment_length_seconds: 14
  min_confidence: 0.8
whisper_model: base
"""

    config = get_config_from_str(old_config)

    # Check that old OpenAI values were translated to the new LLM values
    assert config.llm_api_key == "sk-old-api-key-123456"
    assert config.llm_model == "gpt-3.5-turbo"
    assert isinstance(config.whisper, LocalWhisperConfig)
    assert config.whisper.model == "base"
