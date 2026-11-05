"""Thin client for the AI provider. Only the backend holds the API key."""
import httpx
from fastapi import HTTPException, status

from app.config import settings


class UpstreamError(Exception):
    """The provider failed (rate limit, outage, malformed output); the caller's quota is refunded."""

    def __init__(self, upstream_status: int, detail: str = ""):
        super().__init__(detail)
        self.upstream_status = upstream_status
        self.detail = detail


def require_key() -> None:
    """Checked before a call is counted, so a missing key never costs the user quota."""
    if not settings.groq_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI features are not configured on the server.")


def _headers() -> dict[str, str]:
    require_key()
    return {"Authorization": f"Bearer {settings.groq_api_key}"}


def _check(response: httpx.Response) -> None:
    if response.status_code != 200:
        raise UpstreamError(response.status_code, response.text[:300])


def chat(payload: dict) -> dict:
    try:
        response = httpx.post(
            f"{settings.groq_base_url}/chat/completions", headers=_headers(), json=payload, timeout=60
        )
    except httpx.HTTPError as err:
        raise UpstreamError(0, str(err)) from err
    _check(response)
    return response.json()


def transcribe(audio: bytes, filename: str, content_type: str, language: str | None) -> dict:
    data = {"model": settings.groq_whisper_model}
    if language:
        data["language"] = language
    try:
        response = httpx.post(
            f"{settings.groq_base_url}/audio/transcriptions",
            headers=_headers(),
            data=data,
            files={"file": (filename, audio, content_type)},
            timeout=60,
        )
    except httpx.HTTPError as err:
        raise UpstreamError(0, str(err)) from err
    _check(response)
    return response.json()
