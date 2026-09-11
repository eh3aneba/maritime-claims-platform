from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_durable_write_ownership_authorization_schemas import (
    RecoveryDurableWriteOwnershipAuthorizationOperationRead,
    RecoveryDurableWriteOwnershipAuthorizationRead,
    RecoveryDurableWriteOwnershipAuthorizationReason,
    RecoveryDurableWriteOwnershipAuthorizationReceiptRead,
    RecoveryDurableWriteOwnershipAuthorizationRequest,
)
from app.modules.documents.recovery_durable_write_ownership_authorization_service import (
    RecoveryDurableWriteOwnershipAuthorizationConflict,
    RecoveryDurableWriteOwnershipAuthorizationNotFound,
    RecoveryDurableWriteOwnershipAuthorizationUnavailable,
    approve_durable_write_ownership_authorization,
    get_durable_write_ownership_authorization,
    list_durable_write_ownership_authorization_receipts,
    reject_durable_write_ownership_authorization,
    request_durable_write_ownership_authorization,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-durable-write-ownership-authorization"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryDurableWriteOwnershipAuthorizationNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryDurableWriteOwnershipAuthorizationUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(a) -> dict:
    return {
        "claim_id": str(a.claim_id),
        "document_id": str(a.document_id),
        "phase_af_health_qualification_id": str(a.phase_af_health_qualification_id),
        "transition_lease_id": str(a.transition_lease_id),
        "phase_ad_authorization_id": str(a.phase_ad_authorization_id),
        "replica_id": str(a.replica_id),
        "phase_af_health_qualification_hash": a.phase_af_health_qualification_hash,
        "phase_af_health_receipt_hash": a.phase_af_health_receipt_hash,
        "transition_lease_hash": a.transition_lease_hash,
        "phase_ad_authorization_hash": a.phase_ad_authorization_hash,
        "source_file_hash": a.source_file_hash,
        "source_file_size_bytes": a.source_file_size_bytes,
        "read_route_version_at_request": a.read_route_version_at_request,
        "write_route_version_at_request": a.write_route_version_at_request,
        "request_snapshot_hash": a.request_snapshot_hash,
        "authorization_hash": a.authorization_hash,
        "health_state": a.health_state,
        "max_execution_windows": a.max_execution_windows,
        "review_expires_at": a.review_expires_at.isoformat(),
        "authorization_expires_at": a.authorization_expires_at.isoformat() if a.authorization_expires_at else None,
        "status": a.status,
        "local_authoritative": True,
        "storage_write_performed": False,
        "write_route_lease_created": False,
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


def _operation(a, receipt, outcome: str):
    return RecoveryDurableWriteOwnershipAuthorizationOperationRead(
        authorization=RecoveryDurableWriteOwnershipAuthorizationRead.model_validate(a),
        receipt=RecoveryDurableWriteOwnershipAuthorizationReceiptRead.model_validate(receipt) if receipt else None,
        outcome=outcome,
    )


def _commit(db: Session, a, receipt) -> None:
    db.commit()
    db.refresh(a)
    if receipt is not None:
        db.refresh(receipt)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-write-ownership-authorizations",
    response_model=RecoveryDurableWriteOwnershipAuthorizationOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    payload: RecoveryDurableWriteOwnershipAuthorizationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        a, receipt, outcome = request_durable_write_ownership_authorization(
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
                "pending_second_approval": "EVIDENCE_RECOVERY_DURABLE_WRITE_OWNERSHIP_AUTH_REQUESTED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_WRITE_OWNERSHIP_AUTH_REQUEST_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_durable_write_ownership_authorization",
            entity_id=a.id,
            new_values={**_audit_values(a), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, a, receipt)
    except (
        RecoveryDurableWriteOwnershipAuthorizationNotFound,
        RecoveryDurableWriteOwnershipAuthorizationConflict,
        RecoveryDurableWriteOwnershipAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase AG authorization conflicts with immutable lineage") from exc
    return _operation(a, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-write-ownership-authorizations/{authorization_id}/approve",
    response_model=RecoveryDurableWriteOwnershipAuthorizationOperationRead,
)
def approve_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryDurableWriteOwnershipAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        a, receipt, outcome = approve_durable_write_ownership_authorization(
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
                "approved": "EVIDENCE_RECOVERY_DURABLE_WRITE_OWNERSHIP_AUTH_APPROVED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_WRITE_OWNERSHIP_AUTH_APPROVAL_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_DURABLE_WRITE_OWNERSHIP_AUTH_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_DURABLE_WRITE_OWNERSHIP_AUTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_durable_write_ownership_authorization",
            entity_id=a.id,
            new_values={**_audit_values(a), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, a, receipt)
    except (
        RecoveryDurableWriteOwnershipAuthorizationNotFound,
        RecoveryDurableWriteOwnershipAuthorizationConflict,
        RecoveryDurableWriteOwnershipAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(a, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-write-ownership-authorizations/{authorization_id}/reject",
    response_model=RecoveryDurableWriteOwnershipAuthorizationOperationRead,
)
def reject_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryDurableWriteOwnershipAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        a, receipt, outcome = reject_durable_write_ownership_authorization(
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
                "rejected": "EVIDENCE_RECOVERY_DURABLE_WRITE_OWNERSHIP_AUTH_REJECTED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_WRITE_OWNERSHIP_AUTH_REJECTION_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_DURABLE_WRITE_OWNERSHIP_AUTH_EXPIRED",
            }[outcome],
            entity_type="evidence_recovery_durable_write_ownership_authorization",
            entity_id=a.id,
            new_values={**_audit_values(a), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, a, receipt)
    except (
        RecoveryDurableWriteOwnershipAuthorizationNotFound,
        RecoveryDurableWriteOwnershipAuthorizationConflict,
        RecoveryDurableWriteOwnershipAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(a, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-write-ownership-authorizations/{authorization_id}",
    response_model=RecoveryDurableWriteOwnershipAuthorizationRead,
)
def get_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        a = get_durable_write_ownership_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryDurableWriteOwnershipAuthorizationNotFound as exc:
        raise _error(exc) from exc
    return RecoveryDurableWriteOwnershipAuthorizationRead.model_validate(a)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-write-ownership-authorizations/{authorization_id}/receipts",
    response_model=list[RecoveryDurableWriteOwnershipAuthorizationReceiptRead],
)
def list_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        receipts = list_durable_write_ownership_authorization_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryDurableWriteOwnershipAuthorizationNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryDurableWriteOwnershipAuthorizationReceiptRead.model_validate(item) for item in receipts]
