from flask import Flask

from .config_routes import config_bp
from .feed_routes import feed_bp
from .jobs_routes import jobs_bp
from .main_routes import main_bp
from .post_routes import post_bp


def register_routes(app: Flask) -> None:
    """Register all route blueprints with the Flask app."""
    app.register_blueprint(main_bp)
    app.register_blueprint(feed_bp)
    app.register_blueprint(post_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(jobs_bp)
