from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_durable_read_reauthorized_renewal_health_schemas import (
    RecoveryDurableReadReauthorizedRenewalHealthQualificationOperationRead,
    RecoveryDurableReadReauthorizedRenewalHealthQualificationRead,
    RecoveryDurableReadReauthorizedRenewalHealthQualificationReason,
    RecoveryDurableReadReauthorizedRenewalHealthQualificationReceiptRead,
    RecoveryDurableReadReauthorizedRenewalHealthQualificationRequest,
)
from app.modules.documents.recovery_durable_read_reauthorized_renewal_health_service import (
    RecoveryDurableReadReauthorizedRenewalHealthConflict,
    RecoveryDurableReadReauthorizedRenewalHealthNotFound,
    RecoveryDurableReadReauthorizedRenewalHealthUnavailable,
    get_durable_read_reauthorized_renewal_health_qualification,
    list_durable_read_reauthorized_renewal_health_receipts,
    qualify_durable_read_reauthorized_renewal_health,
    reject_durable_read_reauthorized_renewal_health,
    request_durable_read_reauthorized_renewal_health_qualification,
)

router = APIRouter(
    prefix="/claims",
    tags=["evidence-recovery-durable-read-reauthorized-renewal-health"],
)


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryDurableReadReauthorizedRenewalHealthNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryDurableReadReauthorizedRenewalHealthUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(qualification) -> dict:
    return {
        "claim_id": str(qualification.claim_id),
        "document_id": str(qualification.document_id),
        "reauthorized_renewal_lease_id": str(qualification.reauthorized_renewal_lease_id),
        "activation_receipt_id": str(qualification.activation_receipt_id),
        "terminal_receipt_id": str(qualification.terminal_receipt_id),
        "reauthorization_id": str(qualification.reauthorization_id),
        "phase_q_health_qualification_id": str(qualification.phase_q_health_qualification_id),
        "prior_renewal_lease_id": str(qualification.prior_renewal_lease_id),
        "replica_id": str(qualification.replica_id),
        "reauthorized_renewal_lease_hash": qualification.reauthorized_renewal_lease_hash,
        "activation_receipt_hash": qualification.activation_receipt_hash,
        "terminal_receipt_hash": qualification.terminal_receipt_hash,
        "reauthorization_hash": qualification.reauthorization_hash,
        "phase_q_health_qualification_hash": qualification.phase_q_health_qualification_hash,
        "prior_renewal_lease_hash": qualification.prior_renewal_lease_hash,
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
        "review_expires_at": qualification.review_expires_at.isoformat(),
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


def _operation(
    qualification,
    receipt,
    outcome: str,
) -> RecoveryDurableReadReauthorizedRenewalHealthQualificationOperationRead:
    return RecoveryDurableReadReauthorizedRenewalHealthQualificationOperationRead(
        qualification=RecoveryDurableReadReauthorizedRenewalHealthQualificationRead.model_validate(
            qualification
        ),
        receipt=(
            RecoveryDurableReadReauthorizedRenewalHealthQualificationReceiptRead.model_validate(
                receipt
            )
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
    "/{claim_id}/documents/{document_id}/recovery-durable-read-reauthorized-renewal-health-qualification",
    response_model=RecoveryDurableReadReauthorizedRenewalHealthQualificationOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_health_endpoint(
    claim_id: UUID,
    document_id: UUID,
    payload: RecoveryDurableReadReauthorizedRenewalHealthQualificationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadReauthorizedRenewalHealthQualificationOperationRead:
    try:
        qualification, receipt, outcome = (
            request_durable_read_reauthorized_renewal_health_qualification(
                db,
                organization_id=current_user.organization_id,
                claim_id=claim_id,
                document_id=document_id,
                reauthorized_renewal_lease_id=payload.reauthorized_renewal_lease_id,
                requested_by_id=current_user.id,
                reason=payload.reason,
            )
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "pending_second_approval": "EVIDENCE_RECOVERY_DRR_REAUTHORIZED_RENEWAL_HEALTH_REQUESTED",
                "unchanged": "EVIDENCE_RECOVERY_DRR_REAUTHORIZED_RENEWAL_HEALTH_REQUEST_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_DRR_REAUTHORIZED_RENEWAL_HEALTH_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_DRR_REAUTHORIZED_RENEWAL_HEALTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_drr_reauthorized_renewal_health_qualification",
            entity_id=qualification.id,
            new_values={
                **_audit_values(qualification),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        _commit(db, qualification, receipt)
    except (
        RecoveryDurableReadReauthorizedRenewalHealthNotFound,
        RecoveryDurableReadReauthorizedRenewalHealthConflict,
        RecoveryDurableReadReauthorizedRenewalHealthUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Reauthorized renewal health qualification conflicts with immutable lineage",
        ) from exc
    return _operation(qualification, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-reauthorized-renewal-health-qualifications/{health_qualification_id}/qualify",
    response_model=RecoveryDurableReadReauthorizedRenewalHealthQualificationOperationRead,
)
def qualify_health_endpoint(
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    payload: RecoveryDurableReadReauthorizedRenewalHealthQualificationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadReauthorizedRenewalHealthQualificationOperationRead:
    try:
        qualification, receipt, outcome = qualify_durable_read_reauthorized_renewal_health(
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
                "qualified": "EVIDENCE_RECOVERY_DRR_REAUTHORIZED_RENEWAL_HEALTH_QUALIFIED",
                "degraded": "EVIDENCE_RECOVERY_DRR_REAUTHORIZED_RENEWAL_HEALTH_DEGRADED",
                "unchanged": "EVIDENCE_RECOVERY_DRR_REAUTHORIZED_RENEWAL_HEALTH_ASSESSMENT_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_DRR_REAUTHORIZED_RENEWAL_HEALTH_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_DRR_REAUTHORIZED_RENEWAL_HEALTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_drr_reauthorized_renewal_health_qualification",
            entity_id=qualification.id,
            new_values={
                **_audit_values(qualification),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        _commit(db, qualification, receipt)
    except (
        RecoveryDurableReadReauthorizedRenewalHealthNotFound,
        RecoveryDurableReadReauthorizedRenewalHealthConflict,
        RecoveryDurableReadReauthorizedRenewalHealthUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase T receipt conflict") from exc
    return _operation(qualification, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-reauthorized-renewal-health-qualifications/{health_qualification_id}/reject",
    response_model=RecoveryDurableReadReauthorizedRenewalHealthQualificationOperationRead,
)
def reject_health_endpoint(
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    payload: RecoveryDurableReadReauthorizedRenewalHealthQualificationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadReauthorizedRenewalHealthQualificationOperationRead:
    try:
        qualification, receipt, outcome = reject_durable_read_reauthorized_renewal_health(
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
                "rejected": "EVIDENCE_RECOVERY_DRR_REAUTHORIZED_RENEWAL_HEALTH_REJECTED",
                "unchanged": "EVIDENCE_RECOVERY_DRR_REAUTHORIZED_RENEWAL_HEALTH_REJECTION_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_DRR_REAUTHORIZED_RENEWAL_HEALTH_EXPIRED",
            }[outcome],
            entity_type="evidence_recovery_drr_reauthorized_renewal_health_qualification",
            entity_id=qualification.id,
            new_values={
                **_audit_values(qualification),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        _commit(db, qualification, receipt)
    except (
        RecoveryDurableReadReauthorizedRenewalHealthNotFound,
        RecoveryDurableReadReauthorizedRenewalHealthConflict,
        RecoveryDurableReadReauthorizedRenewalHealthUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(qualification, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-reauthorized-renewal-health-qualifications/{health_qualification_id}",
    response_model=RecoveryDurableReadReauthorizedRenewalHealthQualificationRead,
)
def get_health_endpoint(
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryDurableReadReauthorizedRenewalHealthQualificationRead:
    try:
        qualification = get_durable_read_reauthorized_renewal_health_qualification(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=health_qualification_id,
        )
    except RecoveryDurableReadReauthorizedRenewalHealthNotFound as exc:
        raise _error(exc) from exc
    return RecoveryDurableReadReauthorizedRenewalHealthQualificationRead.model_validate(
        qualification
    )


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-reauthorized-renewal-health-qualifications/{health_qualification_id}/receipts",
    response_model=list[RecoveryDurableReadReauthorizedRenewalHealthQualificationReceiptRead],
)
def list_health_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RecoveryDurableReadReauthorizedRenewalHealthQualificationReceiptRead]:
    try:
        receipts = list_durable_read_reauthorized_renewal_health_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=health_qualification_id,
        )
    except RecoveryDurableReadReauthorizedRenewalHealthNotFound as exc:
        raise _error(exc) from exc
    return [
        RecoveryDurableReadReauthorizedRenewalHealthQualificationReceiptRead.model_validate(
            item
        )
        for item in receipts
    ]
