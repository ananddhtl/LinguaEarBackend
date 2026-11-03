import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import OneTimeToken, User


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_token(
    db: Session, user: User, purpose: str, ttl: timedelta, new_email: str | None = None
) -> str:
    """Returns the raw token (to email). Any earlier unused token for the same purpose is dropped."""
    db.execute(
        delete(OneTimeToken).where(
            OneTimeToken.user_id == user.id,
            OneTimeToken.purpose == purpose,
            OneTimeToken.used_at.is_(None),
        )
    )
    raw = secrets.token_urlsafe(32)
    db.add(
        OneTimeToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=_hash(raw),
            new_email=new_email,
            expires_at=datetime.now(timezone.utc) + ttl,
        )
    )
    db.commit()
    return raw


def consume_token(db: Session, purpose: str, raw: str) -> OneTimeToken | None:
    """Marks a valid token used and returns it; None if unknown, used, expired or wrong purpose.

    The caller must commit.
    """
    row = db.scalar(
        select(OneTimeToken)
        .where(OneTimeToken.token_hash == _hash(raw), OneTimeToken.purpose == purpose)
        .with_for_update()
    )
    now = datetime.now(timezone.utc)
    if row is None or row.used_at is not None or row.expires_at < now:
        return None
    row.used_at = now
    return row
