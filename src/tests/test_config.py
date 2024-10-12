from config import Config, get_config, ProcessingConfig, OutputConfig


def test_example_config():
    # this way if we add some new fields to the config we'll be forced to also
    # update the example.

    expected_config = Config(
        openai_api_key="sk-proj-XXXXXXXXXXXXXXXXXXXXXXXX",
        processing=ProcessingConfig(
            system_prompt_path="config/system_prompt.txt",
            user_prompt_template_path="config/user_prompt.jinja",
            num_segments_to_input_to_prompt=30,
        ),
        podcasts={
            "my_podcast.rss": "https://www.example.com/original/podcast/rss/feed.rss"
        },
        output=OutputConfig(
            fade_ms=3000,
            min_ad_segement_separation_seconds=60,
            min_ad_segment_length_seconds=14,
            min_confidence=0.8,
        ),
    )
    assert get_config("config/config.yml.example") == expected_config
