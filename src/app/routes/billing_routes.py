import logging
import os
from typing import Any, Optional

from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models import User, UserFeed
from app.writer.client import writer_client

from .auth_routes import _require_authenticated_user

logger = logging.getLogger("global_logger")

billing_bp = Blueprint("billing", __name__)


def _get_stripe_client() -> tuple[Optional[Any], Optional[str]]:
    secret = os.getenv("STRIPE_SECRET_KEY")
    if not secret:
        return None, "Stripe secret key missing"
    try:
        import stripe
    except ImportError:
        return None, "Stripe library not installed"
    stripe.api_key = secret
    return stripe, None


def _product_id() -> Optional[str]:
    return os.getenv("STRIPE_PRODUCT_ID")


def _min_subscription_amount_cents() -> int:
    """Minimum non-zero subscription amount in cents.

    Allow 0 to cancel, otherwise enforce this minimum.
    Configurable via STRIPE_MIN_SUBSCRIPTION_AMOUNT_CENTS.
    """

    raw = os.getenv("STRIPE_MIN_SUBSCRIPTION_AMOUNT_CENTS")
    if raw is None or raw == "":
        return 100
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Invalid STRIPE_MIN_SUBSCRIPTION_AMOUNT_CENTS=%r; defaulting to 100",
            raw,
        )
        return 100
    return max(0, value)


def _user_feed_usage(user: User) -> dict[str, int]:
    feeds_in_use = UserFeed.query.filter_by(user_id=user.id).count()
    allowance = getattr(user, "manual_feed_allowance", None)
    if allowance is None:
        allowance = getattr(user, "feed_allowance", 0) or 0
    remaining = max(0, allowance - feeds_in_use)
    return {
        "feed_allowance": allowance,
        "feeds_in_use": feeds_in_use,
        "remaining": remaining,
    }


@billing_bp.route("/api/billing/summary", methods=["GET"])
def billing_summary() -> Any:
    """Return feed allowance and subscription state for the current user."""
    user = _require_authenticated_user()
    if user is None:
        logger.warning("Billing summary requested by unauthenticated user")
        return jsonify({"error": "Authentication required"}), 401

    logger.info("Billing summary requested for user %s", user.id)
    usage = _user_feed_usage(user)
    product_id = _product_id()
    stripe_client, _ = _get_stripe_client()
    current_amount = 0

    if (
        stripe_client is not None
        and user.stripe_customer_id
        and not user.stripe_subscription_id
    ):
        # Try to find an active subscription if we don't have one linked
        subs = stripe_client.Subscription.list(
            customer=user.stripe_customer_id, limit=1, status="active"
        )
        if subs and subs.get("data"):
            sub = subs["data"][0]
            items = sub.get("items", {}).get("data", [])
            # For PWYW bundle, allowance is 10 if active
            feed_allowance = 10 if items else 0

            writer_client.action(
                "set_user_billing_fields",
                {
                    "user_id": user.id,
                    "stripe_subscription_id": sub["id"],
                    "feed_subscription_status": sub["status"],
                    "feed_allowance": feed_allowance,
                },
                wait=True,
            )
            db.session.expire(user)
            usage = _user_feed_usage(user)

    # Fetch current price amount if subscribed
    if (
        stripe_client is not None
        and user.stripe_subscription_id
        and user.feed_subscription_status == "active"
    ):
        try:
            sub = stripe_client.Subscription.retrieve(
                user.stripe_subscription_id, expand=["items.data.price"]
            )
            if sub and sub.get("items") and sub["items"]["data"]:
                price_item = sub["items"]["data"][0].get("price")
                if price_item:
                    current_amount = price_item.get("unit_amount", 0)
        except Exception as e:
            logger.error("Error fetching subscription details: %s", e)

    return jsonify(
        {
            "feed_allowance": usage["feed_allowance"],
            "feeds_in_use": usage["feeds_in_use"],
            "remaining": usage["remaining"],
            "current_amount": current_amount,
            "min_amount_cents": _min_subscription_amount_cents(),
            "subscription_status": getattr(
                user, "feed_subscription_status", "inactive"
            ),
            "stripe_subscription_id": getattr(user, "stripe_subscription_id", None),
            "stripe_customer_id": getattr(user, "stripe_customer_id", None),
            "product_id": product_id,
        }
    )


def _build_return_urls() -> tuple[str, str]:
    host = request.host_url.rstrip("/")
    success = f"{host}/billing?checkout=success"
    cancel = f"{host}/billing?checkout=cancel"
    return success, cancel


