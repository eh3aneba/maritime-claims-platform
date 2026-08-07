from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import TokenError, decode_access_token
from app.db.session import get_db
from app.modules.organizations.models import Organization, OrganizationStatus
from app.modules.users.models import User, UserRole

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)


def _extract_token(
    credentials: HTTPAuthorizationCredentials | None,
    cookie_token: str | None,
) -> str | None:
    if credentials and credentials.scheme.lower() == "bearer":
        return credentials.credentials
    return cookie_token


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    cookie_token: Annotated[str | None, Cookie(alias=settings.auth_cookie_name)] = None,
) -> User:
    del request  # Reserved for future request-aware audit/security controls.
    token = _extract_token(credentials, cookie_token)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    try:
        payload = decode_access_token(token)
        user_id = UUID(payload["sub"])
        token_org_id = UUID(payload["org"])
    except (TokenError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token") from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is inactive or unavailable")

    # Never authorize from org claims carried in the token alone. The database membership is authoritative.
    if user.organization_id != token_org_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication context is no longer valid")

    organization = db.get(Organization, user.organization_id)
    if (
        organization is None
        or organization.deleted_at is not None
        or organization.status != OrganizationStatus.ACTIVE
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Organization is inactive or unavailable")

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*allowed_roles: UserRole) -> Callable[[CurrentUser], User]:
    def dependency(current_user: CurrentUser) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user

    return dependency
