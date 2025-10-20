from __future__ import annotations

import base64
import binascii
from typing import Any

from flask import Response, current_app, g, request

from app.auth.service import authenticate
from app.auth.state import failure_rate_limiter

REALM = "Podly"

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


def init_auth_middleware(app: Any) -> None:
    """Attach the authentication guard to the Flask app."""

    @app.before_request  # type: ignore[misc]
    def enforce_basic_auth() -> Response | None:
        # pylint: disable=too-many-return-statements
        if request.method == "OPTIONS":
            return None

        settings = current_app.config.get("AUTH_SETTINGS")
        if not settings or not settings.require_auth:
            return None

        if _is_public_request(request.path):
            return None

        client_identifier = request.remote_addr or "unknown"

        retry_after = failure_rate_limiter.retry_after(client_identifier)
        if retry_after:
            return _too_many_requests(retry_after)

        credentials = _parse_basic_credentials(request.headers.get("Authorization"))
        if credentials is None:
            return _unauthorized()

        username, password = credentials
        user = authenticate(username, password)
        if user is None:
            backoff = failure_rate_limiter.register_failure(client_identifier)
            response = _unauthorized("Invalid credentials.")
            if backoff:
                response.headers["Retry-After"] = str(backoff)
            return response

        failure_rate_limiter.register_success(client_identifier)
        g.current_user = user
        g.basic_auth_credentials = (username, password)
        return None


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


def _unauthorized(message: str | None = None) -> Response:
    response = Response(message or "Unauthorized", status=401)
    response.headers["WWW-Authenticate"] = f'Basic realm="{REALM}"'
    return response


def _too_many_requests(retry_after: int) -> Response:
    response = Response("Too Many Authentication Attempts", status=429)
    response.headers["Retry-After"] = str(retry_after)
    return response
