import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

log = logging.getLogger("uvicorn.error")


def send_email(to: str, subject: str, body: str) -> None:
    if not settings.smtp_host:
        log.warning("SMTP not configured - email to %s not sent:\nSubject: %s\n%s", to, subject, body)
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password or "")
            smtp.send_message(msg)
    except Exception:
        # Runs in a background task; a mail outage must not surface as a request error.
        log.exception("Failed to send email to %s", to)


def send_verification_email(to: str, token: str) -> None:
    link = f"{settings.frontend_url}/verify-email?token={token}"
    send_email(
        to,
        "Verify your LinguaEar email",
        f"Confirm your email address:\n{link}\n\nToken: {token}\n\n"
        f"This link expires in {settings.verify_email_hours} hours.",
    )


def send_password_reset_email(to: str, token: str) -> None:
    link = f"{settings.frontend_url}/reset-password?token={token}"
    send_email(
        to,
        "Reset your LinguaEar password",
        f"Reset your password:\n{link}\n\nToken: {token}\n\n"
        f"This link expires in {settings.reset_password_minutes} minutes. "
        "If you didn't ask for this, ignore this email.",
    )
