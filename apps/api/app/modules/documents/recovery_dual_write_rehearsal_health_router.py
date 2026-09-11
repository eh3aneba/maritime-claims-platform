from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_dual_write_rehearsal_health_schemas import (
    RecoveryDualWriteRehearsalHealthOperationRead,
    RecoveryDualWriteRehearsalHealthQualificationRead,
    RecoveryDualWriteRehearsalHealthQualificationReason,
    RecoveryDualWriteRehearsalHealthQualificationRequest,
    RecoveryDualWriteRehearsalHealthReceiptRead,
)
from app.modules.documents.recovery_dual_write_rehearsal_health_service import (
    RecoveryDualWriteRehearsalHealthConflict,
    RecoveryDualWriteRehearsalHealthNotFound,
    RecoveryDualWriteRehearsalHealthUnavailable,
    get_recovery_dual_write_rehearsal_health_qualification,
    list_recovery_dual_write_rehearsal_health_receipts,
    qualify_recovery_dual_write_rehearsal_health,
    reject_recovery_dual_write_rehearsal_health,
    request_recovery_dual_write_rehearsal_health_qualification,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-dual-write-rehearsal-health"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryDualWriteRehearsalHealthNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryDualWriteRehearsalHealthUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(q) -> dict:
    return {
        "claim_id": str(q.claim_id),
        "document_id": str(q.document_id),
        "execution_id": str(q.execution_id),
        "execution_receipt_id": str(q.execution_receipt_id),
        "phase_x_authorization_id": str(q.phase_x_authorization_id),
        "phase_x_approval_receipt_id": str(q.phase_x_approval_receipt_id),
        "phase_w_health_qualification_id": str(q.phase_w_health_qualification_id),
        "phase_v_transition_lease_id": str(q.phase_v_transition_lease_id),
        "phase_u_authorization_id": str(q.phase_u_authorization_id),
        "phase_t_health_qualification_id": str(q.phase_t_health_qualification_id),
        "replica_id": str(q.replica_id),
        "execution_hash": q.execution_hash,
        "verification_hash": q.verification_hash,
        "execution_receipt_hash": q.execution_receipt_hash,
        "phase_x_authorization_hash": q.phase_x_authorization_hash,
        "phase_x_approval_receipt_hash": q.phase_x_approval_receipt_hash,
        "source_file_hash": q.source_file_hash,
        "source_file_size_bytes": q.source_file_size_bytes,
        "recovery_bucket_fingerprint": q.recovery_bucket_fingerprint,
        "rehearsal_object_key_fingerprint": q.rehearsal_object_key_fingerprint,
        "observed_file_hash": q.observed_file_hash,
        "observed_file_size_bytes": q.observed_file_size_bytes,
        "integrity_proof_hash": q.integrity_proof_hash,
        "request_snapshot_hash": q.request_snapshot_hash,
        "health_qualification_hash": q.health_qualification_hash,
        "health_state": q.health_state,
        "route_version_at_request": q.route_version_at_request,
        "review_expires_at": q.review_expires_at.isoformat(),
        "status": q.status,
        "storage_write_performed": False,
        "routable_dual_write_authority_created": False,
        "rehearsal_object_routable": False,
        "dual_write_active": False,
        "durable_write_authority_created": False,
        "read_path_switched": False,
        "write_path_switched": False,
        "document_storage_key_mutated": False,
        "authoritative_storage_changed": False,
        "destructive_action_performed": False,
        "s3_copy_performed": False,
        "s3_delete_performed": False,
        "local_delete_performed": False,
    }


def _operation(q, receipt, outcome: str):
    return RecoveryDualWriteRehearsalHealthOperationRead(
        qualification=RecoveryDualWriteRehearsalHealthQualificationRead.model_validate(q),
        receipt=RecoveryDualWriteRehearsalHealthReceiptRead.model_validate(receipt) if receipt else None,
        outcome=outcome,
    )


def _commit(db: Session, q, receipt) -> None:
    db.commit()
    db.refresh(q)
    if receipt is not None:
        db.refresh(receipt)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-dual-write-rehearsal-health-qualification",
    response_model=RecoveryDualWriteRehearsalHealthOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_health_endpoint(
    claim_id: UUID,
    document_id: UUID,
    payload: RecoveryDualWriteRehearsalHealthQualificationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        q, receipt, outcome = request_recovery_dual_write_rehearsal_health_qualification(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            execution_id=payload.execution_id,
            requested_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "pending_second_approval": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_HEALTH_REQUESTED",
                "unchanged": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_HEALTH_REQUEST_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_dual_write_rehearsal_health_qualification",
            entity_id=q.id,
            new_values={**_audit_values(q), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, q, receipt)
    except (
        RecoveryDualWriteRehearsalHealthNotFound,
        RecoveryDualWriteRehearsalHealthConflict,
        RecoveryDualWriteRehearsalHealthUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase Z health qualification conflicts with immutable lineage") from exc
    return _operation(q, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-dual-write-rehearsal-health-qualifications/{health_qualification_id}/qualify",
    response_model=RecoveryDualWriteRehearsalHealthOperationRead,
)
def qualify_health_endpoint(
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    payload: RecoveryDualWriteRehearsalHealthQualificationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        q, receipt, outcome = qualify_recovery_dual_write_rehearsal_health(
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
                "qualified": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_HEALTH_QUALIFIED",
                "unchanged": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_HEALTH_QUALIFICATION_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_HEALTH_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_HEALTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_dual_write_rehearsal_health_qualification",
            entity_id=q.id,
            new_values={**_audit_values(q), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, q, receipt)
    except (
        RecoveryDualWriteRehearsalHealthNotFound,
        RecoveryDualWriteRehearsalHealthConflict,
        RecoveryDualWriteRehearsalHealthUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(q, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-dual-write-rehearsal-health-qualifications/{health_qualification_id}/reject",
    response_model=RecoveryDualWriteRehearsalHealthOperationRead,
)
def reject_health_endpoint(
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    payload: RecoveryDualWriteRehearsalHealthQualificationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        q, receipt, outcome = reject_recovery_dual_write_rehearsal_health(
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
                "rejected": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_HEALTH_REJECTED",
                "unchanged": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_HEALTH_REJECTION_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_HEALTH_EXPIRED",
            }[outcome],
            entity_type="evidence_recovery_dual_write_rehearsal_health_qualification",
            entity_id=q.id,
            new_values={**_audit_values(q), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, q, receipt)
    except (
        RecoveryDualWriteRehearsalHealthNotFound,
        RecoveryDualWriteRehearsalHealthConflict,
        RecoveryDualWriteRehearsalHealthUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(q, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-dual-write-rehearsal-health-qualifications/{health_qualification_id}",
    response_model=RecoveryDualWriteRehearsalHealthQualificationRead,
)
def get_health_endpoint(
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        q = get_recovery_dual_write_rehearsal_health_qualification(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=health_qualification_id,
        )
    except RecoveryDualWriteRehearsalHealthNotFound as exc:
        raise _error(exc) from exc
    return RecoveryDualWriteRehearsalHealthQualificationRead.model_validate(q)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-dual-write-rehearsal-health-qualifications/{health_qualification_id}/receipts",
    response_model=list[RecoveryDualWriteRehearsalHealthReceiptRead],
)
def list_health_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        receipts = list_recovery_dual_write_rehearsal_health_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=health_qualification_id,
        )
    except RecoveryDualWriteRehearsalHealthNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryDualWriteRehearsalHealthReceiptRead.model_validate(item) for item in receipts]
