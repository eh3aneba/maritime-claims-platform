from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_read_path_cutover_schemas import (
    RecoveryReadPathCutoverAuthorizationOperationRead,
    RecoveryReadPathCutoverAuthorizationRead,
    RecoveryReadPathCutoverAuthorizationReason,
    RecoveryReadPathCutoverAuthorizationReceiptRead,
)
from app.modules.documents.recovery_read_path_cutover_service import (
    RecoveryReadPathCutoverAuthorizationConflict,
    RecoveryReadPathCutoverAuthorizationNotFound,
    RecoveryReadPathCutoverAuthorizationUnavailable,
    approve_recovery_read_path_cutover_authorization,
    get_recovery_read_path_cutover_authorization,
    list_recovery_read_path_cutover_authorization_receipts,
    reject_recovery_read_path_cutover_authorization,
    request_recovery_read_path_cutover_authorization,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-read-path-cutover-authorization"])


def _audit_values(authorization) -> dict:
    return {
        "claim_id": str(authorization.claim_id),
        "document_id": str(authorization.document_id),
        "execution_lease_id": str(authorization.execution_lease_id),
        "execution_activation_receipt_id": str(authorization.execution_activation_receipt_id),
        "execution_rollback_receipt_id": str(authorization.execution_rollback_receipt_id),
        "cutover_admission_id": str(authorization.cutover_admission_id),
        "admission_approval_receipt_id": str(authorization.admission_approval_receipt_id),
        "authority_switch_rehearsal_id": str(authorization.authority_switch_rehearsal_id),
        "shadow_promotion_id": str(authorization.shadow_promotion_id),
        "attestation_id": str(authorization.attestation_id),
        "replica_id": str(authorization.replica_id),
        "restore_rehearsal_id": str(authorization.restore_rehearsal_id),
        "restore_verification_id": str(authorization.restore_verification_id),
        "shadow_verification_id": str(authorization.shadow_verification_id),
        "lease_hash": authorization.lease_hash,
        "execution_snapshot_hash": authorization.execution_snapshot_hash,
        "execution_activation_receipt_hash": authorization.execution_activation_receipt_hash,
        "execution_rollback_receipt_hash": authorization.execution_rollback_receipt_hash,
        "execution_transition_proof_hash": authorization.execution_transition_proof_hash,
        "admission_hash": authorization.admission_hash,
        "admission_approval_receipt_hash": authorization.admission_approval_receipt_hash,
        "rehearsal_contract_hash": authorization.rehearsal_contract_hash,
        "rehearsal_lineage_hash": authorization.rehearsal_lineage_hash,
        "source_authority_fingerprint": authorization.source_authority_fingerprint,
        "candidate_authority_fingerprint": authorization.candidate_authority_fingerprint,
        "configuration_fingerprint": authorization.configuration_fingerprint,
        "request_snapshot_hash": authorization.request_snapshot_hash,
        "authorization_hash": authorization.authorization_hash,
        "status": authorization.status,
        "routable_authority_created": False,
        "read_path_switched": False,
        "document_storage_key_mutated": False,
        "active_backend_changed": False,
        "authoritative_storage_changed": False,
        "destructive_action_performed": False,
        "s3_delete_performed": False,
        "local_delete_performed": False,
    }


def _operation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryReadPathCutoverAuthorizationNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryReadPathCutoverAuthorizationConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, RecoveryReadPathCutoverAuthorizationUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Recovery read-path cutover authorization conflict",
    )


