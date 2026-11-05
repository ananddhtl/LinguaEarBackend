from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import mailer
from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models import SupportTicket, User
from app.schemas import TicketCreate, TicketOut

router = APIRouter(prefix="/support", tags=["support"])


def _owned(db: Session, user: User, ticket_id: int) -> SupportTicket:
    # Same 404 for "missing" and "someone else's", so ids can't be probed.
    ticket = db.scalar(select(SupportTicket).where(SupportTicket.id == ticket_id, SupportTicket.user_id == user.id))
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    return ticket


@router.post("/tickets", response_model=TicketOut, status_code=status.HTTP_201_CREATED)
def create_ticket(
    body: TicketCreate,
    tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Saves a help request and emails it to support. The user gets a confirmation email."""
    since = datetime.now(timezone.utc) - timedelta(days=1)
    recent = db.scalar(
        select(func.count(SupportTicket.id)).where(SupportTicket.user_id == user.id, SupportTicket.created_at >= since)
    )
    if recent >= settings.max_tickets_per_day:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"You can send up to {settings.max_tickets_per_day} requests a day. Please try again tomorrow.",
        )

    ticket = SupportTicket(user_id=user.id, **body.model_dump())
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    tasks.add_task(
        mailer.send_ticket_to_support, ticket.id, user.email, user.username, ticket.category, ticket.subject, ticket.message
    )
    tasks.add_task(mailer.send_ticket_confirmation, user.email, ticket.id, ticket.subject)
    return ticket


@router.get("/tickets", response_model=list[TicketOut])
def my_tickets(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = select(SupportTicket).where(SupportTicket.user_id == user.id).order_by(SupportTicket.created_at.desc()).limit(50)
    return db.scalars(query).all()


@router.get("/tickets/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _owned(db, user, ticket_id)


@router.post("/tickets/{ticket_id}/close", response_model=TicketOut)
def close_ticket(ticket_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ticket = _owned(db, user, ticket_id)
    ticket.status = "closed"
    db.commit()
    db.refresh(ticket)
    return ticket
