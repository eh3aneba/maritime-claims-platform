from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_authoritative_storage_ratification_authorization_schemas import (
    RecoveryAuthoritativeStorageRatificationAuthorizationOperationRead,
    RecoveryAuthoritativeStorageRatificationAuthorizationRead,
    RecoveryAuthoritativeStorageRatificationAuthorizationReason,
    RecoveryAuthoritativeStorageRatificationAuthorizationReceiptRead,
    RecoveryAuthoritativeStorageRatificationAuthorizationRequest,
)
from app.modules.documents.recovery_authoritative_storage_ratification_authorization_service import (
    RecoveryAuthoritativeStorageRatificationAuthorizationConflict,
    RecoveryAuthoritativeStorageRatificationAuthorizationNotFound,
    RecoveryAuthoritativeStorageRatificationAuthorizationUnavailable,
    approve_authoritative_storage_ratification_authorization,
    get_authoritative_storage_ratification_authorization,
    list_authoritative_storage_ratification_authorization_receipts,
    reject_authoritative_storage_ratification_authorization,
    request_authoritative_storage_ratification_authorization,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-authoritative-storage-ratification-authorization"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryAuthoritativeStorageRatificationAuthorizationNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryAuthoritativeStorageRatificationAuthorizationUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(a) -> dict:
    return {
        "claim_id": str(a.claim_id),
        "document_id": str(a.document_id),
        "phase_al_health_qualification_id": str(a.phase_al_health_qualification_id),
        "authoritative_storage_ownership_lease_id": str(a.authoritative_storage_ownership_lease_id),
        "phase_aj_authorization_id": str(a.phase_aj_authorization_id),
        "phase_ai_health_qualification_id": str(a.phase_ai_health_qualification_id),
        "durable_write_ownership_lease_id": str(a.durable_write_ownership_lease_id),
        "replica_id": str(a.replica_id),
        "request_snapshot_hash": a.request_snapshot_hash,
        "authorization_hash": a.authorization_hash,
        "current_authority_kind": a.current_authority_kind,
        "target_ratification_kind": a.target_ratification_kind,
        "health_state": a.health_state,
        "max_execution_windows": a.max_execution_windows,
        "ratification_authorized": a.ratification_authorized,
        "status": a.status,
        "review_expires_at": a.review_expires_at.isoformat(),
        "authorization_expires_at": a.authorization_expires_at.isoformat() if a.authorization_expires_at else None,
        "local_evidence_preserved": True,
        "storage_write_performed": False,
        "route_mutation_performed": False,
        "ownership_mutation_performed": False,
        "read_path_switched": False,
        "write_path_switched": False,
        "document_storage_key_mutated": False,
        "destructive_action_performed": False,
        "physical_disposal_authorized": False,
        "s3_put_performed": False,
        "s3_copy_performed": False,
        "s3_delete_performed": False,
        "local_overwrite_performed": False,
        "local_move_performed": False,
        "local_delete_performed": False,
    }


def _operation(a, receipt, outcome: str):
    return RecoveryAuthoritativeStorageRatificationAuthorizationOperationRead(
        authorization=RecoveryAuthoritativeStorageRatificationAuthorizationRead.model_validate(a),
        receipt=(
            RecoveryAuthoritativeStorageRatificationAuthorizationReceiptRead.model_validate(receipt)
            if receipt
            else None
        ),
        outcome=outcome,
    )


def _commit(db: Session, a, receipt) -> None:
    db.commit()
    db.refresh(a)
    if receipt is not None:
        db.refresh(receipt)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-authoritative-storage-ratification-authorizations",
    response_model=RecoveryAuthoritativeStorageRatificationAuthorizationOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    payload: RecoveryAuthoritativeStorageRatificationAuthorizationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        a, receipt, outcome = request_authoritative_storage_ratification_authorization(
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
                "pending_second_approval": "EVIDENCE_RECOVERY_AUTHORITATIVE_STORAGE_RATIFICATION_AUTH_REQUESTED",
                "unchanged": "EVIDENCE_RECOVERY_AUTHORITATIVE_STORAGE_RATIFICATION_AUTH_REQUEST_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_authoritative_storage_ratification_authorization",
            entity_id=a.id,
            new_values={**_audit_values(a), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, a, receipt)
    except (
        RecoveryAuthoritativeStorageRatificationAuthorizationNotFound,
        RecoveryAuthoritativeStorageRatificationAuthorizationConflict,
        RecoveryAuthoritativeStorageRatificationAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase AM authorization conflicts with immutable lineage") from exc
    return _operation(a, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-authoritative-storage-ratification-authorizations/{authorization_id}/approve",
    response_model=RecoveryAuthoritativeStorageRatificationAuthorizationOperationRead,
)
def approve_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryAuthoritativeStorageRatificationAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        a, receipt, outcome = approve_authoritative_storage_ratification_authorization(
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
                "approved": "EVIDENCE_RECOVERY_AUTHORITATIVE_STORAGE_RATIFICATION_AUTH_APPROVED",
                "unchanged": "EVIDENCE_RECOVERY_AUTHORITATIVE_STORAGE_RATIFICATION_AUTH_APPROVAL_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_AUTHORITATIVE_STORAGE_RATIFICATION_AUTH_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_AUTHORITATIVE_STORAGE_RATIFICATION_AUTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_authoritative_storage_ratification_authorization",
            entity_id=a.id,
            new_values={**_audit_values(a), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, a, receipt)
    except (
        RecoveryAuthoritativeStorageRatificationAuthorizationNotFound,
        RecoveryAuthoritativeStorageRatificationAuthorizationConflict,
        RecoveryAuthoritativeStorageRatificationAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(a, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-authoritative-storage-ratification-authorizations/{authorization_id}/reject",
    response_model=RecoveryAuthoritativeStorageRatificationAuthorizationOperationRead,
)
def reject_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryAuthoritativeStorageRatificationAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        a, receipt, outcome = reject_authoritative_storage_ratification_authorization(
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
                "rejected": "EVIDENCE_RECOVERY_AUTHORITATIVE_STORAGE_RATIFICATION_AUTH_REJECTED",
                "unchanged": "EVIDENCE_RECOVERY_AUTHORITATIVE_STORAGE_RATIFICATION_AUTH_REJECTION_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_AUTHORITATIVE_STORAGE_RATIFICATION_AUTH_EXPIRED",
            }[outcome],
            entity_type="evidence_recovery_authoritative_storage_ratification_authorization",
            entity_id=a.id,
            new_values={**_audit_values(a), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, a, receipt)
    except (
        RecoveryAuthoritativeStorageRatificationAuthorizationNotFound,
        RecoveryAuthoritativeStorageRatificationAuthorizationConflict,
        RecoveryAuthoritativeStorageRatificationAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(a, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-authoritative-storage-ratification-authorizations/{authorization_id}",
    response_model=RecoveryAuthoritativeStorageRatificationAuthorizationRead,
)
def get_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        a = get_authoritative_storage_ratification_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryAuthoritativeStorageRatificationAuthorizationNotFound as exc:
        raise _error(exc) from exc
    return RecoveryAuthoritativeStorageRatificationAuthorizationRead.model_validate(a)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-authoritative-storage-ratification-authorizations/{authorization_id}/receipts",
    response_model=list[RecoveryAuthoritativeStorageRatificationAuthorizationReceiptRead],
)
def list_authorization_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        receipts = list_authoritative_storage_ratification_authorization_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryAuthoritativeStorageRatificationAuthorizationNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryAuthoritativeStorageRatificationAuthorizationReceiptRead.model_validate(item) for item in receipts]
