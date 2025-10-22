from __future__ import annotations

import logging
from typing import cast

from flask import Blueprint, Response, current_app, g, jsonify, request

from app.auth.service import (
    AuthServiceError,
    DuplicateUserError,
    InvalidCredentialsError,
    LastAdminRemovalError,
    PasswordValidationError,
    authenticate,
    change_password,
    create_user,
    delete_user,
    list_users,
    set_role,
    update_password,
)
from app.auth.state import failure_rate_limiter
from app.models import User

logger = logging.getLogger("global_logger")


auth_bp = Blueprint("auth", __name__)

RouteResult = Response | tuple[Response, int] | tuple[Response, int, dict[str, str]]


def _auth_enabled() -> bool:
    settings = current_app.config.get("AUTH_SETTINGS")
    return bool(settings and settings.require_auth)


@auth_bp.route("/api/auth/status", methods=["GET"])
def auth_status() -> Response:
    return jsonify({"require_auth": _auth_enabled()})


@auth_bp.route("/api/auth/login", methods=["POST"])
def login() -> RouteResult:
    if not _auth_enabled():
        return jsonify({"error": "Authentication is disabled."}), 404

    payload = request.get_json(silent=True) or {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""

    if not username or not password:
        return jsonify({"error": "Username and password are required."}), 400

    client_identifier = request.remote_addr or "unknown"
    retry_after = failure_rate_limiter.retry_after(client_identifier)
    if retry_after:
        return (
            jsonify({"error": "Too many failed attempts.", "retry_after": retry_after}),
            429,
            {"Retry-After": str(retry_after)},
        )

    authenticated = authenticate(username, password)
    if authenticated is None:
        backoff = failure_rate_limiter.register_failure(client_identifier)
        response_headers = {"WWW-Authenticate": 'Basic realm="Podly"'}
        if backoff:
            response_headers["Retry-After"] = str(backoff)
        return (
            jsonify({"error": "Invalid username or password."}),
            401,
            response_headers,
        )

    failure_rate_limiter.register_success(client_identifier)
    return jsonify(
        {
            "user": {
                "id": authenticated.id,
                "username": authenticated.username,
                "role": authenticated.role,
            }
        }
    )


@auth_bp.route("/api/auth/me", methods=["GET"])
def auth_me() -> RouteResult:
    if not _auth_enabled():
        return jsonify({"error": "Authentication is disabled."}), 404

    user = _require_authenticated_user()
    if user is None:
        return _unauthorized_response()

    return jsonify(
        {
            "user": {
                "id": user.id,
                "username": user.username,
                "role": user.role,
            }
        }
    )


@auth_bp.route("/api/auth/change-password", methods=["POST"])
def change_password_route() -> RouteResult:
    if not _auth_enabled():
        return jsonify({"error": "Authentication is disabled."}), 404

    user = _require_authenticated_user()
    if user is None:
        return _unauthorized_response()

    payload = request.get_json(silent=True) or {}
    current_password = payload.get("current_password") or ""
    new_password = payload.get("new_password") or ""

    if not current_password or not new_password:
        return (
            jsonify({"error": "Current and new passwords are required."}),
            400,
        )

    try:
        change_password(user, current_password, new_password)
    except InvalidCredentialsError as exc:
        return jsonify({"error": str(exc)}), 401
    except PasswordValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except AuthServiceError as exc:  # fallback
        logger.error("Password change failed: %s", exc)
        return jsonify({"error": "Unable to change password."}), 500

    return jsonify({"status": "ok"})


@auth_bp.route("/api/auth/users", methods=["GET"])
def list_users_route() -> RouteResult:
    if not _auth_enabled():
        return jsonify({"error": "Authentication is disabled."}), 404

    user = _require_authenticated_user()
    if user is None:
        return _unauthorized_response()

    if not user.role == "admin":
        return jsonify({"error": "Admin privileges required."}), 403

    users = list_users()
    return jsonify(
        {
            "users": [
                {
                    "id": u.id,
                    "username": u.username,
                    "role": u.role,
                    "created_at": u.created_at.isoformat(),
                    "updated_at": u.updated_at.isoformat(),
                }
                for u in users
            ]
        }
    )


@auth_bp.route("/api/auth/users", methods=["POST"])
def create_user_route() -> RouteResult:
    if not _auth_enabled():
        return jsonify({"error": "Authentication is disabled."}), 404

    user = _require_authenticated_user()
    if user is None:
        return _unauthorized_response()
    if user.role != "admin":
        return jsonify({"error": "Admin privileges required."}), 403

    payload = request.get_json(silent=True) or {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    role = (payload.get("role") or "user").strip()

    if not username or not password:
        return jsonify({"error": "Username and password are required."}), 400

    try:
        new_user = create_user(username, password, role)
    except (PasswordValidationError, DuplicateUserError, AuthServiceError) as exc:
        status = 409 if isinstance(exc, DuplicateUserError) else 400
        return jsonify({"error": str(exc)}), status

    return (
        jsonify(
            {
                "user": {
                    "id": new_user.id,
                    "username": new_user.username,
                    "role": new_user.role,
                    "created_at": new_user.created_at.isoformat(),
                    "updated_at": new_user.updated_at.isoformat(),
                }
            }
        ),
        201,
    )


@auth_bp.route("/api/auth/users/<string:username>", methods=["PATCH"])
def update_user_route(username: str) -> RouteResult:
    if not _auth_enabled():
        return jsonify({"error": "Authentication is disabled."}), 404

    acting_user = _require_authenticated_user()
    if acting_user is None:
        return _unauthorized_response()

    if acting_user.role != "admin":
        return jsonify({"error": "Admin privileges required."}), 403

    target = User.query.filter_by(username=username.lower()).first()
    if target is None:
        return jsonify({"error": "User not found."}), 404

    payload = request.get_json(silent=True) or {}
    role = payload.get("role")
    new_password = payload.get("password")

    try:
        if role is not None:
            set_role(target, role)
        if new_password:
            update_password(target, new_password)
        return jsonify({"status": "ok"})
    except (PasswordValidationError, LastAdminRemovalError, AuthServiceError) as exc:
        status_code = 400
        return jsonify({"error": str(exc)}), status_code


@auth_bp.route("/api/auth/users/<string:username>", methods=["DELETE"])
def delete_user_route(username: str) -> RouteResult:
    if not _auth_enabled():
        return jsonify({"error": "Authentication is disabled."}), 404

    acting_user = _require_authenticated_user()
    if acting_user is None:
        return _unauthorized_response()
    if acting_user.role != "admin":
        return jsonify({"error": "Admin privileges required."}), 403

    target = User.query.filter_by(username=username.lower()).first()
    if target is None:
        return jsonify({"error": "User not found."}), 404

    try:
        delete_user(target)
    except LastAdminRemovalError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"status": "ok"})


def _require_authenticated_user() -> User | None:
    if not _auth_enabled():
        return None

    current = getattr(g, "current_user", None)
    if current is None:
        return None

    return cast(User | None, User.query.get(current.id))


def _unauthorized_response() -> RouteResult:
    if not _auth_enabled():
        return jsonify({"error": "Authentication is disabled."}), 404

    return (
        jsonify({"error": "Authentication required."}),
        401,
        {"WWW-Authenticate": 'Basic realm="Podly"'},
    )
