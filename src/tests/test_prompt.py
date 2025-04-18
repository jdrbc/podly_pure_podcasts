from podcast_processor.prompt import generate_system_prompt


def test_prompt_expected_output_match() -> None:

    with open("config/system_prompt.txt", "r") as f:
        system_prompt = f.read()

    assert system_prompt == generate_system_prompt()
