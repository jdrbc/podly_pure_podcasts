import json
import logging
import os
import secrets
import sys
from pathlib import Path
from typing import Any

from flask import Flask
from flask_cors import CORS
from flask_migrate import upgrade
from sqlalchemy import event
from sqlalchemy.engine import Engine

from app.auth import AuthSettings, load_auth_settings
from app.auth.bootstrap import bootstrap_admin_user
from app.auth.middleware import init_auth_middleware
from app.background import add_background_job, schedule_cleanup_job
from app.extensions import db, migrate, scheduler
from app.logger import setup_logger
from app.runtime_config import config, is_test
from shared.processing_paths import get_in_root, get_srv_root

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
    app = _create_flask_app()
    auth_settings = _load_auth_settings()

    _apply_auth_settings(app, auth_settings)
    _configure_session(app, auth_settings)
    _configure_cors(app)
    _configure_scheduler(app)
    _configure_database(app)
    _configure_external_loggers()
    _initialize_extensions(app)
    _register_routes_and_middleware(app)

    with app.app_context():
        _run_app_startup(auth_settings)

    app.config["AUTH_SETTINGS"] = auth_settings.without_password()

    _validate_env_key_conflicts()
    _start_scheduler_and_jobs(app)
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
    """
    llm_key = os.environ.get("LLM_API_KEY")
    groq_key = os.environ.get("GROQ_API_KEY")

    conflicts: list[str] = []
    if llm_key and groq_key and llm_key != groq_key:
        conflicts.append(
            "LLM_API_KEY and GROQ_API_KEY are both set but have different values"
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


def _create_flask_app() -> Flask:
    static_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), "static"))
    return Flask(__name__, static_folder=static_folder)


def _load_auth_settings() -> AuthSettings:
    try:
        return load_auth_settings()
    except RuntimeError as exc:
        logger.critical("Authentication configuration error: %s", exc)
        raise


def _apply_auth_settings(app: Flask, auth_settings: AuthSettings) -> None:
    app.config["AUTH_SETTINGS"] = auth_settings
    app.config["REQUIRE_AUTH"] = auth_settings.require_auth
    app.config["AUTH_ADMIN_USERNAME"] = auth_settings.admin_username


def _configure_session(app: Flask, auth_settings: AuthSettings) -> None:
    secret_key = os.environ.get("PODLY_SECRET_KEY")
    if not secret_key:
        try:
            secret_key = secrets.token_urlsafe(64)
        except Exception as exc:  # pylint: disable=broad-except
            raise RuntimeError("Failed to generate session secret key.") from exc
        if auth_settings.require_auth:
            logger.warning(
                "Generated ephemeral session secret key because PODLY_SECRET_KEY is not set; "
                "all sessions will be invalidated on restart."
            )

    app.config["SECRET_KEY"] = secret_key
    app.config["SESSION_COOKIE_NAME"] = os.environ.get(
        "PODLY_SESSION_COOKIE_NAME", "podly_session"
    )
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # We always allow HTTP cookies so self-hosted installs work behind simple HTTP reverse proxies.
    app.config["SESSION_COOKIE_SECURE"] = False


def _configure_cors(app: Flask) -> None:
    default_cors = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    cors_origins_env = os.environ.get("CORS_ORIGINS")
    if cors_origins_env:
        cors_origins = [
            origin.strip() for origin in cors_origins_env.split(",") if origin.strip()
        ]
    else:
        cors_origins = default_cors
    CORS(
        app,
        resources={r"/*": {"origins": cors_origins}},
        allow_headers=["Content-Type", "Authorization", "Range"],
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        supports_credentials=True,
    )


def _configure_scheduler(app: Flask) -> None:
    app.config.from_object(SchedulerConfig())


def _configure_database(app: Flask) -> None:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///sqlite3.db?timeout=90"
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "connect_args": {
            "timeout": 90,
            "check_same_thread": False,
        },
    }
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False


def _configure_external_loggers() -> None:
    groq_logger = logging.getLogger("groq")
    groq_logger.setLevel(logging.INFO)


def _initialize_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)


def _register_routes_and_middleware(app: Flask) -> None:
    from app.routes import register_routes  # pylint: disable=import-outside-toplevel

    register_routes(app)
    init_auth_middleware(app)

    from app import models  # pylint: disable=import-outside-toplevel, unused-import


def _run_app_startup(auth_settings: AuthSettings) -> None:
    upgrade()
    bootstrap_admin_user(auth_settings)
    try:
        from app.config_store import (  # pylint: disable=import-outside-toplevel
            ensure_defaults_and_hydrate,
        )

        ensure_defaults_and_hydrate()

        from app.processor import (  # pylint: disable=import-outside-toplevel
            ProcessorSingleton,
        )

        ProcessorSingleton.reset_instance()
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(f"Failed to initialize settings: {exc}")


def _start_scheduler_and_jobs(app: Flask) -> None:
    _clear_scheduler_jobstore()
    setup_scheduler(app)

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
    schedule_cleanup_job(getattr(config, "post_cleanup_retention_days", None))
