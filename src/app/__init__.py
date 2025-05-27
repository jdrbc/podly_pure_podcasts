import json
import logging
import os
import sys

from flask import Flask
from flask_apscheduler import APScheduler  # type: ignore
from flask_cors import CORS
from flask_migrate import Migrate, upgrade
from flask_sqlalchemy import SQLAlchemy

from app.logger import setup_logger
from shared.config import get_config

is_test = "pytest" in sys.modules
config = (
    get_config("config/config.yml")
    if not is_test
    else get_config("config/config_test.yml")
)
setup_logger("global_logger", "config/app.log")
logger = logging.getLogger("global_logger")


def setup_dirs() -> None:
    if not os.path.exists("in"):
        os.makedirs("in")
    if not os.path.exists("srv"):
        os.makedirs("srv")


class SchedulerConfig:
    SCHEDULER_API_ENABLED = True
    SCHEDULER_JOBSTORES = {
        "default": {
            "type": "sqlalchemy",
            "url": "sqlite:///src/instance/jobs.sqlite",
        }
    }
    SCHEDULER_EXECUTORS = {"default": {"type": "threadpool", "max_workers": 1}}
    SCHEDULER_JOB_DEFAULTS = {"coalesce": False, "max_instances": config.threads}


def setup_scheduler(app: Flask) -> None:
    """Initialize and start the scheduler."""
    if not is_test:
        scheduler.init_app(app)
        scheduler.start()


def add_background_job() -> None:
    """Add the recurring background job for refreshing feeds."""
    from app.jobs import (  # pylint: disable=import-outside-toplevel
        run_refresh_all_feeds,
    )

    scheduler.add_job(
        id="refresh_all_feeds",
        func=run_refresh_all_feeds,
        trigger="interval",
        minutes=config.background_update_interval_minute,
        replace_existing=True,
    )


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static")

    # Configure CORS
    default_origins = [f"http://localhost:{config.frontend_server_port}"] 
    if config.server:
        server_url = config.server
        if not server_url.startswith(('http://', 'https://')):
            server_url = f"http://{server_url}"
        
        # Add frontend URL with configured port
        frontend_url = f"{server_url}:{config.frontend_server_port}"
        default_origins.append(frontend_url)
        
        # Also add the server URL without port for cases where it's served on port 80/443
        if not server_url.endswith((':80', ':443')):
            default_origins.append(server_url)
    
    cors_origins = os.environ.get("CORS_ORIGINS", ",".join(default_origins)).split(",")
    CORS(
        app,
        resources={r"/*": {"origins": cors_origins}},
        allow_headers=["Content-Type", "Authorization", "Range"],
        methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        supports_credentials=True,
    )

    # Load scheduler configuration
    app.config.from_object(SchedulerConfig())

    # Configure the database URI (SQLite with a 90-second timeout)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///sqlite3.db?timeout=90"
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

    # Always start the scheduler for on-demand jobs
    logger.info(f"Starting scheduler with {config.threads} thread(s).")
    setup_scheduler(app)

    # Only add the recurring background job if enabled
    if config.background_update_interval_minute is not None:
        logger.info(
            f"Background scheduler is enabled with interval of {config.background_update_interval_minute} minutes."
        )
        add_background_job()
    else:
        logger.info(
            "Background scheduler is disabled by configuration, but scheduler is available for on-demand jobs."
        )

    return app


db = SQLAlchemy()
scheduler = APScheduler()
migrate = Migrate(directory="./src/migrations")

setup_dirs()
print("Config:\n", json.dumps(config.redacted().model_dump(), indent=2))