def _operation_read(authorization, receipt, outcome: str) -> RecoveryReadPathCutoverAuthorizationOperationRead:
    return RecoveryReadPathCutoverAuthorizationOperationRead(
        authorization=RecoveryReadPathCutoverAuthorizationRead.model_validate(authorization),
        receipt=(
            RecoveryReadPathCutoverAuthorizationReceiptRead.model_validate(receipt)
            if receipt is not None
            else None
        ),
        outcome=outcome,
    )


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-cutover-execution-leases/{execution_lease_id}/read-path-cutover-authorization",
    response_model=RecoveryReadPathCutoverAuthorizationOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_read_path_cutover_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    execution_lease_id: UUID,
    payload: RecoveryReadPathCutoverAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryReadPathCutoverAuthorizationOperationRead:
    try:
        authorization, receipt, outcome = request_recovery_read_path_cutover_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            execution_lease_id=execution_lease_id,
            requested_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "requested": "EVIDENCE_RECOVERY_READ_PATH_CUTOVER_AUTH_REQUESTED",
                "unchanged": "EVIDENCE_RECOVERY_READ_PATH_CUTOVER_AUTH_REQUEST_REPLAYED",
                "invalidated": "EVIDENCE_RECOVERY_READ_PATH_CUTOVER_AUTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_read_path_cutover_authorization",
            entity_id=authorization.id,
            new_values={
                **_audit_values(authorization),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        db.commit()
        db.refresh(authorization)
        if receipt is not None:
            db.refresh(receipt)
    except (
        RecoveryReadPathCutoverAuthorizationNotFound,
        RecoveryReadPathCutoverAuthorizationConflict,
        RecoveryReadPathCutoverAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _operation_error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Read-path cutover authorization conflicts with immutable lineage",
        ) from exc
    return _operation_read(authorization, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-read-path-cutover-authorizations/{authorization_id}",
    response_model=RecoveryReadPathCutoverAuthorizationRead,
)
def get_read_path_cutover_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryReadPathCutoverAuthorizationRead:
    try:
        authorization = get_recovery_read_path_cutover_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryReadPathCutoverAuthorizationNotFound as exc:
        raise _operation_error(exc) from exc
    return RecoveryReadPathCutoverAuthorizationRead.model_validate(authorization)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-read-path-cutover-authorizations/{authorization_id}/approve",
    response_model=RecoveryReadPathCutoverAuthorizationOperationRead,
)
def approve_read_path_cutover_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryReadPathCutoverAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryReadPathCutoverAuthorizationOperationRead:
    try:
        authorization, receipt, outcome = approve_recovery_read_path_cutover_authorization(
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
                "approved": "EVIDENCE_RECOVERY_READ_PATH_CUTOVER_AUTH_APPROVED",
                "unchanged": "EVIDENCE_RECOVERY_READ_PATH_CUTOVER_AUTH_APPROVAL_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_READ_PATH_CUTOVER_AUTH_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_READ_PATH_CUTOVER_AUTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_read_path_cutover_authorization",
            entity_id=authorization.id,
            new_values={
                **_audit_values(authorization),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        db.commit()
        db.refresh(authorization)
        if receipt is not None:
            db.refresh(receipt)
    except (
        RecoveryReadPathCutoverAuthorizationNotFound,
        RecoveryReadPathCutoverAuthorizationConflict,
        RecoveryReadPathCutoverAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _operation_error(exc) from exc
    return _operation_read(authorization, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-read-path-cutover-authorizations/{authorization_id}/reject",
    response_model=RecoveryReadPathCutoverAuthorizationOperationRead,
)
def reject_read_path_cutover_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryReadPathCutoverAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryReadPathCutoverAuthorizationOperationRead:
    try:
        authorization, receipt, outcome = reject_recovery_read_path_cutover_authorization(
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
                "rejected": "EVIDENCE_RECOVERY_READ_PATH_CUTOVER_AUTH_REJECTED",
                "unchanged": "EVIDENCE_RECOVERY_READ_PATH_CUTOVER_AUTH_REJECTION_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_read_path_cutover_authorization",
            entity_id=authorization.id,
            new_values={
                **_audit_values(authorization),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        db.commit()
        db.refresh(authorization)
        if receipt is not None:
            db.refresh(receipt)
    except (
        RecoveryReadPathCutoverAuthorizationNotFound,
        RecoveryReadPathCutoverAuthorizationConflict,
        RecoveryReadPathCutoverAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _operation_error(exc) from exc
    return _operation_read(authorization, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-read-path-cutover-authorizations/{authorization_id}/receipts",
    response_model=list[RecoveryReadPathCutoverAuthorizationReceiptRead],
)
def list_read_path_cutover_authorization_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RecoveryReadPathCutoverAuthorizationReceiptRead]:
    try:
        receipts = list_recovery_read_path_cutover_authorization_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryReadPathCutoverAuthorizationNotFound as exc:
        raise _operation_error(exc) from exc
    return [
        RecoveryReadPathCutoverAuthorizationReceiptRead.model_validate(item)
        for item in receipts
    ]
