from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_physical_disposal_authorization_schemas import (
    PhysicalDisposalAdmissionDecision,
    PhysicalDisposalAdmissionRead,
    PhysicalDisposalAdmissionReceiptRead,
    PhysicalDisposalAdmissionRequest,
)
from app.modules.claims.retention_physical_disposal_authorization_service import (
    PhysicalDisposalAdmissionError,
    PhysicalDisposalAdmissionRetryableError,
    approve_physical_disposal_admission,
    get_physical_disposal_admission,
    list_physical_disposal_admissions,
    reject_physical_disposal_admission,
    request_physical_disposal_admission,
)
from app.modules.claims.retention_physical_disposal_receipt_service import (
    list_physical_disposal_admission_receipts,
)
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.claims.retention_service import RetentionNotFoundError

router = APIRouter(tags=["retention"])


def _read(authorization) -> PhysicalDisposalAdmissionRead:
    return PhysicalDisposalAdmissionRead.model_validate(authorization)


def _audit_values(authorization) -> dict:
    return {
        "claim_id": str(authorization.claim_id),
        "disposal_release_review_id": str(authorization.disposal_release_review_id),
        "disposal_quarantine_stage_id": str(authorization.disposal_quarantine_stage_id),
        "disposal_execution_manifest_id": str(authorization.disposal_execution_manifest_id),
        "status": authorization.status,
        "release_review_hash": authorization.release_review_hash,
        "release_approval_hash": authorization.release_approval_hash,
        "manifest_hash": authorization.manifest_hash,
        "inventory_hash": authorization.inventory_hash,
        "document_bindings_hash": authorization.document_bindings_hash,
        "separation_actor_set_hash": authorization.separation_actor_set_hash,
        "document_count": authorization.document_count,
        "total_file_size_bytes": authorization.total_file_size_bytes,
        "authorization_hash": authorization.authorization_hash,
        "approval_hash": authorization.approval_hash,
        "authorization_expires_at": authorization.authorization_expires_at.isoformat(),
        "physical_disposal_authorized": authorization.physical_disposal_authorized,
        "max_execution_count": authorization.max_execution_count,
        "execution_count": authorization.execution_count,
        "storage_identifiers_raw_logged": False,
        "destructive_action_performed": authorization.destructive_action_performed,
        "storage_write_performed": authorization.storage_write_performed,
        "s3_delete_performed": authorization.s3_delete_performed,
        "local_delete_performed": authorization.local_delete_performed,
    }


def _retryable_http_error(exc: PhysicalDisposalAdmissionRetryableError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "physical_disposal_recovery_unavailable",
            "retryable": True,
            "detail": str(exc),
        },
    )


@router.post(
    "/{claim_id}/disposal-release-reviews/{review_id}/physical-disposal-admission",
    response_model=PhysicalDisposalAdmissionRead,
    status_code=status.HTTP_201_CREATED,
)
def request_physical_disposal_admission_endpoint(
    claim_id: UUID,
    review_id: UUID,
    payload: PhysicalDisposalAdmissionRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> PhysicalDisposalAdmissionRead:
    try:
        authorization = request_physical_disposal_admission(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            review_id=review_id,
            requested_by_id=current_user.id,
            request_reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action="PHYSICAL_DISPOSAL_ADMISSION_REQUESTED",
            entity_type="physical_disposal_admission_authorization",
            entity_id=authorization.id,
            new_values=_audit_values(authorization),
        )
        db.commit()
        db.refresh(authorization)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PhysicalDisposalAdmissionRetryableError as exc:
        db.rollback()
        raise _retryable_http_error(exc) from exc
    except PhysicalDisposalAdmissionError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "physical_disposal_admission_failed",
                "blocking_reasons": exc.blocking_reasons,
            },
        ) from exc
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _read(authorization)


