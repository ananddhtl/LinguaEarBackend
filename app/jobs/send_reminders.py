"""Emails a practice reminder to users who asked for one and haven't practised today.

Run it once a day from cron, for example at 17:00:
    0 17 * * *  cd /path/to/LinguaEarBackend && .venv/bin/python -m app.jobs.send_reminders

Use --dry-run to list who would be emailed without sending anything.
"""
import sys
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select

from app import mailer
from app.db import SessionLocal
from app.models import NotificationPreference, ScoreEvent, User
from app.routers.notifications import unsubscribe_url
from app.routers.scores import _streak


def run(dry_run: bool = False) -> int:
    now = datetime.now(timezone.utc)
    start_of_day = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    sent = 0

    with SessionLocal() as db:
        rows = db.execute(
            select(User, NotificationPreference)
            .join(NotificationPreference, NotificationPreference.user_id == User.id)
            .where(
                NotificationPreference.practice_reminders.is_(True),
                User.is_active.is_(True),
                User.email_verified.is_(True),
            )
        ).all()

        for user, prefs in rows:
            if prefs.last_reminder_at and now - prefs.last_reminder_at < timedelta(hours=20):
                continue  # at most one a day
            practised_today = db.scalar(
                select(ScoreEvent.id).where(ScoreEvent.user_id == user.id, ScoreEvent.created_at >= start_of_day).limit(1)
            )
            if practised_today:
                continue

            days = set(
                d.date()
                for d in db.scalars(select(ScoreEvent.created_at).where(ScoreEvent.user_id == user.id)).all()
            )
            streak = _streak(days, now.date())
            print(f"{'would send' if dry_run else 'sending'} to {user.email} (streak {streak})")
            if not dry_run:
                mailer.send_practice_reminder(
                    user.email, user.username, streak, unsubscribe_url(user.id, "practice_reminders")
                )
                prefs.last_reminder_at = now
                db.commit()
            sent += 1
    return sent


if __name__ == "__main__":
    count = run(dry_run="--dry-run" in sys.argv)
    print(f"done: {count} reminder(s)")
