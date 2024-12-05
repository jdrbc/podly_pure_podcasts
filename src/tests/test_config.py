import pytest

from shared.config import (
    Config,
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
        openai_api_key="sk-proj-XXXXXXXXXXXXXXXXXXXXXXXX",
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
        openai_base_url="https://api.openai.com/v1",
        remote_whisper=False,
        whisper_model="base",
        automatically_whitelist_new_episodes=True,
        number_of_episodes_to_whitelist_from_archive_of_new_feed=1,
        server=None,
        threads=1,
        server_port=5001,
    )
    assert get_config("config/config.yml.example") == expected_config
