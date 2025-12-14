from typing import Any, Dict

from app.extensions import db
from app.models import User


def create_user_action(params: Dict[str, Any]) -> Dict[str, Any]:
    username = (params.get("username") or "").strip().lower()
    password = params.get("password")
    role = params.get("role") or "user"

    if not username:
        raise ValueError("username is required")
    if not isinstance(password, str) or not password:
        raise ValueError("password is required")
    if role not in {"admin", "user"}:
        raise ValueError("role must be 'admin' or 'user'")
    if User.query.filter_by(username=username).first():
        raise ValueError("A user with that username already exists")

    user = User(username=username, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    return {"user_id": user.id}


def update_user_password_action(params: Dict[str, Any]) -> Dict[str, Any]:
    user_id = params.get("user_id")
    new_password = params.get("new_password")
    if not user_id:
        raise ValueError("user_id is required")
    if not isinstance(new_password, str) or not new_password:
        raise ValueError("new_password is required")

    user = db.session.get(User, int(user_id))
    if not user:
        raise ValueError(f"User {user_id} not found")

    user.set_password(new_password)
    db.session.flush()
    return {"user_id": user.id}


def delete_user_action(params: Dict[str, Any]) -> Dict[str, Any]:
    user_id = params.get("user_id")
    if not user_id:
        raise ValueError("user_id is required")
    user = db.session.get(User, int(user_id))
    if not user:
        return {"deleted": False}
    db.session.delete(user)
    return {"deleted": True}


def set_user_role_action(params: Dict[str, Any]) -> Dict[str, Any]:
    user_id = params.get("user_id")
    role = params.get("role")
    if not user_id or not role:
        raise ValueError("user_id and role are required")
    if role not in {"admin", "user"}:
        raise ValueError("role must be 'admin' or 'user'")
    user = db.session.get(User, int(user_id))
    if not user:
        raise ValueError(f"User {user_id} not found")
    user.role = role
    db.session.flush()
    return {"user_id": user.id}


def set_manual_feed_allowance_action(params: Dict[str, Any]) -> Dict[str, Any]:
    user_id = params.get("user_id")
    allowance = params.get("allowance")

    if not user_id:
        raise ValueError("user_id is required")

    user = db.session.get(User, int(user_id))
    if not user:
        raise ValueError(f"User {user_id} not found")

    if allowance is None:
        user.manual_feed_allowance = None
    else:
        try:
            user.manual_feed_allowance = int(allowance)
        except (ValueError, TypeError) as exc:
            raise ValueError("allowance must be an integer or None") from exc

    db.session.flush()
    return {"user_id": user.id}


def upsert_discord_user_action(params: Dict[str, Any]) -> Dict[str, Any]:
    discord_id = params.get("discord_id")
    discord_username = params.get("discord_username")
    allow_registration = bool(params.get("allow_registration", True))

    if not discord_id or not discord_username:
        raise ValueError("discord_id and discord_username are required")

    existing_user: User | None = User.query.filter_by(
        discord_id=str(discord_id)
    ).first()
    if existing_user:
        existing_user.discord_username = str(discord_username)
        db.session.flush()
        return {"user_id": existing_user.id, "created": False}

    if not allow_registration:
        raise ValueError("Self-registration via Discord is disabled")

    base_username = str(discord_username).lower().replace(" ", "_")[:50]
    username = base_username
    counter = 1
    while User.query.filter_by(username=username).first():
        username = f"{base_username}_{counter}"
        counter += 1

    new_user = User(
        username=username,
        password_hash="",
        role="user",
        discord_id=str(discord_id),
        discord_username=str(discord_username),
    )
    db.session.add(new_user)
    db.session.flush()
    return {"user_id": new_user.id, "created": True}


def set_user_billing_fields_action(params: Dict[str, Any]) -> Dict[str, Any]:
    user_id = params.get("user_id")
    if not user_id:
        raise ValueError("user_id is required")

    user = db.session.get(User, int(user_id))
    if not user:
        raise ValueError(f"User {user_id} not found")

    if "stripe_customer_id" in params:
        user.stripe_customer_id = params.get("stripe_customer_id")
    if "stripe_subscription_id" in params:
        user.stripe_subscription_id = params.get("stripe_subscription_id")
    if "feed_allowance" in params:
        user.feed_allowance = int(params.get("feed_allowance") or 0)
    if "feed_subscription_status" in params:
        user.feed_subscription_status = params.get("feed_subscription_status") or ""

    db.session.flush()
    return {"user_id": user.id}


def set_user_billing_by_customer_id_action(params: Dict[str, Any]) -> Dict[str, Any]:
    customer_id = params.get("stripe_customer_id")
    if not customer_id:
        raise ValueError("stripe_customer_id is required")

    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    if not user:
        return {"updated": False}

    if "stripe_subscription_id" in params:
        user.stripe_subscription_id = params.get("stripe_subscription_id")
    if "feed_allowance" in params:
        user.feed_allowance = int(params.get("feed_allowance") or 0)
    if "feed_subscription_status" in params:
        user.feed_subscription_status = params.get("feed_subscription_status") or ""

    db.session.flush()
    return {"updated": True, "user_id": user.id}
