import json
import logging
import os

from flask import Flask
from flask_apscheduler import APScheduler  # type: ignore
from flask_migrate import Migrate, upgrade
from flask_sqlalchemy import SQLAlchemy

from app.logger import setup_logger
from shared.config import get_config

config = get_config("config/config.yml")
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
    scheduler.init_app(app)
    scheduler.start()
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

    from app.routes import main_bp  # pylint: disable=import-outside-toplevel

    app.register_blueprint(main_bp)

    from app import models  # pylint: disable=import-outside-toplevel, unused-import

    with app.app_context():
        upgrade()

    if config.background_update_interval_minute is not None:
        logger.info(f"Background scheduler is enabled with {config.threads} thread(s).")
        setup_scheduler(app)
    else:
        logger.info("Background scheduler is disabled by configuration.")

    return app


db = SQLAlchemy()
scheduler = APScheduler()
migrate = Migrate(directory="./src/migrations")

setup_dirs()
print("Config:\n", json.dumps(config.redacted().model_dump(), indent=2))
