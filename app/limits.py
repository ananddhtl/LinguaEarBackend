"""Per-user daily quotas and a short-term burst limit for the AI endpoints."""
import time
from collections import defaultdict, deque
from datetime import date, datetime, time as dtime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import plans
from app.billing import current_plan
from app.config import settings
from app.models import Analysis, UsageCount, User

KINDS = ("analyze", "game", "scan", "transcribe")

LABELS = {
    "analyze": "phrase analyses",
    "game": "game replies",
    "scan": "camera scans",
    "transcribe": "voice recordings",
}

# Responses carrying this header are our own limits, so clients must not retry them like a flaky 429.
QUOTA_HEADER = {"X-Quota-Exceeded": "1"}


def _tier(db: Session, user: User) -> str:
    return current_plan(db, user) or "standard"


def daily_limit(kind: str, tier: str = "standard") -> int:
    return plans.limits_for(tier).daily(kind)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def resets_at() -> datetime:
    """Next 00:00 UTC, when the daily counts start over."""
    tomorrow = _today() + timedelta(days=1)
    return datetime.combine(tomorrow, dtime.min, tzinfo=timezone.utc)


# --- burst limit (per process; fine for a single worker) -------------------------------------
_recent: dict[int, deque[float]] = defaultdict(deque)


def check_burst(user: User) -> None:
    now = time.monotonic()
    window = _recent[user.id]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= settings.ai_calls_per_minute:
        retry = max(1, int(60 - (now - window[0])))
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            {"code": "rate", "message": "You're going a bit fast. Try again in a few seconds.", "retry_after": retry},
            {**QUOTA_HEADER, "Retry-After": str(retry)},
        )
    window.append(now)


# --- daily quota -----------------------------------------------------------------------------
def consume(db: Session, user: User, kind: str) -> int:
    """Counts one call and returns how many are left today, or raises 429 when none are."""
    limit = daily_limit(kind, _tier(db, user))
    # One atomic statement: it only increments while the count is below the limit.
    row = db.execute(
        text(
            """
            INSERT INTO usage_counts (user_id, kind, day, count)
            VALUES (:user_id, :kind, :day, 1)
            ON CONFLICT (user_id, kind, day)
            DO UPDATE SET count = usage_counts.count + 1
            WHERE usage_counts.count < :limit
            RETURNING count
            """
        ),
        {"user_id": user.id, "kind": kind, "day": _today(), "limit": limit},
    ).first()
    db.commit()

    if row is None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            {
                "code": "quota",
                "kind": kind,
                "limit": limit,
                "message": f"You've used all {limit} {LABELS[kind]} for today. The limit resets at midnight UTC.",
                "resets_at": resets_at().isoformat(),
            },
            QUOTA_HEADER,
        )
    return limit - row[0]


def refund(db: Session, user: User, kind: str) -> None:
    """Gives a call back when the provider failed, so an outage doesn't eat the user's quota."""
    row = db.get(UsageCount, (user.id, kind, _today()))
    if row is not None and row.count > 0:
        row.count -= 1
        db.commit()


def usage_summary(db: Session, user: User) -> dict:
    counts = {
        k: c
        for k, c in db.execute(
            select(UsageCount.kind, UsageCount.count).where(UsageCount.user_id == user.id, UsageCount.day == _today())
        )
    }
    saved = db.scalar(select(func.count(Analysis.id)).where(Analysis.user_id == user.id))
    tier = _tier(db, user)
    return {
        "resets_at": resets_at().isoformat(),
        "tier": tier,
        "limits": {k: {"used": counts.get(k, 0), "limit": daily_limit(k, tier)} for k in KINDS},
        "saved_phrases": {"used": saved or 0, "limit": plans.limits_for(tier).saved_phrases},
    }
