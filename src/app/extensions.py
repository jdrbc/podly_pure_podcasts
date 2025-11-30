from flask_apscheduler import APScheduler  # type: ignore
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

from app.db_concurrency import RetryingSession

# Unbound singletons; initialized in app factory
db = SQLAlchemy(session_options={"class_": RetryingSession})
scheduler = APScheduler()
migrate = Migrate(directory="./src/migrations")
