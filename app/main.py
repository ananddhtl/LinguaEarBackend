from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers import auth, users

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
    ],
)
app.include_router(auth.router)
app.include_router(users.router)


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}
