from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import (
    CurrentAuthContext,
    CurrentUser,
    enforce_mfa_policy_for_context,
    require_roles,
)
from app.modules.claims.retention_models import ClaimLegalHold
from app.modules.claims.retention_schemas import (
    DisposalEligibilityRead,
    LegalHoldCreate,
    LegalHoldRead,
    LegalHoldRelease,
    RetentionPolicyCreate,
    RetentionPolicyRead,
)
from app.modules.claims.retention_service import (
    RetentionNotFoundError,
    create_retention_policy,
    get_current_retention_policy,
    get_legal_hold,
    list_legal_holds,
    list_retention_policies,
    place_legal_hold,
    preview_disposal_eligibility,
    release_legal_hold,
)
from app.modules.users.models import User, UserRole

router = APIRouter(tags=["retention"])


def require_retention_admin_mfa(
    context: CurrentAuthContext,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if context.user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )
    enforce_mfa_policy_for_context(db, context=context)
    return context.user


RetentionAdminMfa = Annotated[User, Depends(require_retention_admin_mfa)]
RetentionReader = Annotated[
    User,
    Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER)),
]


def _hold_read(hold: ClaimLegalHold) -> LegalHoldRead:
    return LegalHoldRead(
        id=hold.id,
        organization_id=hold.organization_id,
        claim_id=hold.claim_id,
        source=hold.source,
        reason=hold.reason,
        placed_by_id=hold.placed_by_id,
        released_at=hold.released_at,
        released_by_id=hold.released_by_id,
        release_reason=hold.release_reason,
        is_active=hold.released_at is None,
        created_at=hold.created_at,
        updated_at=hold.updated_at,
    )


@router.post(
    "/retention/policies",
    response_model=RetentionPolicyRead,
    status_code=status.HTTP_201_CREATED,
)
def create_retention_policy_endpoint(
    payload: RetentionPolicyCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RetentionPolicyRead:
    try:
        policy = create_retention_policy(
            db,
            organization_id=current_user.organization_id,
            closed_claim_retention_days=payload.closed_claim_retention_days,
            evidence_retention_days=payload.evidence_retention_days,
            enabled=payload.enabled,
            disposal_enabled=payload.disposal_enabled,
            created_by_id=current_user.id,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="RETENTION_POLICY_VERSION_PINNED",
            entity_type="tenant_retention_policy",
            entity_id=policy.id,
            new_values={
                "policy_number": policy.policy_number,
                "policy_hash": policy.policy_hash,
                "previous_policy_hash": policy.previous_policy_hash,
                "closed_claim_retention_days": policy.closed_claim_retention_days,
                "evidence_retention_days": policy.evidence_retention_days,
                "enabled": policy.enabled,
                "disposal_enabled": policy.disposal_enabled,
            },
        )
        db.commit()
        db.refresh(policy)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Retention policy conflicts with current tenant lineage",
        ) from exc
    return RetentionPolicyRead.model_validate(policy)


@router.get("/retention/policies", response_model=list[RetentionPolicyRead])
def retention_policy_history_endpoint(
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RetentionPolicyRead]:
    return [
        RetentionPolicyRead.model_validate(policy)
        for policy in list_retention_policies(
            db,
            organization_id=current_user.organization_id,
        )
    ]


@router.get("/retention/policy", response_model=RetentionPolicyRead)
def current_retention_policy_endpoint(
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RetentionPolicyRead:
    policy = get_current_retention_policy(
        db,
        organization_id=current_user.organization_id,
    )
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active retention policy not found",
        )
    return RetentionPolicyRead.model_validate(policy)


@router.post(
    "/{claim_id}/legal-holds",
    response_model=LegalHoldRead,
    status_code=status.HTTP_201_CREATED,
)
def place_legal_hold_endpoint(
    claim_id: UUID,
    payload: LegalHoldCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> LegalHoldRead:
    try:
        hold = place_legal_hold(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            source=payload.source,
            reason=payload.reason,
            placed_by_id=current_user.id,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="CLAIM_LEGAL_HOLD_PLACED",
            entity_type="claim_legal_hold",
            entity_id=hold.id,
            new_values={
                "claim_id": str(hold.claim_id),
                "source": hold.source,
                "active": True,
            },
        )
        db.commit()
        db.refresh(hold)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _hold_read(hold)


@router.get("/{claim_id}/legal-holds", response_model=list[LegalHoldRead])
def list_legal_holds_endpoint(
    claim_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[LegalHoldRead]:
    try:
        holds = list_legal_holds(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
        )
    except RetentionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [_hold_read(hold) for hold in holds]


@router.post(
    "/{claim_id}/legal-holds/{hold_id}/release",
    response_model=LegalHoldRead,
)
def release_legal_hold_endpoint(
    claim_id: UUID,
    hold_id: UUID,
    payload: LegalHoldRelease,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> LegalHoldRead:
    try:
        hold = get_legal_hold(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            hold_id=hold_id,
        )
        changed = release_legal_hold(
            hold,
            released_by_id=current_user.id,
            release_reason=payload.reason,
        )
        if changed:
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action="CLAIM_LEGAL_HOLD_RELEASED",
                entity_type="claim_legal_hold",
                entity_id=hold.id,
                old_values={"active": True},
                new_values={"active": False, "claim_id": str(hold.claim_id)},
            )
            db.commit()
            db.refresh(hold)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _hold_read(hold)


@router.get(
    "/{claim_id}/disposal-eligibility",
    response_model=DisposalEligibilityRead,
)
def disposal_eligibility_endpoint(
    claim_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: CurrentUser,
) -> DisposalEligibilityRead:
    try:
        result = preview_disposal_eligibility(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
        )
    except RetentionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return DisposalEligibilityRead(**result.__dict__)
