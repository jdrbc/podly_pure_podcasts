from dataclasses import dataclass
from typing import Dict, Optional

from dotenv import dotenv_values


@dataclass
class EnvSettings:
    OpenAIMaxTokens: int
    OpenAIAPIKey: str
    OpenAIBaseURL: str
    OpenAIModel: str
    RemoteWhisper: bool
    WhisperModel: str
    OpenAITimeout: int


def get_or_die(source: Dict[str, Optional[str]], key: str) -> str:
    assert key in source
    value_in_dict = source[key]
    assert value_in_dict is not None
    return value_in_dict


def get_or_default(env: Dict[str, Optional[str]], key: str, default: str):
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
        OpenAIMaxTokens=int(get_or_default(env, "OPENAI_MAX_TOKENS", "4096")),
        OpenAIAPIKey=get_or_die(env, "OPENAI_API_KEY"),
        OpenAIBaseURL=get_or_default(
            env, "OPENAI_BASE_URL", "https://api.openai.com/v1"
        ),
        OpenAIModel=get_or_default(env, "OPENAI_MODEL", "gpt-4o"),
        RemoteWhisper=True if env.get("REMOTE_WHISPER", None) is not None else False,
        WhisperModel=get_or_default(env, "WHISPER_MODEL", "base"),
        OpenAITimeout=int(get_or_default(env, "OPENAI_TIMEOUT", "300")),
    )
