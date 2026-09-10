from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_durable_read_health_schemas import (
    RecoveryDurableReadHealthQualificationOperationRead,
    RecoveryDurableReadHealthQualificationRead,
    RecoveryDurableReadHealthQualificationReason,
    RecoveryDurableReadHealthQualificationReceiptRead,
    RecoveryDurableReadHealthQualificationRequest,
)
from app.modules.documents.recovery_durable_read_health_service import (
    RecoveryDurableReadHealthConflict,
    RecoveryDurableReadHealthNotFound,
    RecoveryDurableReadHealthUnavailable,
    get_durable_read_health_qualification,
    list_durable_read_health_receipts,
    qualify_durable_read_health,
    reject_durable_read_health,
    request_durable_read_health_qualification,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-durable-read-health"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryDurableReadHealthNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryDurableReadHealthUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(qualification) -> dict:
    return {
        "claim_id": str(qualification.claim_id),
        "document_id": str(qualification.document_id),
        "durable_lease_id": str(qualification.durable_lease_id),
        "activation_receipt_id": str(qualification.activation_receipt_id),
        "terminal_receipt_id": str(qualification.terminal_receipt_id),
        "authorization_id": str(qualification.authorization_id),
        "qualification_id": str(qualification.qualification_id),
        "replica_id": str(qualification.replica_id),
        "durable_lease_hash": qualification.durable_lease_hash,
        "activation_receipt_hash": qualification.activation_receipt_hash,
        "terminal_receipt_hash": qualification.terminal_receipt_hash,
        "authorization_hash": qualification.authorization_hash,
        "phase_k_qualification_hash": qualification.phase_k_qualification_hash,
        "replica_hash": qualification.replica_hash,
        "source_file_hash": qualification.source_file_hash,
        "source_file_size_bytes": qualification.source_file_size_bytes,
        "local_storage_key_fingerprint": qualification.local_storage_key_fingerprint,
        "recovery_bucket_fingerprint": qualification.recovery_bucket_fingerprint,
        "candidate_storage_key_fingerprint": qualification.candidate_storage_key_fingerprint,
        "source_authority_fingerprint": qualification.source_authority_fingerprint,
        "candidate_authority_fingerprint": qualification.candidate_authority_fingerprint,
        "configuration_fingerprint": qualification.configuration_fingerprint,
        "terminal_phase": qualification.terminal_phase,
        "verified_durable_read_count": qualification.verified_durable_read_count,
        "integrity_failure_count": qualification.integrity_failure_count,
        "storage_unavailable_count": qualification.storage_unavailable_count,
        "route_expired_attempt_count": qualification.route_expired_attempt_count,
        "operational_event_count": qualification.operational_event_count,
        "health_state": qualification.health_state,
        "operational_evidence_hash": qualification.operational_evidence_hash,
        "route_version_at_request": qualification.route_version_at_request,
        "request_snapshot_hash": qualification.request_snapshot_hash,
        "health_qualification_hash": qualification.health_qualification_hash,
        "status": qualification.status,
        "routable_authority_created": False,
        "durable_read_route_created": False,
        "read_path_switched": False,
        "write_path_switched": False,
        "document_storage_key_mutated": False,
        "authoritative_storage_changed": False,
        "destructive_action_performed": False,
        "s3_delete_performed": False,
        "local_delete_performed": False,
    }


def _operation(qualification, receipt, outcome: str) -> RecoveryDurableReadHealthQualificationOperationRead:
    return RecoveryDurableReadHealthQualificationOperationRead(
        qualification=RecoveryDurableReadHealthQualificationRead.model_validate(qualification),
        receipt=(
            RecoveryDurableReadHealthQualificationReceiptRead.model_validate(receipt)
            if receipt is not None
            else None
        ),
        outcome=outcome,
    )


def _commit(db: Session, qualification, receipt) -> None:
    db.commit()
    db.refresh(qualification)
    if receipt is not None:
        db.refresh(receipt)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-health-qualification",
    response_model=RecoveryDurableReadHealthQualificationOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_durable_read_health_qualification_endpoint(
    claim_id: UUID,
    document_id: UUID,
    payload: RecoveryDurableReadHealthQualificationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadHealthQualificationOperationRead:
    try:
        qualification, receipt, outcome = request_durable_read_health_qualification(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            durable_lease_id=payload.durable_lease_id,
            requested_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "pending_second_approval": "EVIDENCE_RECOVERY_DURABLE_READ_HEALTH_REQUESTED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_HEALTH_REQUEST_REPLAYED",
                "invalidated": "EVIDENCE_RECOVERY_DURABLE_READ_HEALTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_durable_read_health_qualification",
            entity_id=qualification.id,
            new_values={
                **_audit_values(qualification),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        _commit(db, qualification, receipt)
    except (RecoveryDurableReadHealthNotFound, RecoveryDurableReadHealthConflict, RecoveryDurableReadHealthUnavailable) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Durable read health qualification conflicts with immutable lineage") from exc
    return _operation(qualification, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-health-qualifications/{health_qualification_id}/qualify",
    response_model=RecoveryDurableReadHealthQualificationOperationRead,
)
def qualify_durable_read_health_endpoint(
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    payload: RecoveryDurableReadHealthQualificationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadHealthQualificationOperationRead:
    try:
        qualification, receipt, outcome = qualify_durable_read_health(
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
                "qualified": "EVIDENCE_RECOVERY_DURABLE_READ_HEALTH_QUALIFIED",
                "degraded": "EVIDENCE_RECOVERY_DURABLE_READ_HEALTH_DEGRADED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_HEALTH_ASSESSMENT_REPLAYED",
                "invalidated": "EVIDENCE_RECOVERY_DURABLE_READ_HEALTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_durable_read_health_qualification",
            entity_id=qualification.id,
            new_values={
                **_audit_values(qualification),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        _commit(db, qualification, receipt)
    except (RecoveryDurableReadHealthNotFound, RecoveryDurableReadHealthConflict, RecoveryDurableReadHealthUnavailable) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Durable read health receipt conflict") from exc
    return _operation(qualification, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-health-qualifications/{health_qualification_id}/reject",
    response_model=RecoveryDurableReadHealthQualificationOperationRead,
)
def reject_durable_read_health_endpoint(
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    payload: RecoveryDurableReadHealthQualificationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadHealthQualificationOperationRead:
    try:
        qualification, receipt, outcome = reject_durable_read_health(
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
                "rejected": "EVIDENCE_RECOVERY_DURABLE_READ_HEALTH_REJECTED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_HEALTH_REJECTION_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_durable_read_health_qualification",
            entity_id=qualification.id,
            new_values={
                **_audit_values(qualification),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        _commit(db, qualification, receipt)
    except (RecoveryDurableReadHealthNotFound, RecoveryDurableReadHealthConflict, RecoveryDurableReadHealthUnavailable) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(qualification, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-health-qualifications/{health_qualification_id}",
    response_model=RecoveryDurableReadHealthQualificationRead,
)
def get_durable_read_health_qualification_endpoint(
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryDurableReadHealthQualificationRead:
    try:
        qualification = get_durable_read_health_qualification(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=health_qualification_id,
        )
    except RecoveryDurableReadHealthNotFound as exc:
        raise _error(exc) from exc
    return RecoveryDurableReadHealthQualificationRead.model_validate(qualification)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-health-qualifications/{health_qualification_id}/receipts",
    response_model=list[RecoveryDurableReadHealthQualificationReceiptRead],
)
def list_durable_read_health_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RecoveryDurableReadHealthQualificationReceiptRead]:
    try:
        receipts = list_durable_read_health_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=health_qualification_id,
        )
    except RecoveryDurableReadHealthNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryDurableReadHealthQualificationReceiptRead.model_validate(item) for item in receipts]