@router.get(
    "/{claim_id}/physical-disposal-admissions",
    response_model=list[PhysicalDisposalAdmissionRead],
)
def list_physical_disposal_admissions_endpoint(
    claim_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[PhysicalDisposalAdmissionRead]:
    try:
        authorizations = list_physical_disposal_admissions(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
        )
    except RetentionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [_read(item) for item in authorizations]


@router.get(
    "/{claim_id}/physical-disposal-admissions/{authorization_id}",
    response_model=PhysicalDisposalAdmissionRead,
)
def get_physical_disposal_admission_endpoint(
    claim_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> PhysicalDisposalAdmissionRead:
    try:
        authorization = get_physical_disposal_admission(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            authorization_id=authorization_id,
        )
    except RetentionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _read(authorization)


@router.get(
    "/{claim_id}/physical-disposal-admissions/{authorization_id}/receipts",
    response_model=list[PhysicalDisposalAdmissionReceiptRead],
)
def list_physical_disposal_admission_receipts_endpoint(
    claim_id: UUID,
    authorization_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[PhysicalDisposalAdmissionReceiptRead]:
    try:
        receipts = list_physical_disposal_admission_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            authorization_id=authorization_id,
        )
    except RetentionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [PhysicalDisposalAdmissionReceiptRead.model_validate(item) for item in receipts]


@router.post(
    "/{claim_id}/physical-disposal-admissions/{authorization_id}/approve",
    response_model=PhysicalDisposalAdmissionRead,
)
def approve_physical_disposal_admission_endpoint(
    claim_id: UUID,
    authorization_id: UUID,
    payload: PhysicalDisposalAdmissionDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> PhysicalDisposalAdmissionRead:
    try:
        authorization, outcome = approve_physical_disposal_admission(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            authorization_id=authorization_id,
            approved_by_id=current_user.id,
            approval_reason=payload.reason,
        )
        if outcome != "unchanged":
            action = {
                "authorized": "PHYSICAL_DISPOSAL_ADMISSION_AUTHORIZED",
                "invalidated": "PHYSICAL_DISPOSAL_ADMISSION_INVALIDATED",
                "expired": "PHYSICAL_DISPOSAL_ADMISSION_EXPIRED",
            }[outcome]
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action=action,
                entity_type="physical_disposal_admission_authorization",
                entity_id=authorization.id,
                new_values=_audit_values(authorization),
            )
            db.commit()
            db.refresh(authorization)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PhysicalDisposalAdmissionRetryableError as exc:
        db.rollback()
        raise _retryable_http_error(exc) from exc
    except PhysicalDisposalAdmissionError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "physical_disposal_admission_failed",
                "blocking_reasons": exc.blocking_reasons,
            },
        ) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _read(authorization)


@router.post(
    "/{claim_id}/physical-disposal-admissions/{authorization_id}/reject",
    response_model=PhysicalDisposalAdmissionRead,
)
def reject_physical_disposal_admission_endpoint(
    claim_id: UUID,
    authorization_id: UUID,
    payload: PhysicalDisposalAdmissionDecision,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> PhysicalDisposalAdmissionRead:
    try:
        authorization, outcome = reject_physical_disposal_admission(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            authorization_id=authorization_id,
            rejected_by_id=current_user.id,
            rejection_reason=payload.reason,
        )
        if outcome != "unchanged":
            action = (
                "PHYSICAL_DISPOSAL_ADMISSION_REJECTED"
                if outcome == "rejected"
                else "PHYSICAL_DISPOSAL_ADMISSION_EXPIRED"
            )
            write_audit_log(
                db,
                organization_id=current_user.organization_id,
                user_id=current_user.id,
                action=action,
                entity_type="physical_disposal_admission_authorization",
                entity_id=authorization.id,
                new_values=_audit_values(authorization),
            )
            db.commit()
            db.refresh(authorization)
    except RetentionNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PhysicalDisposalAdmissionError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "physical_disposal_admission_failed",
                "blocking_reasons": exc.blocking_reasons,
            },
        ) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _read(authorization)