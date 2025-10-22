from __future__ import annotations

import os
from dataclasses import dataclass, replace


def _str_to_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    lowered = value.strip().lower()
    return lowered in {"1", "true", "t", "yes", "y", "on"}


@dataclass(slots=True, frozen=True)
class AuthSettings:
    """Runtime authentication configuration derived from environment variables."""

    require_auth: bool
    admin_username: str
    admin_password: str | None

    @property
    def admin_password_required(self) -> bool:
        return self.require_auth

    def without_password(self) -> "AuthSettings":
        """Return a copy with the password removed to avoid retaining plaintext."""
        return replace(self, admin_password=None)


def load_auth_settings() -> AuthSettings:
    """Load authentication settings from environment variables."""
    require_auth = _str_to_bool(os.environ.get("REQUIRE_AUTH"), default=False)
    admin_username = os.environ.get("PODLY_ADMIN_USERNAME", "podly_admin").strip()
    admin_password = os.environ.get("PODLY_ADMIN_PASSWORD")

    if require_auth:
        if not admin_username:
            raise RuntimeError(
                "PODLY_ADMIN_USERNAME must be set to a non-empty value when "
                "REQUIRE_AUTH=true."
            )
        if admin_password is None:
            raise RuntimeError(
                "PODLY_ADMIN_PASSWORD must be provided when REQUIRE_AUTH=true."
            )

    return AuthSettings(
        require_auth=require_auth,
        admin_username=admin_username or "podly_admin",
        admin_password=admin_password,
    )
