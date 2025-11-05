from __future__ import annotations

import base64
import binascii
import re
from typing import Any

from flask import Response, current_app, g, jsonify, request, session

from app.auth.feed_tokens import FeedTokenAuthResult, authenticate_feed_token
from app.auth.service import AuthenticatedUser, authenticate
from app.auth.state import failure_rate_limiter
from app.models import User

REALM = "Podly"
SESSION_USER_KEY = "user_id"

# Paths that remain public even when auth is required.
_PUBLIC_PATHS: set[str] = {
    "/",
    "/health",
    "/robots.txt",
    "/manifest.json",
    "/favicon.ico",
    "/api/auth/login",
    "/api/auth/status",
}

_PUBLIC_PREFIXES: tuple[str, ...] = (
    "/static/",
    "/assets/",
    "/images/",
    "/fonts/",
    "/.well-known/",
)

_PUBLIC_EXTENSIONS: tuple[str, ...] = (
    ".js",
    ".css",
    ".map",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".webp",
    ".txt",
)


_BASIC_AUTH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/feed/[^/]+$"),
    re.compile(r"^/api/posts/[^/]+/(audio|download(?:/original)?)$"),
    re.compile(r"^/post/[^/]+(?:\\.mp3|/original\\.mp3)$"),
)


def init_auth_middleware(app: Any) -> None:
    """Attach the authentication guard to the Flask app."""

    @app.before_request  # type: ignore[misc]
    def enforce_authentication() -> Response | None:
        # pylint: disable=too-many-return-statements
        if request.method == "OPTIONS":
            return None

        settings = current_app.config.get("AUTH_SETTINGS")
        if not settings or not settings.require_auth:
            return None

        if _is_public_request(request.path):
            return None

        client_identifier = request.remote_addr or "unknown"

        session_user = _load_session_user()
        if session_user is not None:
            g.current_user = session_user
            g.basic_auth_credentials = None
            failure_rate_limiter.register_success(client_identifier)
            return None

        if not _is_basic_auth_endpoint(request.path):
            return _json_unauthorized()

        retry_after = failure_rate_limiter.retry_after(client_identifier)
        if retry_after:
            return _too_many_requests(retry_after)

        credentials = _parse_basic_credentials(request.headers.get("Authorization"))
        if credentials is None:
            return _basic_unauthorized()

        username, password = credentials
        token_result: FeedTokenAuthResult | None = None
        user = authenticate(username, password)
        if user is None:
            token_result = authenticate_feed_token(username, password, request.path)
            if token_result is None:
                backoff = failure_rate_limiter.register_failure(client_identifier)
                response = _basic_unauthorized("Invalid credentials.")
                if backoff:
                    response.headers["Retry-After"] = str(backoff)
                return response
            user = token_result.user

        failure_rate_limiter.register_success(client_identifier)
        g.current_user = user
        g.basic_auth_credentials = (username, password)
        if token_result is not None:
            g.feed_token = token_result
        return None


def _load_session_user() -> AuthenticatedUser | None:
    raw_user_id = session.get(SESSION_USER_KEY)
    if isinstance(raw_user_id, str) and raw_user_id.isdigit():
        user_id = int(raw_user_id)
    elif isinstance(raw_user_id, int):
        user_id = raw_user_id
    else:
        return None

    user = User.query.get(user_id)
    if user is None:
        session.pop(SESSION_USER_KEY, None)
        return None

    return AuthenticatedUser(id=user.id, username=user.username, role=user.role)


def _is_basic_auth_endpoint(path: str) -> bool:
    return any(pattern.match(path) for pattern in _BASIC_AUTH_PATTERNS)


def _parse_basic_credentials(header_value: str | None) -> tuple[str, str] | None:
    if not header_value:
        return None

    if not header_value.startswith("Basic "):
        return None

    encoded = header_value.split(" ", 1)[1]
    try:
        decoded_bytes = base64.b64decode(encoded, validate=True)
        decoded = decoded_bytes.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None

    if ":" not in decoded:
        return None

    username, password = decoded.split(":", 1)
    return username, password


def _is_public_request(path: str) -> bool:
    if path in _PUBLIC_PATHS:
        return True

    if any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES):
        return True

    if any(path.endswith(ext) for ext in _PUBLIC_EXTENSIONS):
        return True

    return False


def _json_unauthorized(message: str = "Authentication required.") -> Response:
    response = jsonify({"error": message})
    response.status_code = 401
    return response


def _basic_unauthorized(message: str | None = None) -> Response:
    response = Response(message or "Unauthorized", status=401)
    response.headers["WWW-Authenticate"] = f'Basic realm="{REALM}"'
    return response


def _too_many_requests(retry_after: int) -> Response:
    response = Response("Too Many Authentication Attempts", status=429)
    response.headers["Retry-After"] = str(retry_after)
    return response
