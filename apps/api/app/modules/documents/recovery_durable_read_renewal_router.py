from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_durable_read_renewal_approval_service import (
    approve_durable_read_renewal_authorization,
)
from app.modules.documents.recovery_durable_read_renewal_schemas import (
    RecoveryDurableReadRenewalAuthorizationOperationRead,
    RecoveryDurableReadRenewalAuthorizationRead,
    RecoveryDurableReadRenewalAuthorizationReason,
    RecoveryDurableReadRenewalAuthorizationReceiptRead,
)
from app.modules.documents.recovery_durable_read_renewal_service import (
    RecoveryDurableReadRenewalAuthorizationConflict,
    RecoveryDurableReadRenewalAuthorizationNotFound,
    RecoveryDurableReadRenewalAuthorizationUnavailable,
    get_durable_read_renewal_authorization,
    list_durable_read_renewal_authorization_receipts,
    reject_durable_read_renewal_authorization,
    request_durable_read_renewal_authorization,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-durable-read-renewal"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryDurableReadRenewalAuthorizationNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryDurableReadRenewalAuthorizationUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(authorization) -> dict:
    return {
        "claim_id": str(authorization.claim_id),
        "document_id": str(authorization.document_id),
        "health_qualification_id": str(authorization.health_qualification_id),
        "health_qualification_receipt_id": str(authorization.health_qualification_receipt_id),
        "durable_lease_id": str(authorization.durable_lease_id),
        "activation_receipt_id": str(authorization.activation_receipt_id),
        "terminal_receipt_id": str(authorization.terminal_receipt_id),
        "prior_authorization_id": str(authorization.prior_authorization_id),
        "phase_k_qualification_id": str(authorization.phase_k_qualification_id),
        "replica_id": str(authorization.replica_id),
        "health_qualification_hash": authorization.health_qualification_hash,
        "health_request_snapshot_hash": authorization.health_request_snapshot_hash,
        "health_qualification_receipt_hash": authorization.health_qualification_receipt_hash,
        "operational_evidence_hash": authorization.operational_evidence_hash,
        "health_state": authorization.health_state,
        "durable_lease_hash": authorization.durable_lease_hash,
        "lease_snapshot_hash": authorization.lease_snapshot_hash,
        "activation_receipt_hash": authorization.activation_receipt_hash,
        "terminal_receipt_hash": authorization.terminal_receipt_hash,
        "prior_authorization_hash": authorization.prior_authorization_hash,
        "phase_k_qualification_hash": authorization.phase_k_qualification_hash,
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
        "route_version_at_request": authorization.route_version_at_request,
        "integrity_proof_hash": authorization.integrity_proof_hash,
        "request_snapshot_hash": authorization.request_snapshot_hash,
        "authorization_hash": authorization.authorization_hash,
        "status": authorization.status,
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
    return RecoveryDurableReadRenewalAuthorizationOperationRead(
        authorization=RecoveryDurableReadRenewalAuthorizationRead.model_validate(
            authorization
        ),
        receipt=(
            RecoveryDurableReadRenewalAuthorizationReceiptRead.model_validate(receipt)
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
    "/{claim_id}/documents/{document_id}/recovery-durable-read-health-qualifications/{health_qualification_id}/renewal-authorization",
    response_model=RecoveryDurableReadRenewalAuthorizationOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_durable_read_renewal_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    payload: RecoveryDurableReadRenewalAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadRenewalAuthorizationOperationRead:
    try:
        authorization, receipt, outcome = request_durable_read_renewal_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=health_qualification_id,
            requested_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "pending_second_approval": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_AUTH_REQUESTED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_AUTH_REQUEST_REPLAYED",
                "invalidated": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_AUTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_durable_read_renewal_authorization",
            entity_id=authorization.id,
            new_values={
                **_audit_values(authorization),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        _commit(db, authorization, receipt)
    except (
        RecoveryDurableReadRenewalAuthorizationNotFound,
        RecoveryDurableReadRenewalAuthorizationConflict,
        RecoveryDurableReadRenewalAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Durable read renewal authorization conflicts with immutable lineage",
        ) from exc
    return _operation(authorization, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-renewal-authorizations/{authorization_id}/approve",
    response_model=RecoveryDurableReadRenewalAuthorizationOperationRead,
)
def approve_durable_read_renewal_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryDurableReadRenewalAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadRenewalAuthorizationOperationRead:
    try:
        authorization, receipt, outcome = approve_durable_read_renewal_authorization(
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
                "approved": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_AUTH_APPROVED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_AUTH_APPROVAL_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_AUTH_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_AUTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_durable_read_renewal_authorization",
            entity_id=authorization.id,
            new_values={
                **_audit_values(authorization),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        _commit(db, authorization, receipt)
    except (
        RecoveryDurableReadRenewalAuthorizationNotFound,
        RecoveryDurableReadRenewalAuthorizationConflict,
        RecoveryDurableReadRenewalAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Renewal authorization receipt conflict") from exc
    return _operation(authorization, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-renewal-authorizations/{authorization_id}/reject",
    response_model=RecoveryDurableReadRenewalAuthorizationOperationRead,
)
def reject_durable_read_renewal_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryDurableReadRenewalAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadRenewalAuthorizationOperationRead:
    try:
        authorization, receipt, outcome = reject_durable_read_renewal_authorization(
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
                "rejected": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_AUTH_REJECTED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_AUTH_REJECTION_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_durable_read_renewal_authorization",
            entity_id=authorization.id,
            new_values={
                **_audit_values(authorization),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        _commit(db, authorization, receipt)
    except (
        RecoveryDurableReadRenewalAuthorizationNotFound,
        RecoveryDurableReadRenewalAuthorizationConflict,
        RecoveryDurableReadRenewalAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(authorization, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-renewal-authorizations/{authorization_id}",
    response_model=RecoveryDurableReadRenewalAuthorizationRead,
)
def get_durable_read_renewal_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryDurableReadRenewalAuthorizationRead:
    try:
        authorization = get_durable_read_renewal_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryDurableReadRenewalAuthorizationNotFound as exc:
        raise _error(exc) from exc
    return RecoveryDurableReadRenewalAuthorizationRead.model_validate(authorization)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-renewal-authorizations/{authorization_id}/receipts",
    response_model=list[RecoveryDurableReadRenewalAuthorizationReceiptRead],
)
def list_durable_read_renewal_authorization_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RecoveryDurableReadRenewalAuthorizationReceiptRead]:
    try:
        receipts = list_durable_read_renewal_authorization_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryDurableReadRenewalAuthorizationNotFound as exc:
        raise _error(exc) from exc
    return [
        RecoveryDurableReadRenewalAuthorizationReceiptRead.model_validate(item)
        for item in receipts
    ]
