from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_routable_dual_write_canary_execution_schemas import (
    RecoveryRoutableDualWriteCanaryExecutionReason,
    RecoveryRoutableDualWriteCanaryLeaseRead,
    RecoveryRoutableDualWriteCanaryOperationRead,
    RecoveryRoutableDualWriteCanaryReceiptRead,
)
from app.modules.documents.recovery_routable_dual_write_canary_execution_service import (
    RecoveryRoutableDualWriteCanaryExecutionConflict,
    RecoveryRoutableDualWriteCanaryExecutionNotFound,
    RecoveryRoutableDualWriteCanaryExecutionUnavailable,
    execute_routable_dual_write_canary,
    get_routable_dual_write_canary_lease,
    list_routable_dual_write_canary_receipts,
    rollback_routable_dual_write_canary,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-routable-dual-write-canary-execution"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryRoutableDualWriteCanaryExecutionNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryRoutableDualWriteCanaryExecutionUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(lease) -> dict:
    return {
        "claim_id": str(lease.claim_id),
        "document_id": str(lease.document_id),
        "authorization_id": str(lease.authorization_id),
        "authorization_approval_receipt_id": str(lease.authorization_approval_receipt_id),
        "phase_z_health_qualification_id": str(lease.phase_z_health_qualification_id),
        "execution_id": str(lease.execution_id),
        "phase_x_authorization_id": str(lease.phase_x_authorization_id),
        "replica_id": str(lease.replica_id),
        "authorization_hash": lease.authorization_hash,
        "authorization_approval_receipt_hash": lease.authorization_approval_receipt_hash,
        "source_file_hash": lease.source_file_hash,
        "source_file_size_bytes": lease.source_file_size_bytes,
        "canary_object_key_fingerprint": lease.canary_object_key_fingerprint,
        "verification_hash": lease.verification_hash,
        "lease_snapshot_hash": lease.lease_snapshot_hash,
        "lease_hash": lease.lease_hash,
        "status": lease.status,
        "max_canary_writes": lease.max_canary_writes,
        "storage_write_performed": lease.storage_write_performed,
        "canary_executed": True,
        "canary_write_verified": True,
        "routable_dual_write_active": lease.routable_dual_write_active,
        "local_authoritative": True,
        "durable_write_authority_created": False,
        "rehearsal_object_routable": False,
        "read_path_switched": False,
        "write_path_switched": False,
        "document_storage_key_mutated": False,
        "authoritative_storage_changed": False,
        "destructive_action_performed": False,
        "s3_copy_performed": False,
        "s3_delete_performed": False,
        "local_delete_performed": False,
    }


def _operation(lease, receipt, outcome: str):
    return RecoveryRoutableDualWriteCanaryOperationRead(
        lease=RecoveryRoutableDualWriteCanaryLeaseRead.model_validate(lease),
        receipt=RecoveryRoutableDualWriteCanaryReceiptRead.model_validate(receipt) if receipt else None,
        outcome=outcome,
    )


def _commit(db: Session, lease, receipt) -> None:
    db.commit()
    db.refresh(lease)
    if receipt is not None:
        db.refresh(receipt)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-routable-dual-write-canary-authorizations/{authorization_id}/execute",
    response_model=RecoveryRoutableDualWriteCanaryOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_canary_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryRoutableDualWriteCanaryExecutionReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        lease, receipt, outcome = execute_routable_dual_write_canary(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
            activated_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "activated": "EVIDENCE_RECOVERY_ROUTABLE_DUAL_WRITE_CANARY_ACTIVATED",
                "unchanged": "EVIDENCE_RECOVERY_ROUTABLE_DUAL_WRITE_CANARY_ACTIVATION_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_routable_dual_write_canary_lease",
            entity_id=lease.id,
            new_values={**_audit_values(lease), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, lease, receipt)
    except (
        RecoveryRoutableDualWriteCanaryExecutionNotFound,
        RecoveryRoutableDualWriteCanaryExecutionConflict,
        RecoveryRoutableDualWriteCanaryExecutionUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase AB execution conflicts with immutable lineage") from exc
    return _operation(lease, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-routable-dual-write-canary-leases/{lease_id}/rollback",
    response_model=RecoveryRoutableDualWriteCanaryOperationRead,
)
def rollback_canary_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    payload: RecoveryRoutableDualWriteCanaryExecutionReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        lease, receipt, outcome = rollback_routable_dual_write_canary(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
            actor_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "rolled_back": "EVIDENCE_RECOVERY_ROUTABLE_DUAL_WRITE_CANARY_ROLLED_BACK",
                "expired": "EVIDENCE_RECOVERY_ROUTABLE_DUAL_WRITE_CANARY_EXPIRED",
                "unchanged": "EVIDENCE_RECOVERY_ROUTABLE_DUAL_WRITE_CANARY_ROLLBACK_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_routable_dual_write_canary_lease",
            entity_id=lease.id,
            new_values={**_audit_values(lease), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, lease, receipt)
    except (
        RecoveryRoutableDualWriteCanaryExecutionNotFound,
        RecoveryRoutableDualWriteCanaryExecutionConflict,
        RecoveryRoutableDualWriteCanaryExecutionUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase AB rollback conflicts with immutable lineage") from exc
    return _operation(lease, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-routable-dual-write-canary-leases/{lease_id}",
    response_model=RecoveryRoutableDualWriteCanaryLeaseRead,
)
def get_canary_lease_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        lease = get_routable_dual_write_canary_lease(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
        )
    except RecoveryRoutableDualWriteCanaryExecutionNotFound as exc:
        raise _error(exc) from exc
    return RecoveryRoutableDualWriteCanaryLeaseRead.model_validate(lease)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-routable-dual-write-canary-leases/{lease_id}/receipts",
    response_model=list[RecoveryRoutableDualWriteCanaryReceiptRead],
)
def list_canary_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        receipts = list_routable_dual_write_canary_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
        )
    except RecoveryRoutableDualWriteCanaryExecutionNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryRoutableDualWriteCanaryReceiptRead.model_validate(item) for item in receipts]
