import os

from flask_apscheduler import APScheduler  # type: ignore
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

# Unbound singletons; initialized in app factory
db = SQLAlchemy()
scheduler = APScheduler()

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
migrations_dir = os.path.join(base_dir, "migrations")

migrate = Migrate(directory=migrations_dir)