@billing_bp.route("/api/billing/subscription", methods=["POST"])
def update_subscription() -> Any:  # pylint: disable=too-many-statements
    """Update subscription amount or create new subscription."""
    user = _require_authenticated_user()
    if user is None:
        logger.warning("Update subscription requested by unauthenticated user")
        return jsonify({"error": "Authentication required"}), 401

    payload = request.get_json(silent=True) or {}
    amount = int(payload.get("amount") or 0)
    logger.info("Update subscription for user %s: %s cents", user.id, amount)

    # Allow 0 to cancel, otherwise enforce configured minimum.
    min_amount_cents = _min_subscription_amount_cents()
    if 0 < amount < min_amount_cents:
        min_amount_dollars = min_amount_cents / 100.0
        return (
            jsonify({"error": f"Minimum amount is ${min_amount_dollars:.2f}"}),
            400,
        )

    stripe_client, stripe_err = _get_stripe_client()
    product_id = _product_id()
    if stripe_client is None or not product_id:
        logger.error("Stripe not configured. err=%s", stripe_err)
        return (
            jsonify(
                {
                    "error": "STRIPE_NOT_CONFIGURED",
                    "message": "Billing system is not configured.",
                }
            ),
            503,
        )

    try:
        requested_subscription_id = payload.get("subscription_id")
        if (
            requested_subscription_id
            and not user.stripe_subscription_id
            and stripe_client is not None
        ):
            # Attach known subscription id to the user if it belongs to their customer
            sub = stripe_client.Subscription.retrieve(requested_subscription_id)
            if sub and sub.get("customer") == user.stripe_customer_id:
                writer_client.action(
                    "set_user_billing_fields",
                    {"user_id": user.id, "stripe_subscription_id": sub["id"]},
                    wait=True,
                )
                db.session.expire(user)

        # Ensure customer exists
        if not user.stripe_customer_id:
            customer = stripe_client.Customer.create(
                name=user.username or f"user-{user.id}",
                metadata={"user_id": user.id},
            )
            writer_client.action(
                "set_user_billing_fields",
                {"user_id": user.id, "stripe_customer_id": customer["id"]},
                wait=True,
            )
            db.session.expire(user)

        # If subscription exists, update or cancel
        if user.stripe_subscription_id:
            if amount <= 0:
                logger.info("Canceling subscription for user %s", user.id)
                stripe_client.Subscription.delete(user.stripe_subscription_id)
                writer_client.action(
                    "set_user_billing_fields",
                    {
                        "user_id": user.id,
                        "feed_allowance": 0,
                        "feed_subscription_status": "canceled",
                        "stripe_subscription_id": None,
                    },
                    wait=True,
                )
                db.session.expire(user)
                usage = _user_feed_usage(user)
                return jsonify(
                    {
                        "feed_allowance": usage["feed_allowance"],
                        "feeds_in_use": usage["feeds_in_use"],
                        "remaining": usage["remaining"],
                        "subscription_status": user.feed_subscription_status,
                        "requires_stripe_checkout": False,
                        "message": "Subscription canceled.",
                    }
                )

            # Update existing subscription with new price
            sub = stripe_client.Subscription.retrieve(
                user.stripe_subscription_id, expand=["items"]
            )
            items = sub["items"]["data"]
            if not items:
                return jsonify({"error": "Subscription has no items"}), 400
            item_id = items[0]["id"]

            updated = stripe_client.Subscription.modify(
                user.stripe_subscription_id,
                items=[
                    {
                        "id": item_id,
                        "price_data": {
                            "currency": "usd",
                            "product": product_id,
                            "unit_amount": amount,
                            "recurring": {"interval": "month"},
                        },
                    }
                ],
                proration_behavior="none",
            )
            logger.info(
                "Updated subscription for user %s to amount %s", user.id, amount
            )
            status = updated["status"]
            writer_client.action(
                "set_user_billing_fields",
                {
                    "user_id": user.id,
                    "feed_allowance": 10,  # Fixed allowance for active sub
                    "feed_subscription_status": status,
                },
                wait=True,
            )
            db.session.expire(user)
            usage = _user_feed_usage(user)
            return jsonify(
                {
                    "feed_allowance": usage["feed_allowance"],
                    "feeds_in_use": usage["feeds_in_use"],
                    "remaining": usage["remaining"],
                    "subscription_status": status,
                    "requires_stripe_checkout": False,
                    "message": "Subscription updated.",
                }
            )

        # Otherwise, create checkout session for a new subscription
        if amount <= 0:
            writer_client.action(
                "set_user_billing_fields",
                {
                    "user_id": user.id,
                    "feed_allowance": 0,
                    "feed_subscription_status": "inactive",
                },
                wait=True,
            )
            db.session.expire(user)
            usage = _user_feed_usage(user)
            return jsonify(
                {
                    "feed_allowance": usage["feed_allowance"],
                    "feeds_in_use": usage["feeds_in_use"],
                    "remaining": usage["remaining"],
                    "subscription_status": user.feed_subscription_status,
                    "requires_stripe_checkout": False,
                    "message": "No subscription created for zero amount.",
                }
            )
        logger.info(
            "Creating checkout session for user %s with amount %s", user.id, amount
        )
        success_url, cancel_url = _build_return_urls()
        session = stripe_client.checkout.Session.create(
            mode="subscription",
            customer=user.stripe_customer_id,
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "product": product_id,
                        "unit_amount": amount,
                        "recurring": {"interval": "month"},
                    },
                    "quantity": 1,
                }
            ],
            subscription_data={"metadata": {"user_id": user.id}},
            metadata={"user_id": user.id},
            success_url=payload.get("success_url") or success_url,
            cancel_url=payload.get("cancel_url") or cancel_url,
        )
        return jsonify(
            {
                "checkout_url": session["url"],
                "requires_stripe_checkout": True,
                "feed_allowance": user.feed_allowance,
                "feeds_in_use": _user_feed_usage(user)["feeds_in_use"],
                "subscription_status": user.feed_subscription_status,
            }
        )
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Stripe error updating subscription: %s", exc)
        return jsonify({"error": "STRIPE_ERROR", "message": str(exc)}), 502

    usage = _user_feed_usage(user)
    return jsonify(
        {
            "feed_allowance": usage["feed_allowance"],
            "feeds_in_use": usage["feeds_in_use"],
            "remaining": usage["remaining"],
            "subscription_status": user.feed_subscription_status,
            "requires_stripe_checkout": True,
            "message": "Local update completed.",
        }
    )


