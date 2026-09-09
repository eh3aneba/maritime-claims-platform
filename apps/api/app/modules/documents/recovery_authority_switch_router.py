from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_authority_switch_schemas import (
    RecoveryAuthoritySwitchOperationRead,
    RecoveryAuthoritySwitchReason,
    RecoveryAuthoritySwitchReceiptRead,
    RecoveryAuthoritySwitchRehearsalRead,
)
from app.modules.documents.recovery_authority_switch_service import (
    RecoveryAuthoritySwitchConflict,
    RecoveryAuthoritySwitchNotFound,
    RecoveryAuthoritySwitchUnavailable,
    activate_recovery_authority_switch_rehearsal,
    get_recovery_authority_switch_rehearsal,
    list_recovery_authority_switch_receipts,
    prepare_recovery_authority_switch_rehearsal,
    rollback_recovery_authority_switch_rehearsal,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-authority-switch-rehearsal"])


def _audit_values(rehearsal) -> dict:
    return {
        "claim_id": str(rehearsal.claim_id),
        "document_id": str(rehearsal.document_id),
        "shadow_promotion_id": str(rehearsal.shadow_promotion_id),
        "attestation_id": str(rehearsal.attestation_id),
        "replica_id": str(rehearsal.replica_id),
        "restore_rehearsal_id": str(rehearsal.restore_rehearsal_id),
        "restore_verification_id": str(rehearsal.restore_verification_id),
        "shadow_verification_id": str(rehearsal.shadow_verification_id),
        "attestation_request_snapshot_hash": rehearsal.attestation_request_snapshot_hash,
        "promotion_plan_hash": rehearsal.promotion_plan_hash,
        "configuration_fingerprint": rehearsal.configuration_fingerprint,
        "shadow_promotion_hash": rehearsal.shadow_promotion_hash,
        "shadow_verification_hash": rehearsal.shadow_verification_hash,
        "source_file_hash": rehearsal.source_file_hash,
        "source_storage_key_fingerprint": rehearsal.source_storage_key_fingerprint,
        "shadow_storage_key_fingerprint": rehearsal.shadow_storage_key_fingerprint,
        "lineage_hash": rehearsal.lineage_hash,
        "source_authority_fingerprint": rehearsal.source_authority_fingerprint,
        "candidate_authority_fingerprint": rehearsal.candidate_authority_fingerprint,
        "contract_hash": rehearsal.contract_hash,
        "status": rehearsal.status,
        "virtual_authority_class": rehearsal.virtual_authority_class,
        "virtual_authority_fingerprint": rehearsal.virtual_authority_fingerprint,
        "cutover_performed": False,
        "authoritative_storage_changed": False,
        "document_storage_key_mutated": False,
        "active_backend_changed": False,
        "source_deleted": False,
        "remote_delete_performed": False,
        "destructive_action_performed": False,
    }


def _operation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryAuthoritySwitchNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryAuthoritySwitchConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, RecoveryAuthoritySwitchUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Recovery authority-switch rehearsal conflict")


def _operation_read(rehearsal, receipt, outcome: str) -> RecoveryAuthoritySwitchOperationRead:
    return RecoveryAuthoritySwitchOperationRead(
        rehearsal=RecoveryAuthoritySwitchRehearsalRead.model_validate(rehearsal),
        receipt=(RecoveryAuthoritySwitchReceiptRead.model_validate(receipt) if receipt is not None else None),
        outcome=outcome,
    )


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-shadow-promotions/{shadow_promotion_id}/authority-switch-rehearsal",
    response_model=RecoveryAuthoritySwitchOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def prepare_authority_switch_rehearsal_endpoint(
    claim_id: UUID,
    document_id: UUID,
    shadow_promotion_id: UUID,
    payload: RecoveryAuthoritySwitchReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryAuthoritySwitchOperationRead:
    try:
        rehearsal, receipt, outcome = prepare_recovery_authority_switch_rehearsal(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            shadow_promotion_id=shadow_promotion_id,
            prepared_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "prepared": "EVIDENCE_RECOVERY_AUTHORITY_SWITCH_PREPARED",
                "unchanged": "EVIDENCE_RECOVERY_AUTHORITY_SWITCH_PREPARE_REPLAYED",
                "invalidated": "EVIDENCE_RECOVERY_AUTHORITY_SWITCH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_authority_switch_rehearsal",
            entity_id=rehearsal.id,
            new_values={
                **_audit_values(rehearsal),
                "receipt_hash": receipt.receipt_hash if receipt is not None else None,
                "outcome": outcome,
            },
        )
        db.commit()
        db.refresh(rehearsal)
        if receipt is not None:
            db.refresh(receipt)
    except (RecoveryAuthoritySwitchNotFound, RecoveryAuthoritySwitchConflict, RecoveryAuthoritySwitchUnavailable) as exc:
        db.rollback()
        raise _operation_error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Authority-switch rehearsal conflicts with an immutable lineage",
        ) from exc
    return _operation_read(rehearsal, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-authority-switch-rehearsals/{rehearsal_id}",
    response_model=RecoveryAuthoritySwitchRehearsalRead,
)
def get_authority_switch_rehearsal_endpoint(
    claim_id: UUID,
    document_id: UUID,
    rehearsal_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryAuthoritySwitchRehearsalRead:
    try:
        rehearsal = get_recovery_authority_switch_rehearsal(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            rehearsal_id=rehearsal_id,
        )
    except RecoveryAuthoritySwitchNotFound as exc:
        raise _operation_error(exc) from exc
    return RecoveryAuthoritySwitchRehearsalRead.model_validate(rehearsal)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-authority-switch-rehearsals/{rehearsal_id}/activate",
    response_model=RecoveryAuthoritySwitchOperationRead,
)
def activate_authority_switch_rehearsal_endpoint(
    claim_id: UUID,
    document_id: UUID,
    rehearsal_id: UUID,
    payload: RecoveryAuthoritySwitchReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryAuthoritySwitchOperationRead:
    try:
        rehearsal, receipt, outcome = activate_recovery_authority_switch_rehearsal(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            rehearsal_id=rehearsal_id,
            activated_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "activated": "EVIDENCE_RECOVERY_AUTHORITY_SWITCH_VIRTUALLY_ACTIVATED",
                "unchanged": "EVIDENCE_RECOVERY_AUTHORITY_SWITCH_ACTIVATION_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_AUTHORITY_SWITCH_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_AUTHORITY_SWITCH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_authority_switch_rehearsal",
            entity_id=rehearsal.id,
            new_values={
                **_audit_values(rehearsal),
                "receipt_hash": receipt.receipt_hash if receipt is not None else None,
                "outcome": outcome,
            },
        )
        db.commit()
        db.refresh(rehearsal)
        if receipt is not None:
            db.refresh(receipt)
    except (RecoveryAuthoritySwitchNotFound, RecoveryAuthoritySwitchConflict, RecoveryAuthoritySwitchUnavailable) as exc:
        db.rollback()
        raise _operation_error(exc) from exc
    return _operation_read(rehearsal, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-authority-switch-rehearsals/{rehearsal_id}/rollback",
    response_model=RecoveryAuthoritySwitchOperationRead,
)
def rollback_authority_switch_rehearsal_endpoint(
    claim_id: UUID,
    document_id: UUID,
    rehearsal_id: UUID,
    payload: RecoveryAuthoritySwitchReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryAuthoritySwitchOperationRead:
    try:
        rehearsal, receipt, outcome = rollback_recovery_authority_switch_rehearsal(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            rehearsal_id=rehearsal_id,
            rolled_back_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "rolled_back": "EVIDENCE_RECOVERY_AUTHORITY_SWITCH_VIRTUALLY_ROLLED_BACK",
                "unchanged": "EVIDENCE_RECOVERY_AUTHORITY_SWITCH_ROLLBACK_REPLAYED",
                "invalidated": "EVIDENCE_RECOVERY_AUTHORITY_SWITCH_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_authority_switch_rehearsal",
            entity_id=rehearsal.id,
            new_values={
                **_audit_values(rehearsal),
                "receipt_hash": receipt.receipt_hash if receipt is not None else None,
                "outcome": outcome,
            },
        )
        db.commit()
        db.refresh(rehearsal)
        if receipt is not None:
            db.refresh(receipt)
    except (RecoveryAuthoritySwitchNotFound, RecoveryAuthoritySwitchConflict, RecoveryAuthoritySwitchUnavailable) as exc:
        db.rollback()
        raise _operation_error(exc) from exc
    return _operation_read(rehearsal, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-authority-switch-rehearsals/{rehearsal_id}/receipts",
    response_model=list[RecoveryAuthoritySwitchReceiptRead],
)
def list_authority_switch_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    rehearsal_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RecoveryAuthoritySwitchReceiptRead]:
    try:
        receipts = list_recovery_authority_switch_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            rehearsal_id=rehearsal_id,
        )
    except RecoveryAuthoritySwitchNotFound as exc:
        raise _operation_error(exc) from exc
    return [RecoveryAuthoritySwitchReceiptRead.model_validate(item) for item in receipts]
