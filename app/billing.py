"""Who has access: an active trial or an active subscription."""
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models import Subscription, User

# Stripe statuses that keep access. "past_due" is a grace period while Stripe retries the payment.
ACCESS_STATUSES = {"active", "trialing", "past_due"}


def _aware(moment: datetime | None) -> datetime | None:
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def current_plan(db: Session, user: User) -> str | None:
    """"standard" or "pro" while the user has access, otherwise None."""
    if not settings.billing_enforced:
        return "standard"  # development: no paywall, Standard limits so they can still be tested

    sub = db.get(Subscription, user.id)
    if sub is not None and sub.status in ACCESS_STATUSES:
        return sub.tier

    trial_end = _aware(user.trial_ends_at)
    if trial_end is not None and trial_end > datetime.now(timezone.utc):
        return "standard"
    return None


def status_for(db: Session, user: User) -> dict:
    now = datetime.now(timezone.utc)
    sub = db.get(Subscription, user.id)
    plan = current_plan(db, user)
    trial_end = _aware(user.trial_ends_at)
    subscribed = sub is not None and sub.status in ACCESS_STATUSES

    if not settings.billing_enforced:
        state = "free"
    elif subscribed:
        state = "subscribed"
    elif plan is not None:
        state = "trial"
    else:
        state = "expired"

    trial_days_left = None
    if state == "trial" and trial_end is not None:
        trial_days_left = max(0, -(-int((trial_end - now).total_seconds()) // 86400))  # round up

    return {
        "access": plan is not None,
        "state": state,
        "tier": plan,
        "subscription_status": sub.status if sub else None,
        "trial_ends_at": trial_end,
        "trial_days_left": trial_days_left,
        "current_period_end": _aware(sub.current_period_end) if sub else None,
        "cancel_at_period_end": bool(sub.cancel_at_period_end) if sub else False,
    }


def require_subscriber(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    """Use on features that need a verified email and an active trial or plan.

    Answers 403 for an unverified email and 402 when there is no plan, so the app can show the right screen.
    """
    if settings.require_verified_for_access and not user.email_verified:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"code": "email_not_verified", "message": "Verify your email to use this feature."},
        )
    if current_plan(db, user) is None:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            {
                "code": "subscription_required",
                "message": "Your free trial has ended. Choose a plan to keep learning.",
            },
        )
    return user
