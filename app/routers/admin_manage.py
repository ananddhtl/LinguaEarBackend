from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import cast, func, or_, select, Date
from sqlalchemy.orm import Session

from app import limits, mailer
from app.billing import ACCESS_STATUSES, current_plan, status_for
from app.db import get_db
from app.models import (
    Analysis,
    Scenario,
    ScenarioRequest,
    ScoreEvent,
    Subscription,
    SupportTicket,
    TicketReply,
    UsageCount,
    User,
)
from app.routers.admin import require_admin
from app.schemas import (
    AdminTicketDetail,
    AdminTicketOut,
    AdminUserDetail,
    AdminUserList,
    AdminUserOut,
    AdminUserPatch,
    TicketReplyIn,
    TicketReplyOut,
    TicketStatusPatch,
)
import secrets

router = APIRouter(prefix="/admin", tags=["admin"])


# ---- Stats ----


@router.get("/stats")
def stats(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Numbers for the admin overview."""
    now = datetime.now(timezone.utc)
    today = limits._today()
    week_ago = now - timedelta(days=7)

    def count(query) -> int:
        return db.scalar(query) or 0

    signups = {
        str(day): n
        for day, n in db.execute(
            select(cast(User.created_at, Date), func.count(User.id))
            .where(User.created_at >= now - timedelta(days=14))
            .group_by(cast(User.created_at, Date))
        )
    }
    usage_today = {
        kind: total
        for kind, total in db.execute(
            select(UsageCount.kind, func.sum(UsageCount.count)).where(UsageCount.day == today).group_by(UsageCount.kind)
        )
    }
    tiers = {
        tier: n
        for tier, n in db.execute(
            select(Subscription.tier, func.count(Subscription.user_id))
            .where(Subscription.status.in_(ACCESS_STATUSES))
            .group_by(Subscription.tier)
        )
    }
    return {
        "users": {
            "total": count(select(func.count(User.id))),
            "verified": count(select(func.count(User.id)).where(User.email_verified)),
            "new_7d": count(select(func.count(User.id)).where(User.created_at >= week_ago)),
            "active_7d": count(
                select(func.count(func.distinct(UsageCount.user_id))).where(UsageCount.day >= today - timedelta(days=6))
            ),
            "on_trial": count(
                select(func.count(User.id)).where(
                    User.trial_ends_at > now,
                    ~select(Subscription.user_id).where(Subscription.user_id == User.id).exists(),
                )
            ),
        },
        "subscriptions": {"standard": tiers.get("standard", 0), "pro": tiers.get("pro", 0)},
        "tickets": {"open": count(select(func.count(SupportTicket.id)).where(SupportTicket.status == "open"))},
        "scenarios": {
            "live": count(select(func.count(Scenario.id)).where(Scenario.published)),
            "total": count(select(func.count(Scenario.id))),
            "pending_requests": count(select(func.count(ScenarioRequest.id)).where(ScenarioRequest.status == "pending")),
        },
        "ai_calls_today": {k: int(v or 0) for k, v in usage_today.items()},
        "signups_14d": signups,
    }


# ---- Users ----


def _user_out(db: Session, user: User) -> dict:
    return {**AdminUserOut.model_validate(user).model_dump(), "plan": current_plan(db, user)}


def _user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.get("/users", response_model=AdminUserList)
def list_users(
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = select(User)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(User.email.ilike(like), User.username.ilike(like), User.full_name.ilike(like)))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(User.id.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "users": [_user_out(db, u) for u in rows]}


@router.get("/users/{user_id}", response_model=AdminUserDetail)
def get_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = _user(db, user_id)
    return {
        **_user_out(db, user),
        "billing": status_for(db, user),
        "usage": limits.usage_summary(db, user),
        "points": db.scalar(select(func.coalesce(func.sum(ScoreEvent.points), 0)).where(ScoreEvent.user_id == user.id)),
        "saved_phrases": db.scalar(select(func.count(Analysis.id)).where(Analysis.user_id == user.id)) or 0,
        "tickets": db.scalar(select(func.count(SupportTicket.id)).where(SupportTicket.user_id == user.id)) or 0,
    }


@router.patch("/users/{user_id}", response_model=AdminUserOut)
def update_user(
    user_id: int, body: AdminUserPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    user = _user(db, user_id)
    changes = body.model_dump(exclude_unset=True)
    if user.id == admin.id and (changes.get("is_active") is False or changes.get("is_admin") is False):
        # Stops an admin from locking themselves (and possibly everyone) out.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot remove your own admin access or deactivate yourself")

    if (days := changes.pop("extend_trial_days", None)) is not None:
        base = max(user.trial_ends_at or datetime.now(timezone.utc), datetime.now(timezone.utc))
        user.trial_ends_at = base + timedelta(days=days)
    for field, value in changes.items():
        if value is not None:
            setattr(user, field, value)
    if changes.get("is_active") is False:
        user.token_secret = secrets.token_hex(32)  # signs them out of every device at once
    db.commit()
    db.refresh(user)
    return _user_out(db, user)


# ---- Support tickets ----


def _ticket_out(db: Session, ticket: SupportTicket) -> dict:
    owner = db.get(User, ticket.user_id)
    return {
        **AdminTicketOut.model_validate(
            {
                **{c: getattr(ticket, c) for c in ("id", "category", "subject", "message", "status", "created_at", "updated_at")},
                "user_id": ticket.user_id,
                "username": owner.username if owner else None,
                "email": owner.email if owner else None,
            }
        ).model_dump(),
    }


@router.get("/tickets", response_model=list[AdminTicketOut])
def list_tickets(
    status_filter: str | None = Query(default=None, alias="status", pattern="^(open|closed)$"),
    limit: int = Query(default=100, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = select(SupportTicket)
    if status_filter:
        query = query.where(SupportTicket.status == status_filter)
    tickets = db.scalars(query.order_by(SupportTicket.created_at.desc()).limit(limit)).all()
    return [_ticket_out(db, t) for t in tickets]


def _ticket(db: Session, ticket_id: int) -> SupportTicket:
    ticket = db.get(SupportTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    return ticket


def _detail(db: Session, ticket: SupportTicket) -> dict:
    replies = db.scalars(select(TicketReply).where(TicketReply.ticket_id == ticket.id).order_by(TicketReply.id)).all()
    return {**_ticket_out(db, ticket), "replies": [TicketReplyOut.model_validate(r).model_dump() for r in replies]}


@router.get("/tickets/{ticket_id}", response_model=AdminTicketDetail)
def get_ticket(ticket_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return _detail(db, _ticket(db, ticket_id))


@router.patch("/tickets/{ticket_id}", response_model=AdminTicketDetail)
def set_ticket_status(
    ticket_id: int, body: TicketStatusPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    ticket = _ticket(db, ticket_id)
    ticket.status = body.status
    db.commit()
    db.refresh(ticket)
    return _detail(db, ticket)


@router.post("/tickets/{ticket_id}/reply", response_model=AdminTicketDetail, status_code=status.HTTP_201_CREATED)
def reply_to_ticket(
    ticket_id: int,
    body: TicketReplyIn,
    tasks: BackgroundTasks,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Emails the answer to the user and keeps a copy on the ticket."""
    ticket = _ticket(db, ticket_id)
    owner = db.get(User, ticket.user_id)
    db.add(TicketReply(ticket_id=ticket.id, admin_id=admin.id, message=body.message.strip()))
    db.commit()
    if owner is not None:
        tasks.add_task(
            mailer.send_email,
            owner.email,
            f"Re: {ticket.subject} (ticket #{ticket.id})",
            f"{body.message.strip()}\n\n-- \nLinguaEar support\nYour original request: {ticket.subject}",
            mailer.support_address(),
        )
    return _detail(db, ticket)
