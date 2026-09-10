from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_durable_read_promotion_approval_service import (
    approve_durable_read_promotion_authorization,
)
from app.modules.documents.recovery_durable_read_promotion_schemas import (
    RecoveryDurableReadPromotionAuthorizationOperationRead,
    RecoveryDurableReadPromotionAuthorizationRead,
    RecoveryDurableReadPromotionAuthorizationReason,
    RecoveryDurableReadPromotionAuthorizationReceiptRead,
)
from app.modules.documents.recovery_durable_read_promotion_service import (
    RecoveryDurableReadPromotionAuthorizationConflict,
    RecoveryDurableReadPromotionAuthorizationNotFound,
    RecoveryDurableReadPromotionAuthorizationUnavailable,
    get_durable_read_promotion_authorization,
    list_durable_read_promotion_authorization_receipts,
    reject_durable_read_promotion_authorization,
    request_durable_read_promotion_authorization,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-durable-read-promotion"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryDurableReadPromotionAuthorizationNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryDurableReadPromotionAuthorizationUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(authorization) -> dict:
    return {
        "claim_id": str(authorization.claim_id),
        "document_id": str(authorization.document_id),
        "qualification_id": str(authorization.qualification_id),
        "qualification_receipt_id": str(authorization.qualification_receipt_id),
        "replica_id": str(authorization.replica_id),
        "qualification_hash": authorization.qualification_hash,
        "qualification_bundle_hash": authorization.qualification_bundle_hash,
        "qualification_request_snapshot_hash": authorization.qualification_request_snapshot_hash,
        "qualification_receipt_hash": authorization.qualification_receipt_hash,
        "replica_hash": authorization.replica_hash,
        "source_file_hash": authorization.source_file_hash,
        "source_file_size_bytes": authorization.source_file_size_bytes,
        "local_storage_key_fingerprint": authorization.local_storage_key_fingerprint,
        "recovery_bucket_fingerprint": authorization.recovery_bucket_fingerprint,
        "candidate_storage_key_fingerprint": authorization.candidate_storage_key_fingerprint,
        "source_authority_fingerprint": authorization.source_authority_fingerprint,
        "candidate_authority_fingerprint": authorization.candidate_authority_fingerprint,
        "configuration_fingerprint": authorization.configuration_fingerprint,
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
    return RecoveryDurableReadPromotionAuthorizationOperationRead(
        authorization=RecoveryDurableReadPromotionAuthorizationRead.model_validate(
            authorization
        ),
        receipt=(
            RecoveryDurableReadPromotionAuthorizationReceiptRead.model_validate(receipt)
            if receipt is not None
            else None
        ),
        outcome=outcome,
    )


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-routable-read-qualifications/{qualification_id}/durable-read-promotion-authorization",
    response_model=RecoveryDurableReadPromotionAuthorizationOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_durable_read_promotion_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
    payload: RecoveryDurableReadPromotionAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadPromotionAuthorizationOperationRead:
    try:
        authorization, receipt, outcome = request_durable_read_promotion_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            qualification_id=qualification_id,
            requested_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "pending_second_approval": "EVIDENCE_RECOVERY_DURABLE_READ_PROMOTION_AUTH_REQUESTED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_PROMOTION_AUTH_REQUEST_REPLAYED",
                "invalidated": "EVIDENCE_RECOVERY_DURABLE_READ_PROMOTION_AUTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_durable_read_promotion_authorization",
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
        RecoveryDurableReadPromotionAuthorizationNotFound,
        RecoveryDurableReadPromotionAuthorizationConflict,
        RecoveryDurableReadPromotionAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Durable read promotion authorization conflicts with immutable recovery lineage",
        ) from exc
    return _operation(authorization, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-promotion-authorizations/{authorization_id}/approve",
    response_model=RecoveryDurableReadPromotionAuthorizationOperationRead,
)
def approve_durable_read_promotion_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryDurableReadPromotionAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadPromotionAuthorizationOperationRead:
    try:
        authorization, receipt, outcome = approve_durable_read_promotion_authorization(
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
                "approved": "EVIDENCE_RECOVERY_DURABLE_READ_PROMOTION_AUTH_APPROVED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_PROMOTION_AUTH_APPROVAL_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_DURABLE_READ_PROMOTION_AUTH_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_DURABLE_READ_PROMOTION_AUTH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_durable_read_promotion_authorization",
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
        RecoveryDurableReadPromotionAuthorizationNotFound,
        RecoveryDurableReadPromotionAuthorizationConflict,
        RecoveryDurableReadPromotionAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Authorization receipt conflict") from exc
    return _operation(authorization, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-promotion-authorizations/{authorization_id}/reject",
    response_model=RecoveryDurableReadPromotionAuthorizationOperationRead,
)
def reject_durable_read_promotion_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryDurableReadPromotionAuthorizationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadPromotionAuthorizationOperationRead:
    try:
        authorization, receipt, outcome = reject_durable_read_promotion_authorization(
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
                "rejected": "EVIDENCE_RECOVERY_DURABLE_READ_PROMOTION_AUTH_REJECTED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_PROMOTION_AUTH_REJECTION_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_durable_read_promotion_authorization",
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
        RecoveryDurableReadPromotionAuthorizationNotFound,
        RecoveryDurableReadPromotionAuthorizationConflict,
        RecoveryDurableReadPromotionAuthorizationUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(authorization, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-promotion-authorizations/{authorization_id}",
    response_model=RecoveryDurableReadPromotionAuthorizationRead,
)
def get_durable_read_promotion_authorization_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryDurableReadPromotionAuthorizationRead:
    try:
        authorization = get_durable_read_promotion_authorization(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryDurableReadPromotionAuthorizationNotFound as exc:
        raise _error(exc) from exc
    return RecoveryDurableReadPromotionAuthorizationRead.model_validate(authorization)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-promotion-authorizations/{authorization_id}/receipts",
    response_model=list[RecoveryDurableReadPromotionAuthorizationReceiptRead],
)
def list_durable_read_promotion_authorization_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RecoveryDurableReadPromotionAuthorizationReceiptRead]:
    try:
        receipts = list_durable_read_promotion_authorization_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
    except RecoveryDurableReadPromotionAuthorizationNotFound as exc:
        raise _error(exc) from exc
    return [
        RecoveryDurableReadPromotionAuthorizationReceiptRead.model_validate(item)
        for item in receipts
    ]
