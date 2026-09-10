from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_durable_read_renewal_reauthorization_schemas import (
    RecoveryDurableReadRenewalReauthorizationOperationRead,
    RecoveryDurableReadRenewalReauthorizationRead,
    RecoveryDurableReadRenewalReauthorizationReason,
    RecoveryDurableReadRenewalReauthorizationReceiptRead,
)
from app.modules.documents.recovery_durable_read_renewal_reauthorization_service import (
    RecoveryDurableReadRenewalReauthorizationConflict,
    RecoveryDurableReadRenewalReauthorizationNotFound,
    RecoveryDurableReadRenewalReauthorizationUnavailable,
    approve_durable_read_renewal_reauthorization,
    get_durable_read_renewal_reauthorization,
    list_durable_read_renewal_reauthorization_receipts,
    reject_durable_read_renewal_reauthorization,
    request_durable_read_renewal_reauthorization,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-durable-read-renewal-reauthorization"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryDurableReadRenewalReauthorizationNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryDurableReadRenewalReauthorizationUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(authorization) -> dict:
    return {
        "claim_id": str(authorization.claim_id),
        "document_id": str(authorization.document_id),
        "phase_q_health_qualification_id": str(authorization.phase_q_health_qualification_id),
        "phase_q_health_receipt_id": str(authorization.phase_q_health_receipt_id),
        "renewal_lease_id": str(authorization.renewal_lease_id),
        "activation_receipt_id": str(authorization.activation_receipt_id),
        "terminal_receipt_id": str(authorization.terminal_receipt_id),
        "prior_renewal_authorization_id": str(authorization.prior_renewal_authorization_id),
        "phase_n_health_qualification_id": str(authorization.phase_n_health_qualification_id),
        "prior_durable_lease_id": str(authorization.prior_durable_lease_id),
        "replica_id": str(authorization.replica_id),
        "phase_q_health_qualification_hash": authorization.phase_q_health_qualification_hash,
        "phase_q_request_snapshot_hash": authorization.phase_q_request_snapshot_hash,
        "phase_q_health_receipt_hash": authorization.phase_q_health_receipt_hash,
        "operational_evidence_hash": authorization.operational_evidence_hash,
        "health_state": authorization.health_state,
        "renewal_lease_hash": authorization.renewal_lease_hash,
        "lease_snapshot_hash": authorization.lease_snapshot_hash,
        "activation_receipt_hash": authorization.activation_receipt_hash,
        "terminal_receipt_hash": authorization.terminal_receipt_hash,
        "prior_renewal_authorization_hash": authorization.prior_renewal_authorization_hash,
        "phase_n_health_qualification_hash": authorization.phase_n_health_qualification_hash,
        "prior_durable_lease_hash": authorization.prior_durable_lease_hash,
        "replica_hash": authorization.replica_hash,
        "source_file_hash": authorization.source_file_hash,
        "source_file_size_bytes": authorization.source_file_size_bytes,
        "local_storage_key_fingerprint": authorization.local_storage_key_fingerprint,
        "recovery_bucket_fingerprint": authorization.recovery_bucket_fingerprint,
        "candidate_storage_key_fingerprint": authorization.candidate_storage_key_fingerprint,
        "source_authority_fingerprint": authorization.source_authority_fingerprint,
        "candidate_authority_fingerprint": authorization.candidate_authority_fingerprint,
        "configuration_fingerprint": authorization.configuration_fingerprint,
        "verified_durable_read_count": authorization.verified_durable_read_count,
        "integrity_failure_count": authorization.integrity_failure_count,
        "storage_unavailable_count": authorization.storage_unavailable_count,
        "route_expired_attempt_count": authorization.route_expired_attempt_count,
        "operational_event_count": authorization.operational_event_count,
        "route_version_at_request": authorization.route_version_at_request,
        "integrity_proof_hash": authorization.integrity_proof_hash,
        "request_snapshot_hash": authorization.request_snapshot_hash,
        "authorization_hash": authorization.authorization_hash,
        "status": authorization.status,
        "review_expires_at": authorization.review_expires_at.isoformat(),
        "authorization_expires_at": (
            authorization.authorization_expires_at.isoformat()
            if authorization.authorization_expires_at is not None
            else None
        ),
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


def _operation(authorization, receipt, outcome: str):
    return RecoveryDurableReadRenewalReauthorizationOperationRead(
        authorization=RecoveryDurableReadRenewalReauthorizationRead.model_validate(authorization),
        receipt=(
            RecoveryDurableReadRenewalReauthorizationReceiptRead.model_validate(receipt)
            if receipt is not None
            else None
        ),
        outcome=outcome,
    )


def _commit(db: Session, authorization, receipt) -> None:
    db.commit()
    db.refresh(authorization)
    if receipt is not None:
        db.refresh(receipt)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-renewal-health-qualifications/{phase_q_health_qualification_id}/renewal-reauthorization",
    response_model=RecoveryDurableReadRenewalReauthorizationOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_durable_read_renewal_reauthorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    phase_q_health_qualification_id: UUID,
    payload: RecoveryDurableReadRenewalReauthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadRenewalReauthorizationOperationRead:
    try:
        authorization, receipt, outcome = request_durable_read_renewal_reauthorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            phase_q_health_qualification_id=phase_q_health_qualification_id,
            requested_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "pending_second_approval": "EVIDENCE_RECOVERY_DRR_REAUTH_REQUESTED",
                "unchanged": "EVIDENCE_RECOVERY_DRR_REAUTH_REQUEST_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_DRR_REAUTH_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_DRR_REAUTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_durable_read_renewal_reauthorization",
            entity_id=authorization.id,
            new_values={**_audit_values(authorization), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, authorization, receipt)
    except (
        RecoveryDurableReadRenewalReauthorizationNotFound,
        RecoveryDurableReadRenewalReauthorizationConflict,
        RecoveryDurableReadRenewalReauthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase R reauthorization conflicts with immutable lineage") from exc
    return _operation(authorization, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-renewal-reauthorizations/{authorization_id}/approve",
    response_model=RecoveryDurableReadRenewalReauthorizationOperationRead,
)
def approve_durable_read_renewal_reauthorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryDurableReadRenewalReauthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadRenewalReauthorizationOperationRead:
    try:
        authorization, receipt, outcome = approve_durable_read_renewal_reauthorization(
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
                "approved": "EVIDENCE_RECOVERY_DRR_REAUTH_APPROVED",
                "unchanged": "EVIDENCE_RECOVERY_DRR_REAUTH_APPROVAL_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_DRR_REAUTH_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_DRR_REAUTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_durable_read_renewal_reauthorization",
            entity_id=authorization.id,
            new_values={**_audit_values(authorization), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, authorization, receipt)
    except (
        RecoveryDurableReadRenewalReauthorizationNotFound,
        RecoveryDurableReadRenewalReauthorizationConflict,
        RecoveryDurableReadRenewalReauthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase R approval receipt conflict") from exc
    return _operation(authorization, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-renewal-reauthorizations/{authorization_id}/reject",
    response_model=RecoveryDurableReadRenewalReauthorizationOperationRead,
)
def reject_durable_read_renewal_reauthorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryDurableReadRenewalReauthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadRenewalReauthorizationOperationRead:
    try:
        authorization, receipt, outcome = reject_durable_read_renewal_reauthorization(
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
                "rejected": "EVIDENCE_RECOVERY_DRR_REAUTH_REJECTED",
                "unchanged": "EVIDENCE_RECOVERY_DRR_REAUTH_REJECTION_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_durable_read_renewal_reauthorization",
            entity_id=authorization.id,
            new_values={**_audit_values(authorization), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, authorization, receipt)
    except (
        RecoveryDurableReadRenewalReauthorizationNotFound,
        RecoveryDurableReadRenewalReauthorizationConflict,
        RecoveryDurableReadRenewalReauthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(authorization, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-renewal-reauthorizations/{authorization_id}",
    response_model=RecoveryDurableReadRenewalReauthorizationRead,
)
def get_durable_read_renewal_reauthorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryDurableReadRenewalReauthorizationRead:
    try:
        authorization = get_durable_read_renewal_reauthorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryDurableReadRenewalReauthorizationNotFound as exc:
        raise _error(exc) from exc
    return RecoveryDurableReadRenewalReauthorizationRead.model_validate(authorization)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-renewal-reauthorizations/{authorization_id}/receipts",
    response_model=list[RecoveryDurableReadRenewalReauthorizationReceiptRead],
)
def list_durable_read_renewal_reauthorization_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RecoveryDurableReadRenewalReauthorizationReceiptRead]:
    try:
        receipts = list_durable_read_renewal_reauthorization_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryDurableReadRenewalReauthorizationNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryDurableReadRenewalReauthorizationReceiptRead.model_validate(item) for item in receipts]
