import logging
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app import groq, limits
from app.config import settings
from app.db import get_db
from app.billing import require_subscriber
from app.deps import get_current_user
from app.models import User
from app.schemas import ChatRequest, UsageSummary

log = logging.getLogger(__name__)

router = APIRouter(tags=["ai"])

Kind = Literal["analyze", "game", "scan"]


def _validate_prompt(body: ChatRequest, kind: str) -> None:
    """Keeps the proxy to its job: bounded text, and images only for scans (as inline data, never a URL)."""
    chars = 0
    images = 0
    for message in body.messages:
        if isinstance(message.content, str):
            chars += len(message.content)
            continue
        for part in message.content:
            if part.get("type") == "text":
                chars += len(str(part.get("text", "")))
            elif part.get("type") == "image_url":
                url = str((part.get("image_url") or {}).get("url", ""))
                if kind != "scan" or not url.startswith("data:image/"):
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Images are only accepted for scans, as data URLs.")
                if len(url) > settings.max_image_chars:
                    raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The photo is too large.")
                images += 1
            else:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported message content.")
    if chars > settings.max_prompt_chars:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The request is too long.")
    if images > 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Send one photo at a time.")


def _upstream_failed(err: groq.UpstreamError) -> HTTPException:
    log.warning("AI provider error %s: %s", err.upstream_status, err.detail)
    return HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        {"code": "upstream", "message": "The AI service had a problem. Please try again.", "upstream": err.upstream_status, "retryable": True},
    )


@router.post("/ai/chat/{kind}")
def chat(
    kind: Kind,
    body: ChatRequest,
    user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    """Forwards a prompt to the provider using the server's key, counting it against the user's daily quota.

    The model, token cap and options are chosen here, not by the client. The reply is the provider's own
    chat-completion JSON, so the app reads it exactly as before.
    """
    _validate_prompt(body, kind)
    groq.require_key()
    limits.check_burst(user)
    limits.consume(db, user, kind)

    payload = {
        "model": settings.groq_vision_model if kind == "scan" else settings.groq_text_model,
        "messages": [m.model_dump() for m in body.messages],
        "temperature": body.temperature,
        "max_completion_tokens": settings.max_output_tokens,
    }
    if body.json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        return groq.chat(payload)
    except groq.UpstreamError as err:
        limits.refund(db, user, kind)
        raise _upstream_failed(err)


@router.post("/ai/transcribe")
def transcribe(
    file: UploadFile = File(...),
    language: Literal["de", "en"] | None = Form(None),
    user: User = Depends(require_subscriber),
    db: Session = Depends(get_db),
):
    audio = file.file.read(settings.max_audio_bytes + 1)
    if len(audio) > settings.max_audio_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The recording is too long.")
    if not audio:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The recording is empty.")

    groq.require_key()
    limits.check_burst(user)
    limits.consume(db, user, "transcribe")
    try:
        result = groq.transcribe(audio, file.filename or "recording.m4a", file.content_type or "audio/m4a", language)
    except groq.UpstreamError as err:
        limits.refund(db, user, "transcribe")
        raise _upstream_failed(err)
    return {"text": result.get("text", "")}


@router.get("/usage/me", response_model=UsageSummary)
def my_usage(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return limits.usage_summary(db, user)
