import secrets
import smtplib

import httpx

from fastapi import APIRouter, HTTPException, Query, status

from app.config import settings

router = APIRouter(tags=["diagnostics"], include_in_schema=False)


@router.get("/health/email")
def email_health(token: str | None = Query(None)):
    """Tests the SMTP connection step by step, without sending anything, and says where it stops.

    Off unless DIAGNOSTICS_TOKEN is set, and it never reveals the password or other secrets.
    """
    expected = settings.diagnostics_token
    if not expected or not token or not secrets.compare_digest(token, expected):
        raise HTTPException(status.HTTP_404_NOT_FOUND)  # looks like any other missing page

    if settings.brevo_api_key:
        # With the web API configured, this is the path mail takes, so test that one.
        try:
            r = httpx.get(
                "https://api.brevo.com/v3/account",
                headers={"api-key": settings.brevo_api_key, "accept": "application/json"},
                timeout=15,
            )
            return {
                "method": "brevo-api",
                "ok": r.status_code == 200,
                "status": r.status_code,
                "from": settings.smtp_from,
                "detail": "key accepted" if r.status_code == 200 else r.text[:200],
            }
        except Exception as err:
            return {"method": "brevo-api", "ok": False, "error": f"{type(err).__name__}: {str(err)[:160]}"}

    report = {
        "method": "smtp",
        "host": settings.smtp_host,
        "port": settings.smtp_port,
        "user_set": bool(settings.smtp_user),
        "password_set": bool(settings.smtp_password),
        "from": settings.smtp_from,
    }
    if not settings.smtp_host:
        return {**report, "ok": False, "stage": "config", "error": "SMTP_HOST is not set"}

    stage = "connect"
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            stage = "starttls"
            smtp.starttls()
            if settings.smtp_user:
                stage = "login"
                smtp.login(settings.smtp_user, settings.smtp_password or "")
        return {**report, "ok": True, "stage": "login" if settings.smtp_user else "starttls"}
    except Exception as err:
        return {**report, "ok": False, "stage": stage, "error": f"{type(err).__name__}: {str(err)[:160]}"}
