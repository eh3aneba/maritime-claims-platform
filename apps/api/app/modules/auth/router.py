from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import CurrentAuthContext, CurrentUser, require_roles
from app.modules.auth.schemas import AuthSessionRead, LoginRequest, LoginResponse
from app.modules.auth.service import (
    authenticate_user,
    create_auth_session,
    get_auth_session_for_tenant,
    revoke_auth_session,
)
from app.modules.users.models import User, UserRole
from app.modules.users.schemas import UserRead

router = APIRouter(prefix="/auth", tags=["authentication"])
settings = get_settings()


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> LoginResponse:
    user = authenticate_user(
        db,
        organization_slug=payload.organization_slug,
        email=str(payload.email),
        password=payload.password,
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid organization, email, or password",
        )

    auth_session = create_auth_session(db, user=user)
    write_audit_log(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        action="LOGIN_SUCCESS",
        entity_type="auth_session",
        entity_id=auth_session.id,
        new_values={
            "identity_source": auth_session.identity_source,
            "auth_method": auth_session.auth_method,
        },
    )
    db.commit()
    db.refresh(user)

    token = create_access_token(
        user_id=user.id,
        organization_id=user.organization_id,
        role=user.role.value,
        session_id=auth_session.id,
        identity_source=auth_session.identity_source,
        auth_method=auth_session.auth_method,
    )
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        httponly=True,
        secure=settings.app_env.lower() in {"staging", "production"},
        samesite="lax",
        max_age=settings.access_token_expire_minutes * 60,
        path="/",
    )
    return LoginResponse(access_token=token, user=UserRead.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
) -> None:
    revoke_auth_session(
        auth_session=current_context.session,
        revoked_by_id=current_context.user.id,
        reason="logout",
    )
    write_audit_log(
        db,
        organization_id=current_context.user.organization_id,
        user_id=current_context.user.id,
        action="LOGOUT",
        entity_type="auth_session",
        entity_id=current_context.session.id,
    )
    db.commit()
    response.delete_cookie(key=settings.auth_cookie_name, path="/")
    return None


@router.get("/me", response_model=UserRead)
def me(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)


@router.get("/session", response_model=AuthSessionRead)
def current_session(current_context: CurrentAuthContext) -> AuthSessionRead:
    return AuthSessionRead.model_validate(current_context.session)


@router.post("/sessions/{session_id}/revoke", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session_as_admin(
    session_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> None:
    auth_session = get_auth_session_for_tenant(
        db,
        session_id=session_id,
        organization_id=current_user.organization_id,
    )
    if auth_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Authentication session not found",
        )

    changed = revoke_auth_session(
        auth_session=auth_session,
        revoked_by_id=current_user.id,
        reason="admin_revocation",
    )
    if changed:
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="AUTH_SESSION_REVOKED",
            entity_type="auth_session",
            entity_id=auth_session.id,
            new_values={"target_user_id": str(auth_session.user_id)},
        )
        db.commit()
    return None
