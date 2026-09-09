from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_promotion_schemas import (
    RecoveryPromotionAttestationRead,
    RecoveryPromotionDecision,
    RecoveryPromotionRequest,
)
from app.modules.documents.recovery_promotion_service import (
    RecoveryPromotionConflict,
    RecoveryPromotionNotFound,
    RecoveryPromotionUnavailable,
    approve_recovery_promotion_attestation,
    get_recovery_promotion_attestation,
    list_recovery_promotion_attestations,
    reject_recovery_promotion_attestation,
    request_recovery_promotion_attestation,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-promotion"])


def _audit_values(attestation) -> dict:
    return {
        "claim_id": str(attestation.claim_id),
        "document_id": str(attestation.document_id),
        "replica_id": str(attestation.replica_id),
        "rehearsal_id": str(attestation.rehearsal_id),
        "restore_verification_id": str(attestation.restore_verification_id),
        "replica_hash": attestation.replica_hash,
        "rehearsal_hash": attestation.rehearsal_hash,
        "restore_verification_hash": attestation.restore_verification_hash,
        "source_file_hash": attestation.source_file_hash,
        "source_file_size_bytes": attestation.source_file_size_bytes,
        "source_storage_key_fingerprint": attestation.source_storage_key_fingerprint,
        "recovery_bucket_fingerprint": attestation.recovery_bucket_fingerprint,
        "recovery_storage_key_fingerprint": attestation.recovery_storage_key_fingerprint,
        "staging_storage_key_fingerprint": attestation.staging_storage_key_fingerprint,
        "configuration_fingerprint": attestation.configuration_fingerprint,
        "promotion_plan_hash": attestation.promotion_plan_hash,
        "request_snapshot_hash": attestation.request_snapshot_hash,
        "status": attestation.status,
        "cutover_performed": False,
        "authoritative_storage_changed": False,
        "source_storage_key_mutated": False,
        "source_deleted": False,
        "remote_delete_performed": False,
        "destructive_action_performed": False,
    }


def _operation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryPromotionNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryPromotionConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, RecoveryPromotionUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Recovery promotion attestation conflict")


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-promotion-attestations",
    response_model=RecoveryPromotionAttestationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_recovery_promotion_attestation_endpoint(
    claim_id: UUID,
    document_id: UUID,
    payload: RecoveryPromotionRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryPromotionAttestationRead:
    try:
        attestation = request_recovery_promotion_attestation(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            requested_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="EVIDENCE_RECOVERY_PROMOTION_ATTESTATION_REQUESTED",
            entity_type="evidence_recovery_promotion_attestation",
            entity_id=attestation.id,
            new_values=_audit_values(attestation),
        )
        db.commit()
        db.refresh(attestation)
    except (RecoveryPromotionNotFound, RecoveryPromotionConflict, RecoveryPromotionUnavailable) as exc:
        db.rollback()
        raise _operation_error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Recovery promotion attestation conflicts with an immutable request lineage",
        ) from exc
    return RecoveryPromotionAttestationRead.model_validate(attestation)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-promotion-attestations",
    response_model=list[RecoveryPromotionAttestationRead],
)
def list_recovery_promotion_attestations_endpoint(
    claim_id: UUID,
    document_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RecoveryPromotionAttestationRead]:
    items = list_recovery_promotion_attestations(
        db,
        organization_id=current_user.organization_id,
        claim_id=claim_id,
        document_id=document_id,
    )
    return [RecoveryPromotionAttestationRead.model_validate(item) for item in items]


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-promotion-attestations/{attestation_id}",
    response_model=RecoveryPromotionAttestationRead,
)
def get_recovery_promotion_attestation_endpoint(
    claim_id: UUID,
    document_id: UUID,
    attestation_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryPromotionAttestationRead:
    try:
        attestation = get_recovery_promotion_attestation(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            attestation_id=attestation_id,
        )
    except RecoveryPromotionNotFound as exc:
        raise _operation_error(exc) from exc
    return RecoveryPromotionAttestationRead.model_validate(attestation)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-promotion-attestations/{attestation_id}/approve",
    response_model=RecoveryPromotionAttestationRead,
)
def approve_recovery_promotion_attestation_endpoint(
    claim_id: UUID,
    document_id: UUID,
    attestation_id: UUID,
    payload: RecoveryPromotionDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryPromotionAttestationRead:
    try:
        attestation, outcome = approve_recovery_promotion_attestation(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            attestation_id=attestation_id,
            approved_by_id=current_user.id,
            reason=payload.reason,
        )
        action = {
            "approved": "EVIDENCE_RECOVERY_PROMOTION_ATTESTATION_APPROVED",
            "invalidated": "EVIDENCE_RECOVERY_PROMOTION_ATTESTATION_INVALIDATED",
            "expired": "EVIDENCE_RECOVERY_PROMOTION_ATTESTATION_EXPIRED",
            "unchanged": "EVIDENCE_RECOVERY_PROMOTION_ATTESTATION_REREAD",
        }[outcome]
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action=action,
            entity_type="evidence_recovery_promotion_attestation",
            entity_id=attestation.id,
            new_values=_audit_values(attestation),
        )
        db.commit()
        db.refresh(attestation)
    except (RecoveryPromotionNotFound, RecoveryPromotionConflict, RecoveryPromotionUnavailable) as exc:
        db.rollback()
        raise _operation_error(exc) from exc
    return RecoveryPromotionAttestationRead.model_validate(attestation)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-promotion-attestations/{attestation_id}/reject",
    response_model=RecoveryPromotionAttestationRead,
)
def reject_recovery_promotion_attestation_endpoint(
    claim_id: UUID,
    document_id: UUID,
    attestation_id: UUID,
    payload: RecoveryPromotionDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryPromotionAttestationRead:
    try:
        attestation, outcome = reject_recovery_promotion_attestation(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            attestation_id=attestation_id,
            rejected_by_id=current_user.id,
            reason=payload.reason,
        )
        action = {
            "rejected": "EVIDENCE_RECOVERY_PROMOTION_ATTESTATION_REJECTED",
            "expired": "EVIDENCE_RECOVERY_PROMOTION_ATTESTATION_EXPIRED",
            "unchanged": "EVIDENCE_RECOVERY_PROMOTION_ATTESTATION_REREAD",
        }[outcome]
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action=action,
            entity_type="evidence_recovery_promotion_attestation",
            entity_id=attestation.id,
            new_values=_audit_values(attestation),
        )
        db.commit()
        db.refresh(attestation)
    except (RecoveryPromotionNotFound, RecoveryPromotionConflict, RecoveryPromotionUnavailable) as exc:
        db.rollback()
        raise _operation_error(exc) from exc
    return RecoveryPromotionAttestationRead.model_validate(attestation)
