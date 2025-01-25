import os

import pytest

from shared.config import get_config


@pytest.mark.skip
def test_call_model() -> None:
    """for convenient local testing. marked skip for CI"""

    # this import won't work without a valid config.
    from podcast_processor.podcast_processor import (  # pylint: disable=import-outside-toplevel
        PodcastProcessor,
    )

    os.environ["LITELLM_LOG"] = "DEBUG"

    config = get_config("config/config.yml")
    processor = PodcastProcessor(config=config)

    resp = processor.call_model(
        config.llm_model, system_prompt="ANSWER ME", user_prompt="who are you?"
    )
    assert resp == ""
