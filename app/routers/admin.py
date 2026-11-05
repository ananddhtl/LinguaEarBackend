from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import Scenario, ScenarioRequest, User
from app.schemas import (
    ScenarioIn,
    ScenarioOut,
    ScenarioPatch,
    ScenarioRequestAdminOut,
    ScenarioRequestReview,
)


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        # Same answer as a missing page, so the admin area isn't advertised.
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return user


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/me")
def me(user: User = Depends(require_admin)):
    """Lets the admin portal check that the signed-in account is an admin."""
    return {"id": user.id, "username": user.username, "email": user.email}


def _scenario(db: Session, scenario_id: int) -> Scenario:
    scenario = db.get(Scenario, scenario_id)
    if scenario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scenario not found")
    return scenario


@router.get("/scenarios", response_model=list[ScenarioOut])
def all_scenarios(db: Session = Depends(get_db)):
    """Every scenario, published or not."""
    return db.scalars(select(Scenario).order_by(Scenario.sort_order, Scenario.id)).all()


@router.post("/scenarios", response_model=ScenarioOut, status_code=status.HTTP_201_CREATED)
def create_scenario(body: ScenarioIn, db: Session = Depends(get_db)):
    if db.scalar(select(Scenario.id).where(Scenario.slug == body.slug)):
        raise HTTPException(status.HTTP_409_CONFLICT, "That slug is already used")
    data = body.model_dump()
    scenario = Scenario(**data)
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    return scenario


@router.patch("/scenarios/{scenario_id}", response_model=ScenarioOut)
def update_scenario(scenario_id: int, body: ScenarioPatch, db: Session = Depends(get_db)):
    scenario = _scenario(db, scenario_id)
    changes = body.model_dump(exclude_unset=True)
    if "openings" in changes and changes["openings"] is not None:
        merged = {**scenario.openings, **changes["openings"]}
        if any(not str(merged.get(lv, "")).strip() for lv in ("beginner", "intermediate", "professional")):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "An opening line is needed for every level")
        changes["openings"] = merged
    for field, value in changes.items():
        if value is not None:
            setattr(scenario, field, value)
    db.commit()
    db.refresh(scenario)
    return scenario


@router.delete("/scenarios/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scenario(scenario_id: int, db: Session = Depends(get_db)):
    db.delete(_scenario(db, scenario_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/scenario-requests", response_model=list[ScenarioRequestAdminOut])
def scenario_requests(
    status_filter: str | None = Query(None, alias="status", pattern="^(pending|approved|rejected)$"),
    db: Session = Depends(get_db),
):
    query = select(ScenarioRequest, User.username).join(User, User.id == ScenarioRequest.user_id)
    if status_filter:
        query = query.where(ScenarioRequest.status == status_filter)
    rows = db.execute(query.order_by(ScenarioRequest.created_at.desc()).limit(200)).all()
    return [{**ScenarioRequestAdminOut.model_validate(r).model_dump(), "username": name} for r, name in rows]


@router.patch("/scenario-requests/{request_id}", response_model=ScenarioRequestAdminOut)
def review_request(request_id: int, body: ScenarioRequestReview, db: Session = Depends(get_db)):
    req = db.get(ScenarioRequest, request_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    req.status = body.status
    req.admin_note = body.admin_note
    db.commit()
    db.refresh(req)
    username = db.scalar(select(User.username).where(User.id == req.user_id))
    return {**ScenarioRequestAdminOut.model_validate(req).model_dump(), "username": username}
