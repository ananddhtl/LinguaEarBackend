import os

from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers import ai, analyses, auth, billing, diagnostics, notifications, scores, support, users

app = FastAPI(
    title="LinguaEar API",
    version="0.1.0",
    description=(
        "JWT authentication with rotating refresh tokens.\n\n"
        "**Try it in Swagger:** register via `POST /auth/register`, click **Authorize**, "
        "and log in with your email as the username."
    ),
    openapi_tags=[
        {"name": "auth", "description": "Register, log in, refresh, verify email, reset password."},
        {"name": "profile", "description": "View and update the signed-in user's profile and password."},
        {"name": "support", "description": "Help requests (tickets) from users."},
        {"name": "notifications", "description": "Optional email preferences and unsubscribe links."},
        {"name": "billing", "description": "Free trial, plans and Stripe checkout."},
        {"name": "ai", "description": "AI features (speech to text, tutor, game, camera) with daily per-user limits."},
        {"name": "scores", "description": "Points, level and streak for the signed-in user."},
        {"name": "analyses", "description": "Save, list and delete the signed-in user's tutor results."},
    ],
)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(analyses.router)
app.include_router(scores.router)
app.include_router(ai.router)
app.include_router(diagnostics.router)
app.include_router(billing.router)
app.include_router(support.router)
app.include_router(notifications.router)


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    # Render sets RENDER_GIT_COMMIT, so this shows which version of the code is actually running.
    return {"status": "ok", "commit": os.getenv("RENDER_GIT_COMMIT", "")[:7] or None}
