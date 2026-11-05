from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import cast, func, or_, select, Date
from sqlalchemy.orm import Session

from app import limits, mailer
from app.billing import ACCESS_STATUSES, current_plan, status_for
from app.db import get_db
from app.config import settings
from app.models import (
    Analysis,
    RefreshToken,
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
    AdminHistoryPage,
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


def _account_type(user: User, plan: str | None, subscribed: bool) -> str:
    if user.is_admin:
        return "admin"
    if subscribed and plan:
        return plan
    return "trial" if plan else "expired"


def _users_out(db: Session, users: list[User]) -> list[dict]:
    """Profile, plan and activity numbers for a page of users, with one query per number rather than per user."""
    if not users:
        return []
    ids = [u.id for u in users]
    today = limits._today()

    def per_user(query) -> dict:
        return {uid: value for uid, value in db.execute(query)}

    points = per_user(
        select(ScoreEvent.user_id, func.sum(ScoreEvent.points)).where(ScoreEvent.user_id.in_(ids)).group_by(ScoreEvent.user_id)
    )
    saved = per_user(
        select(Analysis.user_id, func.count(Analysis.id)).where(Analysis.user_id.in_(ids)).group_by(Analysis.user_id)
    )
    calls_7d = per_user(
        select(UsageCount.user_id, func.sum(UsageCount.count))
        .where(UsageCount.user_id.in_(ids), UsageCount.day >= today - timedelta(days=6))
        .group_by(UsageCount.user_id)
    )
    calls_today = per_user(
        select(UsageCount.user_id, func.sum(UsageCount.count))
        .where(UsageCount.user_id.in_(ids), UsageCount.day == today)
        .group_by(UsageCount.user_id)
    )
    last_seen = per_user(
        select(RefreshToken.user_id, func.max(RefreshToken.created_at))
        .where(RefreshToken.user_id.in_(ids))
        .group_by(RefreshToken.user_id)
    )
    subscribed = {
        uid
        for (uid,) in db.execute(
            select(Subscription.user_id).where(Subscription.user_id.in_(ids), Subscription.status.in_(ACCESS_STATUSES))
        )
    }

    rows = []
    for u in users:
        plan = current_plan(db, u)
        total = int(points.get(u.id) or 0)
        rows.append(
            {
                **AdminUserOut.model_validate(u).model_dump(),
                "plan": plan,
                "account_type": _account_type(u, plan, u.id in subscribed),
                "points": total,
                "level": total // settings.points_per_level + 1,
                "saved_phrases": int(saved.get(u.id) or 0),
                "calls_today": int(calls_today.get(u.id) or 0),
                "calls_7d": int(calls_7d.get(u.id) or 0),
                "last_active": last_seen.get(u.id),
            }
        )
    return rows


def _user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.get("/users", response_model=AdminUserList)
def list_users(
    q: str | None = Query(default=None, max_length=100),
    kind: str | None = Query(default=None, pattern="^(admin|pro|standard|trial|expired|disabled)$"),
    limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = select(User)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(User.email.ilike(like), User.username.ilike(like), User.full_name.ilike(like)))
    if kind == "disabled":
        query = query.where(User.is_active.is_(False))
    elif kind == "admin":
        query = query.where(User.is_admin)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    if kind in ("pro", "standard", "trial", "expired"):
        # The plan is worked out from billing rules, so these filters run over the matches in Python.
        everyone = _users_out(db, db.scalars(query.order_by(User.id.desc())).all())
        matches = [r for r in everyone if r["account_type"] == kind]
        return {"total": len(matches), "users": matches[offset : offset + limit]}
    rows = db.scalars(query.order_by(User.id.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "users": _users_out(db, rows)}


@router.get("/users/{user_id}", response_model=AdminUserDetail)
def get_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = _user(db, user_id)
    today = limits._today()
    per_day = {
        str(day): int(n or 0)
        for day, n in db.execute(
            select(UsageCount.day, func.sum(UsageCount.count))
            .where(UsageCount.user_id == user.id, UsageCount.day >= today - timedelta(days=13))
            .group_by(UsageCount.day)
        )
    }
    scores = db.scalars(
        select(ScoreEvent).where(ScoreEvent.user_id == user.id).order_by(ScoreEvent.id.desc()).limit(10)
    ).all()
    return {
        **_users_out(db, [user])[0],
        "billing": status_for(db, user),
        "usage": limits.usage_summary(db, user),
        "tickets": db.scalar(select(func.count(SupportTicket.id)).where(SupportTicket.user_id == user.id)) or 0,
        "daily_usage": [
            {"day": str(today - timedelta(days=i)), "calls": per_day.get(str(today - timedelta(days=i)), 0)}
            for i in range(13, -1, -1)
        ],
        "recent_scores": [{"kind": e.kind, "points": e.points, "created_at": e.created_at} for e in scores],
    }


@router.get("/users/{user_id}/history", response_model=AdminHistoryPage)
def user_history(
    user_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """The phrases and scans this user chose to save. Prompts they did not save are never stored."""
    _user(db, user_id)
    where = Analysis.user_id == user_id
    total = db.scalar(select(func.count(Analysis.id)).where(where)) or 0
    items = db.scalars(select(Analysis).where(where).order_by(Analysis.id.desc()).limit(limit).offset(offset)).all()
    return {"total": total, "items": items}


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
    return _users_out(db, [user])[0]


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
