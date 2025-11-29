from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.auth.discord_settings import DiscordSettings
from app.extensions import db
from app.models import User

DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_OAUTH2_AUTHORIZE = "https://discord.com/oauth2/authorize"
DISCORD_OAUTH2_TOKEN = "https://discord.com/api/oauth2/token"


class DiscordAuthError(Exception):
    """Base error for Discord auth failures."""


class DiscordGuildRequirementError(DiscordAuthError):
    """User is not in required guild(s)."""


class DiscordRegistrationDisabledError(DiscordAuthError):
    """Self-registration is disabled."""


@dataclass
class DiscordUser:
    id: str
    username: str


def generate_oauth_state() -> str:
    """Generate a secure random state parameter for OAuth2."""
    return secrets.token_urlsafe(32)


def build_authorization_url(settings: DiscordSettings, state: str) -> str:
    """Build the Discord OAuth2 authorization URL."""
    scopes = ["identify"]
    if settings.guild_ids:
        scopes.append("guilds")

    params = {
        "client_id": settings.client_id,
        "redirect_uri": settings.redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }
    return f"{DISCORD_OAUTH2_AUTHORIZE}?{urlencode(params)}"


def exchange_code_for_token(settings: DiscordSettings, code: str) -> dict[str, Any]:
    """Exchange an authorization code for an access token (synchronous)."""
    with httpx.Client() as client:
        response = client.post(
            DISCORD_OAUTH2_TOKEN,
            data={
                "client_id": settings.client_id,
                "client_secret": settings.client_secret,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result


def get_discord_user(access_token: str) -> DiscordUser:
    """Fetch Discord user info using an access token (synchronous)."""
    with httpx.Client() as client:
        response = client.get(
            f"{DISCORD_API_BASE}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        data = response.json()
        return DiscordUser(
            id=data["id"],
            username=data["username"],
        )


def check_guild_membership(access_token: str, settings: DiscordSettings) -> bool:
    """Check if user is in any of the required guilds (synchronous)."""
    if not settings.guild_ids:
        return True

    with httpx.Client() as client:
        response = client.get(
            f"{DISCORD_API_BASE}/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        user_guilds = {g["id"] for g in response.json()}

        return any(gid in user_guilds for gid in settings.guild_ids)


def find_or_create_user_from_discord(
    discord_user: DiscordUser,
    settings: DiscordSettings,
) -> User:
    """Find an existing user by Discord ID or create a new one."""
    # Check if user exists by Discord ID
    existing_user: User | None = User.query.filter_by(discord_id=discord_user.id).first()
    if existing_user:
        # Update Discord username (it can change)
        existing_user.discord_username = discord_user.username
        db.session.commit()
        return existing_user

    # Create new user
    if not settings.allow_registration:
        raise DiscordRegistrationDisabledError(
            "Self-registration via Discord is disabled."
        )

    # Generate unique username from Discord username
    base_username = discord_user.username.lower().replace(" ", "_")[:50]
    username = base_username
    counter = 1
    while User.query.filter_by(username=username).first():
        username = f"{base_username}_{counter}"
        counter += 1

    new_user = User(
        username=username,
        password_hash="",  # No password for Discord-only users
        role="user",
        discord_id=discord_user.id,
        discord_username=discord_user.username,
    )
    db.session.add(new_user)
    db.session.commit()
    return new_user
