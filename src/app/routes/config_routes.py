import logging
from typing import Any, Dict

import flask
import litellm
from flask import Blueprint, jsonify, request
from groq import Groq
from openai import OpenAI

from app import config as runtime_config
from app.config_store import read_combined, to_pydantic_config, update_combined
from app.processor import ProcessorSingleton

logger = logging.getLogger("global_logger")


config_bp = Blueprint("config", __name__)


def _sanitize_config_for_client(cfg: Dict[str, Any]) -> Dict[str, Any]:
    try:
        data: Dict[str, Any] = dict(cfg)
        llm: Dict[str, Any] = dict(data.get("llm", {}))
        whisper: Dict[str, Any] = dict(data.get("whisper", {}))

        if "llm_api_key" in llm:
            llm.pop("llm_api_key", None)
        if "api_key" in whisper:
            whisper.pop("api_key", None)

        data["llm"] = llm
        data["whisper"] = whisper
        return data
    except Exception:
        return {}


@config_bp.route("/api/config", methods=["GET"])
def api_get_config() -> flask.Response:
    try:
        data = read_combined()

        _hydrate_runtime_config(data)

        return flask.jsonify(_sanitize_config_for_client(data))
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Failed to read configuration: {e}")
        return flask.make_response(
            jsonify({"error": "Failed to read configuration"}), 500
        )


def _hydrate_runtime_config(data: Dict[str, Any]) -> None:
    # LLM overlay
    data.setdefault("llm", {})
    data["llm"]["llm_api_key"] = getattr(
        runtime_config, "llm_api_key", data["llm"].get("llm_api_key")
    )
    data["llm"]["llm_model"] = getattr(
        runtime_config, "llm_model", data["llm"].get("llm_model")
    )
    data["llm"]["openai_base_url"] = getattr(
        runtime_config, "openai_base_url", data["llm"].get("openai_base_url")
    )
    data["llm"]["openai_timeout"] = getattr(
        runtime_config, "openai_timeout", data["llm"].get("openai_timeout")
    )
    data["llm"]["openai_max_tokens"] = getattr(
        runtime_config, "openai_max_tokens", data["llm"].get("openai_max_tokens")
    )
    data["llm"]["llm_max_concurrent_calls"] = getattr(
        runtime_config,
        "llm_max_concurrent_calls",
        data["llm"].get("llm_max_concurrent_calls"),
    )
    data["llm"]["llm_max_retry_attempts"] = getattr(
        runtime_config,
        "llm_max_retry_attempts",
        data["llm"].get("llm_max_retry_attempts"),
    )
    data["llm"]["llm_max_input_tokens_per_call"] = getattr(
        runtime_config,
        "llm_max_input_tokens_per_call",
        data["llm"].get("llm_max_input_tokens_per_call"),
    )
    data["llm"]["llm_enable_token_rate_limiting"] = getattr(
        runtime_config,
        "llm_enable_token_rate_limiting",
        data["llm"].get("llm_enable_token_rate_limiting"),
    )
    data["llm"]["llm_max_input_tokens_per_minute"] = getattr(
        runtime_config,
        "llm_max_input_tokens_per_minute",
        data["llm"].get("llm_max_input_tokens_per_minute"),
    )

    # Whisper overlay (handle both dict and typed objects)
    data.setdefault("whisper", {})
    rt_whisper = getattr(runtime_config, "whisper", None)
    if isinstance(rt_whisper, dict):
        wtype = rt_whisper.get("whisper_type")
        data["whisper"]["whisper_type"] = wtype or data["whisper"].get("whisper_type")
        if wtype == "local":
            data["whisper"]["model"] = rt_whisper.get(
                "model", data["whisper"].get("model")
            )
        elif wtype == "remote":
            data["whisper"]["model"] = rt_whisper.get(
                "model", data["whisper"].get("model")
            )
            data["whisper"]["api_key"] = rt_whisper.get(
                "api_key", data["whisper"].get("api_key")
            )
            data["whisper"]["base_url"] = rt_whisper.get(
                "base_url", data["whisper"].get("base_url")
            )
            data["whisper"]["language"] = rt_whisper.get(
                "language", data["whisper"].get("language")
            )
            data["whisper"]["timeout_sec"] = rt_whisper.get(
                "timeout_sec", data["whisper"].get("timeout_sec")
            )
            data["whisper"]["chunksize_mb"] = rt_whisper.get(
                "chunksize_mb", data["whisper"].get("chunksize_mb")
            )
        elif wtype == "groq":
            data["whisper"]["api_key"] = rt_whisper.get(
                "api_key", data["whisper"].get("api_key")
            )
            data["whisper"]["model"] = rt_whisper.get(
                "model", data["whisper"].get("model")
            )
            data["whisper"]["language"] = rt_whisper.get(
                "language", data["whisper"].get("language")
            )
            data["whisper"]["max_retries"] = rt_whisper.get(
                "max_retries", data["whisper"].get("max_retries")
            )
    else:
        # typed pydantic whisper configs
        if rt_whisper is not None and hasattr(rt_whisper, "whisper_type"):
            wtype = getattr(rt_whisper, "whisper_type")
            data["whisper"]["whisper_type"] = wtype
            if wtype == "local":
                data["whisper"]["model"] = getattr(
                    rt_whisper, "model", data["whisper"].get("model")
                )
            elif wtype == "remote":
                data["whisper"]["model"] = getattr(
                    rt_whisper, "model", data["whisper"].get("model")
                )
                data["whisper"]["api_key"] = getattr(
                    rt_whisper, "api_key", data["whisper"].get("api_key")
                )
                data["whisper"]["base_url"] = getattr(
                    rt_whisper, "base_url", data["whisper"].get("base_url")
                )
                data["whisper"]["language"] = getattr(
                    rt_whisper, "language", data["whisper"].get("language")
                )
                data["whisper"]["timeout_sec"] = getattr(
                    rt_whisper, "timeout_sec", data["whisper"].get("timeout_sec")
                )
                data["whisper"]["chunksize_mb"] = getattr(
                    rt_whisper, "chunksize_mb", data["whisper"].get("chunksize_mb")
                )
            elif wtype == "groq":
                data["whisper"]["api_key"] = getattr(
                    rt_whisper, "api_key", data["whisper"].get("api_key")
                )
                data["whisper"]["model"] = getattr(
                    rt_whisper, "model", data["whisper"].get("model")
                )
                data["whisper"]["language"] = getattr(
                    rt_whisper, "language", data["whisper"].get("language")
                )
                data["whisper"]["max_retries"] = getattr(
                    rt_whisper, "max_retries", data["whisper"].get("max_retries")
                )


