from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app import plans
from app.billing import current_plan, require_subscriber
from app.models import Analysis, User
from app.schemas import AnalysisCreate, AnalysisOut, QuizScore

router = APIRouter(prefix="/analyses", tags=["analyses"])


def _owned(db: Session, user: User, analysis_id: int) -> Analysis:
    # Same 404 for "missing" and "someone else's", so ids can't be probed.
    analysis = db.scalar(select(Analysis).where(Analysis.id == analysis_id, Analysis.user_id == user.id))
    if analysis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analysis not found")
    return analysis


@router.post("", response_model=AnalysisOut, status_code=status.HTTP_201_CREATED)
def save_analysis(
    body: AnalysisCreate,
    user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    saved = db.scalar(select(func.count(Analysis.id)).where(Analysis.user_id == user.id))
    cap = plans.limits_for(current_plan(db, user) or "standard").saved_phrases
    if saved >= cap:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"You've reached the limit of {cap} saved phrases. Delete some to save more.",
        )
    analysis = Analysis(user_id=user.id, **body.model_dump())
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


@router.get("", response_model=list[AnalysisOut])
def list_analyses(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    source: Literal["speech", "scan"] | None = Query(None, description="Only phrases spoken or only scanned"),
    since: datetime | None = Query(None, description="Only phrases saved at or after this moment"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Newest first. `source` and `since` narrow the list."""
    query = select(Analysis).where(Analysis.user_id == user.id)
    if source is not None:
        query = query.where(Analysis.source == source)
    if since is not None:
        query = query.where(Analysis.created_at >= since)
    query = query.order_by(Analysis.created_at.desc(), Analysis.id.desc()).limit(limit).offset(offset)
    return db.scalars(query).all()


@router.get("/{analysis_id}", response_model=AnalysisOut)
def get_analysis(
    analysis_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _owned(db, user, analysis_id)


@router.patch("/{analysis_id}/quiz-score", response_model=AnalysisOut)
def update_quiz_score(
    analysis_id: int,
    body: QuizScore,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Records the result of taking (or retaking) the quiz for a saved phrase."""
    analysis = _owned(db, user, analysis_id)
    analysis.quiz_score = body.quiz_score
    analysis.quiz_total = body.quiz_total
    db.commit()
    db.refresh(analysis)
    return analysis


@router.delete("/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_analysis(
    analysis_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.delete(_owned(db, user, analysis_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
