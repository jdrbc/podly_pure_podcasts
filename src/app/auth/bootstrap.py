from __future__ import annotations

import logging

from flask import current_app

from app.db_concurrency import commit_with_profile, pessimistic_write_lock
from app.extensions import db
from app.models import User

from .settings import AuthSettings

logger = logging.getLogger("global_logger")


def bootstrap_admin_user(auth_settings: AuthSettings) -> None:
    """Ensure an administrator user exists when auth is required."""
    logger.info("Bootstrapping admin user...")

    if not auth_settings.require_auth:
        return

    # Avoid seeding if users already exist.
    current_admin = db.session.query(User.id).limit(1).first()
    if current_admin is not None:
        logger.info("Admin user already exists; skipping bootstrap.")
        return

    password = auth_settings.admin_password
    if not password:
        logger.error(
            "REQUIRE_AUTH=true but PODLY_ADMIN_PASSWORD is missing during bootstrap."
        )
        raise RuntimeError(
            "Authentication bootstrap failed: PODLY_ADMIN_PASSWORD is required."
        )

    username = auth_settings.admin_username
    user = User(username=username, role="admin")
    user.set_password(password)

    with pessimistic_write_lock():
        db.session.add(user)
        commit_with_profile(
            db.session,
            must_succeed=True,
            context="bootstrap_admin_user",
            logger_obj=logger,
        )

    logger.info(
        "Bootstrapped initial admin user '%s'. Ensure environment secrets are stored securely.",
        username,
    )

    # Clear the password from the Flask config if it was set to avoid lingering plaintext.
    current_app.config.pop("PODLY_ADMIN_PASSWORD", None)
