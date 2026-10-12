from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import (
    CurrentAuthContext,
    enforce_current_mfa_for_context,
    require_roles,
)
from app.modules.auth.models import AuthSession
from app.modules.auth.service import revoke_auth_session
from app.modules.users.models import User, UserRole
from app.modules.users.schemas import (
    UserCreate,
    UserDeactivateRead,
    UserDeactivateRequest,
    UserRead,
)
from app.modules.users.service import DuplicateUserError, create_user_in_organization

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> UserRead:
    try:
        user = create_user_in_organization(db, organization_id=current_user.organization_id, payload=payload)
    except DuplicateUserError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action="CREATE_USER",
        entity_type="user",
        entity_id=user.id,
        new_values={"email": user.email, "role": user.role.value},
    )
    db.commit()
    db.refresh(user)
    return UserRead.model_validate(user)


@router.post("/{user_id}/deactivate", response_model=UserDeactivateRead)
def deactivate_user_for_pilot_offboarding(
    user_id: UUID,
    payload: UserDeactivateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_context: CurrentAuthContext,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> UserDeactivateRead:
    """Deactivate one *other* same-tenant user and revoke every known session.

    This is an explicit, MFA-protected app membership offboarding transaction;
    it does not remove documents, clear legal holds, revoke upstream SSO
    sessions or disable external integration credentials. A user that races
    with a pending login remains denied by the authoritative is_active check.
    """
    # Offboarding always requires current, verified MFA even if the tenant
    # configured an optional MFA policy for ordinary Admin routes.
    enforce_current_mfa_for_context(db, context=current_context)
    target = db.scalar(
        select(User)
        .where(
            User.id == user_id,
            User.organization_id == current_user.organization_id,
            User.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    if target.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An Admin cannot deactivate their own active session",
        )

    newly_deactivated = target.is_active
    target.is_active = False

    # Scope both dimensions, including when a malformed/foreign session ID
    # exists elsewhere; never expose individual tokens or session identifiers.
    outstanding = list(
        db.scalars(
            select(AuthSession)
            .where(
                AuthSession.organization_id == current_user.organization_id,
                AuthSession.user_id == target.id,
                AuthSession.revoked_at.is_(None),
            )
            .with_for_update()
        )
    )
    for session in outstanding:
        revoke_auth_session(
            auth_session=session,
            revoked_by_id=current_user.id,
            reason="pilot_user_deactivation",
        )

    if newly_deactivated or outstanding:
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="PILOT_USER_DEACTIVATED_AND_SESSIONS_REVOKED",
            entity_type="user",
            entity_id=target.id,
            new_values={
                "is_active": False,
                "newly_deactivated": newly_deactivated,
                "sessions_revoked": len(outstanding),
                "change_ticket_ref": payload.change_ticket_ref,
                "external_identity_deprovisioned": False,
                "external_integrations_disabled": False,
            },
        )
        db.commit()
    return UserDeactivateRead(
        id=target.id,
        is_active=False,
        newly_deactivated=newly_deactivated,
        sessions_revoked=len(outstanding),
    )
