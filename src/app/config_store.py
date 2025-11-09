from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

from app.background import add_background_job, schedule_cleanup_job
from app.extensions import db, scheduler
from app.models import (
    AppSettings,
    LLMSettings,
    OutputSettings,
    ProcessingSettings,
    WhisperSettings,
)
from app.runtime_config import config as runtime_config
from shared import defaults as DEFAULTS
from shared.config import Config as PydanticConfig
from shared.config import (
    GroqWhisperConfig,
    LocalWhisperConfig,
    RemoteWhisperConfig,
    TestWhisperConfig,
)

logger = logging.getLogger("global_logger")


def _is_empty(value: Any) -> bool:
    return value is None or value == ""


def _parse_int(val: Any) -> Optional[int]:
    try:
        return int(val) if val is not None else None
    except Exception:
        return None


def _parse_bool(val: Any) -> Optional[bool]:
    if val is None:
        return None
    s = str(val).strip().lower()
    if s in {"1", "true", "yes", "on"}:
        return True
    if s in {"0", "false", "no", "off"}:
        return False
    return None


def _set_if_empty(obj: Any, attr: str, new_val: Any) -> bool:
    if _is_empty(new_val):
        return False
    if _is_empty(getattr(obj, attr)):
        setattr(obj, attr, new_val)
        return True
    return False


def _set_if_default(obj: Any, attr: str, new_val: Any, default_val: Any) -> bool:
    if new_val is None:
        return False
    if getattr(obj, attr) == default_val:
        setattr(obj, attr, new_val)
        return True
    return False


def _ensure_row(model: type, defaults: Dict[str, Any]) -> Any:
    row = db.session.get(model, 1)
    if row is None:
        row = model(id=1, **defaults)
        db.session.add(row)
        db.session.commit()
    return row


def ensure_defaults() -> None:
    _ensure_row(
        LLMSettings,
        {
            "llm_model": DEFAULTS.LLM_DEFAULT_MODEL,
            "openai_timeout": DEFAULTS.OPENAI_DEFAULT_TIMEOUT_SEC,
            "openai_max_tokens": DEFAULTS.OPENAI_DEFAULT_MAX_TOKENS,
            "llm_max_concurrent_calls": DEFAULTS.LLM_DEFAULT_MAX_CONCURRENT_CALLS,
            "llm_max_retry_attempts": DEFAULTS.LLM_DEFAULT_MAX_RETRY_ATTEMPTS,
            "llm_enable_token_rate_limiting": DEFAULTS.LLM_ENABLE_TOKEN_RATE_LIMITING,
        },
    )

    _ensure_row(
        WhisperSettings,
        {
            "whisper_type": DEFAULTS.WHISPER_DEFAULT_TYPE,
            "local_model": DEFAULTS.WHISPER_LOCAL_MODEL,
            "remote_model": DEFAULTS.WHISPER_REMOTE_MODEL,
            "remote_base_url": DEFAULTS.WHISPER_REMOTE_BASE_URL,
            "remote_language": DEFAULTS.WHISPER_REMOTE_LANGUAGE,
            "remote_timeout_sec": DEFAULTS.WHISPER_REMOTE_TIMEOUT_SEC,
            "remote_chunksize_mb": DEFAULTS.WHISPER_REMOTE_CHUNKSIZE_MB,
            "groq_model": DEFAULTS.WHISPER_GROQ_MODEL,
            "groq_language": DEFAULTS.WHISPER_GROQ_LANGUAGE,
            "groq_max_retries": DEFAULTS.WHISPER_GROQ_MAX_RETRIES,
        },
    )

    _ensure_row(
        ProcessingSettings,
        {
            "num_segments_to_input_to_prompt": DEFAULTS.PROCESSING_NUM_SEGMENTS_TO_INPUT_TO_PROMPT,
        },
    )

    _ensure_row(
        OutputSettings,
        {
            "fade_ms": DEFAULTS.OUTPUT_FADE_MS,
            "min_ad_segement_separation_seconds": DEFAULTS.OUTPUT_MIN_AD_SEGMENT_SEPARATION_SECONDS,
            "min_ad_segment_length_seconds": DEFAULTS.OUTPUT_MIN_AD_SEGMENT_LENGTH_SECONDS,
            "min_confidence": DEFAULTS.OUTPUT_MIN_CONFIDENCE,
        },
    )

    _ensure_row(
        AppSettings,
        {
            "background_update_interval_minute": DEFAULTS.APP_BACKGROUND_UPDATE_INTERVAL_MINUTE,
            "automatically_whitelist_new_episodes": DEFAULTS.APP_AUTOMATICALLY_WHITELIST_NEW_EPISODES,
            "post_cleanup_retention_days": DEFAULTS.APP_POST_CLEANUP_RETENTION_DAYS,
            "number_of_episodes_to_whitelist_from_archive_of_new_feed": DEFAULTS.APP_NUM_EPISODES_TO_WHITELIST_FROM_ARCHIVE_OF_NEW_FEED,
        },
    )