@billing_bp.route("/api/billing/portal-session", methods=["POST"])
def billing_portal_session() -> Any:
    user = _require_authenticated_user()
    if user is None:
        logger.warning("Billing portal session requested by unauthenticated user")
        return jsonify({"error": "Authentication required"}), 401

    logger.info("Billing portal session requested for user %s", user.id)
    stripe_client, stripe_err = _get_stripe_client()
    if stripe_client is None:
        return jsonify({"error": "STRIPE_NOT_CONFIGURED", "message": stripe_err}), 400
    if not user.stripe_customer_id:
        return (
            jsonify(
                {
                    "error": "NO_STRIPE_CUSTOMER",
                    "message": "No Stripe customer on file.",
                }
            ),
            400,
        )

    return_url, _ = _build_return_urls()
    try:
        session = stripe_client.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=return_url,
        )
        return jsonify({"url": session["url"]})
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Failed to create billing portal session: %s", exc)
        return jsonify({"error": "STRIPE_ERROR", "message": str(exc)}), 502


def _update_user_from_subscription(sub: Any) -> None:
    customer_id = sub.get("customer")
    if not customer_id:
        return
    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    if not user:
        return

    status = sub.get("status") if isinstance(sub, dict) else sub["status"]

    # For PWYW bundle, allowance is 10 if active
    feed_allowance = 10 if status in ("active", "trialing", "past_due") else 0

    writer_client.action(
        "set_user_billing_by_customer_id",
        {
            "stripe_customer_id": customer_id,
            "feed_allowance": feed_allowance,
            "feed_subscription_status": status,
            "stripe_subscription_id": (
                sub.get("id") if isinstance(sub, dict) else sub["id"]
            ),
        },
        wait=True,
    )


@billing_bp.route("/api/billing/stripe-webhook", methods=["POST"])
def stripe_webhook() -> Any:
    stripe_client, stripe_err = _get_stripe_client()
    if stripe_client is None:
        return jsonify({"error": "STRIPE_NOT_CONFIGURED", "message": stripe_err}), 400

    payload = request.data
    sig_header = request.headers.get("Stripe-Signature")
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        logger.error("Stripe webhook secret not configured; rejecting webhook request.")
        return (
            jsonify(
                {
                    "error": "WEBHOOK_SECRET_MISSING",
                    "message": "Stripe webhook secret is not configured.",
                }
            ),
            400,
        )

    try:
        event = stripe_client.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
        logger.info("Stripe webhook received: %s", event["type"])
    except Exception as exc:  # pylint: disable=broad-except
        logger.error("Invalid Stripe webhook: %s", exc)
        return jsonify({"error": "INVALID_SIGNATURE"}), 400

    event_type = event["type"]
    data_object = event["data"]["object"]

    if event_type in (
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "customer.subscription.paused",
    ):
        _update_user_from_subscription(data_object)
    elif event_type == "checkout.session.completed":
        sub_id = data_object.get("subscription")
        customer_id = data_object.get("customer")
        user_id = data_object.get("metadata", {}).get("user_id")
        user = None
        if customer_id:
            user = User.query.filter_by(stripe_customer_id=customer_id).first()
        if user is None and user_id:
            user = db.session.get(User, int(user_id))
        if user and customer_id:
            writer_client.action(
                "set_user_billing_fields",
                {"user_id": user.id, "stripe_customer_id": customer_id},
                wait=True,
            )
            db.session.expire(user)
        if user and sub_id:
            writer_client.action(
                "set_user_billing_fields",
                {"user_id": user.id, "stripe_subscription_id": sub_id},
                wait=True,
            )
            db.session.expire(user)
    else:
        logger.info("Unhandled Stripe event: %s", event_type)

    return jsonify({"status": "ok"})
