from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_read_ownership_transition_authorization_schemas import (
    RecoveryReadOwnershipTransitionAuthorizationOperationRead,
    RecoveryReadOwnershipTransitionAuthorizationRead,
    RecoveryReadOwnershipTransitionAuthorizationReason,
    RecoveryReadOwnershipTransitionAuthorizationReceiptRead,
)
from app.modules.documents.recovery_read_ownership_transition_authorization_service import (
    RecoveryReadOwnershipTransitionAuthorizationConflict,
    RecoveryReadOwnershipTransitionAuthorizationNotFound,
    RecoveryReadOwnershipTransitionAuthorizationUnavailable,
    approve_read_ownership_transition_authorization,
    get_read_ownership_transition_authorization,
    list_read_ownership_transition_authorization_receipts,
    reject_read_ownership_transition_authorization,
    request_read_ownership_transition_authorization,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-read-ownership-transition-authorization"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryReadOwnershipTransitionAuthorizationNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryReadOwnershipTransitionAuthorizationUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(authorization) -> dict:
    return {
        "claim_id": str(authorization.claim_id),
        "document_id": str(authorization.document_id),
        "phase_t_health_qualification_id": str(authorization.phase_t_health_qualification_id),
        "phase_t_health_receipt_id": str(authorization.phase_t_health_receipt_id),
        "reauthorized_renewal_lease_id": str(authorization.reauthorized_renewal_lease_id),
        "activation_receipt_id": str(authorization.activation_receipt_id),
        "terminal_receipt_id": str(authorization.terminal_receipt_id),
        "reauthorization_id": str(authorization.reauthorization_id),
        "phase_q_health_qualification_id": str(authorization.phase_q_health_qualification_id),
        "prior_renewal_lease_id": str(authorization.prior_renewal_lease_id),
        "replica_id": str(authorization.replica_id),
        "phase_t_health_qualification_hash": authorization.phase_t_health_qualification_hash,
        "phase_t_request_snapshot_hash": authorization.phase_t_request_snapshot_hash,
        "phase_t_health_receipt_hash": authorization.phase_t_health_receipt_hash,
        "operational_evidence_hash": authorization.operational_evidence_hash,
        "health_state": authorization.health_state,
        "reauthorized_renewal_lease_hash": authorization.reauthorized_renewal_lease_hash,
        "lease_snapshot_hash": authorization.lease_snapshot_hash,
        "activation_receipt_hash": authorization.activation_receipt_hash,
        "terminal_receipt_hash": authorization.terminal_receipt_hash,
        "reauthorization_hash": authorization.reauthorization_hash,
        "phase_q_health_qualification_hash": authorization.phase_q_health_qualification_hash,
        "prior_renewal_lease_hash": authorization.prior_renewal_lease_hash,
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
    return RecoveryReadOwnershipTransitionAuthorizationOperationRead(
        authorization=RecoveryReadOwnershipTransitionAuthorizationRead.model_validate(authorization),
        receipt=(
            RecoveryReadOwnershipTransitionAuthorizationReceiptRead.model_validate(receipt)
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
    "/{claim_id}/documents/{document_id}/recovery-durable-read-reauthorized-renewal-health-qualifications/{phase_t_health_qualification_id}/read-ownership-transition-authorization",
    response_model=RecoveryReadOwnershipTransitionAuthorizationOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_read_ownership_transition_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    phase_t_health_qualification_id: UUID,
    payload: RecoveryReadOwnershipTransitionAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryReadOwnershipTransitionAuthorizationOperationRead:
    try:
        authorization, receipt, outcome = request_read_ownership_transition_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            phase_t_health_qualification_id=phase_t_health_qualification_id,
            requested_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "pending_second_approval": "EVIDENCE_RECOVERY_READ_OWNERSHIP_AUTH_REQUESTED",
                "unchanged": "EVIDENCE_RECOVERY_READ_OWNERSHIP_AUTH_REQUEST_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_READ_OWNERSHIP_AUTH_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_READ_OWNERSHIP_AUTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_read_ownership_transition_authorization",
            entity_id=authorization.id,
            new_values={**_audit_values(authorization), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, authorization, receipt)
    except (
        RecoveryReadOwnershipTransitionAuthorizationNotFound,
        RecoveryReadOwnershipTransitionAuthorizationConflict,
        RecoveryReadOwnershipTransitionAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase U authorization conflicts with immutable lineage") from exc
    return _operation(authorization, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-read-ownership-transition-authorizations/{authorization_id}/approve",
    response_model=RecoveryReadOwnershipTransitionAuthorizationOperationRead,
)
def approve_read_ownership_transition_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryReadOwnershipTransitionAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryReadOwnershipTransitionAuthorizationOperationRead:
    try:
        authorization, receipt, outcome = approve_read_ownership_transition_authorization(
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
                "approved": "EVIDENCE_RECOVERY_READ_OWNERSHIP_AUTH_APPROVED",
                "unchanged": "EVIDENCE_RECOVERY_READ_OWNERSHIP_AUTH_APPROVAL_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_READ_OWNERSHIP_AUTH_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_READ_OWNERSHIP_AUTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_read_ownership_transition_authorization",
            entity_id=authorization.id,
            new_values={**_audit_values(authorization), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, authorization, receipt)
    except (
        RecoveryReadOwnershipTransitionAuthorizationNotFound,
        RecoveryReadOwnershipTransitionAuthorizationConflict,
        RecoveryReadOwnershipTransitionAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase U approval receipt conflict") from exc
    return _operation(authorization, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-read-ownership-transition-authorizations/{authorization_id}/reject",
    response_model=RecoveryReadOwnershipTransitionAuthorizationOperationRead,
)
def reject_read_ownership_transition_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryReadOwnershipTransitionAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryReadOwnershipTransitionAuthorizationOperationRead:
    try:
        authorization, receipt, outcome = reject_read_ownership_transition_authorization(
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
                "rejected": "EVIDENCE_RECOVERY_READ_OWNERSHIP_AUTH_REJECTED",
                "unchanged": "EVIDENCE_RECOVERY_READ_OWNERSHIP_AUTH_REJECTION_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_READ_OWNERSHIP_AUTH_EXPIRED",
            }[outcome],
            entity_type="evidence_recovery_read_ownership_transition_authorization",
            entity_id=authorization.id,
            new_values={**_audit_values(authorization), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, authorization, receipt)
    except (
        RecoveryReadOwnershipTransitionAuthorizationNotFound,
        RecoveryReadOwnershipTransitionAuthorizationConflict,
        RecoveryReadOwnershipTransitionAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(authorization, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-read-ownership-transition-authorizations/{authorization_id}",
    response_model=RecoveryReadOwnershipTransitionAuthorizationRead,
)
def get_read_ownership_transition_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryReadOwnershipTransitionAuthorizationRead:
    try:
        authorization = get_read_ownership_transition_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryReadOwnershipTransitionAuthorizationNotFound as exc:
        raise _error(exc) from exc
    return RecoveryReadOwnershipTransitionAuthorizationRead.model_validate(authorization)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-read-ownership-transition-authorizations/{authorization_id}/receipts",
    response_model=list[RecoveryReadOwnershipTransitionAuthorizationReceiptRead],
)
def list_read_ownership_transition_authorization_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RecoveryReadOwnershipTransitionAuthorizationReceiptRead]:
    try:
        receipts = list_read_ownership_transition_authorization_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryReadOwnershipTransitionAuthorizationNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryReadOwnershipTransitionAuthorizationReceiptRead.model_validate(item) for item in receipts]
