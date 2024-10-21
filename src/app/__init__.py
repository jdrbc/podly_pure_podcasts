import json
import logging
import os

from flask import Flask
from flask_migrate import Migrate, upgrade
from flask_sqlalchemy import SQLAlchemy

from app.logger import setup_logger
from shared.config import get_config


def setup_dirs() -> None:
    if not os.path.exists("processing"):
        os.makedirs("processing")
    if not os.path.exists("in"):
        os.makedirs("in")
    if not os.path.exists("srv"):
        os.makedirs("srv")


def create_app() -> Flask:
    app = Flask(__name__)

    # Configure the app (for example, SQLite for development)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///sqlite3.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Initialize the sqlalchemy object with the Flask app context
    db.init_app(app)
    migrate.init_app(app, db)

    from app.old_routes import old_bp  # pylint: disable=import-outside-toplevel

    # Import and register the routes (views)
    from app.routes import main_bp  # pylint: disable=import-outside-toplevel

    app.register_blueprint(main_bp)
    app.register_blueprint(old_bp)

    from app import models  # pylint: disable=import-outside-toplevel, unused-import

    with app.app_context():
        db.create_all()
        upgrade()

    return app


db = SQLAlchemy()
migrate = Migrate(directory="./src/migrations")
config = get_config("config/config.yml")


setup_logger("global_logger", "config/app.log")
logger = logging.getLogger("global_logger")


setup_dirs()
print("Config:\n", json.dumps(config.redacted().model_dump(), indent=2))
