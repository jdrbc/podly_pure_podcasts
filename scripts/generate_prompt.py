#!/usr/bin/env python3


from podcast_processor.prompt import DEFAULT_SYSTEM_PROMPT_PATH, generate_system_prompt


def main() -> None:
    system_prompt = generate_system_prompt()
    with open(DEFAULT_SYSTEM_PROMPT_PATH, "w") as f:
        f.write(system_prompt)


if __name__ == "__main__":
    main()
