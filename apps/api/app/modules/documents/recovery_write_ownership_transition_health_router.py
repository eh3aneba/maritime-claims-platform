from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_write_ownership_transition_health_schemas import (
    RecoveryWriteOwnershipTransitionHealthOperationRead,
    RecoveryWriteOwnershipTransitionHealthQualificationRead,
    RecoveryWriteOwnershipTransitionHealthReason,
    RecoveryWriteOwnershipTransitionHealthReceiptRead,
    RecoveryWriteOwnershipTransitionHealthRequest,
)
from app.modules.documents.recovery_write_ownership_transition_health_service import (
    RecoveryWriteOwnershipTransitionHealthConflict,
    RecoveryWriteOwnershipTransitionHealthNotFound,
    RecoveryWriteOwnershipTransitionHealthUnavailable,
    get_write_ownership_transition_health_qualification,
    list_write_ownership_transition_health_receipts,
    qualify_write_ownership_transition_health,
    reject_write_ownership_transition_health,
    request_write_ownership_transition_health_qualification,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-write-ownership-transition-health"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryWriteOwnershipTransitionHealthNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryWriteOwnershipTransitionHealthUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(q) -> dict:
    return {
        "claim_id": str(q.claim_id),
        "document_id": str(q.document_id),
        "transition_lease_id": str(q.transition_lease_id),
        "authorization_id": str(q.authorization_id),
        "phase_ac_health_qualification_id": str(q.phase_ac_health_qualification_id),
        "canary_lease_id": str(q.canary_lease_id),
        "replica_id": str(q.replica_id),
        "activation_receipt_hash": q.activation_receipt_hash,
        "terminal_receipt_hash": q.terminal_receipt_hash,
        "activation_snapshot_hash": q.activation_snapshot_hash,
        "lease_hash": q.lease_hash,
        "source_file_hash": q.source_file_hash,
        "source_file_size_bytes": q.source_file_size_bytes,
        "observed_local_hash": q.observed_local_hash,
        "observed_local_size_bytes": q.observed_local_size_bytes,
        "observed_recovery_hash": q.observed_recovery_hash,
        "observed_recovery_size_bytes": q.observed_recovery_size_bytes,
        "read_route_version_at_request": q.read_route_version_at_request,
        "write_route_version_at_request": q.write_route_version_at_request,
        "integrity_proof_hash": q.integrity_proof_hash,
        "request_snapshot_hash": q.request_snapshot_hash,
        "health_qualification_hash": q.health_qualification_hash,
        "health_state": q.health_state,
        "review_expires_at": q.review_expires_at.isoformat(),
        "status": q.status,
        "local_authoritative": True,
        "storage_write_performed": False,
        "write_route_reactivated": False,
        "durable_write_authority_created": False,
        "read_path_switched": False,
        "write_path_switched": False,
        "document_storage_key_mutated": False,
        "authoritative_storage_changed": False,
        "destructive_action_performed": False,
        "s3_put_performed": False,
        "s3_copy_performed": False,
        "s3_delete_performed": False,
        "local_overwrite_performed": False,
        "local_move_performed": False,
        "local_delete_performed": False,
    }


def _operation(q, receipt, outcome: str):
    return RecoveryWriteOwnershipTransitionHealthOperationRead(
        qualification=RecoveryWriteOwnershipTransitionHealthQualificationRead.model_validate(q),
        receipt=RecoveryWriteOwnershipTransitionHealthReceiptRead.model_validate(receipt) if receipt else None,
        outcome=outcome,
    )


def _commit(db: Session, q, receipt) -> None:
    db.commit()
    db.refresh(q)
    if receipt is not None:
        db.refresh(receipt)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-write-ownership-transition-health-qualification",
    response_model=RecoveryWriteOwnershipTransitionHealthOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_health_endpoint(
    claim_id: UUID,
    document_id: UUID,
    payload: RecoveryWriteOwnershipTransitionHealthRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        q, receipt, outcome = request_write_ownership_transition_health_qualification(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            transition_lease_id=payload.transition_lease_id,
            requested_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "pending_second_approval": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_HEALTH_REQUESTED",
                "unchanged": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_HEALTH_REQUEST_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_write_ownership_transition_health_qualification",
            entity_id=q.id,
            new_values={**_audit_values(q), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, q, receipt)
    except (
        RecoveryWriteOwnershipTransitionHealthNotFound,
        RecoveryWriteOwnershipTransitionHealthConflict,
        RecoveryWriteOwnershipTransitionHealthUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase AF health qualification conflicts with immutable lineage") from exc
    return _operation(q, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-write-ownership-transition-health-qualifications/{health_qualification_id}/qualify",
    response_model=RecoveryWriteOwnershipTransitionHealthOperationRead,
)
def qualify_health_endpoint(
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    payload: RecoveryWriteOwnershipTransitionHealthReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        q, receipt, outcome = qualify_write_ownership_transition_health(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=health_qualification_id,
            qualified_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "qualified": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_HEALTH_QUALIFIED",
                "unchanged": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_HEALTH_QUALIFICATION_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_HEALTH_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_HEALTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_write_ownership_transition_health_qualification",
            entity_id=q.id,
            new_values={**_audit_values(q), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, q, receipt)
    except (
        RecoveryWriteOwnershipTransitionHealthNotFound,
        RecoveryWriteOwnershipTransitionHealthConflict,
        RecoveryWriteOwnershipTransitionHealthUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(q, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-write-ownership-transition-health-qualifications/{health_qualification_id}/reject",
    response_model=RecoveryWriteOwnershipTransitionHealthOperationRead,
)
def reject_health_endpoint(
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    payload: RecoveryWriteOwnershipTransitionHealthReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        q, receipt, outcome = reject_write_ownership_transition_health(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=health_qualification_id,
            rejected_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "rejected": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_HEALTH_REJECTED",
                "unchanged": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_HEALTH_REJECTION_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_HEALTH_EXPIRED",
            }[outcome],
            entity_type="evidence_recovery_write_ownership_transition_health_qualification",
            entity_id=q.id,
            new_values={**_audit_values(q), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, q, receipt)
    except (
        RecoveryWriteOwnershipTransitionHealthNotFound,
        RecoveryWriteOwnershipTransitionHealthConflict,
        RecoveryWriteOwnershipTransitionHealthUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(q, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-write-ownership-transition-health-qualifications/{health_qualification_id}",
    response_model=RecoveryWriteOwnershipTransitionHealthQualificationRead,
)
def get_health_endpoint(
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        q = get_write_ownership_transition_health_qualification(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=health_qualification_id,
        )
    except RecoveryWriteOwnershipTransitionHealthNotFound as exc:
        raise _error(exc) from exc
    return RecoveryWriteOwnershipTransitionHealthQualificationRead.model_validate(q)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-write-ownership-transition-health-qualifications/{health_qualification_id}/receipts",
    response_model=list[RecoveryWriteOwnershipTransitionHealthReceiptRead],
)
def list_health_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        receipts = list_write_ownership_transition_health_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=health_qualification_id,
        )
    except RecoveryWriteOwnershipTransitionHealthNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryWriteOwnershipTransitionHealthReceiptRead.model_validate(item) for item in receipts]
