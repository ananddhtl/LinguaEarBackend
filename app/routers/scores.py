from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import cast, Date, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.billing import require_subscriber
from app.deps import get_current_user
from app.models import Analysis, ScoreEvent, User
from app.schemas import GameScoreEvent, QuizScoreEvent, ScoreAwarded, ScoreSummary

router = APIRouter(prefix="/scores", tags=["scores"])


def _total(db: Session, user: User) -> int:
    return db.scalar(select(func.coalesce(func.sum(ScoreEvent.points), 0)).where(ScoreEvent.user_id == user.id))


def _streak(days: set[date], today: date) -> int:
    """Consecutive days with a score, ending today (or yesterday, so the streak survives until tonight)."""
    day = today if today in days else today - timedelta(days=1)
    count = 0
    while day in days:
        count += 1
        day -= timedelta(days=1)
    return count


@router.post("/quiz", response_model=ScoreAwarded)
def record_quiz(
    body: QuizScoreEvent,
    user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    """Points for finishing a quiz: per correct answer, plus a bonus for a perfect round."""
    points = body.correct * settings.points_per_correct_answer
    if body.correct == body.total and body.total >= 3:
        points += settings.perfect_quiz_bonus

    if body.analysis_id is not None:
        owned = db.scalar(select(Analysis.id).where(Analysis.id == body.analysis_id, Analysis.user_id == user.id))
        if owned is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found")
        # Retaking a saved phrase's quiz earns nothing more.
        db.add(ScoreEvent(user_id=user.id, kind="quiz", points=points, ref_id=body.analysis_id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return ScoreAwarded(points=0, total_points=_total(db, user))
    else:
        db.add(ScoreEvent(user_id=user.id, kind="quiz", points=points))
        db.commit()
    return ScoreAwarded(points=points, total_points=_total(db, user))


@router.post("/game", response_model=ScoreAwarded)
def record_game(
    body: GameScoreEvent,
    user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    points = min(body.points, settings.max_game_points_per_event)
    if points > 0:
        db.add(ScoreEvent(user_id=user.id, kind="game", points=points))
        db.commit()
    return ScoreAwarded(points=points, total_points=_total(db, user))


@router.get("/me", response_model=ScoreSummary)
def my_score(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    total = _total(db, user)
    now = datetime.now(timezone.utc)
    start_of_day = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)

    today_points = db.scalar(
        select(func.coalesce(func.sum(ScoreEvent.points), 0)).where(
            ScoreEvent.user_id == user.id, ScoreEvent.created_at >= start_of_day
        )
    )
    day = cast(func.timezone("UTC", ScoreEvent.created_at), Date)
    days = set(
        db.scalars(
            select(day).where(ScoreEvent.user_id == user.id).distinct().order_by(day.desc()).limit(400)
        ).all()
    )

    return ScoreSummary(
        total_points=total,
        level=total // settings.points_per_level + 1,
        level_points=total % settings.points_per_level,
        level_size=settings.points_per_level,
        streak_days=_streak(days, now.date()),
        today_points=today_points,
    )
