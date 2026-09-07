from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

settings = get_settings()
password_hasher = PasswordHasher()


class TokenError(ValueError):
    """Raised when an authentication token cannot be trusted."""


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(
    *,
    user_id: UUID,
    organization_id: UUID,
    role: str,
    session_id: UUID,
    identity_source: str,
    auth_method: str,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org": str(organization_id),
        "role": role,
        "sid": str(session_id),
        "src": identity_source,
        "amr": auth_method,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "iss": settings.token_issuer,
        "aud": settings.token_audience,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            issuer=settings.token_issuer,
            audience=settings.token_audience,
        )
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid or expired access token") from exc

    required_claims = ("sub", "org", "sid", "src", "amr")
    if any(not payload.get(claim) for claim in required_claims):
        raise TokenError("Token is missing required identity or session claims")
    return payload
