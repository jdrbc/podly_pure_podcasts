import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import click
from flask import Flask
from flask_cors import CORS
from flask_migrate import upgrade
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.background import add_background_job
from app.extensions import db, migrate, scheduler
from app.logger import setup_logger
from shared import defaults as DEFAULTS
from shared.config import Config as RuntimeConfig
from shared.config import LocalWhisperConfig, OutputConfig, ProcessingConfig
from shared.processing_paths import get_in_root, get_srv_root

is_test = "pytest" in sys.modules
# For tests, use in-memory config for deterministic behavior. For runtime,
# initialize with sensible defaults; DB-backed settings will hydrate immediately after migrations.
if is_test:
    from shared.test_utils import create_standard_test_config

    config = create_standard_test_config()
else:
    config = RuntimeConfig(
        llm_api_key=None,
        llm_model=DEFAULTS.LLM_DEFAULT_MODEL,
        openai_base_url=None,
        openai_max_tokens=DEFAULTS.OPENAI_DEFAULT_MAX_TOKENS,
        openai_timeout=DEFAULTS.OPENAI_DEFAULT_TIMEOUT_SEC,
        output=OutputConfig(
            fade_ms=DEFAULTS.OUTPUT_FADE_MS,
            min_ad_segement_separation_seconds=DEFAULTS.OUTPUT_MIN_AD_SEGMENT_SEPARATION_SECONDS,
            min_ad_segment_length_seconds=DEFAULTS.OUTPUT_MIN_AD_SEGMENT_LENGTH_SECONDS,
            min_confidence=DEFAULTS.OUTPUT_MIN_CONFIDENCE,
        ),
        processing=ProcessingConfig(
            num_segments_to_input_to_prompt=DEFAULTS.PROCESSING_NUM_SEGMENTS_TO_INPUT_TO_PROMPT,
        ),
        background_update_interval_minute=DEFAULTS.APP_BACKGROUND_UPDATE_INTERVAL_MINUTE,
        llm_max_concurrent_calls=DEFAULTS.LLM_DEFAULT_MAX_CONCURRENT_CALLS,
        llm_max_retry_attempts=DEFAULTS.LLM_DEFAULT_MAX_RETRY_ATTEMPTS,
        llm_enable_token_rate_limiting=DEFAULTS.LLM_ENABLE_TOKEN_RATE_LIMITING,
        llm_max_input_tokens_per_call=DEFAULTS.LLM_MAX_INPUT_TOKENS_PER_CALL,
        llm_max_input_tokens_per_minute=DEFAULTS.LLM_MAX_INPUT_TOKENS_PER_MINUTE,
        automatically_whitelist_new_episodes=DEFAULTS.APP_AUTOMATICALLY_WHITELIST_NEW_EPISODES,
        number_of_episodes_to_whitelist_from_archive_of_new_feed=DEFAULTS.APP_NUM_EPISODES_TO_WHITELIST_FROM_ARCHIVE_OF_NEW_FEED,
        whisper=LocalWhisperConfig(model=DEFAULTS.WHISPER_LOCAL_MODEL),
    )
setup_logger("global_logger", "src/instance/logs/app.log")
logger = logging.getLogger("global_logger")


def setup_dirs() -> None:
    in_root = get_in_root()
    srv_root = get_srv_root()
    os.makedirs(in_root, exist_ok=True)
    os.makedirs(srv_root, exist_ok=True)


class SchedulerConfig:
    SCHEDULER_JOBSTORES = {
        "default": {
            "type": "sqlalchemy",
            "url": "sqlite:///src/instance/jobs.sqlite",
        }
    }
    SCHEDULER_EXECUTORS = {"default": {"type": "threadpool", "max_workers": 1}}
    SCHEDULER_JOB_DEFAULTS = {"coalesce": False, "max_instances": 1}


@event.listens_for(Engine, "connect", once=False)
def _set_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    module = getattr(dbapi_connection.__class__, "__module__", "")
    if not module.startswith(("sqlite3", "pysqlite2")):
        return

    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        # Keep busy timeout low so our explicit retry logic can respond quickly.
        cursor.execute("PRAGMA busy_timeout=2000;")
    finally:
        cursor.close()


def setup_scheduler(app: Flask) -> None:
    """Initialize and start the scheduler."""
    if not is_test:
        scheduler.init_app(app)
        scheduler.start()


