from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_routable_read_qualification_schemas import (
    RecoveryRoutableReadQualificationOperationRead,
    RecoveryRoutableReadQualificationRead,
    RecoveryRoutableReadQualificationReason,
    RecoveryRoutableReadQualificationReceiptRead,
    RecoveryRoutableReadQualificationRequest,
)
from app.modules.documents.recovery_routable_read_qualification_service import (
    RecoveryRoutableReadQualificationConflict,
    RecoveryRoutableReadQualificationNotFound,
    get_routable_read_qualification,
    list_routable_read_qualification_receipts,
    qualify_routable_read_qualification,
    reject_routable_read_qualification,
    request_routable_read_qualification,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-routable-read-qualification"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryRoutableReadQualificationNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(qualification) -> dict:
    return {
        "claim_id": str(qualification.claim_id),
        "document_id": str(qualification.document_id),
        "replica_id": str(qualification.replica_id),
        "first_cutover_lease_id": str(qualification.first_cutover_lease_id),
        "second_cutover_lease_id": str(qualification.second_cutover_lease_id),
        "first_authorization_id": str(qualification.first_authorization_id),
        "second_authorization_id": str(qualification.second_authorization_id),
        "qualification_bundle_hash": qualification.qualification_bundle_hash,
        "request_snapshot_hash": qualification.request_snapshot_hash,
        "qualification_hash": qualification.qualification_hash,
        "first_cycle_proof_hash": qualification.first_cycle_proof_hash,
        "second_cycle_proof_hash": qualification.second_cycle_proof_hash,
        "replica_hash": qualification.replica_hash,
        "source_file_hash": qualification.source_file_hash,
        "source_file_size_bytes": qualification.source_file_size_bytes,
        "recovery_bucket_fingerprint": qualification.recovery_bucket_fingerprint,
        "candidate_storage_key_fingerprint": qualification.candidate_storage_key_fingerprint,
        "source_authority_fingerprint": qualification.source_authority_fingerprint,
        "candidate_authority_fingerprint": qualification.candidate_authority_fingerprint,
        "configuration_fingerprint": qualification.configuration_fingerprint,
        "route_version_at_request": qualification.route_version_at_request,
        "successful_cycle_count": qualification.successful_cycle_count,
        "status": qualification.status,
        "routable_authority_created": False,
        "read_path_switched": False,
        "write_path_switched": False,
        "document_storage_key_mutated": False,
        "authoritative_storage_changed": False,
        "destructive_action_performed": False,
        "s3_delete_performed": False,
        "local_delete_performed": False,
    }


def _operation(qualification, receipt, outcome: str) -> RecoveryRoutableReadQualificationOperationRead:
    return RecoveryRoutableReadQualificationOperationRead(
        qualification=RecoveryRoutableReadQualificationRead.model_validate(qualification),
        receipt=(
            RecoveryRoutableReadQualificationReceiptRead.model_validate(receipt)
            if receipt is not None
            else None
        ),
        outcome=outcome,
    )


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-routable-read-qualification",
    response_model=RecoveryRoutableReadQualificationOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def request_routable_read_qualification_endpoint(
    claim_id: UUID,
    document_id: UUID,
    payload: RecoveryRoutableReadQualificationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryRoutableReadQualificationOperationRead:
    try:
        qualification, receipt, outcome = request_routable_read_qualification(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            cutover_lease_ids=payload.cutover_lease_ids,
            requested_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "pending_second_approval": "EVIDENCE_RECOVERY_ROUTABLE_READ_QUALIFICATION_REQUESTED",
                "unchanged": "EVIDENCE_RECOVERY_ROUTABLE_READ_QUALIFICATION_REQUEST_REPLAYED",
                "invalidated": "EVIDENCE_RECOVERY_ROUTABLE_READ_QUALIFICATION_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_routable_read_qualification",
            entity_id=qualification.id,
            new_values={
                **_audit_values(qualification),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        db.commit()
        db.refresh(qualification)
        if receipt is not None:
            db.refresh(receipt)
    except (RecoveryRoutableReadQualificationNotFound, RecoveryRoutableReadQualificationConflict) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Qualification conflicts with immutable recovery lineage",
        ) from exc
    return _operation(qualification, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-routable-read-qualifications/{qualification_id}/qualify",
    response_model=RecoveryRoutableReadQualificationOperationRead,
)
def qualify_routable_read_qualification_endpoint(
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
    payload: RecoveryRoutableReadQualificationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryRoutableReadQualificationOperationRead:
    try:
        qualification, receipt, outcome = qualify_routable_read_qualification(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            qualification_id=qualification_id,
            qualified_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "qualified": "EVIDENCE_RECOVERY_ROUTABLE_READ_QUALIFICATION_APPROVED",
                "unchanged": "EVIDENCE_RECOVERY_ROUTABLE_READ_QUALIFICATION_APPROVAL_REPLAYED",
                "invalidated": "EVIDENCE_RECOVERY_ROUTABLE_READ_QUALIFICATION_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_routable_read_qualification",
            entity_id=qualification.id,
            new_values={
                **_audit_values(qualification),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        db.commit()
        db.refresh(qualification)
        if receipt is not None:
            db.refresh(receipt)
    except (RecoveryRoutableReadQualificationNotFound, RecoveryRoutableReadQualificationConflict) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Qualification receipt conflict") from exc
    return _operation(qualification, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-routable-read-qualifications/{qualification_id}/reject",
    response_model=RecoveryRoutableReadQualificationOperationRead,
)
def reject_routable_read_qualification_endpoint(
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
    payload: RecoveryRoutableReadQualificationReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryRoutableReadQualificationOperationRead:
    try:
        qualification, receipt, outcome = reject_routable_read_qualification(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            qualification_id=qualification_id,
            rejected_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "rejected": "EVIDENCE_RECOVERY_ROUTABLE_READ_QUALIFICATION_REJECTED",
                "unchanged": "EVIDENCE_RECOVERY_ROUTABLE_READ_QUALIFICATION_REJECTION_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_routable_read_qualification",
            entity_id=qualification.id,
            new_values={
                **_audit_values(qualification),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        db.commit()
        db.refresh(qualification)
        if receipt is not None:
            db.refresh(receipt)
    except (RecoveryRoutableReadQualificationNotFound, RecoveryRoutableReadQualificationConflict) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(qualification, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-routable-read-qualifications/{qualification_id}",
    response_model=RecoveryRoutableReadQualificationRead,
)
def get_routable_read_qualification_endpoint(
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryRoutableReadQualificationRead:
    try:
        qualification = get_routable_read_qualification(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            qualification_id=qualification_id,
        )
    except RecoveryRoutableReadQualificationNotFound as exc:
        raise _error(exc) from exc
    return RecoveryRoutableReadQualificationRead.model_validate(qualification)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-routable-read-qualifications/{qualification_id}/receipts",
    response_model=list[RecoveryRoutableReadQualificationReceiptRead],
)
def list_routable_read_qualification_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RecoveryRoutableReadQualificationReceiptRead]:
    try:
        receipts = list_routable_read_qualification_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            qualification_id=qualification_id,
        )
    except RecoveryRoutableReadQualificationNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryRoutableReadQualificationReceiptRead.model_validate(item) for item in receipts]
