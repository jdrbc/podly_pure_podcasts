from __future__ import annotations

import bcrypt


def hash_password(password: str, *, rounds: int = 12) -> str:
    """Hash a password using bcrypt with the provided work factor."""
    salt = bcrypt.gensalt(rounds)
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Verify the provided password against the stored bcrypt hash."""
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except ValueError:
        return False
