import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User
from app.security import hash_password

log = logging.getLogger("uvicorn.error")


def seed_admin(db: Session) -> None:
    """Creates the admin account from ADMIN_EMAIL / ADMIN_PASSWORD, or makes that account an admin if it exists.

    An existing account keeps its password, so changing the variable later does not silently reset it.
    """
    email, password = settings.admin_email, settings.admin_password
    if not email or not password:
        return
    email = email.strip().lower()
    if len(password) < 8:
        log.warning("ADMIN_PASSWORD is shorter than 8 characters: no admin account was created")
        return

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        taken = db.scalar(select(User.id).where(User.username == settings.admin_username))
        user = User(
            username=settings.admin_username if taken is None else f"{settings.admin_username}{email.split('@')[0]}"[:30],
            email=email,
            hashed_password=hash_password(password),
        )
        db.add(user)
        log.info("Created admin account %s", email)
    user.is_admin = True
    user.is_active = True
    user.email_verified = True
    db.commit()
