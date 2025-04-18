from podcast_processor.prompt import DEFAULT_SYSTEM_PROMPT_PATH, generate_system_prompt


def test_prompt_expected_output_match() -> None:

    with open(DEFAULT_SYSTEM_PROMPT_PATH, "r") as f:
        system_prompt = f.read()

    assert system_prompt == generate_system_prompt()
