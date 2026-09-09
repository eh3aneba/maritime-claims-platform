from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_shadow_schemas import (
    RecoveryShadowOperationRead,
    RecoveryShadowPromotionRead,
    RecoveryShadowRequest,
    RecoveryShadowVerificationRead,
)
from app.modules.documents.recovery_shadow_service import (
    RecoveryShadowConflict,
    RecoveryShadowNotFound,
    RecoveryShadowUnavailable,
    get_recovery_shadow_promotion,
    list_recovery_shadow_verifications,
    rehearse_recovery_shadow_promotion,
    verify_recovery_shadow_promotion,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-shadow-promotion"])


def _shadow_audit_values(shadow) -> dict:
    return {
        "claim_id": str(shadow.claim_id),
        "document_id": str(shadow.document_id),
        "attestation_id": str(shadow.attestation_id),
        "replica_id": str(shadow.replica_id),
        "rehearsal_id": str(shadow.rehearsal_id),
        "restore_verification_id": str(shadow.restore_verification_id),
        "attestation_request_snapshot_hash": shadow.attestation_request_snapshot_hash,
        "promotion_plan_hash": shadow.promotion_plan_hash,
        "configuration_fingerprint": shadow.configuration_fingerprint,
        "source_file_hash": shadow.source_file_hash,
        "source_file_size_bytes": shadow.source_file_size_bytes,
        "source_storage_key_fingerprint": shadow.source_storage_key_fingerprint,
        "recovery_bucket_fingerprint": shadow.recovery_bucket_fingerprint,
        "recovery_storage_key_fingerprint": shadow.recovery_storage_key_fingerprint,
        "staging_storage_key_fingerprint": shadow.staging_storage_key_fingerprint,
        "shadow_storage_key_fingerprint": shadow.shadow_storage_key_fingerprint,
        "shadow_file_hash": shadow.shadow_file_hash,
        "shadow_file_size_bytes": shadow.shadow_file_size_bytes,
        "shadow_promotion_hash": shadow.shadow_promotion_hash,
        "source_remains_authoritative": True,
        "cutover_performed": False,
        "authoritative_storage_changed": False,
        "source_storage_key_mutated": False,
        "source_deleted": False,
        "remote_delete_performed": False,
        "destructive_action_performed": False,
    }


def _verification_audit_values(verification) -> dict:
    return {
        "claim_id": str(verification.claim_id),
        "document_id": str(verification.document_id),
        "attestation_id": str(verification.attestation_id),
        "shadow_promotion_id": str(verification.shadow_promotion_id),
        "expected_file_hash": verification.expected_file_hash,
        "expected_file_size_bytes": verification.expected_file_size_bytes,
        "shadow_file_hash": verification.shadow_file_hash,
        "shadow_file_size_bytes": verification.shadow_file_size_bytes,
        "promotion_plan_hash": verification.promotion_plan_hash,
        "configuration_fingerprint": verification.configuration_fingerprint,
        "shadow_storage_key_fingerprint": verification.shadow_storage_key_fingerprint,
        "source_remains_authoritative": True,
        "cutover_performed": False,
        "authoritative_storage_changed": False,
        "source_storage_key_mutated": False,
        "destructive_action_performed": False,
    }


def _operation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryShadowNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryShadowConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, RecoveryShadowUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Recovery shadow promotion conflict")


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-promotion-attestations/{attestation_id}/shadow-rehearsal",
    response_model=RecoveryShadowOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def rehearse_shadow_promotion_endpoint(
    claim_id: UUID,
    document_id: UUID,
    attestation_id: UUID,
    payload: RecoveryShadowRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryShadowOperationRead:
    try:
        shadow, verification, created = rehearse_recovery_shadow_promotion(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            attestation_id=attestation_id,
            promoted_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action=(
                "EVIDENCE_RECOVERY_SHADOW_PROMOTION_CREATED"
                if created
                else "EVIDENCE_RECOVERY_SHADOW_PROMOTION_REVERIFIED"
            ),
            entity_type="evidence_recovery_shadow_promotion",
            entity_id=shadow.id,
            new_values={
                **_shadow_audit_values(shadow),
                "verification_hash": verification.verification_hash,
                "created": created,
            },
        )
        db.commit()
        db.refresh(shadow)
        db.refresh(verification)
    except (RecoveryShadowNotFound, RecoveryShadowConflict, RecoveryShadowUnavailable) as exc:
        db.rollback()
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="EVIDENCE_RECOVERY_SHADOW_PROMOTION_FAILED",
            entity_type="document",
            entity_id=document_id,
            new_values={
                "claim_id": str(claim_id),
                "attestation_id": str(attestation_id),
                "failure_class": type(exc).__name__,
                "source_remains_authoritative": True,
                "cutover_performed": False,
                "authoritative_storage_changed": False,
                "source_storage_key_mutated": False,
                "source_deleted": False,
                "remote_delete_performed": False,
                "destructive_action_performed": False,
            },
        )
        db.commit()
        raise _operation_error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Shadow promotion conflicts with an existing immutable lineage",
        ) from exc

    return RecoveryShadowOperationRead(
        rehearsal=RecoveryShadowPromotionRead.model_validate(shadow),
        verification=RecoveryShadowVerificationRead.model_validate(verification),
        created=created,
    )


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-promotion-attestations/{attestation_id}/shadow-rehearsal",
    response_model=RecoveryShadowPromotionRead,
)
def get_shadow_promotion_endpoint(
    claim_id: UUID,
    document_id: UUID,
    attestation_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryShadowPromotionRead:
    try:
        shadow = get_recovery_shadow_promotion(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            attestation_id=attestation_id,
        )
    except RecoveryShadowNotFound as exc:
        raise _operation_error(exc) from exc
    return RecoveryShadowPromotionRead.model_validate(shadow)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-promotion-attestations/{attestation_id}/shadow-rehearsal/verify",
    response_model=RecoveryShadowVerificationRead,
)
def verify_shadow_promotion_endpoint(
    claim_id: UUID,
    document_id: UUID,
    attestation_id: UUID,
    payload: RecoveryShadowRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryShadowVerificationRead:
    try:
        verification = verify_recovery_shadow_promotion(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            attestation_id=attestation_id,
            verified_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="EVIDENCE_RECOVERY_SHADOW_PROMOTION_REVERIFIED",
            entity_type="evidence_recovery_shadow_promotion",
            entity_id=verification.shadow_promotion_id,
            new_values=_verification_audit_values(verification),
        )
        db.commit()
        db.refresh(verification)
    except (RecoveryShadowNotFound, RecoveryShadowConflict, RecoveryShadowUnavailable) as exc:
        db.rollback()
        raise _operation_error(exc) from exc
    return RecoveryShadowVerificationRead.model_validate(verification)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-promotion-attestations/{attestation_id}/shadow-rehearsal/verifications",
    response_model=list[RecoveryShadowVerificationRead],
)
def list_shadow_promotion_verifications_endpoint(
    claim_id: UUID,
    document_id: UUID,
    attestation_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RecoveryShadowVerificationRead]:
    try:
        items = list_recovery_shadow_verifications(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            attestation_id=attestation_id,
        )
    except RecoveryShadowNotFound as exc:
        raise _operation_error(exc) from exc
    return [RecoveryShadowVerificationRead.model_validate(item) for item in items]