@config_bp.route("/api/config", methods=["PUT"])
def api_put_config() -> flask.Response:
    payload = request.get_json(silent=True) or {}
    try:
        data = update_combined(payload)

        try:
            db_cfg = to_pydantic_config()
        except Exception as hydrate_err:  # pylint: disable=broad-except
            logger.error(f"Post-update config hydration failed: {hydrate_err}")
            return flask.make_response(
                jsonify(
                    {"error": "Invalid configuration", "details": str(hydrate_err)}
                ),
                400,
            )

        for field_name in runtime_config.__class__.model_fields.keys():
            setattr(runtime_config, field_name, getattr(db_cfg, field_name))
        ProcessorSingleton.reset_instance()

        return flask.jsonify(_sanitize_config_for_client(data))
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Failed to update configuration: {e}")
        return flask.make_response(
            jsonify({"error": "Failed to update configuration", "details": str(e)}), 400
        )


@config_bp.route("/api/config/test-llm", methods=["POST"])
def api_test_llm() -> flask.Response:
    payload: Dict[str, Any] = request.get_json(silent=True) or {}
    llm: Dict[str, Any] = dict(payload.get("llm", {}))

    api_key: str | None = llm.get("llm_api_key") or getattr(
        runtime_config, "llm_api_key", None
    )
    model_val = llm.get("llm_model")
    model: str = (
        model_val
        if isinstance(model_val, str)
        else getattr(runtime_config, "llm_model", "gpt-4o")
    )
    base_url: str | None = llm.get("openai_base_url") or getattr(
        runtime_config, "openai_base_url", None
    )
    timeout_val = llm.get("openai_timeout")
    timeout: int = (
        int(timeout_val)
        if timeout_val is not None
        else int(getattr(runtime_config, "openai_timeout", 30))
    )

    if not api_key:
        return flask.make_response(
            jsonify({"ok": False, "error": "Missing llm_api_key"}), 400
        )

    try:
        # Configure litellm for this probe
        litellm.api_key = api_key
        if base_url:
            litellm.api_base = base_url

        # Minimal completion to validate connectivity and credentials
        _ = litellm.completion(
            model=model,
            messages=[
                {"role": "system", "content": "You are a healthcheck probe."},
                {"role": "user", "content": "ping"},
            ],
            max_tokens=1,
            timeout=timeout,
        )

        return flask.jsonify(
            {
                "ok": True,
                "message": "LLM connection OK",
                "model": model,
                "base_url": base_url,
            }
        )
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"LLM connection test failed: {e}")
        return flask.make_response(jsonify({"ok": False, "error": str(e)}), 400)


def _make_error_response(error_msg: str, status_code: int = 400) -> flask.Response:
    return flask.make_response(jsonify({"ok": False, "error": error_msg}), status_code)


def _make_success_response(message: str, **extra_data: Any) -> flask.Response:
    response_data = {"ok": True, "message": message}
    response_data.update(extra_data)
    return flask.jsonify(response_data)


def _get_whisper_config_value(
    whisper_cfg: Dict[str, Any], key: str, default: Any | None = None
) -> Any | None:
    value = whisper_cfg.get(key)
    if value is not None:
        return value
    try:
        runtime_whisper = getattr(runtime_config, "whisper", None)
        if runtime_whisper is not None:
            return getattr(runtime_whisper, key, default)
    except Exception:  # pragma: no cover - defensive
        pass
    return default


