from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import List, Tuple

import flask
from flask import Blueprint, current_app, g, jsonify, request
from sqlalchemy.exc import SQLAlchemyError

from app.credits import credits_enabled, get_balance, manual_adjust
from app.db_concurrency import commit_with_profile, pessimistic_write_lock
from app.extensions import db
from app.models import CreditTransaction, User

logger = logging.getLogger("global_logger")

credits_bp = Blueprint("credits", __name__)


def _require_enabled_user() -> Tuple[User | None, flask.Response | None]:
    if not credits_enabled():
        return None, flask.make_response(
            jsonify({"error": "Credits are disabled"}), 404
        )

    settings = current_app.config.get("AUTH_SETTINGS")
    if not settings or not settings.require_auth:
        return None, flask.make_response(
            jsonify({"error": "Authentication required."}), 401
        )

    current = getattr(g, "current_user", None)
    if current is None:
        return None, flask.make_response(
            jsonify({"error": "Authentication required."}), 401
        )

    user = db.session.get(User, current.id)
    if user is None:
        return None, flask.make_response(jsonify({"error": "User not found."}), 404)

    return user, None


def _require_admin() -> Tuple[User | None, flask.Response | None]:
    user, error = _require_enabled_user()
    if error:
        return None, error
    if user is None or user.role != "admin":
        return None, flask.make_response(
            jsonify({"error": "Admin privileges required."}),
            403,
        )
    return user, None


@credits_bp.route("/api/credits/balance", methods=["GET"])
def api_credits_balance() -> flask.Response:
    user, error = _require_enabled_user()
    if error:
        return error
    assert user is not None

    balance = get_balance(user)
    return flask.jsonify(
        {
            "username": user.username,
            "balance": str(balance),
        }
    )


@credits_bp.route("/api/credits/ledger", methods=["GET"])
def api_credits_ledger() -> flask.Response:
    user, error = _require_enabled_user()
    if error:
        return error
    assert user is not None

    requested_user_id = request.args.get("user_id", type=int)
    all_users = request.args.get("all", type=str, default="").lower() in (
        "1",
        "true",
        "yes",
    )

    # Admin can view all transactions or filter by user_id
    if user.role == "admin" and all_users:
        target_user_id = None  # No filter - all users
    elif user.role == "admin" and requested_user_id:
        target_user_id = requested_user_id
    else:
        target_user_id = user.id

    limit = request.args.get("limit", default=50, type=int) or 50
    limit = max(1, min(limit, 200))

    query = CreditTransaction.query.order_by(CreditTransaction.created_at.desc())
    if target_user_id is not None:
        query = query.filter_by(user_id=target_user_id)

    txns: List[CreditTransaction] = query.limit(limit).all()

    data = [
        {
            "id": txn.id,
            "user_id": txn.user_id,
            "username": txn.user.username if txn.user else None,
            "amount": str(txn.amount_signed),
            "type": txn.type,
            "note": txn.note,
            "feed_id": txn.feed_id,
            "post_id": txn.post_id,
            "idempotency_key": txn.idempotency_key,
            "created_at": txn.created_at.isoformat() if txn.created_at else None,
        }
        for txn in txns
    ]
    return flask.jsonify({"transactions": data, "user_id": target_user_id})


@credits_bp.route("/api/credits/manual-adjust", methods=["POST"])
def api_manual_adjust() -> flask.Response:
    admin_user, error = _require_admin()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    target_user_id = data.get("user_id")
    raw_amount = data.get("amount")
    note = data.get("note")

    if target_user_id is None or raw_amount is None:
        return flask.make_response(
            jsonify({"error": "user_id and amount are required"}), 400
        )

    target_user = db.session.get(User, target_user_id)
    if target_user is None:
        return flask.make_response(jsonify({"error": "Target user not found"}), 404)

    try:
        amount_signed = Decimal(str(raw_amount))
    except (InvalidOperation, ValueError):
        return flask.make_response(jsonify({"error": "Invalid amount"}), 400)

    try:
        # Credits/ledger updates must succeed atomically; serialize writes.
        with pessimistic_write_lock():
            txn, balance = manual_adjust(
                user=target_user, amount_signed=amount_signed, note=note
            )
            commit_with_profile(
                db.session,
                must_succeed=True,
                context="manual_adjust_credits",
                logger_obj=logger,
            )
    except SQLAlchemyError:
        db.session.rollback()
        return flask.make_response(jsonify({"error": "Failed to update credits"}), 500)

    return flask.jsonify(
        {
            "transaction": {
                "id": txn.id,
                "amount": str(txn.amount_signed),
                "type": txn.type,
                "note": txn.note,
                "created_at": txn.created_at.isoformat() if txn.created_at else None,
            },
            "user_id": target_user.id,
            "balance": str(balance),
            "updated_by": admin_user.username if admin_user else None,
        }
    )
