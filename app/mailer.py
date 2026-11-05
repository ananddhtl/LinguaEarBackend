import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

log = logging.getLogger("uvicorn.error")


def send_email(to: str, subject: str, body: str, reply_to: str | None = None) -> None:
    if settings.log_email_bodies:
        log.warning("[dev] email to %s\nSubject: %s\n%s", to, subject, body)
    if not settings.smtp_host:
        log.warning("SMTP not configured - email to %s not sent:\nSubject: %s\n%s", to, subject, body)
        return
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.smtp_from, to, subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    # Runs in a background task; a mail outage must not surface as a request error. SMTP servers are
    # occasionally slow to answer, so one retry catches most one-off timeouts.
    for attempt in (1, 2):
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
                smtp.starttls()
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password or "")
                smtp.send_message(msg)
            return
        except Exception:
            if attempt == 2:
                log.exception("Failed to send email to %s", to)
            else:
                log.warning("Sending email to %s failed, retrying once", to)


def send_verification_code_email(to: str, code: str) -> None:
    send_email(
        to,
        f"{code} is your LinguaEar verification code",
        f"Your LinguaEar verification code is:\n\n    {code}\n\n"
        f"It expires in {settings.verification_code_minutes} minutes. "
        "If you didn't create an account, you can ignore this email.",
    )


def send_verification_email(to: str, token: str) -> None:
    link = f"{settings.frontend_url}/verify-email?token={token}"
    send_email(
        to,
        "Verify your LinguaEar email",
        f"Confirm your email address:\n{link}\n\nToken: {token}\n\n"
        f"This link expires in {settings.verify_email_hours} hours.",
    )


def send_password_reset_code_email(to: str, code: str) -> None:
    send_email(
        to,
        f"{code} is your LinguaEar password reset code",
        f"Your LinguaEar password reset code is:\n\n    {code}\n\n"
        f"It expires in {settings.verification_code_minutes} minutes. "
        "If you didn't ask to reset your password, you can ignore this email: your password has not changed.",
    )


def support_address() -> str | None:
    return settings.support_email or settings.smtp_user


def send_ticket_to_support(ticket_id: int, user_email: str, username: str, category: str, subject: str, message: str) -> None:
    to = support_address()
    if not to:
        log.warning("No support address configured: ticket %s was saved but not emailed", ticket_id)
        return
    send_email(
        to,
        f"[LinguaEar ticket #{ticket_id}] {subject}",
        f"From: {username} <{user_email}>\nCategory: {category}\n\n{message}\n\n"
        "Reply to this email to answer the user directly.",
        reply_to=user_email,
    )


def send_ticket_confirmation(to: str, ticket_id: int, subject: str) -> None:
    send_email(
        to,
        f"We got your message (ticket #{ticket_id})",
        f"Thanks for contacting LinguaEar. We received your request:\n\n    {subject}\n\n"
        "We will reply to this email address as soon as we can.",
        reply_to=support_address(),
    )


def send_practice_reminder(to: str, name: str, streak_days: int, unsubscribe_url: str) -> None:
    streak = f"You are on a {streak_days}-day streak. Keep it going!" if streak_days else "Even five minutes counts."
    send_email(
        to,
        "Time for your German practice",
        f"Hi {name},\n\n{streak}\n\nOpen LinguaEar and practise a phrase today.\n\n"
        f"You can stop these reminders at any time: {unsubscribe_url}",
    )
