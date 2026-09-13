from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_durable_authoritative_storage_health_schemas import (
    RecoveryDurableAuthoritativeStorageHealthOperationRead,
    RecoveryDurableAuthoritativeStorageHealthQualificationRead,
    RecoveryDurableAuthoritativeStorageHealthReason,
    RecoveryDurableAuthoritativeStorageHealthReceiptRead,
    RecoveryDurableAuthoritativeStorageHealthRequest,
)
from app.modules.documents.recovery_durable_authoritative_storage_health_service import (
    RecoveryDurableAuthoritativeStorageHealthConflict,
    RecoveryDurableAuthoritativeStorageHealthNotFound,
    RecoveryDurableAuthoritativeStorageHealthUnavailable,
    get_durable_authoritative_storage_health_qualification,
    list_durable_authoritative_storage_health_receipts,
    qualify_durable_authoritative_storage_health,
    reject_durable_authoritative_storage_health,
    request_durable_authoritative_storage_health_qualification,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-durable-authoritative-storage-health"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryDurableAuthoritativeStorageHealthNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryDurableAuthoritativeStorageHealthUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(q) -> dict:
    return {
        "claim_id": str(q.claim_id),
        "document_id": str(q.document_id),
        "ratification_id": str(q.ratification_id),
        "ratification_hash": q.ratification_hash,
        "ratification_receipt_hash": q.ratification_receipt_hash,
        "phase_am_authorization_id": str(q.phase_am_authorization_id),
        "phase_al_health_qualification_id": str(q.phase_al_health_qualification_id),
        "authoritative_storage_ownership_lease_id": str(q.authoritative_storage_ownership_lease_id),
        "phase_aj_authorization_id": str(q.phase_aj_authorization_id),
        "phase_ai_health_qualification_id": str(q.phase_ai_health_qualification_id),
        "durable_write_ownership_lease_id": str(q.durable_write_ownership_lease_id),
        "replica_id": str(q.replica_id),
        "source_file_hash": q.source_file_hash,
        "source_file_size_bytes": q.source_file_size_bytes,
        "observed_local_hash": q.observed_local_hash,
        "observed_local_size_bytes": q.observed_local_size_bytes,
        "observed_recovery_hash": q.observed_recovery_hash,
        "observed_recovery_size_bytes": q.observed_recovery_size_bytes,
        "authority_route_version_at_request": q.authority_route_version_at_request,
        "read_route_version_at_request": q.read_route_version_at_request,
        "experimental_write_route_version_at_request": q.experimental_write_route_version_at_request,
        "durable_route_version_at_request": q.durable_route_version_at_request,
        "observed_authority_kind": q.observed_authority_kind,
        "observed_authority_tenure": q.observed_authority_tenure,
        "observed_ratification_active": q.observed_ratification_active,
        "observed_durable_authority_created": q.observed_durable_authority_created,
        "observed_local_authoritative": q.observed_local_authoritative,
        "observed_recovery_authoritative": q.observed_recovery_authoritative,
        "observed_authoritative_storage_changed": q.observed_authoritative_storage_changed,
        "integrity_proof_hash": q.integrity_proof_hash,
        "request_snapshot_hash": q.request_snapshot_hash,
        "health_qualification_hash": q.health_qualification_hash,
        "health_state": q.health_state,
        "review_expires_at": q.review_expires_at.isoformat(),
        "status": q.status,
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


def _operation(q, receipt, outcome: str):
    return RecoveryDurableAuthoritativeStorageHealthOperationRead(
        qualification=RecoveryDurableAuthoritativeStorageHealthQualificationRead.model_validate(q),
        receipt=RecoveryDurableAuthoritativeStorageHealthReceiptRead.model_validate(receipt) if receipt else None,
        outcome=outcome,
    )


def _commit(db: Session, q, receipt) -> None:
    db.commit()
    db.refresh(q)
    if receipt is not None:
        db.refresh(receipt)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-authoritative-storage-health-qualification",
    response_model=RecoveryDurableAuthoritativeStorageHealthOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_health_endpoint(
    claim_id: UUID,
    document_id: UUID,
    payload: RecoveryDurableAuthoritativeStorageHealthRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        q, receipt, outcome = request_durable_authoritative_storage_health_qualification(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            ratification_id=payload.ratification_id,
            requested_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "pending_second_approval": "EVIDENCE_RECOVERY_DURABLE_AUTHORITATIVE_STORAGE_HEALTH_REQUESTED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_AUTHORITATIVE_STORAGE_HEALTH_REQUEST_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_durable_authoritative_storage_health_qualification",
            entity_id=q.id,
            new_values={**_audit_values(q), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, q, receipt)
    except (
        RecoveryDurableAuthoritativeStorageHealthNotFound,
        RecoveryDurableAuthoritativeStorageHealthConflict,
        RecoveryDurableAuthoritativeStorageHealthUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase AO health qualification conflicts with immutable durable lineage") from exc
    return _operation(q, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-authoritative-storage-health-qualifications/{qualification_id}/qualify",
    response_model=RecoveryDurableAuthoritativeStorageHealthOperationRead,
)
def qualify_health_endpoint(
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
    payload: RecoveryDurableAuthoritativeStorageHealthReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        q, receipt, outcome = qualify_durable_authoritative_storage_health(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            qualification_id=qualification_id,
            qualified_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "qualified": "EVIDENCE_RECOVERY_DURABLE_AUTHORITATIVE_STORAGE_HEALTH_QUALIFIED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_AUTHORITATIVE_STORAGE_HEALTH_QUALIFICATION_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_DURABLE_AUTHORITATIVE_STORAGE_HEALTH_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_DURABLE_AUTHORITATIVE_STORAGE_HEALTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_durable_authoritative_storage_health_qualification",
            entity_id=q.id,
            new_values={**_audit_values(q), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, q, receipt)
    except (
        RecoveryDurableAuthoritativeStorageHealthNotFound,
        RecoveryDurableAuthoritativeStorageHealthConflict,
        RecoveryDurableAuthoritativeStorageHealthUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(q, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-authoritative-storage-health-qualifications/{qualification_id}/reject",
    response_model=RecoveryDurableAuthoritativeStorageHealthOperationRead,
)
def reject_health_endpoint(
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
    payload: RecoveryDurableAuthoritativeStorageHealthReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        q, receipt, outcome = reject_durable_authoritative_storage_health(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            qualification_id=qualification_id,
            rejected_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "rejected": "EVIDENCE_RECOVERY_DURABLE_AUTHORITATIVE_STORAGE_HEALTH_REJECTED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_AUTHORITATIVE_STORAGE_HEALTH_REJECTION_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_DURABLE_AUTHORITATIVE_STORAGE_HEALTH_EXPIRED",
            }[outcome],
            entity_type="evidence_recovery_durable_authoritative_storage_health_qualification",
            entity_id=q.id,
            new_values={**_audit_values(q), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, q, receipt)
    except (
        RecoveryDurableAuthoritativeStorageHealthNotFound,
        RecoveryDurableAuthoritativeStorageHealthConflict,
        RecoveryDurableAuthoritativeStorageHealthUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(q, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-authoritative-storage-health-qualifications/{qualification_id}",
    response_model=RecoveryDurableAuthoritativeStorageHealthQualificationRead,
)
def get_health_endpoint(
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        q = get_durable_authoritative_storage_health_qualification(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            qualification_id=qualification_id,
        )
    except RecoveryDurableAuthoritativeStorageHealthNotFound as exc:
        raise _error(exc) from exc
    return RecoveryDurableAuthoritativeStorageHealthQualificationRead.model_validate(q)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-authoritative-storage-health-qualifications/{qualification_id}/receipts",
    response_model=list[RecoveryDurableAuthoritativeStorageHealthReceiptRead],
)
def list_health_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        receipts = list_durable_authoritative_storage_health_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            qualification_id=qualification_id,
        )
    except RecoveryDurableAuthoritativeStorageHealthNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryDurableAuthoritativeStorageHealthReceiptRead.model_validate(item) for item in receipts]
