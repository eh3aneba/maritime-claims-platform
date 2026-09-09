import hashlib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_restore_schemas import (
    RecoveryRestoreOperationRead,
    RecoveryRestoreRehearsalRead,
    RecoveryRestoreRequest,
    RecoveryRestoreVerificationRead,
)
from app.modules.documents.recovery_restore_service import (
    RecoveryRestoreConflict,
    RecoveryRestoreNotFound,
    RecoveryRestoreUnavailable,
    get_document_recovery_restore_rehearsal,
    list_document_recovery_restore_verifications,
    rehearse_document_recovery_restore,
    verify_document_recovery_restore,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-restore"])


def _rehearsal_audit_values(rehearsal) -> dict:
    return {
        "claim_id": str(rehearsal.claim_id),
        "document_id": str(rehearsal.document_id),
        "replica_id": str(rehearsal.replica_id),
        "replica_hash": rehearsal.replica_hash,
        "source_file_hash": rehearsal.source_file_hash,
        "source_file_size_bytes": rehearsal.source_file_size_bytes,
        "source_storage_key_fingerprint": rehearsal.source_storage_key_fingerprint,
        "recovery_bucket_fingerprint": rehearsal.recovery_bucket_fingerprint,
        "recovery_storage_key_fingerprint": rehearsal.recovery_storage_key_fingerprint,
        "staging_storage_key_fingerprint": rehearsal.staging_storage_key_fingerprint,
        "restored_file_hash": rehearsal.restored_file_hash,
        "restored_file_size_bytes": rehearsal.restored_file_size_bytes,
        "rehearsal_hash": rehearsal.rehearsal_hash,
        "source_remains_authoritative": True,
        "source_storage_key_mutated": False,
        "source_deleted": False,
        "remote_delete_performed": False,
        "storage_cutover_performed": False,
        "promotion_performed": False,
        "destructive_action_performed": False,
    }


def _verification_audit_values(verification) -> dict:
    return {
        "claim_id": str(verification.claim_id),
        "document_id": str(verification.document_id),
        "replica_id": str(verification.replica_id),
        "rehearsal_id": str(verification.rehearsal_id),
        "expected_file_hash": verification.expected_file_hash,
        "expected_file_size_bytes": verification.expected_file_size_bytes,
        "remote_file_hash": verification.remote_file_hash,
        "remote_file_size_bytes": verification.remote_file_size_bytes,
        "staged_file_hash": verification.staged_file_hash,
        "staged_file_size_bytes": verification.staged_file_size_bytes,
        "recovery_bucket_fingerprint": verification.recovery_bucket_fingerprint,
        "staging_storage_key_fingerprint": verification.staging_storage_key_fingerprint,
        "verification_hash": verification.verification_hash,
        "source_remains_authoritative": True,
        "storage_cutover_performed": False,
        "promotion_performed": False,
        "destructive_action_performed": False,
    }


def _operation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryRestoreNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryRestoreConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, RecoveryRestoreUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Recovery restore rehearsal conflict")


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-restore-rehearsal",
    response_model=RecoveryRestoreOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def rehearse_recovery_restore_endpoint(
    claim_id: UUID,
    document_id: UUID,
    payload: RecoveryRestoreRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryRestoreOperationRead:
    try:
        rehearsal, verification, created = rehearse_document_recovery_restore(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            restored_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action=(
                "EVIDENCE_RECOVERY_RESTORE_REHEARSAL_CREATED"
                if created
                else "EVIDENCE_RECOVERY_RESTORE_REHEARSAL_REVERIFIED"
            ),
            entity_type="evidence_recovery_restore_rehearsal",
            entity_id=rehearsal.id,
            new_values={
                **_rehearsal_audit_values(rehearsal),
                "verification_hash": verification.verification_hash,
                "created": created,
            },
        )
        db.commit()
        db.refresh(rehearsal)
        db.refresh(verification)
    except (RecoveryRestoreNotFound, RecoveryRestoreConflict, RecoveryRestoreUnavailable) as exc:
        db.rollback()
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="EVIDENCE_RECOVERY_RESTORE_REHEARSAL_FAILED",
            entity_type="document",
            entity_id=document_id,
            new_values={
                "claim_id": str(claim_id),
                "failure_class": type(exc).__name__,
                "source_remains_authoritative": True,
                "source_storage_key_mutated": False,
                "source_deleted": False,
                "remote_delete_performed": False,
                "storage_cutover_performed": False,
                "promotion_performed": False,
                "destructive_action_performed": False,
            },
        )
        db.commit()
        raise _operation_error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Recovery restore rehearsal conflicts with an existing immutable lineage",
        ) from exc

    return RecoveryRestoreOperationRead(
        rehearsal=RecoveryRestoreRehearsalRead.model_validate(rehearsal),
        verification=RecoveryRestoreVerificationRead.model_validate(verification),
        created=created,
    )


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-restore-rehearsal",
    response_model=RecoveryRestoreRehearsalRead,
)
def get_recovery_restore_rehearsal_endpoint(
    claim_id: UUID,
    document_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryRestoreRehearsalRead:
    try:
        rehearsal = get_document_recovery_restore_rehearsal(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
    except RecoveryRestoreNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return RecoveryRestoreRehearsalRead.model_validate(rehearsal)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-restore-rehearsal/verify",
    response_model=RecoveryRestoreVerificationRead,
)
def verify_recovery_restore_rehearsal_endpoint(
    claim_id: UUID,
    document_id: UUID,
    payload: RecoveryRestoreRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryRestoreVerificationRead:
    try:
        verification = verify_document_recovery_restore(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            verified_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="EVIDENCE_RECOVERY_RESTORE_REHEARSAL_REVERIFIED",
            entity_type="evidence_recovery_restore_rehearsal",
            entity_id=verification.rehearsal_id,
            new_values=_verification_audit_values(verification),
        )
        db.commit()
        db.refresh(verification)
    except (RecoveryRestoreNotFound, RecoveryRestoreConflict, RecoveryRestoreUnavailable) as exc:
        db.rollback()
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="EVIDENCE_RECOVERY_RESTORE_VERIFICATION_FAILED",
            entity_type="document",
            entity_id=document_id,
            new_values={
                "claim_id": str(claim_id),
                "failure_class": type(exc).__name__,
                "source_remains_authoritative": True,
                "source_storage_key_mutated": False,
                "storage_cutover_performed": False,
                "promotion_performed": False,
                "destructive_action_performed": False,
            },
        )
        db.commit()
        raise _operation_error(exc) from exc
    return RecoveryRestoreVerificationRead.model_validate(verification)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-restore-rehearsal/verifications",
    response_model=list[RecoveryRestoreVerificationRead],
)
def list_recovery_restore_verifications_endpoint(
    claim_id: UUID,
    document_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RecoveryRestoreVerificationRead]:
    try:
        items = list_document_recovery_restore_verifications(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
    except RecoveryRestoreNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [RecoveryRestoreVerificationRead.model_validate(item) for item in items]
