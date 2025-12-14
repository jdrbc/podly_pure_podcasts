"""Authorization guard utilities for admin and authenticated user checks."""

from typing import TYPE_CHECKING, Tuple

import flask
from flask import current_app, g, jsonify

from app.extensions import db

if TYPE_CHECKING:
    from app.models import User


def require_admin(
    action: str = "perform this action",
) -> Tuple["User | None", flask.Response | None]:
    """Ensure the current user is an admin when auth is enabled.

    When auth is disabled (AUTH_SETTINGS.require_auth == False),
    returns (None, None) to allow the operation.

    When auth is enabled:
    - Returns (user, None) if user is authenticated and is admin
    - Returns (None, error_response) if not authenticated or not admin

    Args:
        action: Description of the action for error messages.

    Returns:
        (user, error_response) tuple where only one is non-None.
    """
    settings = current_app.config.get("AUTH_SETTINGS")
    if not settings or not settings.require_auth:
        return None, None

    current = getattr(g, "current_user", None)
    if current is None:
        return None, flask.make_response(
            jsonify({"error": "Authentication required."}), 401
        )

    from app.models import User

    user: User | None = db.session.get(User, current.id)
    if user is None:
        return None, flask.make_response(jsonify({"error": "User not found."}), 404)

    if user.role != "admin":
        return None, flask.make_response(
            jsonify({"error": f"Only admins can {action}."}), 403
        )

    return user, None


def is_auth_enabled() -> bool:
    """Check if authentication is enabled."""
    settings = current_app.config.get("AUTH_SETTINGS")
    return bool(settings and settings.require_auth)
