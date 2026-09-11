from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_write_ownership_transition_authorization_schemas import (
    RecoveryWriteOwnershipTransitionAuthorizationOperationRead,
    RecoveryWriteOwnershipTransitionAuthorizationRead,
    RecoveryWriteOwnershipTransitionAuthorizationReason,
    RecoveryWriteOwnershipTransitionAuthorizationReceiptRead,
    RecoveryWriteOwnershipTransitionAuthorizationRequest,
)
from app.modules.documents.recovery_write_ownership_transition_authorization_service import (
    RecoveryWriteOwnershipTransitionAuthorizationConflict,
    RecoveryWriteOwnershipTransitionAuthorizationNotFound,
    RecoveryWriteOwnershipTransitionAuthorizationUnavailable,
    approve_recovery_write_ownership_transition_authorization,
    get_recovery_write_ownership_transition_authorization,
    list_recovery_write_ownership_transition_authorization_receipts,
    reject_recovery_write_ownership_transition_authorization,
    request_recovery_write_ownership_transition_authorization,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-write-ownership-transition-authorization"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryWriteOwnershipTransitionAuthorizationNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryWriteOwnershipTransitionAuthorizationUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(a) -> dict:
    return {
        "claim_id": str(a.claim_id),
        "document_id": str(a.document_id),
        "phase_ac_health_qualification_id": str(a.phase_ac_health_qualification_id),
        "phase_ac_health_receipt_id": str(a.phase_ac_health_receipt_id),
        "canary_lease_id": str(a.canary_lease_id),
        "phase_aa_authorization_id": str(a.phase_aa_authorization_id),
        "replica_id": str(a.replica_id),
        "phase_ac_health_qualification_hash": a.phase_ac_health_qualification_hash,
        "phase_ac_health_receipt_hash": a.phase_ac_health_receipt_hash,
        "lease_hash": a.lease_hash,
        "phase_aa_authorization_hash": a.phase_aa_authorization_hash,
        "source_file_hash": a.source_file_hash,
        "source_file_size_bytes": a.source_file_size_bytes,
        "request_snapshot_hash": a.request_snapshot_hash,
        "authorization_hash": a.authorization_hash,
        "health_state": a.health_state,
        "max_transition_windows": a.max_transition_windows,
        "read_route_version_at_request": a.read_route_version_at_request,
        "write_route_version_at_request": a.write_route_version_at_request,
        "review_expires_at": a.review_expires_at.isoformat(),
        "authorization_expires_at": a.authorization_expires_at.isoformat() if a.authorization_expires_at else None,
        "status": a.status,
        "local_authoritative": True,
        "storage_write_performed": False,
        "write_route_lease_created": False,
        "routable_dual_write_active": False,
        "durable_write_authority_created": False,
        "read_path_switched": False,
        "write_path_switched": False,
        "document_storage_key_mutated": False,
        "authoritative_storage_changed": False,
        "destructive_action_performed": False,
        "s3_put_performed": False,
        "s3_copy_performed": False,
        "s3_delete_performed": False,
        "local_delete_performed": False,
    }


def _operation(a, receipt, outcome: str):
    return RecoveryWriteOwnershipTransitionAuthorizationOperationRead(
        authorization=RecoveryWriteOwnershipTransitionAuthorizationRead.model_validate(a),
        receipt=RecoveryWriteOwnershipTransitionAuthorizationReceiptRead.model_validate(receipt) if receipt else None,
        outcome=outcome,
    )


def _commit(db: Session, a, receipt) -> None:
    db.commit()
    db.refresh(a)
    if receipt is not None:
        db.refresh(receipt)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-write-ownership-transition-authorization",
    response_model=RecoveryWriteOwnershipTransitionAuthorizationOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_write_ownership_transition_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    payload: RecoveryWriteOwnershipTransitionAuthorizationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        a, receipt, outcome = request_recovery_write_ownership_transition_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=payload.health_qualification_id,
            requested_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "pending_second_approval": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_AUTH_REQUESTED",
                "unchanged": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_AUTH_REQUEST_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_write_ownership_transition_authorization",
            entity_id=a.id,
            new_values={**_audit_values(a), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, a, receipt)
    except (
        RecoveryWriteOwnershipTransitionAuthorizationNotFound,
        RecoveryWriteOwnershipTransitionAuthorizationConflict,
        RecoveryWriteOwnershipTransitionAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase AD authorization conflicts with immutable lineage") from exc
    return _operation(a, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-write-ownership-transition-authorizations/{authorization_id}/approve",
    response_model=RecoveryWriteOwnershipTransitionAuthorizationOperationRead,
)
def approve_write_ownership_transition_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryWriteOwnershipTransitionAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        a, receipt, outcome = approve_recovery_write_ownership_transition_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
            approved_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "approved": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_AUTH_APPROVED",
                "unchanged": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_AUTH_APPROVAL_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_AUTH_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_AUTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_write_ownership_transition_authorization",
            entity_id=a.id,
            new_values={**_audit_values(a), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, a, receipt)
    except (
        RecoveryWriteOwnershipTransitionAuthorizationNotFound,
        RecoveryWriteOwnershipTransitionAuthorizationConflict,
        RecoveryWriteOwnershipTransitionAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(a, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-write-ownership-transition-authorizations/{authorization_id}/reject",
    response_model=RecoveryWriteOwnershipTransitionAuthorizationOperationRead,
)
def reject_write_ownership_transition_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryWriteOwnershipTransitionAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        a, receipt, outcome = reject_recovery_write_ownership_transition_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
            rejected_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "rejected": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_AUTH_REJECTED",
                "unchanged": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_AUTH_REJECTION_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_AUTH_EXPIRED",
            }[outcome],
            entity_type="evidence_recovery_write_ownership_transition_authorization",
            entity_id=a.id,
            new_values={**_audit_values(a), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, a, receipt)
    except (
        RecoveryWriteOwnershipTransitionAuthorizationNotFound,
        RecoveryWriteOwnershipTransitionAuthorizationConflict,
        RecoveryWriteOwnershipTransitionAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(a, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-write-ownership-transition-authorizations/{authorization_id}",
    response_model=RecoveryWriteOwnershipTransitionAuthorizationRead,
)
def get_write_ownership_transition_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        a = get_recovery_write_ownership_transition_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryWriteOwnershipTransitionAuthorizationNotFound as exc:
        raise _error(exc) from exc
    return RecoveryWriteOwnershipTransitionAuthorizationRead.model_validate(a)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-write-ownership-transition-authorizations/{authorization_id}/receipts",
    response_model=list[RecoveryWriteOwnershipTransitionAuthorizationReceiptRead],
)
def list_write_ownership_transition_authorization_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        receipts = list_recovery_write_ownership_transition_authorization_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryWriteOwnershipTransitionAuthorizationNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryWriteOwnershipTransitionAuthorizationReceiptRead.model_validate(item) for item in receipts]
