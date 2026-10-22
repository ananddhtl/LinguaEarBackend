import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models import RefreshToken, User
from app.schemas import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserOut
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    token_user_id,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Verified against when the email is unknown, so login timing doesn't reveal which emails exist.
_DUMMY_HASH = hash_password("dummy-password")


def _issue_tokens(
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


def _revoke_family(db: Session, family_id: uuid.UUID) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    db.commit()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    email = body.email.lower()
    username = body.username.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken")
    user = User(username=username, email=email, hashed_password=hash_password(body.password))
    db.add(user)
    db.commit()
    return _issue_tokens(db, user, remember_me=False)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    valid = verify_password(body.password, user.hashed_password if user else _DUMMY_HASH)
    if not user or not valid or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    return _issue_tokens(db, user, remember_me=body.remember_me)


@router.post("/token", response_model=TokenResponse, include_in_schema=True)
def token(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """OAuth2 form login used by Swagger's Authorize button. Put your email in `username`."""
    return login(LoginRequest(email=form.username, password=form.password), db)


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    try:
        user = db.get(User, token_user_id(body.refresh_token))
        if user is None or not user.is_active:
            raise invalid
        payload = decode_token(body.refresh_token, "refresh", user)
    except (jwt.PyJWTError, KeyError, ValueError):
        raise invalid

    # Row lock so two concurrent refreshes with the same token can't both succeed.
    row = db.scalar(
        select(RefreshToken).where(RefreshToken.jti == uuid.UUID(payload["jti"])).with_for_update()
    )
    if row is None:
        raise invalid
    if row.revoked_at is not None:
        # An already-rotated token was presented again: assume theft, kill the whole chain.
        _revoke_family(db, row.family_id)
        raise invalid

    row.revoked_at = datetime.now(timezone.utc)
    return _issue_tokens(db, user, remember_me=row.remember_me, family_id=row.family_id)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshRequest, db: Session = Depends(get_db)):
    """Revokes the session the refresh token belongs to. Always 204 so it's idempotent."""
    try:
        user = db.get(User, token_user_id(body.refresh_token))
        payload = decode_token(body.refresh_token, "refresh", user)
        row = db.get(RefreshToken, uuid.UUID(payload["jti"]))
    except (jwt.PyJWTError, KeyError, ValueError, AttributeError):
        row = None
    if row:
        _revoke_family(db, row.family_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Signs the user out everywhere: rotating their secret invalidates all their tokens at once."""
    user.token_secret = secrets.token_hex(32)
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user
