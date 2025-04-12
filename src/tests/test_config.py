import pytest

from shared.config import (
    Config,
    LocalWhisperConfig,
    OutputConfig,
    ProcessingConfig,
    RemoteWhisperConfig,
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
        openai_base_url=None,
        whisper=LocalWhisperConfig(model="base"),
        remote_whisper=None,
        whisper_model=None,
        automatically_whitelist_new_episodes=True,
        number_of_episodes_to_whitelist_from_archive_of_new_feed=1,
        server=None,
        threads=1,
        server_port=5001,
    )

    assert get_config("config/config.yml.example") == expected_config
    assert get_config("config/config_old.yml.example") == expected_config


def test_remote_whisper_example_config() -> None:
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
        openai_base_url=None,
        whisper=RemoteWhisperConfig(
            model="whisper-2",
            base_url="https://api.openai.com/v1",
            api_key="this_is_fake",
        ),
        automatically_whitelist_new_episodes=True,
        number_of_episodes_to_whitelist_from_archive_of_new_feed=1,
        server=None,
        threads=1,
        server_port=5001,
    )

    assert get_config("config/config_remote_whisper.yml.example") == expected_config


def test_anthropic_example_config() -> None:
    expected_config = Config(
        openai_api_key="sk-proj-XXXXXXXXXXXXXXXXXXXXXXXX",
        openai_base_url=None,
        openai_max_tokens=4096,
        openai_model="anthropic/claude-3-5-sonnet-20240620",
        openai_timeout=300,
        output=OutputConfig(
            fade_ms=3000,
            min_ad_segement_separation_seconds=60,
            min_ad_segment_length_seconds=14,
            min_confidence=0.8,
        ),
        podcasts=None,
        processing=ProcessingConfig(
            system_prompt_path="config/system_prompt.txt",
            user_prompt_template_path="config/user_prompt.jinja",
            num_segments_to_input_to_prompt=30,
        ),
        server=None,
        server_port=5001,
        background_update_interval_minute=None,
        threads=1,
        whisper=RemoteWhisperConfig(
            whisper_type="remote",
            base_url="http://localhost/v99",
            api_key="this_is_fake",
            language="en",
            model="whisper-2",
        ),
        remote_whisper=None,
        whisper_model=None,
        automatically_whitelist_new_episodes=True,
        number_of_episodes_to_whitelist_from_archive_of_new_feed=1,
    )

    assert get_config("config/config_anthropic.yml.example") == expected_config
