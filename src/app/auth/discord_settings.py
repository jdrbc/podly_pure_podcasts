from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask

    from app.models import DiscordSettings as DiscordSettingsModel


@dataclass(slots=True, frozen=True)
class DiscordSettings:
    enabled: bool
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None
    guild_ids: list[str]
    allow_registration: bool


def load_discord_settings() -> DiscordSettings:
    """Load Discord OAuth2 settings from environment variables and database.

    Environment variables take precedence over database values.
    """
    # Try to load from database first
    db_settings = _load_from_database()

    # Environment variables override database values
    client_id = os.environ.get("DISCORD_CLIENT_ID") or (
        db_settings.client_id if db_settings else None
    )
    client_secret = os.environ.get("DISCORD_CLIENT_SECRET") or (
        db_settings.client_secret if db_settings else None
    )
    redirect_uri = os.environ.get("DISCORD_REDIRECT_URI") or (
        db_settings.redirect_uri if db_settings else None
    )

    enabled = bool(client_id and client_secret and redirect_uri)

    # Guild IDs: env var takes precedence
    guild_ids_env = os.environ.get("DISCORD_GUILD_IDS", "")
    if guild_ids_env:
        guild_ids = [g.strip() for g in guild_ids_env.split(",") if g.strip()]
    elif db_settings and db_settings.guild_ids:
        guild_ids = [g.strip() for g in db_settings.guild_ids.split(",") if g.strip()]
    else:
        guild_ids = []

    # Allow registration: env var takes precedence
    allow_reg_env = os.environ.get("DISCORD_ALLOW_REGISTRATION")
    if allow_reg_env is not None:
        allow_registration = allow_reg_env.lower() in ("true", "1", "yes")
    elif db_settings is not None:
        allow_registration = db_settings.allow_registration
    else:
        allow_registration = True

    return DiscordSettings(
        enabled=enabled,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        guild_ids=guild_ids,
        allow_registration=allow_registration,
    )


def _load_from_database() -> "DiscordSettingsModel | None":
    """Load Discord settings from database, returns None if not available."""
    try:
        from app.extensions import db
        from app.models import DiscordSettings as DiscordSettingsModel

        return db.session.get(DiscordSettingsModel, 1)
    except Exception:
        # Database not initialized or table doesn't exist yet
        return None


def reload_discord_settings(app: "Flask") -> DiscordSettings:
    """Reload Discord settings and update app config."""
    settings = load_discord_settings()
    app.config["DISCORD_SETTINGS"] = settings
    return settings
