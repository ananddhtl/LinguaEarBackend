"""Six-digit emailed codes (email verification and password reset).

Short codes are easy to guess, so they are protected three ways: they expire quickly, they lock after a few
wrong tries, and only a keyed hash is stored (a leaked database alone can't be used to work out the code).
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import OneTimeToken, User

VERIFY = "verify_code"
RESET = "reset_code"

Result = Literal["ok", "wrong", "expired", "locked"]


def _digest(user_id: int, purpose: str, code: str) -> str:
    # The purpose is part of the hash, so a code for one use can never be accepted for another.
    return hmac.new(
        settings.secret_key.encode(), f"{user_id}:{purpose}:{code}".encode(), hashlib.sha256
    ).hexdigest()


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _active(db: Session, user: User, purpose: str) -> OneTimeToken | None:
    return db.scalar(
        select(OneTimeToken)
        .where(OneTimeToken.user_id == user.id, OneTimeToken.purpose == purpose, OneTimeToken.used_at.is_(None))
        .with_for_update()
    )


def issue_code(db: Session, user: User, purpose: str = VERIFY) -> tuple[str | None, int]:
    """Makes a new code. Returns (code, 0), or (None, seconds_to_wait) if one was sent too recently."""
    now = datetime.now(timezone.utc)
    ttl = timedelta(minutes=settings.verification_code_minutes)

    existing = _active(db, user, purpose)
    if existing is not None:
        sent_at = _aware(existing.expires_at) - ttl
        wait = settings.verification_resend_seconds - (now - sent_at).total_seconds()
        if wait > 0:
            db.rollback()
            return None, int(wait) + 1
        db.execute(delete(OneTimeToken).where(OneTimeToken.id == existing.id))

    code = f"{secrets.randbelow(10**6):06d}"
    db.add(OneTimeToken(user_id=user.id, purpose=purpose, token_hash=_digest(user.id, purpose, code), expires_at=now + ttl))
    db.commit()
    return code, 0


def check_code(db: Session, user: User, code: str, purpose: str = VERIFY) -> tuple[Result, int]:
    """Checks a code and, if right, marks it used. Returns the result and how many tries are left.

    Only the code is consumed here; what it unlocks (a verified email, a new password) is up to the caller.
    """
    row = _active(db, user, purpose)
    now = datetime.now(timezone.utc)
    if row is None or _aware(row.expires_at) < now:
        db.rollback()
        return "expired", 0
    if row.attempts >= settings.verification_max_attempts:
        db.rollback()
        return "locked", 0

    if hmac.compare_digest(row.token_hash, _digest(user.id, purpose, code)):
        row.used_at = now
        db.commit()
        return "ok", settings.verification_max_attempts

    row.attempts += 1
    db.commit()
    left = settings.verification_max_attempts - row.attempts
    return ("wrong" if left > 0 else "locked"), max(left, 0)
