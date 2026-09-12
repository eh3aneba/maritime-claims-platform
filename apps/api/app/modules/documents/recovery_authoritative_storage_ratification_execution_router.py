from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_authoritative_storage_ratification_execution_schemas import (
    RecoveryAuthoritativeStorageRatificationExecutionRequest,
    RecoveryAuthoritativeStorageRatificationOperationRead,
    RecoveryAuthoritativeStorageRatificationRead,
    RecoveryAuthoritativeStorageRatificationReceiptRead,
    RecoveryAuthoritativeStorageRatificationRouteRead,
)
from app.modules.documents.recovery_authoritative_storage_ratification_execution_service import (
    RecoveryAuthoritativeStorageRatificationExecutionConflict,
    RecoveryAuthoritativeStorageRatificationExecutionNotFound,
    RecoveryAuthoritativeStorageRatificationExecutionUnavailable,
    execute_authoritative_storage_ratification,
    get_authoritative_storage_ratification,
    list_authoritative_storage_ratification_receipts,
)
from app.modules.documents.recovery_authoritative_storage_ownership_execution_service import (
    get_authoritative_storage_ownership_route,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-authoritative-storage-ratification-execution"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryAuthoritativeStorageRatificationExecutionNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryAuthoritativeStorageRatificationExecutionUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(r, route) -> dict:
    return {
        "claim_id": str(r.claim_id),
        "document_id": str(r.document_id),
        "authorization_id": str(r.authorization_id),
        "phase_al_health_qualification_id": str(r.phase_al_health_qualification_id),
        "authoritative_storage_ownership_lease_id": str(r.authoritative_storage_ownership_lease_id),
        "ratification_hash": r.ratification_hash,
        "authority_kind": r.authority_kind,
        "authority_tenure": r.authority_tenure,
        "ratification_active": True,
        "durable_authority_created": True,
        "authority_route_version": route.route_version,
        "local_authoritative": False,
        "recovery_authoritative": True,
        "authoritative_storage_changed": True,
        "local_evidence_preserved": True,
        "storage_write_performed": False,
        "route_mutation_performed": True,
        "ownership_mutation_performed": True,
        "read_path_switched": False,
        "write_path_switched": False,
        "document_storage_key_mutated": False,
        "destructive_action_performed": False,
        "physical_disposal_authorized": False,
        "s3_put_performed": False,
        "s3_copy_performed": False,
        "s3_delete_performed": False,
        "local_overwrite_performed": False,
        "local_move_performed": False,
        "local_delete_performed": False,
    }


def _operation(r, route, receipt, outcome: str):
    return RecoveryAuthoritativeStorageRatificationOperationRead(
        ratification=RecoveryAuthoritativeStorageRatificationRead.model_validate(r),
        route=RecoveryAuthoritativeStorageRatificationRouteRead.model_validate(route),
        receipt=(
            RecoveryAuthoritativeStorageRatificationReceiptRead.model_validate(receipt)
            if receipt
            else None
        ),
        outcome=outcome,
    )


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-authoritative-storage-ratifications",
    response_model=RecoveryAuthoritativeStorageRatificationOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def execute_ratification_endpoint(
    claim_id: UUID,
    document_id: UUID,
    payload: RecoveryAuthoritativeStorageRatificationExecutionRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        r, route, receipt, outcome = execute_authoritative_storage_ratification(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=payload.authorization_id,
            executed_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "ratified": "EVIDENCE_RECOVERY_AUTHORITATIVE_STORAGE_RATIFICATION_EXECUTED",
                "unchanged": "EVIDENCE_RECOVERY_AUTHORITATIVE_STORAGE_RATIFICATION_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_authoritative_storage_ratification",
            entity_id=r.id,
            new_values={
                **_audit_values(r, route),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        db.commit()
        db.refresh(r)
        db.refresh(route)
        if receipt is not None:
            db.refresh(receipt)
    except (
        RecoveryAuthoritativeStorageRatificationExecutionNotFound,
        RecoveryAuthoritativeStorageRatificationExecutionConflict,
        RecoveryAuthoritativeStorageRatificationExecutionUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Phase AN ratification conflicts with immutable durable ownership lineage",
        ) from exc
    return _operation(r, route, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-authoritative-storage-ratifications/{ratification_id}",
    response_model=RecoveryAuthoritativeStorageRatificationRead,
)
def get_ratification_endpoint(
    claim_id: UUID,
    document_id: UUID,
    ratification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        r = get_authoritative_storage_ratification(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            ratification_id=ratification_id,
        )
    except RecoveryAuthoritativeStorageRatificationExecutionNotFound as exc:
        raise _error(exc) from exc
    return RecoveryAuthoritativeStorageRatificationRead.model_validate(r)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-authoritative-storage-ratifications/{ratification_id}/receipts",
    response_model=list[RecoveryAuthoritativeStorageRatificationReceiptRead],
)
def list_ratification_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    ratification_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        receipts = list_authoritative_storage_ratification_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            ratification_id=ratification_id,
        )
    except RecoveryAuthoritativeStorageRatificationExecutionNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryAuthoritativeStorageRatificationReceiptRead.model_validate(item) for item in receipts]


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-authoritative-storage-ratification-route",
    response_model=RecoveryAuthoritativeStorageRatificationRouteRead,
)
def get_ratification_route_endpoint(
    claim_id: UUID,
    document_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        route = get_authoritative_storage_ownership_route(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RecoveryAuthoritativeStorageRatificationRouteRead.model_validate(route)
