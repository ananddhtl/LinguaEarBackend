import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from pwdlib import PasswordHash

from app.config import settings
from app.models import User

_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return _hasher.verify(password, hashed)


def _user_key(user: User) -> bytes:
    """Signing key unique to this user: server secret combined with the user's own secret."""
    return hmac.new(settings.secret_key.encode(), user.token_secret.encode(), hashlib.sha256).digest()


def _encode(user: User, claims: dict, expires_at: datetime) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            **claims,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "sub": str(user.id),
            "username": user.username,
            "email": user.email,
            "iat": now,
            "nbf": now,
            "exp": expires_at,
        },
        _user_key(user),
        algorithm=settings.jwt_algorithm,
    )


def create_access_token(user: User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)
    return _encode(user, {"type": "access", "jti": str(uuid.uuid4())}, exp)


def create_refresh_token(user: User, jti: uuid.UUID, expires_at: datetime) -> str:
    return _encode(user, {"type": "refresh", "jti": str(jti)}, expires_at)


def token_user_id(token: str) -> int:
    """Reads the (still unverified) subject so the right user's key can be looked up.

    Never trust the result until decode_token() has verified the signature.
    """
    claims = jwt.decode(token, options={"verify_signature": False})
    return int(claims["sub"])


def decode_token(token: str, expected_type: str, user: User) -> dict:
    """Raises jwt.PyJWTError if invalid, expired, signed for another user, or the wrong type."""
    payload = jwt.decode(
        token,
        _user_key(user),
        algorithms=[settings.jwt_algorithm],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
    )
    if payload.get("type") != expected_type or payload.get("sub") != str(user.id):
        raise jwt.InvalidTokenError("wrong token")
    return payload
