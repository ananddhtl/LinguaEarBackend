"""Stripe calls and webhook handling. Subscription state is only ever changed from verified webhooks."""
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit

import stripe
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import plans
from app.config import settings
from app.models import Subscription, User

log = logging.getLogger(__name__)


def _configure() -> None:
    if not settings.stripe_secret_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Payments are not configured on the server.")
    stripe.api_key = settings.stripe_secret_key


# Schemes an app link may use: the app's own, and Expo Go's. Anything else could be used to bounce
# people to an arbitrary site, so it is refused.
APP_SCHEMES = {"linguaear", "exp", "exps"}


def safe_app_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme.lower() not in APP_SCHEMES or any(c in url for c in "\r\n "):
        return None
    return url


def _return_page(kind: str, app_url: str | None) -> str:
    """Our page Stripe sends the browser to; it hands the user on to the app when it has a link for it."""
    query = f"?{urlencode({'r': app_url})}" if app_url else ""
    return f"{settings.public_base_url}/billing/{kind}{query}"


def _ensure_customer(db: Session, user: User) -> str:
    if user.stripe_customer_id:
        return user.stripe_customer_id
    customer = stripe.Customer.create(email=user.email, metadata={"user_id": str(user.id)})
    user.stripe_customer_id = customer["id"]
    db.commit()
    return user.stripe_customer_id


def create_checkout_url(db: Session, user: User, tier: str, return_url: str | None = None) -> str:
    _configure()
    price = plans.price_id(tier)
    if not price:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"The {tier} plan is not available yet.")

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=_ensure_customer(db, user),
        line_items=[{"price": price, "quantity": 1}],
        client_reference_id=str(user.id),
        # Carried onto the subscription so webhooks can find the user even before the customer is linked.
        subscription_data={"metadata": {"user_id": str(user.id), "tier": tier}},
        allow_promotion_codes=True,
        success_url=_return_page("success", safe_app_url(return_url)),
        cancel_url=_return_page("cancel", safe_app_url(return_url)),
    )
    return session["url"]


def create_portal_url(db: Session, user: User, return_url: str | None = None) -> str:
    _configure()
    if not user.stripe_customer_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "There is no subscription to manage yet.")
    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=_return_page("success", safe_app_url(return_url)),
    )
    return session["url"]


def cancel_subscription_for_deletion(db: Session, user: User) -> None:
    """Stops billing before an account is deleted. If it can't be stopped, deletion must not go ahead,
    or the person would keep being charged for an account that no longer exists."""
    from app.billing import ACCESS_STATUSES

    row = db.get(Subscription, user.id)
    if row is None or row.status not in ACCESS_STATUSES:
        return
    _configure()
    try:
        stripe.Subscription.cancel(row.stripe_subscription_id)
    except stripe.InvalidRequestError as err:
        # "No such subscription" / already cancelled on Stripe's side: nothing left to bill.
        if getattr(err, "code", None) != "resource_missing":
            raise
    except Exception as err:
        log.exception("Could not cancel subscription %s for user %s", row.stripe_subscription_id, user.id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "We couldn't cancel your subscription, so your account was not deleted. Please try again or contact support.",
        ) from err


def verify_event(payload: bytes, signature: str | None) -> dict:
    """Checks the signature, then returns the event as a plain dict (Stripe's own objects aren't dicts)."""
    if not settings.stripe_webhook_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Webhooks are not configured on the server.")
    try:
        stripe.Webhook.construct_event(payload, signature or "", settings.stripe_webhook_secret)
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid webhook signature")
    return json.loads(payload)


def _period_end(sub: dict) -> datetime | None:
    # Newer Stripe API versions keep the period on the subscription item, older ones on the subscription.
    items = (sub.get("items") or {}).get("data") or []
    stamp = sub.get("current_period_end") or (items[0].get("current_period_end") if items else None)
    return datetime.fromtimestamp(stamp, tz=timezone.utc) if stamp else None


def _user_for(db: Session, sub: dict) -> User | None:
    customer = sub.get("customer")
    if customer:
        user = db.scalar(select(User).where(User.stripe_customer_id == customer))
        if user:
            return user
    user_id = (sub.get("metadata") or {}).get("user_id")
    if user_id and str(user_id).isdigit():
        user = db.get(User, int(user_id))
        if user and customer and not user.stripe_customer_id:
            user.stripe_customer_id = customer  # first sight of this customer
        return user
    return None


def _apply_subscription(db: Session, sub: dict, deleted: bool = False) -> None:
    user = _user_for(db, sub)
    if user is None:
        log.warning("Stripe subscription %s does not match any user", sub.get("id"))
        return

    items = (sub.get("items") or {}).get("data") or []
    price = (items[0].get("price") or {}).get("id") if items else None
    # Only prices configured as our plans grant access; anything else is ignored.
    tier = plans.tier_for_price(price)
    if tier is None:
        log.warning("Stripe subscription %s has a price that is not a configured plan: %s", sub.get("id"), price)
        return

    row = db.get(Subscription, user.id)
    if row is None:
        row = Subscription(user_id=user.id, stripe_subscription_id=sub["id"], tier=tier, status="incomplete")
        db.add(row)
    row.stripe_subscription_id = sub["id"]
    row.tier = tier
    row.status = "canceled" if deleted else sub.get("status", row.status)
    row.current_period_end = _period_end(sub)
    row.cancel_at_period_end = bool(sub.get("cancel_at_period_end"))
    db.commit()


def apply_event(db: Session, event: dict) -> bool:
    """Updates our records from a verified Stripe event. Returns False for event types we ignore."""
    kind = event["type"]
    obj = event["data"]["object"]

    if kind == "checkout.session.completed":
        user_id = obj.get("client_reference_id")
        if user_id and str(user_id).isdigit() and obj.get("customer"):
            user = db.get(User, int(user_id))
            if user and not user.stripe_customer_id:
                user.stripe_customer_id = obj["customer"]
                db.commit()
        return True
    if kind in ("customer.subscription.created", "customer.subscription.updated"):
        _apply_subscription(db, obj)
        return True
    if kind == "customer.subscription.deleted":
        _apply_subscription(db, obj, deleted=True)
        return True
    return False
