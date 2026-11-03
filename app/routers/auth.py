import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import mailer
from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models import RefreshToken, User
from app.onetime import consume_token, create_token
from app.schemas import (
    EmailRequest,
    LoginRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenRequest,
    TokenResponse,
    UserOut,
)
from app.sessions import issue_tokens, revoke_all_sessions, revoke_family
from app.security import (
    decode_token,
    hash_password,
    token_user_id,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# Verified against when the email is unknown, so login timing doesn't reveal which emails exist.
_DUMMY_HASH = hash_password("dummy-password")


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    email = body.email.lower()
    username = body.username.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken")
    user = User(username=username, email=email, hashed_password=hash_password(body.password))
    db.add(user)
    db.commit()
    raw = create_token(db, user, "verify_email", timedelta(hours=settings.verify_email_hours))
    tasks.add_task(mailer.send_verification_email, user.email, raw)
    return issue_tokens(db, user, remember_me=False)


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    valid = verify_password(body.password, user.hashed_password if user else _DUMMY_HASH)
    if not user or not valid or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if settings.require_verified_email and not user.email_verified:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Email not verified")
    return issue_tokens(db, user, remember_me=body.remember_me)


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
        revoke_family(db, row.family_id)
        raise invalid

    row.revoked_at = datetime.now(timezone.utc)
    return issue_tokens(db, user, remember_me=row.remember_me, family_id=row.family_id)


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
        revoke_family(db, row.family_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Signs the user out everywhere."""
    revoke_all_sessions(db, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/verify-email", response_model=MessageResponse)
def verify_email(body: TokenRequest, db: Session = Depends(get_db)):
    """Confirms the address from the registration email, or a new address from an email change."""
    row = consume_token(db, "verify_email", body.token) or consume_token(db, "change_email", body.token)
    if row is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired token")
    user = db.get(User, row.user_id)
    if row.new_email:
        if db.scalar(select(User).where(User.email == row.new_email, User.id != user.id)):
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
        user.email = row.new_email
    user.email_verified = True
    db.commit()
    return MessageResponse(message="Email verified")


@router.post("/resend-verification", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
def resend_verification(body: EmailRequest, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Always answers the same way so it can't be used to discover which emails are registered."""
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user and user.is_active and not user.email_verified:
        raw = create_token(db, user, "verify_email", timedelta(hours=settings.verify_email_hours))
        tasks.add_task(mailer.send_verification_email, user.email, raw)
    return MessageResponse(message="If that account needs verification, an email has been sent")


@router.post("/forgot-password", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
def forgot_password(body: EmailRequest, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user and user.is_active:
        raw = create_token(db, user, "reset_password", timedelta(minutes=settings.reset_password_minutes))
        tasks.add_task(mailer.send_password_reset_email, user.email, raw)
    return MessageResponse(message="If that email is registered, a reset link has been sent")


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    row = consume_token(db, "reset_password", body.token)
    if row is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired token")
    user = db.get(User, row.user_id)
    user.hashed_password = hash_password(body.new_password)
    user.email_verified = True  # they just proved they control the inbox
    revoke_all_sessions(db, user)  # commits; every existing session is signed out
    return MessageResponse(message="Password updated. Please log in again.")
