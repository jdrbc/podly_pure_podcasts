from typing import Dict, Optional
from pydantic import BaseModel
import os
import yaml


from typing import Optional
from pydantic import BaseModel


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
    output: OutputConfig
    podcasts: Dict[str, str]
    processing: ProcessingConfig
    remote_whisper: bool = False
    whisper_model: str = "base"
    server: Optional[str] = None
    threads: int = 1
    server_port: int = 5001

    def print_redacted(self) -> None:
        # TODO REDACT API KEY FOR LOGABILITY
        print(self)


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
    return Config.model_validate(config_dict)
