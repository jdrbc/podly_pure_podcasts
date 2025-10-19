from flask_apscheduler import APScheduler  # type: ignore
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

# Unbound singletons; initialized in app factory
db = SQLAlchemy()
scheduler = APScheduler()
migrate = Migrate(directory="./src/migrations")
