from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_read_ownership_transition_health_schemas import (
    RecoveryReadOwnershipTransitionHealthOperationRead,
    RecoveryReadOwnershipTransitionHealthQualificationRead,
    RecoveryReadOwnershipTransitionHealthQualificationReason,
    RecoveryReadOwnershipTransitionHealthQualificationRequest,
    RecoveryReadOwnershipTransitionHealthReceiptRead,
)
from app.modules.documents.recovery_read_ownership_transition_health_service import (
    RecoveryReadOwnershipTransitionHealthConflict,
    RecoveryReadOwnershipTransitionHealthNotFound,
    RecoveryReadOwnershipTransitionHealthUnavailable,
    get_recovery_read_ownership_transition_health_qualification,
    list_recovery_read_ownership_transition_health_receipts,
    qualify_recovery_read_ownership_transition_health,
    reject_recovery_read_ownership_transition_health,
    request_recovery_read_ownership_transition_health_qualification,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-read-ownership-transition-health"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryReadOwnershipTransitionHealthNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryReadOwnershipTransitionHealthUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(q) -> dict:
    return {
        "claim_id": str(q.claim_id),
        "document_id": str(q.document_id),
        "transition_lease_id": str(q.transition_lease_id),
        "activation_receipt_id": str(q.activation_receipt_id),
        "terminal_receipt_id": str(q.terminal_receipt_id),
        "authorization_id": str(q.authorization_id),
        "phase_t_health_qualification_id": str(q.phase_t_health_qualification_id),
        "replica_id": str(q.replica_id),
        "transition_lease_hash": q.transition_lease_hash,
        "activation_receipt_hash": q.activation_receipt_hash,
        "terminal_receipt_hash": q.terminal_receipt_hash,
        "authorization_hash": q.authorization_hash,
        "phase_t_health_qualification_hash": q.phase_t_health_qualification_hash,
        "replica_hash": q.replica_hash,
        "source_file_hash": q.source_file_hash,
        "source_file_size_bytes": q.source_file_size_bytes,
        "local_storage_key_fingerprint": q.local_storage_key_fingerprint,
        "recovery_bucket_fingerprint": q.recovery_bucket_fingerprint,
        "candidate_storage_key_fingerprint": q.candidate_storage_key_fingerprint,
        "source_authority_fingerprint": q.source_authority_fingerprint,
        "candidate_authority_fingerprint": q.candidate_authority_fingerprint,
        "configuration_fingerprint": q.configuration_fingerprint,
        "terminal_phase": q.terminal_phase,
        "verified_read_count": q.verified_read_count,
        "integrity_failure_count": q.integrity_failure_count,
        "storage_unavailable_count": q.storage_unavailable_count,
        "route_expired_attempt_count": q.route_expired_attempt_count,
        "operational_event_count": q.operational_event_count,
        "health_state": q.health_state,
        "operational_evidence_hash": q.operational_evidence_hash,
        "route_version_at_request": q.route_version_at_request,
        "request_snapshot_hash": q.request_snapshot_hash,
        "health_qualification_hash": q.health_qualification_hash,
        "review_expires_at": q.review_expires_at.isoformat(),
        "status": q.status,
        "routable_authority_created": False,
        "durable_read_route_created": False,
        "read_ownership_authority_created": False,
        "read_path_switched": False,
        "write_path_switched": False,
        "document_storage_key_mutated": False,
        "authoritative_storage_changed": False,
        "destructive_action_performed": False,
        "s3_delete_performed": False,
        "local_delete_performed": False,
    }


def _operation(q, receipt, outcome: str) -> RecoveryReadOwnershipTransitionHealthOperationRead:
    return RecoveryReadOwnershipTransitionHealthOperationRead(
        qualification=RecoveryReadOwnershipTransitionHealthQualificationRead.model_validate(q),
        receipt=RecoveryReadOwnershipTransitionHealthReceiptRead.model_validate(receipt) if receipt else None,
        outcome=outcome,
    )


def _commit(db: Session, q, receipt) -> None:
    db.commit(); db.refresh(q)
    if receipt is not None: db.refresh(receipt)


@router.post("/{claim_id}/documents/{document_id}/recovery-read-ownership-transition-health-qualification", response_model=RecoveryReadOwnershipTransitionHealthOperationRead, status_code=status.HTTP_201_CREATED)
def request_health_endpoint(claim_id: UUID, document_id: UUID, payload: RecoveryReadOwnershipTransitionHealthQualificationRequest, db: Annotated[Session, Depends(get_db)], current_user: RetentionAdminMfa):
    try:
        q, receipt, outcome = request_recovery_read_ownership_transition_health_qualification(db, organization_id=current_user.organization_id, claim_id=claim_id, document_id=document_id, transition_lease_id=payload.transition_lease_id, requested_by_id=current_user.id, reason=payload.reason)
        write_audit_log(db, organization_id=current_user.organization_id, user_id=current_user.id, action={"pending_second_approval":"EVIDENCE_RECOVERY_READ_OWNERSHIP_HEALTH_REQUESTED","unchanged":"EVIDENCE_RECOVERY_READ_OWNERSHIP_HEALTH_REQUEST_REPLAYED"}[outcome], entity_type="evidence_recovery_read_ownership_transition_health_qualification", entity_id=q.id, new_values={**_audit_values(q), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome})
        _commit(db, q, receipt)
    except (RecoveryReadOwnershipTransitionHealthNotFound, RecoveryReadOwnershipTransitionHealthConflict, RecoveryReadOwnershipTransitionHealthUnavailable) as exc:
        db.rollback(); raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(status_code=409, detail="Phase W health qualification conflicts with immutable lineage") from exc
    return _operation(q, receipt, outcome)


@router.post("/{claim_id}/documents/{document_id}/recovery-read-ownership-transition-health-qualifications/{health_qualification_id}/qualify", response_model=RecoveryReadOwnershipTransitionHealthOperationRead)
def qualify_health_endpoint(claim_id: UUID, document_id: UUID, health_qualification_id: UUID, payload: RecoveryReadOwnershipTransitionHealthQualificationReason, db: Annotated[Session, Depends(get_db)], current_user: RetentionAdminMfa):
    try:
        q, receipt, outcome = qualify_recovery_read_ownership_transition_health(db, organization_id=current_user.organization_id, claim_id=claim_id, document_id=document_id, health_qualification_id=health_qualification_id, qualified_by_id=current_user.id, reason=payload.reason)
        write_audit_log(db, organization_id=current_user.organization_id, user_id=current_user.id, action={"qualified":"EVIDENCE_RECOVERY_READ_OWNERSHIP_HEALTH_QUALIFIED","degraded":"EVIDENCE_RECOVERY_READ_OWNERSHIP_HEALTH_DEGRADED","unchanged":"EVIDENCE_RECOVERY_READ_OWNERSHIP_HEALTH_ASSESSMENT_REPLAYED","expired":"EVIDENCE_RECOVERY_READ_OWNERSHIP_HEALTH_EXPIRED","invalidated":"EVIDENCE_RECOVERY_READ_OWNERSHIP_HEALTH_INVALIDATED"}[outcome], entity_type="evidence_recovery_read_ownership_transition_health_qualification", entity_id=q.id, new_values={**_audit_values(q), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome})
        _commit(db, q, receipt)
    except (RecoveryReadOwnershipTransitionHealthNotFound, RecoveryReadOwnershipTransitionHealthConflict, RecoveryReadOwnershipTransitionHealthUnavailable) as exc:
        db.rollback(); raise _error(exc) from exc
    return _operation(q, receipt, outcome)


@router.post("/{claim_id}/documents/{document_id}/recovery-read-ownership-transition-health-qualifications/{health_qualification_id}/reject", response_model=RecoveryReadOwnershipTransitionHealthOperationRead)
def reject_health_endpoint(claim_id: UUID, document_id: UUID, health_qualification_id: UUID, payload: RecoveryReadOwnershipTransitionHealthQualificationReason, db: Annotated[Session, Depends(get_db)], current_user: RetentionAdminMfa):
    try:
        q, receipt, outcome = reject_recovery_read_ownership_transition_health(db, organization_id=current_user.organization_id, claim_id=claim_id, document_id=document_id, health_qualification_id=health_qualification_id, rejected_by_id=current_user.id, reason=payload.reason)
        write_audit_log(db, organization_id=current_user.organization_id, user_id=current_user.id, action={"rejected":"EVIDENCE_RECOVERY_READ_OWNERSHIP_HEALTH_REJECTED","unchanged":"EVIDENCE_RECOVERY_READ_OWNERSHIP_HEALTH_REJECTION_REPLAYED","expired":"EVIDENCE_RECOVERY_READ_OWNERSHIP_HEALTH_EXPIRED"}[outcome], entity_type="evidence_recovery_read_ownership_transition_health_qualification", entity_id=q.id, new_values={**_audit_values(q), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome})
        _commit(db, q, receipt)
    except (RecoveryReadOwnershipTransitionHealthNotFound, RecoveryReadOwnershipTransitionHealthConflict, RecoveryReadOwnershipTransitionHealthUnavailable) as exc:
        db.rollback(); raise _error(exc) from exc
    return _operation(q, receipt, outcome)


@router.get("/{claim_id}/documents/{document_id}/recovery-read-ownership-transition-health-qualifications/{health_qualification_id}", response_model=RecoveryReadOwnershipTransitionHealthQualificationRead)
def get_health_endpoint(claim_id: UUID, document_id: UUID, health_qualification_id: UUID, db: Annotated[Session, Depends(get_db)], current_user: RetentionReader):
    try:
        q = get_recovery_read_ownership_transition_health_qualification(db, organization_id=current_user.organization_id, claim_id=claim_id, document_id=document_id, health_qualification_id=health_qualification_id)
    except RecoveryReadOwnershipTransitionHealthNotFound as exc:
        raise _error(exc) from exc
    return RecoveryReadOwnershipTransitionHealthQualificationRead.model_validate(q)


@router.get("/{claim_id}/documents/{document_id}/recovery-read-ownership-transition-health-qualifications/{health_qualification_id}/receipts", response_model=list[RecoveryReadOwnershipTransitionHealthReceiptRead])
def list_health_receipts_endpoint(claim_id: UUID, document_id: UUID, health_qualification_id: UUID, db: Annotated[Session, Depends(get_db)], current_user: RetentionReader):
    try:
        receipts = list_recovery_read_ownership_transition_health_receipts(db, organization_id=current_user.organization_id, claim_id=claim_id, document_id=document_id, health_qualification_id=health_qualification_id)
    except RecoveryReadOwnershipTransitionHealthNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryReadOwnershipTransitionHealthReceiptRead.model_validate(item) for item in receipts]
