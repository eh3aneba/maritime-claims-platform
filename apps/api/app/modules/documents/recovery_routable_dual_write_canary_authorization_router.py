from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_routable_dual_write_canary_authorization_schemas import (
    RecoveryRoutableDualWriteCanaryAuthorizationOperationRead,
    RecoveryRoutableDualWriteCanaryAuthorizationRead,
    RecoveryRoutableDualWriteCanaryAuthorizationReason,
    RecoveryRoutableDualWriteCanaryAuthorizationReceiptRead,
    RecoveryRoutableDualWriteCanaryAuthorizationRequest,
)
from app.modules.documents.recovery_routable_dual_write_canary_authorization_service import (
    RecoveryRoutableDualWriteCanaryAuthorizationConflict,
    RecoveryRoutableDualWriteCanaryAuthorizationNotFound,
    RecoveryRoutableDualWriteCanaryAuthorizationUnavailable,
    approve_recovery_routable_dual_write_canary_authorization,
    get_recovery_routable_dual_write_canary_authorization,
    list_recovery_routable_dual_write_canary_authorization_receipts,
    reject_recovery_routable_dual_write_canary_authorization,
    request_recovery_routable_dual_write_canary_authorization,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-routable-dual-write-canary-authorization"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryRoutableDualWriteCanaryAuthorizationNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryRoutableDualWriteCanaryAuthorizationUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(a) -> dict:
    return {
        "claim_id": str(a.claim_id),
        "document_id": str(a.document_id),
        "phase_z_health_qualification_id": str(a.phase_z_health_qualification_id),
        "phase_z_health_receipt_id": str(a.phase_z_health_receipt_id),
        "execution_id": str(a.execution_id),
        "phase_x_authorization_id": str(a.phase_x_authorization_id),
        "replica_id": str(a.replica_id),
        "phase_z_health_qualification_hash": a.phase_z_health_qualification_hash,
        "phase_z_health_receipt_hash": a.phase_z_health_receipt_hash,
        "execution_hash": a.execution_hash,
        "verification_hash": a.verification_hash,
        "source_file_hash": a.source_file_hash,
        "source_file_size_bytes": a.source_file_size_bytes,
        "request_snapshot_hash": a.request_snapshot_hash,
        "authorization_hash": a.authorization_hash,
        "health_state": a.health_state,
        "max_canary_windows": a.max_canary_windows,
        "route_version_at_request": a.route_version_at_request,
        "review_expires_at": a.review_expires_at.isoformat(),
        "authorization_expires_at": a.authorization_expires_at.isoformat() if a.authorization_expires_at else None,
        "status": a.status,
        "storage_write_performed": False,
        "canary_executed": False,
        "routable_dual_write_active": False,
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


def _operation(a, receipt, outcome: str):
    return RecoveryRoutableDualWriteCanaryAuthorizationOperationRead(
        authorization=RecoveryRoutableDualWriteCanaryAuthorizationRead.model_validate(a),
        receipt=RecoveryRoutableDualWriteCanaryAuthorizationReceiptRead.model_validate(receipt) if receipt else None,
        outcome=outcome,
    )


def _commit(db: Session, a, receipt) -> None:
    db.commit()
    db.refresh(a)
    if receipt is not None:
        db.refresh(receipt)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-routable-dual-write-canary-authorization",
    response_model=RecoveryRoutableDualWriteCanaryAuthorizationOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_canary_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    payload: RecoveryRoutableDualWriteCanaryAuthorizationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        a, receipt, outcome = request_recovery_routable_dual_write_canary_authorization(
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
                "pending_second_approval": "EVIDENCE_RECOVERY_ROUTABLE_DUAL_WRITE_CANARY_AUTH_REQUESTED",
                "unchanged": "EVIDENCE_RECOVERY_ROUTABLE_DUAL_WRITE_CANARY_AUTH_REQUEST_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_routable_dual_write_canary_authorization",
            entity_id=a.id,
            new_values={**_audit_values(a), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, a, receipt)
    except (
        RecoveryRoutableDualWriteCanaryAuthorizationNotFound,
        RecoveryRoutableDualWriteCanaryAuthorizationConflict,
        RecoveryRoutableDualWriteCanaryAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase AA authorization conflicts with immutable lineage") from exc
    return _operation(a, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-routable-dual-write-canary-authorizations/{authorization_id}/approve",
    response_model=RecoveryRoutableDualWriteCanaryAuthorizationOperationRead,
)
def approve_canary_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryRoutableDualWriteCanaryAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        a, receipt, outcome = approve_recovery_routable_dual_write_canary_authorization(
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
                "approved": "EVIDENCE_RECOVERY_ROUTABLE_DUAL_WRITE_CANARY_AUTH_APPROVED",
                "unchanged": "EVIDENCE_RECOVERY_ROUTABLE_DUAL_WRITE_CANARY_AUTH_APPROVAL_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_ROUTABLE_DUAL_WRITE_CANARY_AUTH_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_ROUTABLE_DUAL_WRITE_CANARY_AUTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_routable_dual_write_canary_authorization",
            entity_id=a.id,
            new_values={**_audit_values(a), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, a, receipt)
    except (
        RecoveryRoutableDualWriteCanaryAuthorizationNotFound,
        RecoveryRoutableDualWriteCanaryAuthorizationConflict,
        RecoveryRoutableDualWriteCanaryAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(a, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-routable-dual-write-canary-authorizations/{authorization_id}/reject",
    response_model=RecoveryRoutableDualWriteCanaryAuthorizationOperationRead,
)
def reject_canary_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryRoutableDualWriteCanaryAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        a, receipt, outcome = reject_recovery_routable_dual_write_canary_authorization(
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
                "rejected": "EVIDENCE_RECOVERY_ROUTABLE_DUAL_WRITE_CANARY_AUTH_REJECTED",
                "unchanged": "EVIDENCE_RECOVERY_ROUTABLE_DUAL_WRITE_CANARY_AUTH_REJECTION_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_ROUTABLE_DUAL_WRITE_CANARY_AUTH_EXPIRED",
            }[outcome],
            entity_type="evidence_recovery_routable_dual_write_canary_authorization",
            entity_id=a.id,
            new_values={**_audit_values(a), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, a, receipt)
    except (
        RecoveryRoutableDualWriteCanaryAuthorizationNotFound,
        RecoveryRoutableDualWriteCanaryAuthorizationConflict,
        RecoveryRoutableDualWriteCanaryAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(a, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-routable-dual-write-canary-authorizations/{authorization_id}",
    response_model=RecoveryRoutableDualWriteCanaryAuthorizationRead,
)
def get_canary_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        a = get_recovery_routable_dual_write_canary_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryRoutableDualWriteCanaryAuthorizationNotFound as exc:
        raise _error(exc) from exc
    return RecoveryRoutableDualWriteCanaryAuthorizationRead.model_validate(a)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-routable-dual-write-canary-authorizations/{authorization_id}/receipts",
    response_model=list[RecoveryRoutableDualWriteCanaryAuthorizationReceiptRead],
)
def list_canary_authorization_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        receipts = list_recovery_routable_dual_write_canary_authorization_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryRoutableDualWriteCanaryAuthorizationNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryRoutableDualWriteCanaryAuthorizationReceiptRead.model_validate(item) for item in receipts]
