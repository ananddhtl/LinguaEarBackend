import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import decode_token, token_user_id

# Makes Swagger's Authorize button show an email/password login that hits /auth/token.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", {"WWW-Authenticate": "Bearer"}
    )
    if token is None:
        raise unauthorized
    try:
        user = db.get(User, token_user_id(token))
        if user is None or not user.is_active:
            raise unauthorized
        decode_token(token, "access", user)
    except (jwt.PyJWTError, KeyError, ValueError):
        raise unauthorized
    return user
