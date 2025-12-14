from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    request,
    session,
)

from app.auth.discord_service import (
    DiscordAuthError,
    DiscordRegistrationDisabledError,
    build_authorization_url,
    check_guild_membership,
    exchange_code_for_token,
    find_or_create_user_from_discord,
    generate_oauth_state,
    get_discord_user,
)
from app.auth.discord_settings import reload_discord_settings
from app.auth.guards import require_admin
from app.writer.client import writer_client

if TYPE_CHECKING:
    from app.auth.discord_settings import DiscordSettings

logger = logging.getLogger("global_logger")

discord_bp = Blueprint("discord", __name__)

SESSION_OAUTH_STATE_KEY = "discord_oauth_state"
SESSION_USER_KEY = "user_id"
SESSION_OAUTH_PROMPT_UPGRADED = "discord_prompt_upgraded"


def _get_discord_settings() -> DiscordSettings | None:
    return current_app.config.get("DISCORD_SETTINGS")


def _mask_secret(value: str | None) -> str | None:
    """Mask a secret value for display."""
    if not value:
        return None
    if len(value) <= 8:
        return value
    return f"{value[:4]}...{value[-4:]}"


def _has_env_override(env_var: str) -> bool:
    """Check if an environment variable is set."""
    return bool(os.environ.get(env_var))


@discord_bp.route("/api/auth/discord/status", methods=["GET"])
def discord_status() -> Response:
    """Return whether Discord SSO is enabled."""
    settings = _get_discord_settings()
    return jsonify(
        {
            "enabled": settings.enabled if settings else False,
        }
    )


@discord_bp.route("/api/auth/discord/config", methods=["GET"])
def discord_config_get() -> Response | tuple[Response, int]:
    """Get Discord configuration (admin only)."""
    _, error_response = require_admin()
    if error_response:
        return error_response, error_response.status_code

    settings = _get_discord_settings()

    # Build env override info
    env_overrides: dict[str, dict[str, str]] = {}
    if _has_env_override("DISCORD_CLIENT_ID"):
        env_overrides["client_id"] = {"env_var": "DISCORD_CLIENT_ID"}
    if _has_env_override("DISCORD_CLIENT_SECRET"):
        env_overrides["client_secret"] = {
            "env_var": "DISCORD_CLIENT_SECRET",
            "is_secret": "true",
        }
    if _has_env_override("DISCORD_REDIRECT_URI"):
        env_overrides["redirect_uri"] = {
            "env_var": "DISCORD_REDIRECT_URI",
            "value": os.environ.get("DISCORD_REDIRECT_URI", ""),
        }
    if _has_env_override("DISCORD_GUILD_IDS"):
        env_overrides["guild_ids"] = {
            "env_var": "DISCORD_GUILD_IDS",
            "value": os.environ.get("DISCORD_GUILD_IDS", ""),
        }
    if _has_env_override("DISCORD_ALLOW_REGISTRATION"):
        env_overrides["allow_registration"] = {
            "env_var": "DISCORD_ALLOW_REGISTRATION",
            "value": os.environ.get("DISCORD_ALLOW_REGISTRATION", ""),
        }

    return jsonify(
        {
            "config": {
                "enabled": settings.enabled if settings else False,
                "client_id": settings.client_id if settings else None,
                "client_secret_preview": (
                    _mask_secret(settings.client_secret) if settings else None
                ),
                "redirect_uri": settings.redirect_uri if settings else None,
                "guild_ids": (
                    ",".join(settings.guild_ids)
                    if settings and settings.guild_ids
                    else ""
                ),
                "allow_registration": settings.allow_registration if settings else True,
            },
            "env_overrides": env_overrides,
        }
    )


