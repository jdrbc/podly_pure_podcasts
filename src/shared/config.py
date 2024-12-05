from __future__ import annotations

import os
from typing import Dict, Optional

import yaml
from pydantic import BaseModel, Field


class ProcessingConfig(BaseModel):
    system_prompt_path: str
    user_prompt_template_path: str
    num_segments_to_input_to_prompt: int


class OutputConfig(BaseModel):
    fade_ms: int
    min_ad_segement_separation_seconds: int
    min_ad_segment_length_seconds: int
    min_confidence: float


class Config(BaseModel):
    openai_api_key: Optional[str]
    openai_base_url: str = "https://api.openai.com/v1"
    openai_max_tokens: int = 4096
    openai_model: str = "gpt-4o"
    openai_timeout: int = 300
    output: OutputConfig
    podcasts: Optional[Dict[str, str]] = Field(
        default=None,
        deprecated=True,
        description="This field is deprecated and will be removed in a future version",
    )
    processing: ProcessingConfig
    whisper_api_key: Optional[str] = None
    whisper_base_url: Optional[str] = None
    remote_whisper_model: str = "whisper-1"  # openai model, use your own maybe
    whisper_language: str = "en"
    faster_whisper_server: bool = (
        False  # for quirks specific to the faster whisper server
    )
    skip_processing_for_test: bool = False  # for testing
    remote_whisper: bool = False
    server: Optional[str] = None
    server_port: int = 5001
    threads: int = 1
    whisper_model: str = "base"
    automatically_whitelist_new_episodes: bool = True
    number_of_episodes_to_whitelist_from_archive_of_new_feed: int = 1

    def redacted(self) -> Config:
        return self.model_copy(
            update={
                "openai_api_key": "X" * 10,
            },
            deep=True,
        )


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
