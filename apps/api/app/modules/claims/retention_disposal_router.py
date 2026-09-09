from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_disposal_schemas import (
    DisposalAuthorizationDecision,
    DisposalAuthorizationRead,
    DisposalAuthorizationRequest,
)
from app.modules.claims.retention_disposal_service import (
    DisposalAuthorizationBlockedError,
    approve_disposal_authorization,
    get_disposal_authorization,
    list_disposal_authorizations,
    reject_disposal_authorization,
    request_disposal_authorization,
)
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.claims.retention_service import RetentionNotFoundError

router = APIRouter(prefix="/claims", tags=["retention"])


def _read(authorization) -> DisposalAuthorizationRead:
    return DisposalAuthorizationRead.model_validate(authorization)


@router.post(
    "/{claim_id}/disposal-authorizations",
    response_model=DisposalAuthorizationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_disposal_authorization_endpoint(
    claim_id: UUID,
    payload: DisposalAuthorizationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> DisposalAuthorizationRead:
    try:
        authorization = request_disposal_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            requested_by_id=current_user.id,
            request_reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="DISPOSAL_AUTHORIZATION_REQUESTED",
            entity_type="disposal_authorization",
            entity_id=authorization.id,
            new_values={
                "claim_id": str(authorization.claim_id),
                "status": authorization.status,
                "retention_policy_id": str(authorization.retention_policy_id),
                "retention_policy_number": authorization.retention_policy_number,
                "retention_policy_hash": authorization.retention_policy_hash,
                "eligibility_snapshot_hash": authorization.eligibility_snapshot_hash,
                "state_fingerprint": authorization.state_fingerprint,
                "authorization_expires_at": authorization.authorization_expires_at.isoformat(),
                "active_hold_ids": authorization.active_hold_ids,
                "pending_proposal_ids": authorization.pending_proposal_ids,
                "destructive_action_performed": False,
            },
        )
        db.commit()
        db.refresh(authorization)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DisposalAuthorizationBlockedError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "disposal_authorization_blocked",
                "blocking_reasons": exc.blocking_reasons,
            },
        ) from exc
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _read(authorization)


@router.get(
    "/{claim_id}/disposal-authorizations",
    response_model=list[DisposalAuthorizationRead],
)
def list_disposal_authorizations_endpoint(
    claim_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[DisposalAuthorizationRead]:
    try:
        authorizations = list_disposal_authorizations(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
        )
    except RetentionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [_read(authorization) for authorization in authorizations]


@router.get(
    "/{claim_id}/disposal-authorizations/{authorization_id}",
    response_model=DisposalAuthorizationRead,
)
def get_disposal_authorization_endpoint(
    claim_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> DisposalAuthorizationRead:
    try:
        authorization = get_disposal_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            authorization_id=authorization_id,
        )
    except RetentionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _read(authorization)


@router.post(
    "/{claim_id}/disposal-authorizations/{authorization_id}/approve",
    response_model=DisposalAuthorizationRead,
)
def approve_disposal_authorization_endpoint(
    claim_id: UUID,
    authorization_id: UUID,
    payload: DisposalAuthorizationDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> DisposalAuthorizationRead:
    try:
        authorization, outcome = approve_disposal_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            authorization_id=authorization_id,
            approved_by_id=current_user.id,
            decision_reason=payload.reason,
        )
        if outcome != "unchanged":
            action = {
                "approved": "DISPOSAL_AUTHORIZATION_APPROVED",
                "invalidated": "DISPOSAL_AUTHORIZATION_INVALIDATED",
                "expired": "DISPOSAL_AUTHORIZATION_EXPIRED",
            }[outcome]
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action=action,
                entity_type="disposal_authorization",
                entity_id=authorization.id,
                old_values={"status": "pending_second_approval"},
                new_values={
                    "claim_id": str(authorization.claim_id),
                    "status": authorization.status,
                    "decision_reason": authorization.decision_reason,
                    "destructive_action_performed": False,
                },
            )
            db.commit()
            db.refresh(authorization)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _read(authorization)


@router.post(
    "/{claim_id}/disposal-authorizations/{authorization_id}/reject",
    response_model=DisposalAuthorizationRead,
)
def reject_disposal_authorization_endpoint(
    claim_id: UUID,
    authorization_id: UUID,
    payload: DisposalAuthorizationDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> DisposalAuthorizationRead:
    try:
        authorization, outcome = reject_disposal_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            authorization_id=authorization_id,
            rejected_by_id=current_user.id,
            decision_reason=payload.reason,
        )
        if outcome != "unchanged":
            action = (
                "DISPOSAL_AUTHORIZATION_REJECTED"
                if outcome == "rejected"
                else "DISPOSAL_AUTHORIZATION_EXPIRED"
            )
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action=action,
                entity_type="disposal_authorization",
                entity_id=authorization.id,
                old_values={"status": "pending_second_approval"},
                new_values={
                    "claim_id": str(authorization.claim_id),
                    "status": authorization.status,
                    "decision_reason": authorization.decision_reason,
                    "destructive_action_performed": False,
                },
            )
            db.commit()
            db.refresh(authorization)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _read(authorization)
