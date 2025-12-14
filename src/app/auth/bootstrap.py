from __future__ import annotations

import logging

from flask import current_app

from app.db_commit import safe_commit
from app.extensions import db
from app.models import User
from app.writer.client import writer_client

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
    role = current_app.config.get("PODLY_APP_ROLE")
    if role == "writer":
        user = User(username=username, role="admin")
        user.set_password(password)

        db.session.add(user)
        safe_commit(
            db.session,
            must_succeed=True,
            context="bootstrap_admin_user",
            logger_obj=logger,
        )
    else:
        res = writer_client.action(
            "create_user",
            {"username": username, "password": password, "role": "admin"},
            wait=True,
        )
        if not res or not res.success:
            # If another process created the admin concurrently, treat as success.
            if "already exists" not in str(getattr(res, "error", "")):
                raise RuntimeError(
                    getattr(res, "error", "Failed to bootstrap admin user")
                )

    logger.info(
        "Bootstrapped initial admin user '%s'. Ensure environment secrets are stored securely.",
        username,
    )

    # Clear the password from the Flask config if it was set to avoid lingering plaintext.
    current_app.config.pop("PODLY_ADMIN_PASSWORD", None)
