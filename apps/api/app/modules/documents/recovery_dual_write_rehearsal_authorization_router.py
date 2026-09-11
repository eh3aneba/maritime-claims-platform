from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_dual_write_rehearsal_authorization_schemas import (
    RecoveryDualWriteRehearsalAuthorizationOperationRead,
    RecoveryDualWriteRehearsalAuthorizationRead,
    RecoveryDualWriteRehearsalAuthorizationReason,
    RecoveryDualWriteRehearsalAuthorizationReceiptRead,
)
from app.modules.documents.recovery_dual_write_rehearsal_authorization_service import (
    RecoveryDualWriteRehearsalAuthorizationConflict,
    RecoveryDualWriteRehearsalAuthorizationNotFound,
    RecoveryDualWriteRehearsalAuthorizationUnavailable,
    approve_dual_write_rehearsal_authorization,
    get_dual_write_rehearsal_authorization,
    list_dual_write_rehearsal_authorization_receipts,
    reject_dual_write_rehearsal_authorization,
    request_dual_write_rehearsal_authorization,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-dual-write-rehearsal-authorization"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryDualWriteRehearsalAuthorizationNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryDualWriteRehearsalAuthorizationUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(authorization) -> dict:
    return {
        "claim_id": str(authorization.claim_id),
        "document_id": str(authorization.document_id),
        "phase_w_health_qualification_id": str(authorization.phase_w_health_qualification_id),
        "phase_w_health_receipt_id": str(authorization.phase_w_health_receipt_id),
        "phase_v_transition_lease_id": str(authorization.phase_v_transition_lease_id),
        "phase_u_authorization_id": str(authorization.phase_u_authorization_id),
        "phase_t_health_qualification_id": str(authorization.phase_t_health_qualification_id),
        "replica_id": str(authorization.replica_id),
        "phase_w_health_qualification_hash": authorization.phase_w_health_qualification_hash,
        "phase_w_health_receipt_hash": authorization.phase_w_health_receipt_hash,
        "operational_evidence_hash": authorization.operational_evidence_hash,
        "health_state": authorization.health_state,
        "source_file_hash": authorization.source_file_hash,
        "source_file_size_bytes": authorization.source_file_size_bytes,
        "route_version_at_request": authorization.route_version_at_request,
        "integrity_proof_hash": authorization.integrity_proof_hash,
        "request_snapshot_hash": authorization.request_snapshot_hash,
        "authorization_hash": authorization.authorization_hash,
        "max_rehearsal_writes": authorization.max_rehearsal_writes,
        "status": authorization.status,
        "review_expires_at": authorization.review_expires_at.isoformat(),
        "authorization_expires_at": authorization.authorization_expires_at.isoformat() if authorization.authorization_expires_at else None,
        "rehearsal_executed": False,
        "dual_write_active": False,
        "durable_write_authority_created": False,
        "read_path_switched": False,
        "write_path_switched": False,
        "document_storage_key_mutated": False,
        "authoritative_storage_changed": False,
        "destructive_action_performed": False,
        "s3_copy_performed": False,
        "s3_delete_performed": False,
        "local_delete_performed": False,
    }


def _operation(authorization, receipt, outcome: str):
    return RecoveryDualWriteRehearsalAuthorizationOperationRead(
        authorization=RecoveryDualWriteRehearsalAuthorizationRead.model_validate(authorization),
        receipt=RecoveryDualWriteRehearsalAuthorizationReceiptRead.model_validate(receipt) if receipt else None,
        outcome=outcome,
    )


def _commit(db: Session, authorization, receipt) -> None:
    db.commit()
    db.refresh(authorization)
    if receipt is not None:
        db.refresh(receipt)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-read-ownership-transition-health-qualifications/{phase_w_health_qualification_id}/dual-write-rehearsal-authorization",
    response_model=RecoveryDualWriteRehearsalAuthorizationOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_dual_write_rehearsal_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    phase_w_health_qualification_id: UUID,
    payload: RecoveryDualWriteRehearsalAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        authorization, receipt, outcome = request_dual_write_rehearsal_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            phase_w_health_qualification_id=phase_w_health_qualification_id,
            requested_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "pending_second_approval": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_AUTH_REQUESTED",
                "unchanged": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_AUTH_REQUEST_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_AUTH_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_AUTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_dual_write_rehearsal_authorization",
            entity_id=authorization.id,
            new_values={**_audit_values(authorization), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, authorization, receipt)
    except (RecoveryDualWriteRehearsalAuthorizationNotFound, RecoveryDualWriteRehearsalAuthorizationConflict, RecoveryDualWriteRehearsalAuthorizationUnavailable) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase X authorization conflicts with immutable lineage") from exc
    return _operation(authorization, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-dual-write-rehearsal-authorizations/{authorization_id}/approve",
    response_model=RecoveryDualWriteRehearsalAuthorizationOperationRead,
)
def approve_dual_write_rehearsal_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryDualWriteRehearsalAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        authorization, receipt, outcome = approve_dual_write_rehearsal_authorization(
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
                "approved": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_AUTH_APPROVED",
                "unchanged": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_AUTH_APPROVAL_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_AUTH_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_AUTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_dual_write_rehearsal_authorization",
            entity_id=authorization.id,
            new_values={**_audit_values(authorization), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, authorization, receipt)
    except (RecoveryDualWriteRehearsalAuthorizationNotFound, RecoveryDualWriteRehearsalAuthorizationConflict, RecoveryDualWriteRehearsalAuthorizationUnavailable) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase X approval receipt conflict") from exc
    return _operation(authorization, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-dual-write-rehearsal-authorizations/{authorization_id}/reject",
    response_model=RecoveryDualWriteRehearsalAuthorizationOperationRead,
)
def reject_dual_write_rehearsal_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryDualWriteRehearsalAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        authorization, receipt, outcome = reject_dual_write_rehearsal_authorization(
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
                "rejected": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_AUTH_REJECTED",
                "unchanged": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_AUTH_REJECTION_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_DUAL_WRITE_REHEARSAL_AUTH_EXPIRED",
            }[outcome],
            entity_type="evidence_recovery_dual_write_rehearsal_authorization",
            entity_id=authorization.id,
            new_values={**_audit_values(authorization), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, authorization, receipt)
    except (RecoveryDualWriteRehearsalAuthorizationNotFound, RecoveryDualWriteRehearsalAuthorizationConflict, RecoveryDualWriteRehearsalAuthorizationUnavailable) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(authorization, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-dual-write-rehearsal-authorizations/{authorization_id}",
    response_model=RecoveryDualWriteRehearsalAuthorizationRead,
)
def get_dual_write_rehearsal_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        authorization = get_dual_write_rehearsal_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryDualWriteRehearsalAuthorizationNotFound as exc:
        raise _error(exc) from exc
    return RecoveryDualWriteRehearsalAuthorizationRead.model_validate(authorization)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-dual-write-rehearsal-authorizations/{authorization_id}/receipts",
    response_model=list[RecoveryDualWriteRehearsalAuthorizationReceiptRead],
)
def list_dual_write_rehearsal_authorization_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        receipts = list_dual_write_rehearsal_authorization_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryDualWriteRehearsalAuthorizationNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryDualWriteRehearsalAuthorizationReceiptRead.model_validate(item) for item in receipts]
