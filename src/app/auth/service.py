from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence, cast

from app.db_concurrency import commit_with_profile
from app.extensions import db
from app.models import User

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

    user = User(username=normalized_username, role=role)
    user.set_password(password)

    db.session.add(user)
    commit_with_profile(
        db.session, must_succeed=True, context="create_user", logger_obj=logger
    )
    return user


def change_password(user: User, current_password: str, new_password: str) -> None:
    if not user.verify_password(current_password):
        raise InvalidCredentialsError("Current password is incorrect.")

    update_password(user, new_password)


def update_password(user: User, new_password: str) -> None:
    user.set_password(new_password)
    db.session.add(user)
    commit_with_profile(
        db.session, must_succeed=True, context="update_password", logger_obj=logger
    )


def delete_user(user: User) -> None:
    if user.role == "admin" and _count_admins() <= 1:
        raise LastAdminRemovalError("Cannot remove the last admin user.")

    db.session.delete(user)
    commit_with_profile(
        db.session, must_succeed=True, context="delete_user", logger_obj=logger
    )


def set_role(user: User, role: str) -> None:
    if role not in ALLOWED_ROLES:
        raise AuthServiceError(f"Role must be one of {sorted(ALLOWED_ROLES)}.")

    if user.role == "admin" and role != "admin" and _count_admins() <= 1:
        raise LastAdminRemovalError("Cannot demote the last admin user.")

    user.role = role
    db.session.add(user)
    commit_with_profile(
        db.session, must_succeed=True, context="set_role", logger_obj=logger
    )


def _count_admins() -> int:
    return cast(int, User.query.filter_by(role="admin").count())
