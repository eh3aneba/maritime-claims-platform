from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import require_roles
from app.modules.auth.mfa_policy import get_mfa_policy, upsert_mfa_policy
from app.modules.auth.mfa_policy_schemas import MfaPolicyRead, MfaPolicyUpdate
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/auth/mfa-policy", tags=["authentication", "mfa"])


@router.get("", response_model=MfaPolicyRead, response_model_exclude_none=True)
def read_mfa_policy_as_admin(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> MfaPolicyRead:
    policy = get_mfa_policy(db, organization_id=current_user.organization_id)
    if policy is None:
        return MfaPolicyRead(
            organization_id=current_user.organization_id,
            is_enabled=False,
            required_roles=[],
        )
    return MfaPolicyRead.model_validate(policy)


@router.put("", response_model=MfaPolicyRead)
def update_mfa_policy_as_admin(
    payload: MfaPolicyUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
) -> MfaPolicyRead:
    try:
        policy, old_values = upsert_mfa_policy(
            db,
            organization_id=current_user.organization_id,
            is_enabled=payload.is_enabled,
            required_roles=[str(role) for role in payload.required_roles],
            updated_by_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    new_values = {
        "is_enabled": policy.is_enabled,
        "required_roles": list(policy.required_roles),
    }
    if old_values != new_values:
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="MFA_POLICY_UPDATED",
            entity_type="mfa_policy",
            entity_id=policy.id,
            old_values=old_values,
            new_values=new_values,
        )
    db.commit()
    db.refresh(policy)
    return MfaPolicyRead.model_validate(policy)
