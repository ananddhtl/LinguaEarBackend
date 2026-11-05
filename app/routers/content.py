from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ContentBlock, User
from app.routers.admin import require_admin
from app.schemas import CONTENT_MODELS

public = APIRouter(prefix="/content", tags=["content"])
admin = APIRouter(prefix="/admin/content", tags=["admin"])


def _model(key: str):
    model = CONTENT_MODELS.get(key)
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown content key")
    return model


@public.get("/{key}")
def read(key: str, response: Response, db: Session = Depends(get_db)):
    """Website text that was edited in the admin. 404 means nothing was edited, so the site uses its built-in text."""
    _model(key)
    block = db.get(ContentBlock, key)
    if block is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not customised")
    response.headers["Cache-Control"] = "public, max-age=60"
    return block.data


@admin.get("")
def list_content(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    stored = {b.key: b for b in db.scalars(select(ContentBlock))}
    return [
        {
            "key": key,
            "customised": key in stored,
            "updated_at": stored[key].updated_at if key in stored else None,
        }
        for key in CONTENT_MODELS
    ]


@admin.get("/{key}")
def get_content(key: str, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    _model(key)
    block = db.get(ContentBlock, key)
    return {"key": key, "customised": block is not None, "data": block.data if block else None}


@admin.put("/{key}")
def save_content(key: str, body: dict, admin_user: User = Depends(require_admin), db: Session = Depends(get_db)):
    model = _model(key)
    try:
        data = model.model_validate(body).model_dump(exclude_none=True)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = " > ".join(str(p) for p in first["loc"])
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{where}: {first['msg']}")
    block = db.get(ContentBlock, key)
    if block is None:
        db.add(ContentBlock(key=key, data=data, updated_by=admin_user.id))
    else:
        block.data, block.updated_by = data, admin_user.id
    db.commit()
    return {"key": key, "customised": True, "data": data}


@admin.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
def reset_content(key: str, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Goes back to the built-in text."""
    _model(key)
    block = db.get(ContentBlock, key)
    if block is not None:
        db.delete(block)
        db.commit()