@discord_bp.route("/api/auth/discord/config", methods=["PUT"])
def discord_config_put() -> Response | tuple[Response, int]:
    """Update Discord configuration (admin only)."""
    _, error_response = require_admin()
    if error_response:
        return error_response, error_response.status_code

    payload = request.get_json(silent=True) or {}

    try:
        update_params: dict[str, object] = {}

        if "client_id" in payload and not _has_env_override("DISCORD_CLIENT_ID"):
            update_params["client_id"] = payload["client_id"] or None

        if "client_secret" in payload and not _has_env_override(
            "DISCORD_CLIENT_SECRET"
        ):
            secret = payload["client_secret"]
            if secret and not str(secret).endswith("..."):
                update_params["client_secret"] = secret

        if "redirect_uri" in payload and not _has_env_override("DISCORD_REDIRECT_URI"):
            update_params["redirect_uri"] = payload["redirect_uri"] or None

        if "guild_ids" in payload and not _has_env_override("DISCORD_GUILD_IDS"):
            update_params["guild_ids"] = payload["guild_ids"] or None

        if "allow_registration" in payload and not _has_env_override(
            "DISCORD_ALLOW_REGISTRATION"
        ):
            update_params["allow_registration"] = bool(payload["allow_registration"])

        if update_params:
            result = writer_client.action(
                "update_discord_settings", update_params, wait=True
            )
            if not result or not result.success:
                raise RuntimeError(getattr(result, "error", "Writer update failed"))

        # Reload settings into app config
        new_settings = reload_discord_settings(current_app)

        logger.info("Discord settings updated (enabled=%s)", new_settings.enabled)

        return jsonify(
            {
                "status": "ok",
                "config": {
                    "enabled": new_settings.enabled,
                    "client_id": new_settings.client_id,
                    "client_secret_preview": _mask_secret(new_settings.client_secret),
                    "redirect_uri": new_settings.redirect_uri,
                    "guild_ids": (
                        ",".join(new_settings.guild_ids)
                        if new_settings.guild_ids
                        else ""
                    ),
                    "allow_registration": new_settings.allow_registration,
                },
            }
        )

    except Exception as e:
        logger.exception("Failed to update Discord settings: %s", e)
        return jsonify({"error": "Failed to update Discord settings"}), 500


@discord_bp.route("/api/auth/discord/login", methods=["GET"])
def discord_login() -> Response | tuple[Response, int]:
    """Start the Discord OAuth2 flow by returning the authorization URL."""
    settings = _get_discord_settings()
    if not settings or not settings.enabled:
        return jsonify({"error": "Discord SSO is not configured."}), 404

    prompt = request.args.get("prompt", "none")
    state = generate_oauth_state()
    session[SESSION_OAUTH_STATE_KEY] = state
    session[SESSION_OAUTH_PROMPT_UPGRADED] = prompt == "consent"

    auth_url = build_authorization_url(settings, state, prompt=prompt)
    return jsonify({"authorization_url": auth_url})


@discord_bp.route("/api/auth/discord/callback", methods=["GET"])
def discord_callback() -> Response:
    """Handle the OAuth2 callback from Discord."""
    settings = _get_discord_settings()
    if not settings or not settings.enabled:
        return Response(
            response="",
            status=302,
            headers={"Location": "/?error=discord_not_configured"},
        )

    # Verify state to prevent CSRF
    state = request.args.get("state")
    expected_state = session.pop(SESSION_OAUTH_STATE_KEY, None)
    if not state or state != expected_state:
        return Response(
            response="", status=302, headers={"Location": "/?error=invalid_state"}
        )

    # Check for error from Discord (e.g., user denied access)
    error = request.args.get("error")
    if error:
        if error in {"interaction_required", "login_required", "consent_required"}:
            # Try again with an explicit consent prompt (only once) to avoid loops.
            if not session.get(SESSION_OAUTH_PROMPT_UPGRADED):
                new_state = generate_oauth_state()
                session[SESSION_OAUTH_STATE_KEY] = new_state
                session[SESSION_OAUTH_PROMPT_UPGRADED] = True
                auth_url = build_authorization_url(
                    settings, new_state, prompt="consent"
                )
                return Response(response="", status=302, headers={"Location": auth_url})

        return Response(
            response="", status=302, headers={"Location": f"/?error={error}"}
        )

    code = request.args.get("code")
    if not code:
        return Response(
            response="", status=302, headers={"Location": "/?error=missing_code"}
        )

    try:
        # Exchange code for token
        token_data = exchange_code_for_token(settings, code)
        access_token = token_data["access_token"]

        # Get Discord user info
        discord_user = get_discord_user(access_token)

        # Check guild requirements if configured
        if settings.guild_ids:
            is_allowed = check_guild_membership(access_token, settings)
            if not is_allowed:
                return Response(
                    response="",
                    status=302,
                    headers={"Location": "/?error=guild_requirement_not_met"},
                )

        # Find or create user
        user = find_or_create_user_from_discord(discord_user, settings)

        # Create session
        session.clear()
        session[SESSION_USER_KEY] = user.id
        session.permanent = True
        session.pop(SESSION_OAUTH_PROMPT_UPGRADED, None)

        logger.info(
            "Discord SSO login successful for user %s (discord_id=%s)",
            user.username,
            discord_user.id,
        )
        return Response(response="", status=302, headers={"Location": "/"})

    except DiscordRegistrationDisabledError:
        return Response(
            response="",
            status=302,
            headers={"Location": "/?error=registration_disabled"},
        )
    except DiscordAuthError as e:
        logger.warning("Discord auth error: %s", e)
        return Response(
            response="", status=302, headers={"Location": "/?error=auth_failed"}
        )
    except Exception as e:
        logger.exception("Discord auth failed unexpectedly: %s", e)
        return Response(
            response="", status=302, headers={"Location": "/?error=auth_failed"}
        )