def _determine_whisper_type(whisper_cfg: Dict[str, Any]) -> str | None:
    wtype_any = whisper_cfg.get("whisper_type")
    if isinstance(wtype_any, str):
        return wtype_any
    try:
        runtime_whisper = getattr(runtime_config, "whisper", None)
        if runtime_whisper is not None and hasattr(runtime_whisper, "whisper_type"):
            rt_type = getattr(runtime_whisper, "whisper_type")
            return rt_type if isinstance(rt_type, str) else None
    except Exception:  # pragma: no cover - defensive
        pass
    return None


def _test_local_whisper(whisper_cfg: Dict[str, Any]) -> flask.Response:
    """Test local whisper configuration."""
    model_name = _get_whisper_config_value(whisper_cfg, "model", "base.en")
    try:
        import whisper  # type: ignore[import-untyped]
    except ImportError as e:
        return _make_error_response(f"whisper not installed: {e}")

    try:
        available = whisper.available_models()
    except Exception as e:  # pragma: no cover - library call
        available = []
        logger.warning(f"Failed to list local whisper models: {e}")

    if model_name not in available:
        return flask.make_response(
            jsonify(
                {
                    "ok": False,
                    "error": f"Model '{model_name}' not available. Install or adjust model.",
                    "available_models": available,
                }
            ),
            400,
        )
    return _make_success_response(f"Local whisper OK (model {model_name})")


def _test_remote_whisper(whisper_cfg: Dict[str, Any]) -> flask.Response:
    """Test remote whisper configuration."""
    api_key_any = _get_whisper_config_value(whisper_cfg, "api_key")
    base_url_any = _get_whisper_config_value(
        whisper_cfg, "base_url", "https://api.openai.com/v1"
    )
    timeout_any = _get_whisper_config_value(whisper_cfg, "timeout_sec", 30)

    api_key: str | None = api_key_any if isinstance(api_key_any, str) else None
    base_url: str | None = base_url_any if isinstance(base_url_any, str) else None
    timeout: int = int(timeout_any) if timeout_any is not None else 30

    if not api_key:
        return _make_error_response("Missing whisper.api_key")

    _ = OpenAI(base_url=base_url, api_key=api_key, timeout=timeout).models.list()
    return _make_success_response("Remote whisper connection OK", base_url=base_url)


def _test_groq_whisper(whisper_cfg: Dict[str, Any]) -> flask.Response:
    """Test groq whisper configuration."""
    groq_api_key_any = _get_whisper_config_value(whisper_cfg, "api_key")
    groq_api_key: str | None = (
        groq_api_key_any if isinstance(groq_api_key_any, str) else None
    )

    if not groq_api_key:
        return _make_error_response("Missing whisper.api_key")

    _ = Groq(api_key=groq_api_key).models.list()
    return _make_success_response("Groq whisper connection OK")


@config_bp.route("/api/config/test-whisper", methods=["POST"])
def api_test_whisper() -> flask.Response:
    """Test whisper configuration based on whisper_type."""
    payload: Dict[str, Any] = request.get_json(silent=True) or {}
    whisper_cfg: Dict[str, Any] = dict(payload.get("whisper", {}))

    wtype = _determine_whisper_type(whisper_cfg)
    if not wtype:
        return _make_error_response("Missing whisper_type")

    try:
        if wtype == "local":
            return _test_local_whisper(whisper_cfg)
        if wtype == "remote":
            return _test_remote_whisper(whisper_cfg)
        if wtype == "groq":
            return _test_groq_whisper(whisper_cfg)
        return _make_error_response(f"Unknown whisper_type '{wtype}'")
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Whisper connection test failed: {e}")
        return _make_error_response(str(e))


@config_bp.route("/api/config/whisper-capabilities", methods=["GET"])
def api_get_whisper_capabilities() -> flask.Response:
    """Report Whisper capabilities for the current runtime.

    Currently returns a boolean indicating whether local Whisper is importable.
    This enables the frontend to hide the 'local' option when unavailable.
    """
    local_available = False
    try:  # pragma: no cover - simple import feature check
        import whisper

        # If import succeeds, we consider local whisper available.
        # Optionally probe models list, but ignore failures here.
        try:
            _ = whisper.available_models()  # noqa: F841
        except Exception:
            pass
        local_available = True
    except Exception:
        local_available = False

    return flask.jsonify({"local_available": local_available})


@config_bp.route("/api/config/api_configured_check", methods=["GET"])
def api_configured_check() -> flask.Response:
    """Return whether the API configuration is sufficient to process.

    For our purposes, this means an LLM API key is present either in the
    persisted config or the runtime overlay.
    """
    try:
        data = read_combined()
        _hydrate_runtime_config(data)

        llm = data.get("llm", {}) if isinstance(data, dict) else {}
        api_key = llm.get("llm_api_key")
        configured = bool(api_key)
        return flask.jsonify({"configured": configured})
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Failed to check API configuration: {e}")
        # Be conservative: report not configured on error
        return flask.jsonify({"configured": False})
