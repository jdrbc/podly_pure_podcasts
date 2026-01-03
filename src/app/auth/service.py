from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence, cast

from app.extensions import db
from app.models import User
from app.runtime_config import config as runtime_config
from app.writer.client import writer_client

logger = logging.getLogger("global_logger")


class AuthServiceError(Exception):
    """Base class for authentication domain errors."""


class InvalidCredentialsError(AuthServiceError):
    """Raised when provided credentials are invalid."""


class PasswordValidationError(AuthServiceError):
    """Raised when a password fails strength validation."""


class DuplicateUserError(AuthServiceError):
    """Raised when attempting to create a user with an existing username."""


class LastAdminRemovalError(AuthServiceError):
    """Raised when deleting or demoting the final admin user."""


class UserLimitExceededError(AuthServiceError):
    """Raised when creating a user would exceed the configured limit."""


ALLOWED_ROLES: set[str] = {"admin", "user"}


@dataclass(slots=True)
class AuthenticatedUser:
    id: int
    username: str
    role: str


def _normalize_username(username: str) -> str:
    return username.strip().lower()


def authenticate(username: str, password: str) -> AuthenticatedUser | None:
    user = User.query.filter_by(username=_normalize_username(username)).first()
    if user is None:
        return None
    if not user.verify_password(password):
        return None
    return AuthenticatedUser(id=user.id, username=user.username, role=user.role)


def list_users() -> Sequence[User]:
    return cast(
        Sequence[User],
        User.query.order_by(User.created_at.desc(), User.id.desc()).all(),
    )


def create_user(username: str, password: str, role: str = "user") -> User:
    normalized_username = _normalize_username(username)
    if not normalized_username:
        raise AuthServiceError("Username is required.")

    if role not in ALLOWED_ROLES:
        raise AuthServiceError(f"Role must be one of {sorted(ALLOWED_ROLES)}.")

    if User.query.filter_by(username=normalized_username).first():
        raise DuplicateUserError("A user with that username already exists.")

    _enforce_user_limit()

    result = writer_client.action(
        "create_user",
        {"username": normalized_username, "password": password, "role": role},
        wait=True,
    )
    if not result or not result.success or not isinstance(result.data, dict):
        raise AuthServiceError(getattr(result, "error", "Failed to create user"))

    user_id = int(result.data["user_id"])
    user = db.session.get(User, user_id)
    if user is None:
        raise AuthServiceError("User created but not found")
    return user


def change_password(user: User, current_password: str, new_password: str) -> None:
    if not user.verify_password(current_password):
        raise InvalidCredentialsError("Current password is incorrect.")

    update_password(user, new_password)


def update_password(user: User, new_password: str) -> None:
    result = writer_client.action(
        "update_user_password",
        {"user_id": user.id, "new_password": new_password},
        wait=True,
    )
    if not result or not result.success:
        raise AuthServiceError(getattr(result, "error", "Failed to update password"))
    db.session.expire(user)


def delete_user(user: User) -> None:
    if user.role == "admin" and _count_admins() <= 1:
        raise LastAdminRemovalError("Cannot remove the last admin user.")

    result = writer_client.action("delete_user", {"user_id": user.id}, wait=True)
    if not result or not result.success:
        raise AuthServiceError(getattr(result, "error", "Failed to delete user"))


def set_role(user: User, role: str) -> None:
    if role not in ALLOWED_ROLES:
        raise AuthServiceError(f"Role must be one of {sorted(ALLOWED_ROLES)}.")

    if user.role == "admin" and role != "admin" and _count_admins() <= 1:
        raise LastAdminRemovalError("Cannot demote the last admin user.")

    result = writer_client.action(
        "set_user_role", {"user_id": user.id, "role": role}, wait=True
    )
    if not result or not result.success:
        raise AuthServiceError(getattr(result, "error", "Failed to set role"))
    db.session.expire(user)


def set_manual_feed_allowance(user: User, allowance: int | None) -> None:
    result = writer_client.action(
        "set_manual_feed_allowance",
        {"user_id": user.id, "allowance": allowance},
        wait=True,
    )
    if not result or not result.success:
        raise AuthServiceError(getattr(result, "error", "Failed to set allowance"))
    db.session.expire(user)


def update_user_last_active(user_id: int) -> None:
    """Update the last_active timestamp for a user."""
    writer_client.action(
        "update_user_last_active",
        {"user_id": user_id},
        wait=False,
    )


def _count_admins() -> int:
    return cast(int, User.query.filter_by(role="admin").count())


def _enforce_user_limit() -> None:
    """Prevent creating users beyond the configured total limit.

    Limit applies only when authentication is enabled; a non-positive or
    missing limit means unlimited users.
    """

    try:
        limit = getattr(runtime_config, "user_limit_total", None)
    except Exception:  # pragma: no cover - defensive
        limit = None

    if limit is None:
        return

    try:
        limit_int = int(limit)
    except Exception:
        return

    if limit_int < 0:
        return

    current_total = cast(int, User.query.count())
    if limit_int == 0 or current_total >= limit_int:
        raise UserLimitExceededError(
            f"User limit reached ({current_total}/{limit_int}). Delete a user or increase the limit."
        )
