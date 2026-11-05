from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.models import Scenario, ScenarioRequest, User
from app.scenario_levels import LEVELS
from app.schemas import ScenarioList, ScenarioRequestIn, ScenarioRequestOut

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


@router.get("", response_model=ScenarioList)
def list_scenarios(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The published scenarios and the conversation levels, in display order."""
    scenarios = db.scalars(
        select(Scenario).where(Scenario.published.is_(True)).order_by(Scenario.sort_order, Scenario.id)
    ).all()
    return {"levels": LEVELS, "scenarios": scenarios}


@router.post("/requests", response_model=ScenarioRequestOut, status_code=status.HTTP_201_CREATED)
def request_scenario(
    body: ScenarioRequestIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Suggest a scenario. An admin reviews it; nothing is published automatically."""
    since = datetime.now(timezone.utc) - timedelta(days=1)
    recent = db.scalar(
        select(func.count(ScenarioRequest.id)).where(
            ScenarioRequest.user_id == user.id, ScenarioRequest.created_at >= since
        )
    )
    if recent >= settings.max_scenario_requests_per_day:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"You can suggest up to {settings.max_scenario_requests_per_day} scenarios a day. Try again tomorrow.",
        )
    req = ScenarioRequest(user_id=user.id, title=body.title.strip(), description=body.description.strip())
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


@router.get("/requests/mine", response_model=list[ScenarioRequestOut])
def my_requests(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(ScenarioRequest)
        .where(ScenarioRequest.user_id == user.id)
        .order_by(ScenarioRequest.created_at.desc())
        .limit(50)
    ).all()