def create_app() -> Flask:
    static_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "static"))
    app = Flask(__name__, static_folder=static_folder)

    # Configure CORS
    # Default to wildcard to accept all origins, but allow override via environment variable
    default_cors = "*"
    cors_origins_env = os.environ.get("CORS_ORIGINS", default_cors)
    cors_origins = (
        cors_origins_env.split(",") if cors_origins_env != "*" else cors_origins_env
    )
    CORS(
        app,
        resources={r"/*": {"origins": cors_origins}},
        allow_headers=["Content-Type", "Authorization", "Range"],
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        supports_credentials=False,
    )

    # Load scheduler configuration
    app.config.from_object(SchedulerConfig())

    # Configure the database URI (SQLite with a 90-second timeout)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///sqlite3.db?timeout=90"
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "connect_args": {
            "timeout": 90,
            "check_same_thread": False,
        },
    }
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Groq's client logs the entire binary input file when set to DEBUG, which we never want to do.
    groq_logger = logging.getLogger("groq")
    groq_logger.setLevel(logging.INFO)

    db.init_app(app)
    migrate.init_app(app, db)

    # Register all route blueprints
    from app.routes import register_routes  # pylint: disable=import-outside-toplevel

    register_routes(app)

    from app import models  # pylint: disable=import-outside-toplevel, unused-import

    with app.app_context():
        upgrade()
        # Initialize settings and hydrate runtime config in one step
        try:
            from app.config_store import (  # pylint: disable=import-outside-toplevel
                ensure_defaults_and_hydrate,
            )

            ensure_defaults_and_hydrate()

            # Reset processor singleton to pick up the updated config
            from app.processor import (  # pylint: disable=import-outside-toplevel
                ProcessorSingleton,
            )

            ProcessorSingleton.reset_instance()

        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"Failed to initialize settings: {e}")

    # After hydration, enforce environment key consistency rules; fail fast on conflicts
    _validate_env_key_conflicts()

    # Always start the scheduler for on-demand jobs
    _clear_scheduler_jobstore()
    setup_scheduler(app)

    # Clear all jobs on startup to ensure clean state
    from app.jobs_manager import (  # pylint: disable=import-outside-toplevel
        get_jobs_manager,
    )

    jobs_manager = get_jobs_manager()
    clear_result = jobs_manager.clear_all_jobs()
    if clear_result["status"] == "success":
        logger.info(f"Startup: {clear_result['message']}")
    else:
        logger.warning(f"Startup job clearing failed: {clear_result['message']}")

    add_background_job(
        10
        if config.background_update_interval_minute is None
        else int(config.background_update_interval_minute)
    )
    return app


if not is_test:
    setup_dirs()
print("Config:\n", json.dumps(config.model_dump(), indent=2))


def _clear_scheduler_jobstore() -> None:
    """Remove persisted APScheduler jobs so startup adds a clean schedule."""
    jobstore_config = SchedulerConfig.SCHEDULER_JOBSTORES.get("default")
    if not isinstance(jobstore_config, dict):
        return

    url = jobstore_config.get("url")
    if not isinstance(url, str):
        return

    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return

    relative_path = url[len(prefix) :]
    project_root = Path(__file__).resolve().parents[2]
    jobstore_path = (project_root / Path(relative_path)).resolve()
    jobstore_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if jobstore_path.exists():
            jobstore_path.unlink()
            logger.info(
                "Startup: cleared persisted APScheduler jobs at %s", jobstore_path
            )
    except OSError as exc:
        logger.warning(
            "Startup: failed to clear APScheduler jobs at %s: %s", jobstore_path, exc
        )


def _validate_env_key_conflicts() -> None:
    """Validate that environment API key variables are not conflicting.

    Rules:
    - If both LLM_API_KEY and GROQ_API_KEY are set and differ -> error
    - If both LLM_API_KEY and WHISPER_REMOTE_API_KEY are set and differ -> error
    """
    llm_key = os.environ.get("LLM_API_KEY")
    groq_key = os.environ.get("GROQ_API_KEY")
    whisper_remote_key = os.environ.get("WHISPER_REMOTE_API_KEY")

    conflicts: list[str] = []
    if llm_key and groq_key and llm_key != groq_key:
        conflicts.append(
            "LLM_API_KEY and GROQ_API_KEY are both set but have different values"
        )
    if llm_key and whisper_remote_key and llm_key != whisper_remote_key:
        conflicts.append(
            "LLM_API_KEY and WHISPER_REMOTE_API_KEY are both set but have different values"
        )

    if conflicts:
        details = "; ".join(conflicts)
        message = (
            "Configuration error: Conflicting environment API keys detected. "
            f"{details}. To use Groq, prefer setting GROQ_API_KEY only; "
            "alternatively, set the variables to the same value."
        )
        # Crash the process so Docker start fails clearly
        raise SystemExit(message)
