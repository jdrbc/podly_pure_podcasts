from flask import Flask

from .api_routes import api_bp
from .feed_routes import feed_bp
from .main_routes import main_bp


def register_routes(app: Flask) -> None:
    """Register all route blueprints with the Flask app."""
    app.register_blueprint(api_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(feed_bp)
