from dataclasses import dataclass
from typing import Dict, Optional

from dotenv import dotenv_values


@dataclass
class EnvSettings:
    openai_max_tokens: int
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    openai_timeout: int


def get_or_die(source: Dict[str, Optional[str]], key: str) -> str:
    assert key in source
    value_in_dict = source[key]
    assert value_in_dict is not None
    return value_in_dict


def get_or_default(env: Dict[str, Optional[str]], key: str, default: str) -> str:
    value = env.get(key, default)
    return value or default


def populate_env_settings() -> EnvSettings:
    env = dotenv_values(".env")
    for key in env:
        if key == "OPENAI_API_KEY":
            print(key, "********")
        else:
            print(key, env[key])

    return EnvSettings(
        openai_max_tokens=int(get_or_default(env, "OPENAI_MAX_TOKENS", "4096")),
        openai_api_key=get_or_die(env, "OPENAI_API_KEY"),
        openai_base_url=get_or_default(
            env, "OPENAI_BASE_URL", "https://api.openai.com/v1"
        ),
        openai_model=get_or_default(env, "OPENAI_MODEL", "gpt-4o"),
        openai_timeout=int(get_or_default(env, "OPENAI_TIMEOUT", "300")),
    )
