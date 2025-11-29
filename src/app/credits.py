from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Optional, Tuple, cast

from flask import current_app
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import CreditTransaction, Feed, Post, User
from app.runtime_config import config
from podcast_processor.audio import get_audio_duration_ms
from shared import defaults as DEFAULTS

logger = logging.getLogger("global_logger")


class CreditsError(Exception):
    """Base credits error."""


class CreditsDisabledError(CreditsError):
    """Raised when credits are not enabled."""


class InsufficientCreditsError(CreditsError):
    """Raised when balance would drop below zero and blocking is enabled."""


@dataclass(frozen=True, slots=True)
class DebitResult:
    transaction: CreditTransaction
    balance: Decimal
    estimated_minutes: float
    estimated_credits: Decimal


def credits_enabled() -> bool:
    settings = current_app.config.get("AUTH_SETTINGS")
    # Credits feature is always on when authentication is required; off when auth is disabled.
    return bool(settings and settings.require_auth)


def resolve_sponsor_user(feed: Feed) -> Optional[User]:
    """Return the sponsor for a feed, falling back to the first admin if missing."""
    if feed.sponsor_user_id:
        user = cast(Optional[User], User.query.get(feed.sponsor_user_id))
        if user:
            return user
    return cast(
        Optional[User],
        User.query.filter_by(role="admin").order_by(User.id.asc()).first(),
    )


def estimate_minutes_from_unprocessed(path: Optional[str]) -> float:
    """Estimate duration in minutes using the unprocessed/original audio file."""
    if path:
        duration_ms = get_audio_duration_ms(path)
        if duration_ms:
            return max(1.0, duration_ms / 1000.0 / 60.0)
    # Fallback to 60 minutes if we cannot determine duration.
    return 60.0


def _credits_from_minutes(minutes: float) -> Decimal:
    minutes_per_credit = (
        getattr(config, "minutes_per_credit", DEFAULTS.MINUTES_PER_CREDIT)
        or DEFAULTS.MINUTES_PER_CREDIT
    )
    credits = Decimal(minutes / float(minutes_per_credit)).quantize(
        Decimal("0.1"), rounding=ROUND_DOWN
    )
    # Ensure we always charge at least a tenth of a credit for non-zero durations.
    if credits <= 0:
        return Decimal("0.1")
    return credits


def _existing_transaction(idempotency_key: str) -> Optional[CreditTransaction]:
    if not idempotency_key:
        return None
    return cast(
        Optional[CreditTransaction],
        CreditTransaction.query.filter_by(idempotency_key=idempotency_key).first(),
    )


def apply_transaction(
    *,
    user: User,
    amount_signed: Decimal,
    type: str,
    feed: Optional[Feed] = None,
    post: Optional[Post] = None,
    idempotency_key: Optional[str] = None,
    note: Optional[str] = None,
) -> Tuple[CreditTransaction, Decimal]:
    """
    Apply a signed delta to the user's balance and append a transaction.
    Keeps the write short to avoid long SQLite locks.
    """
    session = db.session

    if idempotency_key:
        existing = _existing_transaction(idempotency_key)
        if existing:
            refreshed_user = cast(Optional[User], session.get(User, existing.user_id))
            balance = (
                Decimal(refreshed_user.credits_balance or 0)
                if refreshed_user
                else Decimal("0")
            )
            return existing, balance

    amount_signed = amount_signed.quantize(Decimal("0.1"))

    try:
        locked_user = (
            session.query(User)
            .filter_by(id=user.id)
            .with_for_update(nowait=False)
            .first()
        )
        if locked_user is None:
            raise CreditsError("User missing while applying transaction")

        current_balance = Decimal(locked_user.credits_balance or 0)
        if (current_balance + amount_signed) < Decimal(0):
            raise InsufficientCreditsError("Insufficient credits for this operation")

        locked_user.credits_balance = current_balance + amount_signed

        txn = CreditTransaction(
            user_id=locked_user.id,
            feed_id=getattr(feed, "id", None),
            post_id=getattr(post, "id", None),
            idempotency_key=idempotency_key,
            amount_signed=amount_signed,
            type=type,
            note=note,
        )
        session.add(txn)
        session.flush()
        return txn, Decimal(locked_user.credits_balance or 0)
    except InsufficientCreditsError:
        session.rollback()
        raise
    except IntegrityError as exc:
        session.rollback()
        logger.warning("Integrity error applying credits transaction: %s", exc)
        existing = _existing_transaction(idempotency_key) if idempotency_key else None
        if existing:
            refreshed_user = cast(Optional[User], session.get(User, existing.user_id))
            balance = (
                Decimal(refreshed_user.credits_balance or 0)
                if refreshed_user
                else Decimal("0")
            )
            return existing, balance
        raise


def debit_for_post(
    *,
    feed: Feed,
    post: Post,
    job_id: str,
    unprocessed_audio_path: Optional[str],
) -> DebitResult:
    """Debit credits for a post based on its unprocessed audio duration."""
    if not credits_enabled():
        raise CreditsDisabledError("Credits are disabled")

    sponsor = resolve_sponsor_user(feed)
    if sponsor is None:
        raise CreditsError("No sponsor or admin available for this feed")

    minutes = estimate_minutes_from_unprocessed(unprocessed_audio_path)
    credits_needed = _credits_from_minutes(minutes)

    txn, balance = apply_transaction(
        user=sponsor,
        feed=feed,
        post=post,
        amount_signed=-credits_needed,
        type="debit",
        idempotency_key=f"debit:{post.guid}:{job_id}",
        note="Episode processing debit",
    )

    return DebitResult(
        transaction=txn,
        balance=balance,
        estimated_minutes=minutes,
        estimated_credits=credits_needed,
    )


def manual_adjust(
    *, user: User, amount_signed: Decimal, note: Optional[str]
) -> Tuple[CreditTransaction, Decimal]:
    return apply_transaction(
        user=user, amount_signed=amount_signed, type="manual_adjust", note=note
    )


def get_balance(user: User) -> Decimal:
    return Decimal(user.credits_balance or 0)
