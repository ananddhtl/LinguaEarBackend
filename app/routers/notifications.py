import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models import NotificationPreference, User
from app.schemas import NotificationPrefs

router = APIRouter(prefix="/notifications", tags=["notifications"])

# Optional emails the user can switch off from the link at the bottom of the email.
UNSUBSCRIBE_CATEGORIES = ("practice_reminders", "product_updates")


def _prefs(db: Session, user: User) -> NotificationPreference:
    prefs = db.get(NotificationPreference, user.id)
    if prefs is None:
        prefs = NotificationPreference(user_id=user.id)
        db.add(prefs)
        db.commit()
        db.refresh(prefs)
    return prefs


def unsubscribe_token(user_id: int, category: str) -> str:
    """A signed link token: only this server can make one, so nobody can unsubscribe someone else."""
    return jwt.encode({"sub": str(user_id), "cat": category, "typ": "unsub"}, settings.secret_key, "HS256")


def unsubscribe_url(user_id: int, category: str) -> str:
    return f"{settings.public_base_url}/notifications/unsubscribe?token={unsubscribe_token(user_id, category)}"


@router.get("/preferences", response_model=NotificationPrefs)
def get_preferences(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _prefs(db, user)


@router.put("/preferences", response_model=NotificationPrefs)
def update_preferences(body: NotificationPrefs, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    prefs = _prefs(db, user)
    prefs.practice_reminders = body.practice_reminders
    prefs.product_updates = body.product_updates
    prefs.billing_emails = body.billing_emails
    db.commit()
    db.refresh(prefs)
    return prefs


_PAGE = """<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LinguaEar</title><style>body{{font-family:-apple-system,system-ui,sans-serif;background:#0b0f19;color:#fff;
display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0;text-align:center;padding:24px}}
h1{{font-size:24px;margin:0 0 8px}}p{{color:#8b93a7;margin:0}}</style></head>
<body><div><h1>{title}</h1><p>{text}</p></div></body></html>"""


@router.get("/unsubscribe", response_class=HTMLResponse, include_in_schema=False)
def unsubscribe(token: str, db: Session = Depends(get_db)):
    """The link in the footer of optional emails. It works without logging in."""
    try:
        claims = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id, category = int(claims["sub"]), claims["cat"]
        if claims.get("typ") != "unsub" or category not in UNSUBSCRIBE_CATEGORIES:
            raise ValueError
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This unsubscribe link is not valid.")

    user = db.get(User, user_id)
    if user is not None:
        setattr(_prefs(db, user), category, False)
        db.commit()
    return _PAGE.format(title="You're unsubscribed", text="You won't get these emails any more. You can change this in the app under Settings.")