def _apply_llm_env_overrides_to_db(llm: Any) -> bool:
    """Apply LLM-related environment variable overrides to database settings.

    Returns True if any settings were changed.
    """
    changed = False

    env_llm_key = (
        os.environ.get("LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("GROQ_API_KEY")
    )
    changed = _set_if_empty(llm, "llm_api_key", env_llm_key) or changed

    env_llm_model = os.environ.get("LLM_MODEL")
    changed = (
        _set_if_default(llm, "llm_model", env_llm_model, DEFAULTS.LLM_DEFAULT_MODEL)
        or changed
    )

    env_openai_base_url = os.environ.get("OPENAI_BASE_URL")
    changed = _set_if_empty(llm, "openai_base_url", env_openai_base_url) or changed

    env_openai_timeout = _parse_int(os.environ.get("OPENAI_TIMEOUT"))
    changed = (
        _set_if_default(
            llm,
            "openai_timeout",
            env_openai_timeout,
            DEFAULTS.OPENAI_DEFAULT_TIMEOUT_SEC,
        )
        or changed
    )

    env_openai_max_tokens = _parse_int(os.environ.get("OPENAI_MAX_TOKENS"))
    changed = (
        _set_if_default(
            llm,
            "openai_max_tokens",
            env_openai_max_tokens,
            DEFAULTS.OPENAI_DEFAULT_MAX_TOKENS,
        )
        or changed
    )

    env_llm_max_concurrent = _parse_int(os.environ.get("LLM_MAX_CONCURRENT_CALLS"))
    changed = (
        _set_if_default(
            llm,
            "llm_max_concurrent_calls",
            env_llm_max_concurrent,
            DEFAULTS.LLM_DEFAULT_MAX_CONCURRENT_CALLS,
        )
        or changed
    )

    env_llm_max_retries = _parse_int(os.environ.get("LLM_MAX_RETRY_ATTEMPTS"))
    changed = (
        _set_if_default(
            llm,
            "llm_max_retry_attempts",
            env_llm_max_retries,
            DEFAULTS.LLM_DEFAULT_MAX_RETRY_ATTEMPTS,
        )
        or changed
    )

    env_llm_enable_token_rl = _parse_bool(
        os.environ.get("LLM_ENABLE_TOKEN_RATE_LIMITING")
    )
    if (
        llm.llm_enable_token_rate_limiting == DEFAULTS.LLM_ENABLE_TOKEN_RATE_LIMITING
        and env_llm_enable_token_rl is not None
    ):
        llm.llm_enable_token_rate_limiting = bool(env_llm_enable_token_rl)
        changed = True

    env_llm_max_input_tokens_per_call = _parse_int(
        os.environ.get("LLM_MAX_INPUT_TOKENS_PER_CALL")
    )
    if (
        llm.llm_max_input_tokens_per_call is None
        and env_llm_max_input_tokens_per_call is not None
    ):
        llm.llm_max_input_tokens_per_call = env_llm_max_input_tokens_per_call
        changed = True

    env_llm_max_input_tokens_per_minute = _parse_int(
        os.environ.get("LLM_MAX_INPUT_TOKENS_PER_MINUTE")
    )
    if (
        llm.llm_max_input_tokens_per_minute is None
        and env_llm_max_input_tokens_per_minute is not None
    ):
        llm.llm_max_input_tokens_per_minute = env_llm_max_input_tokens_per_minute
        changed = True

    return changed


def _apply_whisper_env_overrides_to_db(whisper: Any) -> bool:
    """Apply Whisper-related environment variable overrides to database settings.

    Returns True if any settings were changed.
    """
    changed = False

    # Respect explicit whisper type env if still default
    env_whisper_type = os.environ.get("WHISPER_TYPE")
    if env_whisper_type and isinstance(env_whisper_type, str):
        env_whisper_type_norm = env_whisper_type.strip().lower()
        if env_whisper_type_norm in {"local", "remote", "groq"}:
            changed = (
                _set_if_default(
                    whisper,
                    "whisper_type",
                    env_whisper_type_norm,
                    DEFAULTS.WHISPER_DEFAULT_TYPE,
                )
                or changed
            )

    # If GROQ_API_KEY is provided, seed both LLM key and Groq whisper key if empty
    groq_key = os.environ.get("GROQ_API_KEY")
    changed = _set_if_empty(whisper, "groq_api_key", groq_key) or changed

    if whisper.whisper_type == "remote":
        remote_key = os.environ.get("WHISPER_REMOTE_API_KEY") or os.environ.get(
            "OPENAI_API_KEY"
        )
        changed = _set_if_empty(whisper, "remote_api_key", remote_key) or changed

        remote_base = os.environ.get("WHISPER_REMOTE_BASE_URL") or os.environ.get(
            "OPENAI_BASE_URL"
        )
        changed = (
            _set_if_default(
                whisper,
                "remote_base_url",
                remote_base,
                DEFAULTS.WHISPER_REMOTE_BASE_URL,
            )
            or changed
        )

        remote_model = os.environ.get("WHISPER_REMOTE_MODEL")
        changed = (
            _set_if_default(
                whisper, "remote_model", remote_model, DEFAULTS.WHISPER_REMOTE_MODEL
            )
            or changed
        )

        remote_timeout = _parse_int(os.environ.get("WHISPER_REMOTE_TIMEOUT_SEC"))
        changed = (
            _set_if_default(
                whisper,
                "remote_timeout_sec",
                remote_timeout,
                DEFAULTS.WHISPER_REMOTE_TIMEOUT_SEC,
            )
            or changed
        )

        remote_chunksize = _parse_int(os.environ.get("WHISPER_REMOTE_CHUNKSIZE_MB"))
        changed = (
            _set_if_default(
                whisper,
                "remote_chunksize_mb",
                remote_chunksize,
                DEFAULTS.WHISPER_REMOTE_CHUNKSIZE_MB,
            )
            or changed
        )

    elif whisper.whisper_type == "groq":
        groq_model_env = os.environ.get("GROQ_WHISPER_MODEL") or os.environ.get(
            "WHISPER_GROQ_MODEL"
        )
        changed = (
            _set_if_default(
                whisper, "groq_model", groq_model_env, DEFAULTS.WHISPER_GROQ_MODEL
            )
            or changed
        )

        groq_max_retries_env = _parse_int(os.environ.get("GROQ_MAX_RETRIES"))
        changed = (
            _set_if_default(
                whisper,
                "groq_max_retries",
                groq_max_retries_env,
                DEFAULTS.WHISPER_GROQ_MAX_RETRIES,
            )
            or changed
        )

    elif whisper.whisper_type == "local":
        local_model_env = os.environ.get("WHISPER_LOCAL_MODEL")
        changed = (
            _set_if_default(
                whisper, "local_model", local_model_env, DEFAULTS.WHISPER_LOCAL_MODEL
            )
            or changed
        )

    return changed


def _apply_env_overrides_to_db_first_boot() -> None:
    """Persist environment-provided overrides into the DB on first boot.

    Only updates fields that are at default/empty values so we don't clobber
    user-changed settings after first start.
    """
    llm = LLMSettings.query.get(1)
    whisper = WhisperSettings.query.get(1)
    processing = ProcessingSettings.query.get(1)
    output = OutputSettings.query.get(1)
    app_s = AppSettings.query.get(1)

    assert llm and whisper and processing and output and app_s

    changed = False
    changed = _apply_llm_env_overrides_to_db(llm) or changed
    changed = _apply_whisper_env_overrides_to_db(whisper) or changed

    # Future: add processing/output/app env-to-db seeding if envs defined

    if changed:
        db.session.commit()


def read_combined() -> Dict[str, Any]:
    ensure_defaults()

    llm = LLMSettings.query.get(1)
    whisper = WhisperSettings.query.get(1)
    processing = ProcessingSettings.query.get(1)
    output = OutputSettings.query.get(1)
    app_s = AppSettings.query.get(1)

    assert llm and whisper and processing and output and app_s

    whisper_payload: Dict[str, Any] = {"whisper_type": whisper.whisper_type}
    if whisper.whisper_type == "local":
        whisper_payload.update({"model": whisper.local_model})
    elif whisper.whisper_type == "remote":
        whisper_payload.update(
            {
                "model": whisper.remote_model,
                "api_key": whisper.remote_api_key,
                "base_url": whisper.remote_base_url,
                "language": whisper.remote_language,
                "timeout_sec": whisper.remote_timeout_sec,
                "chunksize_mb": whisper.remote_chunksize_mb,
            }
        )
    elif whisper.whisper_type == "groq":
        whisper_payload.update(
            {
                "api_key": whisper.groq_api_key,
                "model": whisper.groq_model,
                "language": whisper.groq_language,
                "max_retries": whisper.groq_max_retries,
            }
        )
    elif whisper.whisper_type == "test":
        whisper_payload.update({})

    return {
        "llm": {
            "llm_api_key": llm.llm_api_key,
            "llm_model": llm.llm_model,
            "openai_base_url": llm.openai_base_url,
            "openai_timeout": llm.openai_timeout,
            "openai_max_tokens": llm.openai_max_tokens,
            "llm_max_concurrent_calls": llm.llm_max_concurrent_calls,
            "llm_max_retry_attempts": llm.llm_max_retry_attempts,
            "llm_max_input_tokens_per_call": llm.llm_max_input_tokens_per_call,
            "llm_enable_token_rate_limiting": llm.llm_enable_token_rate_limiting,
            "llm_max_input_tokens_per_minute": llm.llm_max_input_tokens_per_minute,
        },
        "whisper": whisper_payload,
        "processing": {
            "num_segments_to_input_to_prompt": processing.num_segments_to_input_to_prompt,
        },
        "output": {
            "fade_ms": output.fade_ms,
            "min_ad_segement_separation_seconds": output.min_ad_segement_separation_seconds,
            "min_ad_segment_length_seconds": output.min_ad_segment_length_seconds,
            "min_confidence": output.min_confidence,
        },
        "app": {
            "background_update_interval_minute": app_s.background_update_interval_minute,
            "automatically_whitelist_new_episodes": app_s.automatically_whitelist_new_episodes,
            "post_cleanup_retention_days": app_s.post_cleanup_retention_days,
            "number_of_episodes_to_whitelist_from_archive_of_new_feed": app_s.number_of_episodes_to_whitelist_from_archive_of_new_feed,
        },
    }


def _update_section_llm(data: Dict[str, Any]) -> None:
    row = LLMSettings.query.get(1)
    assert row is not None
    for key in [
        "llm_api_key",
        "llm_model",
        "openai_base_url",
        "openai_timeout",
        "openai_max_tokens",
        "llm_max_concurrent_calls",
        "llm_max_retry_attempts",
        "llm_max_input_tokens_per_call",
        "llm_enable_token_rate_limiting",
        "llm_max_input_tokens_per_minute",
    ]:
        if key in data:
            new_val = data[key]
            if key == "llm_api_key" and _is_empty(new_val):
                continue
            setattr(row, key, new_val)
    db.session.commit()


def _update_section_whisper(data: Dict[str, Any]) -> None:
    row = WhisperSettings.query.get(1)
    assert row is not None
    if "whisper_type" in data and data["whisper_type"] in {
        "local",
        "remote",
        "groq",
        "test",
    }:
        row.whisper_type = data["whisper_type"]
    if row.whisper_type == "local":
        if "model" in data:
            row.local_model = data["model"]
    elif row.whisper_type == "remote":
        for key_map in [
            ("model", "remote_model"),
            ("api_key", "remote_api_key"),
            ("base_url", "remote_base_url"),
            ("language", "remote_language"),
            ("timeout_sec", "remote_timeout_sec"),
            ("chunksize_mb", "remote_chunksize_mb"),
        ]:
            src, dst = key_map
            if src in data:
                new_val = data[src]
                if src == "api_key" and _is_empty(new_val):
                    continue
                setattr(row, dst, new_val)
    elif row.whisper_type == "groq":
        for key_map in [
            ("api_key", "groq_api_key"),
            ("model", "groq_model"),
            ("language", "groq_language"),
            ("max_retries", "groq_max_retries"),
        ]:
            src, dst = key_map
            if src in data:
                new_val = data[src]
                if src == "api_key" and _is_empty(new_val):
                    continue
                setattr(row, dst, new_val)
    else:
        # test type has no extra fields
        pass
    db.session.commit()


def _update_section_processing(data: Dict[str, Any]) -> None:
    row = ProcessingSettings.query.get(1)
    assert row is not None
    for key in [
        "num_segments_to_input_to_prompt",
    ]:
        if key in data:
            setattr(row, key, data[key])
    db.session.commit()


def _update_section_output(data: Dict[str, Any]) -> None:
    row = OutputSettings.query.get(1)
    assert row is not None
    for key in [
        "fade_ms",
        "min_ad_segement_separation_seconds",
        "min_ad_segment_length_seconds",
        "min_confidence",
    ]:
        if key in data:
            setattr(row, key, data[key])
    db.session.commit()


def _update_section_app(data: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    row = AppSettings.query.get(1)
    assert row is not None
    old_interval: Optional[int] = row.background_update_interval_minute
    old_retention: Optional[int] = row.post_cleanup_retention_days
    for key in [
        "background_update_interval_minute",
        "automatically_whitelist_new_episodes",
        "post_cleanup_retention_days",
        "number_of_episodes_to_whitelist_from_archive_of_new_feed",
    ]:
        if key in data:
            setattr(row, key, data[key])
    db.session.commit()
    return old_interval, old_retention


def update_combined(payload: Dict[str, Any]) -> Dict[str, Any]:
    if "llm" in payload:
        _update_section_llm(payload["llm"] or {})
    if "whisper" in payload:
        _update_section_whisper(payload["whisper"] or {})
    if "processing" in payload:
        _update_section_processing(payload["processing"] or {})
    if "output" in payload:
        _update_section_output(payload["output"] or {})
    if "app" in payload:
        old_interval, old_retention = _update_section_app(payload["app"] or {})
        # Reschedule background job if interval changed
        app_s = AppSettings.query.get(1)
        if app_s:
            if old_interval != app_s.background_update_interval_minute:
                try:
                    scheduler.remove_job("refresh_all_feeds")
                except Exception:
                    # job may not exist yet; ignore
                    pass
                if app_s.background_update_interval_minute is not None:
                    add_background_job(int(app_s.background_update_interval_minute))
            if old_retention != app_s.post_cleanup_retention_days:
                schedule_cleanup_job(app_s.post_cleanup_retention_days)

    return read_combined()


def to_pydantic_config() -> PydanticConfig:
    data = read_combined()
    # Map whisper section to discriminated union config
    whisper_obj: Optional[
        LocalWhisperConfig | RemoteWhisperConfig | TestWhisperConfig | GroqWhisperConfig
    ] = None
    w = data["whisper"]
    wtype = w.get("whisper_type")
    if wtype == "local":
        whisper_obj = LocalWhisperConfig(model=w.get("model", "base.en"))
    elif wtype == "remote":
        whisper_obj = RemoteWhisperConfig(
            model=w.get("model", "whisper-1"),
            api_key=w.get("api_key"),
            base_url=w.get("base_url", "https://api.openai.com/v1"),
            language=w.get("language", "en"),
            timeout_sec=w.get("timeout_sec", 600),
            chunksize_mb=w.get("chunksize_mb", 24),
        )
    elif wtype == "groq":
        whisper_obj = GroqWhisperConfig(
            api_key=w.get("api_key"),
            model=w.get("model", DEFAULTS.WHISPER_GROQ_MODEL),
            language=w.get("language", "en"),
            max_retries=w.get("max_retries", 3),
        )
    elif wtype == "test":
        whisper_obj = TestWhisperConfig()

    return PydanticConfig(
        llm_api_key=data["llm"].get("llm_api_key"),
        llm_model=data["llm"].get("llm_model", DEFAULTS.LLM_DEFAULT_MODEL),
        openai_base_url=data["llm"].get("openai_base_url"),
        openai_max_tokens=int(
            data["llm"].get("openai_max_tokens", DEFAULTS.OPENAI_DEFAULT_MAX_TOKENS)
            or DEFAULTS.OPENAI_DEFAULT_MAX_TOKENS
        ),
        openai_timeout=int(
            data["llm"].get("openai_timeout", DEFAULTS.OPENAI_DEFAULT_TIMEOUT_SEC)
            or DEFAULTS.OPENAI_DEFAULT_TIMEOUT_SEC
        ),
        llm_max_concurrent_calls=int(
            data["llm"].get(
                "llm_max_concurrent_calls", DEFAULTS.LLM_DEFAULT_MAX_CONCURRENT_CALLS
            )
            or DEFAULTS.LLM_DEFAULT_MAX_CONCURRENT_CALLS
        ),
        llm_max_retry_attempts=int(
            data["llm"].get(
                "llm_max_retry_attempts", DEFAULTS.LLM_DEFAULT_MAX_RETRY_ATTEMPTS
            )
            or DEFAULTS.LLM_DEFAULT_MAX_RETRY_ATTEMPTS
        ),
        llm_max_input_tokens_per_call=data["llm"].get("llm_max_input_tokens_per_call"),
        llm_enable_token_rate_limiting=bool(
            data["llm"].get(
                "llm_enable_token_rate_limiting",
                DEFAULTS.LLM_ENABLE_TOKEN_RATE_LIMITING,
            )
        ),
        llm_max_input_tokens_per_minute=data["llm"].get(
            "llm_max_input_tokens_per_minute"
        ),
        output=data["output"],
        processing=data["processing"],
        background_update_interval_minute=data["app"].get(
            "background_update_interval_minute"
        ),
        post_cleanup_retention_days=data["app"].get("post_cleanup_retention_days"),
        whisper=whisper_obj,
        automatically_whitelist_new_episodes=bool(
            data["app"].get(
                "automatically_whitelist_new_episodes",
                DEFAULTS.APP_AUTOMATICALLY_WHITELIST_NEW_EPISODES,
            )
        ),
        number_of_episodes_to_whitelist_from_archive_of_new_feed=int(
            data["app"].get(
                "number_of_episodes_to_whitelist_from_archive_of_new_feed",
                DEFAULTS.APP_NUM_EPISODES_TO_WHITELIST_FROM_ARCHIVE_OF_NEW_FEED,
            )
            or DEFAULTS.APP_NUM_EPISODES_TO_WHITELIST_FROM_ARCHIVE_OF_NEW_FEED
        ),
    )


def hydrate_runtime_config_inplace(db_config: Optional[PydanticConfig] = None) -> None:
    """Hydrate the in-process runtime config from DB-backed settings in-place.

    Preserves the identity of the `app.config` Pydantic instance so any modules
    that imported it by value continue to see updated fields.
    """
    cfg = db_config or to_pydantic_config()

    _log_initial_snapshot(cfg)

    _apply_top_level_env_overrides(cfg)

    _apply_whisper_env_overrides(cfg)

    _apply_llm_model_override(cfg)

    _apply_whisper_type_override(cfg)

    _commit_runtime_config(cfg)
    _log_final_snapshot()


def _log_initial_snapshot(cfg: PydanticConfig) -> None:
    logger.info(
        "Config hydration: starting with DB values | whisper_type=%s llm_model=%s openai_base_url=%s llm_api_key_set=%s whisper_api_key_set=%s",
        getattr(getattr(cfg, "whisper", None), "whisper_type", None),
        getattr(cfg, "llm_model", None),
        getattr(cfg, "openai_base_url", None),
        bool(getattr(cfg, "llm_api_key", None)),
        bool(getattr(getattr(cfg, "whisper", None), "api_key", None)),
    )


def _apply_top_level_env_overrides(cfg: PydanticConfig) -> None:
    env_llm_key = (
        os.environ.get("LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("GROQ_API_KEY")
    )
    if env_llm_key:
        cfg.llm_api_key = env_llm_key

    env_openai_base_url = os.environ.get("OPENAI_BASE_URL")
    if env_openai_base_url:
        cfg.openai_base_url = env_openai_base_url


def _apply_whisper_env_overrides(cfg: PydanticConfig) -> None:
    if cfg.whisper is None:
        return
    wtype = getattr(cfg.whisper, "whisper_type", None)
    if wtype == "remote":
        remote_key = os.environ.get("WHISPER_REMOTE_API_KEY") or os.environ.get(
            "OPENAI_API_KEY"
        )
        remote_base = os.environ.get("WHISPER_REMOTE_BASE_URL") or os.environ.get(
            "OPENAI_BASE_URL"
        )
        remote_model = os.environ.get("WHISPER_REMOTE_MODEL")
        if isinstance(cfg.whisper, RemoteWhisperConfig):
            if remote_key:
                cfg.whisper.api_key = remote_key
            if remote_base:
                cfg.whisper.base_url = remote_base
            if remote_model:
                cfg.whisper.model = remote_model
    elif wtype == "groq":
        groq_key = os.environ.get("GROQ_API_KEY")
        groq_model = os.environ.get("GROQ_WHISPER_MODEL") or os.environ.get(
            "WHISPER_GROQ_MODEL"
        )
        if isinstance(cfg.whisper, GroqWhisperConfig):
            if groq_key:
                cfg.whisper.api_key = groq_key
            if groq_model:
                cfg.whisper.model = groq_model
    elif wtype == "local":
        loc_model = os.environ.get("WHISPER_LOCAL_MODEL")
        if isinstance(cfg.whisper, LocalWhisperConfig) and loc_model:
            cfg.whisper.model = loc_model


def _apply_llm_model_override(cfg: PydanticConfig) -> None:
    env_llm_model = os.environ.get("LLM_MODEL")
    if env_llm_model:
        cfg.llm_model = env_llm_model


def _configure_local_whisper(cfg: PydanticConfig) -> None:
    """Configure local whisper type."""
    # Validate that local whisper is available
    try:
        import whisper as _  # type: ignore[import-untyped]  # noqa: F401
    except ImportError as e:
        error_msg = (
            f"WHISPER_TYPE is set to 'local' but whisper library is not available. "
            f"Either install whisper with 'pip install openai-whisper' or set WHISPER_TYPE to 'remote' or 'groq'. "
            f"Import error: {e}"
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg) from e

    existing_model_any = getattr(cfg.whisper, "model", "base.en")
    existing_model = (
        existing_model_any if isinstance(existing_model_any, str) else "base.en"
    )
    loc_model_env = os.environ.get("WHISPER_LOCAL_MODEL")
    loc_model: str = (
        loc_model_env
        if isinstance(loc_model_env, str) and loc_model_env
        else existing_model
    )
    cfg.whisper = LocalWhisperConfig(model=loc_model)


def _configure_remote_whisper(cfg: PydanticConfig) -> None:
    """Configure remote whisper type."""
    existing_model_any = getattr(cfg.whisper, "model", "whisper-1")
    existing_model = (
        existing_model_any if isinstance(existing_model_any, str) else "whisper-1"
    )
    rem_model_env = os.environ.get("WHISPER_REMOTE_MODEL")
    rem_model: str = (
        rem_model_env
        if isinstance(rem_model_env, str) and rem_model_env
        else existing_model
    )

    existing_key_any = getattr(cfg.whisper, "api_key", "")
    existing_key = existing_key_any if isinstance(existing_key_any, str) else ""
    rem_api_key_env = os.environ.get("WHISPER_REMOTE_API_KEY") or os.environ.get(
        "OPENAI_API_KEY"
    )
    rem_api_key: str = (
        rem_api_key_env
        if isinstance(rem_api_key_env, str) and rem_api_key_env
        else existing_key
    )

    existing_base_any = getattr(cfg.whisper, "base_url", "https://api.openai.com/v1")
    existing_base = (
        existing_base_any
        if isinstance(existing_base_any, str)
        else "https://api.openai.com/v1"
    )
    rem_base_env = os.environ.get("WHISPER_REMOTE_BASE_URL") or os.environ.get(
        "OPENAI_BASE_URL"
    )
    rem_base_url: str = (
        rem_base_env
        if isinstance(rem_base_env, str) and rem_base_env
        else existing_base
    )

    existing_lang_any = getattr(cfg.whisper, "language", "en")
    lang: str = existing_lang_any if isinstance(existing_lang_any, str) else "en"

    timeout_sec: int = int(
        os.environ.get(
            "WHISPER_REMOTE_TIMEOUT_SEC",
            str(getattr(cfg.whisper, "timeout_sec", 600)),
        )
    )
    chunksize_mb: int = int(
        os.environ.get(
            "WHISPER_REMOTE_CHUNKSIZE_MB",
            str(getattr(cfg.whisper, "chunksize_mb", 24)),
        )
    )

    cfg.whisper = RemoteWhisperConfig(
        model=rem_model,
        api_key=rem_api_key,
        base_url=rem_base_url,
        language=lang,
        timeout_sec=timeout_sec,
        chunksize_mb=chunksize_mb,
    )


def _configure_groq_whisper(cfg: PydanticConfig) -> None:
    """Configure groq whisper type."""
    existing_key_any = getattr(cfg.whisper, "api_key", "")
    existing_key = existing_key_any if isinstance(existing_key_any, str) else ""
    groq_key_env = os.environ.get("GROQ_API_KEY")
    groq_api_key: str = (
        groq_key_env if isinstance(groq_key_env, str) and groq_key_env else existing_key
    )

    existing_model_any = getattr(cfg.whisper, "model", DEFAULTS.WHISPER_GROQ_MODEL)
    existing_model = (
        existing_model_any
        if isinstance(existing_model_any, str)
        else DEFAULTS.WHISPER_GROQ_MODEL
    )
    groq_model_env = os.environ.get("GROQ_WHISPER_MODEL") or os.environ.get(
        "WHISPER_GROQ_MODEL"
    )
    groq_model_val: str = (
        groq_model_env
        if isinstance(groq_model_env, str) and groq_model_env
        else existing_model
    )

    existing_lang_any = getattr(cfg.whisper, "language", "en")
    groq_lang: str = existing_lang_any if isinstance(existing_lang_any, str) else "en"

    max_retries: int = int(
        os.environ.get("GROQ_MAX_RETRIES", str(getattr(cfg.whisper, "max_retries", 3)))
    )

    cfg.whisper = GroqWhisperConfig(
        api_key=groq_api_key,
        model=groq_model_val,
        language=groq_lang,
        max_retries=max_retries,
    )


def _apply_whisper_type_override(cfg: PydanticConfig) -> None:
    env_whisper_type = os.environ.get("WHISPER_TYPE")

    # Auto-detect whisper type from API key environment variables if not explicitly set
    if not env_whisper_type:
        if os.environ.get("WHISPER_REMOTE_API_KEY"):
            env_whisper_type = "remote"
            logger.info(
                "Auto-detected WHISPER_TYPE=remote from WHISPER_REMOTE_API_KEY environment variable"
            )
        elif os.environ.get("GROQ_API_KEY") and not os.environ.get("LLM_API_KEY"):
            # Only auto-detect groq for whisper if LLM_API_KEY is not set
            # (to avoid confusion when GROQ_API_KEY is only meant for LLM)
            env_whisper_type = "groq"
            logger.info(
                "Auto-detected WHISPER_TYPE=groq from GROQ_API_KEY environment variable"
            )

    if not env_whisper_type:
        return

    wtype = env_whisper_type.strip().lower()
    if wtype == "local":
        _configure_local_whisper(cfg)
    elif wtype == "remote":
        _configure_remote_whisper(cfg)
    elif wtype == "groq":
        _configure_groq_whisper(cfg)
    elif wtype == "test":
        cfg.whisper = TestWhisperConfig()


def _commit_runtime_config(cfg: PydanticConfig) -> None:
    logger.info(
        "Config hydration: after env overrides | whisper_type=%s llm_model=%s openai_base_url=%s llm_api_key_set=%s whisper_api_key_set=%s",
        getattr(getattr(cfg, "whisper", None), "whisper_type", None),
        getattr(cfg, "llm_model", None),
        getattr(cfg, "openai_base_url", None),
        bool(getattr(cfg, "llm_api_key", None)),
        bool(getattr(getattr(cfg, "whisper", None), "api_key", None)),
    )
    # Copy values from cfg to runtime_config, preserving Pydantic model instances
    for key in cfg.model_fields.keys():
        setattr(runtime_config, key, getattr(cfg, key))


def _log_final_snapshot() -> None:
    logger.info(
        "Config hydration: runtime set | whisper_type=%s llm_model=%s openai_base_url=%s",
        getattr(getattr(runtime_config, "whisper", None), "whisper_type", None),
        getattr(runtime_config, "llm_model", None),
        getattr(runtime_config, "openai_base_url", None),
    )


def ensure_defaults_and_hydrate() -> None:
    """Ensure default rows exist, then hydrate the runtime config from DB."""
    ensure_defaults()
    _apply_env_overrides_to_db_first_boot()
    hydrate_runtime_config_inplace()
