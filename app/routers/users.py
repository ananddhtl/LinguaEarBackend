from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import codes, mailer, stripe_service
from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models import User
from app.onetime import create_token
from app.schemas import (
    CodeSent,
    VerifyCodeRequest,
    ChangePasswordRequest,
    DeleteAccountRequest,
    ProfileUpdate,
    TokenResponse,
    UserOut,
)
from app.security import hash_password, verify_password
from app.sessions import issue_tokens, revoke_all_sessions

router = APIRouter(prefix="/users", tags=["profile"])


@router.get("/me", response_model=UserOut)
def get_profile(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=UserOut)
def update_profile(
    body: ProfileUpdate,
    tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Updates only the fields sent. A new email is not applied until the link sent to it is used."""
    changes = body.model_dump(exclude_unset=True)

    if "username" in changes and changes["username"] is not None:
        username = changes["username"].lower()
        if username != user.username:
            if db.scalar(select(User).where(User.username == username)):
                raise HTTPException(status.HTTP_409_CONFLICT, "Username already taken")
            user.username = username
    for field in ("full_name", "bio"):
        if field in changes:
            setattr(user, field, changes[field] or None)

    new_email = (changes.get("email") or "").lower()
    if new_email and new_email != user.email:
        if db.scalar(select(User).where(User.email == new_email)):
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
        db.commit()
        raw = create_token(
            db, user, "change_email", timedelta(hours=settings.verify_email_hours), new_email=new_email
        )
        tasks.add_task(mailer.send_verification_email, new_email, raw)

    db.commit()
    db.refresh(user)
    return user


@router.post("/me/verification-code", response_model=CodeSent)
def send_verification_code(
    tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Emails a fresh 6-digit code. Asking again within a minute returns the wait instead of sending."""
    if user.email_verified:
        raise HTTPException(status.HTTP_409_CONFLICT, "Your email is already verified.")
    code, wait = codes.issue_code(db, user, codes.VERIFY)
    if code is None:
        return CodeSent(sent=False, retry_after=wait)
    tasks.add_task(mailer.send_verification_code_email, user.email, code)
    return CodeSent(sent=True, retry_after=settings.verification_resend_seconds)


@router.post("/me/verify-email", response_model=UserOut)
def verify_email_code(
    body: VerifyCodeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.email_verified:
        return user
    result, left = codes.check_code(db, user, body.code, codes.VERIFY)
    if result == "ok":
        user.email_verified = True
        db.commit()
    else:
        messages = {
            "wrong": f"That code is not right. {left} tr{'y' if left == 1 else 'ies'} left.",
            "expired": "That code has expired. Request a new one.",
            "locked": "Too many wrong codes. Request a new one.",
        }
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, {"code": result, "message": messages[result], "attempts_left": left}
        )
    db.refresh(user)
    return user


@router.post("/me/change-password", response_model=TokenResponse)
def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Signs out every other device and returns fresh tokens for this one."""
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    user.hashed_password = hash_password(body.new_password)
    revoke_all_sessions(db, user)
    return issue_tokens(db, user, remember_me=False)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    body: DeleteAccountRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password is incorrect")
    stripe_service.cancel_subscription_for_deletion(db, user)
    db.delete(user)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
