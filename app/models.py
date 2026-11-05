import secrets
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    full_name: Mapped[str | None] = mapped_column(String(100))
    bio: Mapped[str | None] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Per-user signing secret; rotating it invalidates every token this user holds.
    token_secret: Mapped[str] = mapped_column(String(64), default=lambda: secrets.token_hex(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # End of the free trial; after this, access needs a subscription.
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    # Can use the /admin endpoints (the future admin panel). Set it by hand: UPDATE users SET is_admin = true ...
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class OneTimeToken(Base):
    """Single-use emailed token (email verification, email change, password reset).

    Only a SHA-256 hash is stored, so a database leak doesn't expose usable tokens.
    """

    __tablename__ = "one_time_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(20))  # verify_email | change_email | reset_password
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    new_email: Mapped[str | None] = mapped_column(String(320))  # only for change_email
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # wrong guesses (codes)


class RefreshToken(Base):
    """One row per issued refresh token (keyed by its JWT `jti`).

    Tokens are rotated on every refresh; `family_id` ties a chain of rotations
    together so reuse of an old token can revoke the whole chain.
    """

    __tablename__ = "refresh_tokens"

    jti: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    family_id: Mapped[uuid.UUID] = mapped_column(index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    remember_me: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Analysis(Base):
    """A saved tutor result for one spoken phrase. Text only: audio is never stored."""

    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    transcript: Mapped[str] = mapped_column(Text)
    # Where the phrase came from: spoken into the mic or read from the camera.
    source: Mapped[str] = mapped_column(String(10), default="speech", server_default="speech")
    translation: Mapped[str] = mapped_column(Text, default="", server_default="")  # camera scans
    explanation: Mapped[str] = mapped_column(Text, default="")
    tone: Mapped[str] = mapped_column(String(100), default="")
    grammar: Mapped[str] = mapped_column(Text, default="")
    quiz: Mapped[str] = mapped_column(Text, default="")
    articles: Mapped[list] = mapped_column(JSONB, default=list)  # [{word, gender}]
    compounds: Mapped[list] = mapped_column(JSONB, default=list)  # [{word, parts:[{text, meaning}], meaning}]
    # [{question, options, answer_index, explanation}]; `quiz` above is the older free-text form.
    quiz_questions: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    # Latest quiz result for this phrase; both are null until the quiz has been finished.
    quiz_score: Mapped[int | None] = mapped_column(Integer)
    quiz_total: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class ScoreEvent(Base):
    """Append-only ledger of points a user earned; totals are summed from it."""

    __tablename__ = "score_events"
    __table_args__ = (
        # A saved phrase's quiz pays out once, so retaking it can't be farmed.
        UniqueConstraint("user_id", "kind", "ref_id", name="uq_score_event_ref"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # quiz | game
    points: Mapped[int] = mapped_column(Integer)
    ref_id: Mapped[int | None] = mapped_column(Integer)  # analysis id for quiz events
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class UsageCount(Base):
    """How many times a user has called one AI feature on one (UTC) day."""

    __tablename__ = "usage_counts"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(12), primary_key=True)  # analyze | game | scan | transcribe
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class Subscription(Base):
    """A user's Stripe subscription, kept in step by webhooks. One row per user."""

    __tablename__ = "subscriptions"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    stripe_subscription_id: Mapped[str] = mapped_column(String(64), unique=True)
    tier: Mapped[str] = mapped_column(String(10))  # standard | pro
    status: Mapped[str] = mapped_column(String(20))  # Stripe status: active, trialing, past_due, canceled, ...
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SupportTicket(Base):
    """A help request from a user. Replies go out by email, so a ticket only tracks its own status."""

    __tablename__ = "support_tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(12))  # bug | account | billing | feature | other
    subject: Mapped[str] = mapped_column(String(120))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")  # open | closed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TicketReply(Base):
    """An answer from support. It is emailed to the user and kept here so the thread can be read later."""

    __tablename__ = "ticket_replies"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("support_tickets.id", ondelete="CASCADE"), index=True)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NotificationPreference(Base):
    """Which optional emails a user wants. Security emails (codes, password resets) are always sent."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # Reminders and updates are opt-in; billing emails are about the user's own subscription.
    practice_reminders: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    product_updates: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    billing_emails: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Scenario(Base):
    """A role-play situation for the game. Managed from the admin API, not in the app code."""

    __tablename__ = "scenarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(240))
    category: Mapped[str] = mapped_column(String(30), index=True)
    icon: Mapped[str] = mapped_column(String(40), default="chatbubbles-outline")  # an Ionicons name
    tint: Mapped[str] = mapped_column(String(9), default="#6366F1")
    # Instructions for the AI: who it plays and how it behaves (English, the AI answers in German).
    persona: Mapped[str] = mapped_column(Text)
    # The first line the other person says, per level: {"beginner": "...", "intermediate": "...", "professional": "..."}
    openings: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Phrases worth knowing before starting: [{"de": "...", "en": "..."}]
    key_phrases: Mapped[list] = mapped_column(JSONB, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    published: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ScenarioRequest(Base):
    """A scenario a user would like to see. An admin reads it and, if it fits, writes the scenario."""

    __tablename__ = "scenario_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")  # pending | approved | rejected
    admin_note: Mapped[str] = mapped_column(String(300), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
