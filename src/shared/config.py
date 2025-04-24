from __future__ import annotations

import os
from typing import Dict, Literal, Optional

import yaml
from pydantic import BaseModel, Field, model_validator


class ProcessingConfig(BaseModel):
    system_prompt_path: str
    user_prompt_template_path: str
    num_segments_to_input_to_prompt: int


class OutputConfig(BaseModel):
    fade_ms: int
    min_ad_segement_separation_seconds: int
    min_ad_segment_length_seconds: int
    min_confidence: float


WhisperConfigTypes = Literal["remote", "local", "test"]


class TestWhisperConfig(BaseModel):
    whisper_type: Literal["test"] = "test"


class RemoteWhisperConfig(BaseModel):
    whisper_type: Literal["remote", "groq"] = "remote"
    base_url: str = "https://api.openai.com/v1"  # ignored if groq is used
    api_key: str
    language: str = "en"
    model: str = "whisper-1"  # openai model, use your own maybe
    timeout_sec: int = 600
    chunksize_mb: int = 24


class LocalWhisperConfig(BaseModel):
    whisper_type: Literal["local"] = "local"
    model: str = "base"


class Config(BaseModel):
    llm_api_key: Optional[str] = Field(default=None, alias="openai_api_key")
    llm_model: str = Field(default="gpt-4o", alias="openai_model")
    openai_base_url: Optional[str] = None
    openai_max_tokens: int = 4096
    openai_timeout: int = 300
    output: OutputConfig
    podcasts: Optional[Dict[str, str]] = Field(
        default=None,
        deprecated=True,
        description="This field is deprecated and will be removed in a future version",
    )
    processing: ProcessingConfig
    server: Optional[str] = None
    server_port: int = 5001
    background_update_interval_minute: Optional[int] = None
    job_timeout: int = 10800  # Default to 3 hours if not set
    threads: int = 1
    whisper: Optional[LocalWhisperConfig | RemoteWhisperConfig | TestWhisperConfig] = (
        Field(
            default=None,
            discriminator="whisper_type",
        )
    )
    remote_whisper: Optional[bool] = Field(
        default=False,
        deprecated=True,
        description="deprecated in favor of [Remote|Local]WhisperConfig",
    )
    whisper_model: Optional[str] = Field(
        default="base",
        deprecated=True,
        description="deprecated in favor of [Remote|Local]WhisperConfig",
    )
    automatically_whitelist_new_episodes: bool = True
    number_of_episodes_to_whitelist_from_archive_of_new_feed: int = 1

    def redacted(self) -> Config:
        return self.model_copy(
            update={
                "openai_api_key": "X" * 10,
            },
            deep=True,
        )

    @model_validator(mode="after")
    def validate_whisper_config(self) -> "Config":
        new_style = self.whisper is not None

        if new_style:
            self.whisper_model = None
            self.remote_whisper = None
            return self

        # if we have old style, change to the equivalent new style
        if self.remote_whisper:
            assert (
                self.llm_api_key is not None
            ), "must supply api key to use remote whisper"
            self.whisper = RemoteWhisperConfig(
                api_key=self.llm_api_key,
                base_url=self.openai_base_url or "https://api.openai.com/v1",
            )
        else:
            assert (
                self.whisper_model is not None
            ), "must supply whisper model to use local whisper"
            self.whisper = LocalWhisperConfig(model=self.whisper_model)

        self.whisper_model = None
        self.remote_whisper = None

        return self


def get_config(path: str) -> Config:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No config file found at {path}. Please copy from config/config.yml.example"
        )

    with open(path, "r") as f:
        config_str = f.read()

    return get_config_from_str(config_str)


def get_config_from_str(config_str: str) -> Config:
    config_dict = yaml.safe_load(config_str)

    return Config(**config_dict)
