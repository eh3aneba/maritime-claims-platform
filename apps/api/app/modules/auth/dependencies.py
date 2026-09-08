from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import TokenError, decode_access_token
from app.db.session import get_db
from app.modules.auth.mfa import get_current_totp_factor
from app.modules.auth.mfa_policy import get_mfa_policy, mfa_required_for_role
from app.modules.auth.models import AuthSession
from app.modules.auth.service import get_valid_auth_session
from app.modules.organizations.models import Organization, OrganizationStatus
from app.modules.users.models import User, UserRole

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: AuthSession


def _extract_token(
    credentials: HTTPAuthorizationCredentials | None,
    cookie_token: str | None,
) -> str | None:
    if credentials and credentials.scheme.lower() == "bearer":
        return credentials.credentials
    return cookie_token


def get_current_auth_context(
    db: Annotated[Session, Depends(get_db)],
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    cookie_token: Annotated[
        str | None,
        Cookie(alias=settings.auth_cookie_name),
    ] = None,
) -> AuthContext:
    token = _extract_token(credentials, cookie_token)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    try:
        payload = decode_access_token(token)
        user_id = UUID(payload["sub"])
        token_org_id = UUID(payload["org"])
        session_id = UUID(payload["sid"])
        identity_source = str(payload["src"])
        auth_method = str(payload["amr"])
    except (TokenError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        ) from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User is inactive or unavailable",
        )

    # Membership in the application database is authoritative, never the token or an IdP.
    if user.organization_id != token_org_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication context is no longer valid",
        )

    organization = db.get(Organization, user.organization_id)
    if (
        organization is None
        or organization.deleted_at is not None
        or organization.status != OrganizationStatus.ACTIVE
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Organization is inactive or unavailable",
        )

    auth_session = get_valid_auth_session(
        db,
        session_id=session_id,
        user_id=user.id,
        organization_id=user.organization_id,
        identity_source=identity_source,
        auth_method=auth_method,
    )
    if auth_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication session is no longer valid",
        )

    return AuthContext(user=user, session=auth_session)


CurrentAuthContext = Annotated[AuthContext, Depends(get_current_auth_context)]


def get_current_user(context: CurrentAuthContext) -> User:
    return context.user


CurrentUser = Annotated[User, Depends(get_current_user)]


def _is_mfa_sensitive_auth_path(path: str) -> bool:
    api_prefix = settings.api_v1_prefix.rstrip("/")
    auth_prefix = f"{api_prefix}/auth"
    normalized = path.rstrip("/")
    return (
        normalized == f"{auth_prefix}/mfa-policy"
        or normalized.startswith(f"{auth_prefix}/identity-providers")
        or normalized.startswith(f"{auth_prefix}/external-bindings")
        or normalized.startswith(f"{auth_prefix}/sessions/")
    )


def enforce_mfa_policy_for_context(
    db: Session,
    *,
    context: AuthContext,
) -> None:
    policy = get_mfa_policy(
        db,
        organization_id=context.user.organization_id,
    )
    if not mfa_required_for_role(policy, role=context.user.role):
        return

    factor = get_current_totp_factor(
        db,
        organization_id=context.user.organization_id,
        user_id=context.user.id,
    )
    if factor is None or factor.confirmed_at is None or factor.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "mfa_enrollment_required",
                "message": "An active confirmed MFA factor is required for this action",
            },
        )

    if (
        context.session.mfa_verified_at is None
        or context.session.mfa_method != "totp"
        or context.session.mfa_factor_id != factor.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "mfa_verification_required",
                "message": "MFA verification is required for the current authentication session",
            },
        )


def require_roles(*allowed_roles: UserRole) -> Callable[..., User]:
    def dependency(
        context: CurrentAuthContext,
        request: Request,
        db: Annotated[Session, Depends(get_db)],
    ) -> User:
        current_user = context.user
        # Database User.role remains authoritative; token or IdP role claims are ignored here.
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        if _is_mfa_sensitive_auth_path(request.url.path):
            enforce_mfa_policy_for_context(db, context=context)
        return current_user

    return dependency
