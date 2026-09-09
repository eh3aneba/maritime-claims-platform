import hashlib
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_replication_schemas import (
    RecoveryReplicaRead,
    RecoveryReplicationOperationRead,
    RecoveryReplicationRequest,
    RecoveryVerificationRead,
)
from app.modules.documents.recovery_replication_service import (
    RecoveryReplicationConflict,
    RecoveryReplicationNotFound,
    RecoveryReplicationUnavailable,
    get_document_recovery_replica,
    list_document_recovery_verifications,
    replicate_document_for_recovery,
    verify_document_recovery_replica,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery"])


def _replica_audit_values(replica) -> dict:
    return {
        "claim_id": str(replica.claim_id),
        "document_id": str(replica.document_id),
        "source_file_hash": replica.source_file_hash,
        "source_file_size_bytes": replica.source_file_size_bytes,
        "source_storage_key_fingerprint": replica.source_storage_key_fingerprint,
        "recovery_storage_key_fingerprint": hashlib.sha256(
            replica.recovery_storage_key.encode("utf-8")
        ).hexdigest(),
        "recovery_bucket_fingerprint": replica.recovery_bucket_fingerprint,
        "replica_hash": replica.replica_hash,
        "source_remains_authoritative": True,
        "source_storage_key_mutated": False,
        "source_deleted": False,
        "remote_delete_performed": False,
        "storage_cutover_performed": False,
        "destructive_action_performed": False,
    }


def _verification_audit_values(verification) -> dict:
    return {
        "claim_id": str(verification.claim_id),
        "document_id": str(verification.document_id),
        "replica_id": str(verification.replica_id),
        "expected_file_hash": verification.expected_file_hash,
        "expected_file_size_bytes": verification.expected_file_size_bytes,
        "observed_file_hash": verification.observed_file_hash,
        "observed_file_size_bytes": verification.observed_file_size_bytes,
        "recovery_bucket_fingerprint": verification.recovery_bucket_fingerprint,
        "verification_hash": verification.verification_hash,
        "source_remains_authoritative": True,
        "destructive_action_performed": False,
    }


def _operation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryReplicationNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryReplicationConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, RecoveryReplicationUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Recovery replication conflict")


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-replica",
    response_model=RecoveryReplicationOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def replicate_document_endpoint(
    claim_id: UUID,
    document_id: UUID,
    payload: RecoveryReplicationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryReplicationOperationRead:
    try:
        replica, verification, created = replicate_document_for_recovery(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            replicated_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action=(
                "EVIDENCE_RECOVERY_REPLICA_VERIFIED"
                if created
                else "EVIDENCE_RECOVERY_REPLICA_REVERIFIED"
            ),
            entity_type="evidence_recovery_replica",
            entity_id=replica.id,
            new_values={
                **_replica_audit_values(replica),
                "verification_hash": verification.verification_hash,
                "created": created,
            },
        )
        db.commit()
        db.refresh(replica)
        db.refresh(verification)
    except (RecoveryReplicationNotFound, RecoveryReplicationConflict, RecoveryReplicationUnavailable) as exc:
        db.rollback()
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="EVIDENCE_RECOVERY_REPLICATION_FAILED",
            entity_type="document",
            entity_id=document_id,
            new_values={
                "claim_id": str(claim_id),
                "failure_class": type(exc).__name__,
                "source_remains_authoritative": True,
                "source_deleted": False,
                "remote_delete_performed": False,
                "storage_cutover_performed": False,
                "destructive_action_performed": False,
            },
        )
        db.commit()
        raise _operation_error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Recovery replica lineage conflicts with an existing immutable record",
        ) from exc

    return RecoveryReplicationOperationRead(
        replica=RecoveryReplicaRead.model_validate(replica),
        verification=RecoveryVerificationRead.model_validate(verification),
        created=created,
    )


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-replica",
    response_model=RecoveryReplicaRead,
)
def get_recovery_replica_endpoint(
    claim_id: UUID,
    document_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryReplicaRead:
    try:
        replica = get_document_recovery_replica(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
    except RecoveryReplicationNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return RecoveryReplicaRead.model_validate(replica)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-replica/verify",
    response_model=RecoveryVerificationRead,
)
def verify_recovery_replica_endpoint(
    claim_id: UUID,
    document_id: UUID,
    payload: RecoveryReplicationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryVerificationRead:
    try:
        verification = verify_document_recovery_replica(
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
            action="EVIDENCE_RECOVERY_REPLICA_REVERIFIED",
            entity_type="evidence_recovery_replica",
            entity_id=verification.replica_id,
            new_values=_verification_audit_values(verification),
        )
        db.commit()
        db.refresh(verification)
    except (RecoveryReplicationNotFound, RecoveryReplicationConflict, RecoveryReplicationUnavailable) as exc:
        db.rollback()
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="EVIDENCE_RECOVERY_VERIFICATION_FAILED",
            entity_type="document",
            entity_id=document_id,
            new_values={
                "claim_id": str(claim_id),
                "failure_class": type(exc).__name__,
                "source_remains_authoritative": True,
                "destructive_action_performed": False,
            },
        )
        db.commit()
        raise _operation_error(exc) from exc
    return RecoveryVerificationRead.model_validate(verification)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-replica/verifications",
    response_model=list[RecoveryVerificationRead],
)
def list_recovery_verifications_endpoint(
    claim_id: UUID,
    document_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RecoveryVerificationRead]:
    try:
        items = list_document_recovery_verifications(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
    except RecoveryReplicationNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [RecoveryVerificationRead.model_validate(item) for item in items]
