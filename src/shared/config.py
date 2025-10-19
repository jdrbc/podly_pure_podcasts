from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from shared import defaults as DEFAULTS


class ProcessingConfig(BaseModel):
    num_segments_to_input_to_prompt: int


class OutputConfig(BaseModel):
    fade_ms: int
    min_ad_segement_separation_seconds: int
    min_ad_segment_length_seconds: int
    min_confidence: float


WhisperConfigTypes = Literal["remote", "local", "test", "groq"]


class TestWhisperConfig(BaseModel):
    whisper_type: Literal["test"] = "test"


class RemoteWhisperConfig(BaseModel):
    whisper_type: Literal["remote"] = "remote"
    base_url: str = DEFAULTS.WHISPER_REMOTE_BASE_URL
    api_key: str
    language: str = DEFAULTS.WHISPER_REMOTE_LANGUAGE
    model: str = DEFAULTS.WHISPER_REMOTE_MODEL
    timeout_sec: int = DEFAULTS.WHISPER_REMOTE_TIMEOUT_SEC
    chunksize_mb: int = DEFAULTS.WHISPER_REMOTE_CHUNKSIZE_MB


class GroqWhisperConfig(BaseModel):
    whisper_type: Literal["groq"] = "groq"
    api_key: str
    language: str = DEFAULTS.WHISPER_GROQ_LANGUAGE
    model: str = DEFAULTS.WHISPER_GROQ_MODEL
    max_retries: int = DEFAULTS.WHISPER_GROQ_MAX_RETRIES


class LocalWhisperConfig(BaseModel):
    whisper_type: Literal["local"] = "local"
    model: str = DEFAULTS.WHISPER_LOCAL_MODEL


class Config(BaseModel):
    llm_api_key: Optional[str] = Field(default=None)
    llm_model: str = Field(default=DEFAULTS.LLM_DEFAULT_MODEL)
    openai_base_url: Optional[str] = None
    openai_max_tokens: int = DEFAULTS.OPENAI_DEFAULT_MAX_TOKENS
    openai_timeout: int = DEFAULTS.OPENAI_DEFAULT_TIMEOUT_SEC
    # Optional: Rate limiting controls
    llm_max_concurrent_calls: int = Field(
        default=DEFAULTS.LLM_DEFAULT_MAX_CONCURRENT_CALLS,
        description="Maximum concurrent LLM calls to prevent rate limiting",
    )
    llm_max_retry_attempts: int = Field(
        default=DEFAULTS.LLM_DEFAULT_MAX_RETRY_ATTEMPTS,
        description="Maximum retry attempts for failed LLM calls",
    )
    llm_max_input_tokens_per_call: Optional[int] = Field(
        default=DEFAULTS.LLM_MAX_INPUT_TOKENS_PER_CALL,
        description="Maximum input tokens per LLM call to stay under API limits",
    )
    # Token-based rate limiting
    llm_enable_token_rate_limiting: bool = Field(
        default=DEFAULTS.LLM_ENABLE_TOKEN_RATE_LIMITING,
        description="Enable client-side token-based rate limiting",
    )
    llm_max_input_tokens_per_minute: Optional[int] = Field(
        default=DEFAULTS.LLM_MAX_INPUT_TOKENS_PER_MINUTE,
        description="Override default tokens per minute limit for the model",
    )
    output: OutputConfig
    processing: ProcessingConfig
    server: Optional[str] = Field(
        default=None,
        deprecated=True,
        description="deprecated in favor of request-aware URL generation",
    )
    background_update_interval_minute: Optional[int] = (
        DEFAULTS.APP_BACKGROUND_UPDATE_INTERVAL_MINUTE
    )
    # removed job_timeout
    whisper: Optional[
        LocalWhisperConfig | RemoteWhisperConfig | TestWhisperConfig | GroqWhisperConfig
    ] = Field(
        default=None,
        discriminator="whisper_type",
    )
    remote_whisper: Optional[bool] = Field(
        default=False,
        deprecated=True,
        description="deprecated in favor of [Remote|Local]WhisperConfig",
    )
    whisper_model: Optional[str] = Field(
        default=DEFAULTS.WHISPER_LOCAL_MODEL,
        deprecated=True,
        description="deprecated in favor of [Remote|Local]WhisperConfig",
    )
    automatically_whitelist_new_episodes: bool = (
        DEFAULTS.APP_AUTOMATICALLY_WHITELIST_NEW_EPISODES
    )
    number_of_episodes_to_whitelist_from_archive_of_new_feed: int = (
        DEFAULTS.APP_NUM_EPISODES_TO_WHITELIST_FROM_ARCHIVE_OF_NEW_FEED
    )

    def redacted(self) -> Config:
        return self.model_copy(
            update={
                "llm_api_key": "X" * 10,
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
