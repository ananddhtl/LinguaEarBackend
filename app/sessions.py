import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import RefreshToken, User
from app.schemas import TokenResponse
from app.security import create_access_token, create_refresh_token


def issue_tokens(
    db: Session, user: User, *, remember_me: bool, family_id: uuid.UUID | None = None
) -> TokenResponse:
    days = settings.remember_me_days if remember_me else settings.refresh_token_days
    expires_at = datetime.now(timezone.utc) + timedelta(days=days)
    jti = uuid.uuid4()
    db.add(
        RefreshToken(
            jti=jti,
            family_id=family_id or uuid.uuid4(),
            user_id=user.id,
            remember_me=remember_me,
            expires_at=expires_at,
        )
    )
    db.commit()
    return TokenResponse(
        access_token=create_access_token(user),
        refresh_token=create_refresh_token(user, jti, expires_at),
        expires_in=settings.access_token_minutes * 60,
    )


def revoke_family(db: Session, family_id: uuid.UUID) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    db.commit()


def revoke_all_sessions(db: Session, user: User) -> None:
    """Signs the user out everywhere: new signing secret kills every access/refresh JWT."""
    user.token_secret = secrets.token_hex(32)
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    db.commit()
