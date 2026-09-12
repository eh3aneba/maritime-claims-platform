from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_durable_write_ownership_execution_schemas import (
    RecoveryDurableWriteOwnershipActivationRequest,
    RecoveryDurableWriteOwnershipLeaseRead,
    RecoveryDurableWriteOwnershipOperationRead,
    RecoveryDurableWriteOwnershipReason,
    RecoveryDurableWriteOwnershipReceiptRead,
    RecoveryDurableWriteOwnershipRouteRead,
)
from app.modules.documents.recovery_durable_write_ownership_execution_service import (
    RecoveryDurableWriteOwnershipExecutionConflict,
    RecoveryDurableWriteOwnershipExecutionNotFound,
    RecoveryDurableWriteOwnershipExecutionUnavailable,
    activate_durable_write_ownership,
    get_durable_write_ownership_lease,
    get_durable_write_ownership_route,
    list_durable_write_ownership_receipts,
    reconcile_durable_write_ownership,
    rollback_durable_write_ownership,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-durable-write-ownership-execution"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryDurableWriteOwnershipExecutionNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryDurableWriteOwnershipExecutionUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(lease, route) -> dict:
    return {
        "claim_id": str(lease.claim_id),
        "document_id": str(lease.document_id),
        "authorization_id": str(lease.authorization_id),
        "phase_af_health_qualification_id": str(lease.phase_af_health_qualification_id),
        "transition_lease_id": str(lease.transition_lease_id),
        "replica_id": str(lease.replica_id),
        "authorization_hash": lease.authorization_hash,
        "phase_af_health_qualification_hash": lease.phase_af_health_qualification_hash,
        "transition_lease_hash": lease.transition_lease_hash,
        "source_file_hash": lease.source_file_hash,
        "source_file_size_bytes": lease.source_file_size_bytes,
        "activation_snapshot_hash": lease.activation_snapshot_hash,
        "lease_hash": lease.lease_hash,
        "status": lease.status,
        "write_mode": route.write_mode,
        "route_version": route.route_version,
        "active_durable_write_ownership_lease_id": str(route.active_durable_write_ownership_lease_id) if route.active_durable_write_ownership_lease_id else None,
        "durable_write_ownership_active": lease.durable_write_ownership_active,
        "local_authoritative": True,
        "storage_write_performed": False,
        "durable_write_authority_created": route.durable_write_authority_created,
        "read_path_switched": False,
        "write_path_switched": route.write_path_switched,
        "document_storage_key_mutated": False,
        "authoritative_storage_changed": False,
        "destructive_action_performed": False,
        "s3_put_performed": False,
        "s3_copy_performed": False,
        "s3_delete_performed": False,
        "local_overwrite_performed": False,
        "local_move_performed": False,
        "local_delete_performed": False,
    }


def _operation(lease, route, receipt, outcome: str):
    return RecoveryDurableWriteOwnershipOperationRead(
        lease=RecoveryDurableWriteOwnershipLeaseRead.model_validate(lease),
        route=RecoveryDurableWriteOwnershipRouteRead.model_validate(route),
        receipt=RecoveryDurableWriteOwnershipReceiptRead.model_validate(receipt) if receipt else None,
        outcome=outcome,
    )


def _commit(db: Session, lease, route, receipt) -> None:
    db.commit()
    db.refresh(lease)
    db.refresh(route)
    if receipt is not None:
        db.refresh(receipt)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-write-ownership-leases",
    response_model=RecoveryDurableWriteOwnershipOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def activate_endpoint(
    claim_id: UUID,
    document_id: UUID,
    payload: RecoveryDurableWriteOwnershipActivationRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        lease, receipt, outcome = activate_durable_write_ownership(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=payload.authorization_id,
            activated_by_id=current_user.id,
            reason=payload.reason,
        )
        route = get_durable_write_ownership_route(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "activated": "EVIDENCE_RECOVERY_DURABLE_WRITE_OWNERSHIP_ACTIVATED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_WRITE_OWNERSHIP_ACTIVATION_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_durable_write_ownership_lease",
            entity_id=lease.id,
            new_values={**_audit_values(lease, route), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, lease, route, receipt)
    except (
        RecoveryDurableWriteOwnershipExecutionNotFound,
        RecoveryDurableWriteOwnershipExecutionConflict,
        RecoveryDurableWriteOwnershipExecutionUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase AH execution conflicts with immutable lineage") from exc
    return _operation(lease, route, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-write-ownership-leases/{lease_id}/rollback",
    response_model=RecoveryDurableWriteOwnershipOperationRead,
)
def rollback_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    payload: RecoveryDurableWriteOwnershipReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        lease, receipt, outcome = rollback_durable_write_ownership(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
            rolled_back_by_id=current_user.id,
            reason=payload.reason,
        )
        route = get_durable_write_ownership_route(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "rolled_back": "EVIDENCE_RECOVERY_DURABLE_WRITE_OWNERSHIP_ROLLED_BACK",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_WRITE_OWNERSHIP_ROLLBACK_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_durable_write_ownership_lease",
            entity_id=lease.id,
            new_values={**_audit_values(lease, route), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, lease, route, receipt)
    except (
        RecoveryDurableWriteOwnershipExecutionNotFound,
        RecoveryDurableWriteOwnershipExecutionConflict,
        RecoveryDurableWriteOwnershipExecutionUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(lease, route, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-write-ownership-leases/{lease_id}/reconcile",
    response_model=RecoveryDurableWriteOwnershipOperationRead,
)
def reconcile_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    payload: RecoveryDurableWriteOwnershipReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        lease, receipt, outcome = reconcile_durable_write_ownership(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
            actor_id=current_user.id,
            reason=payload.reason,
        )
        route = get_durable_write_ownership_route(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "invalidated": "EVIDENCE_RECOVERY_DURABLE_WRITE_OWNERSHIP_INVALIDATED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_WRITE_OWNERSHIP_RECONCILED",
            }[outcome],
            entity_type="evidence_recovery_durable_write_ownership_lease",
            entity_id=lease.id,
            new_values={**_audit_values(lease, route), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, lease, route, receipt)
    except (
        RecoveryDurableWriteOwnershipExecutionNotFound,
        RecoveryDurableWriteOwnershipExecutionConflict,
        RecoveryDurableWriteOwnershipExecutionUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(lease, route, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-write-ownership-leases/{lease_id}",
    response_model=RecoveryDurableWriteOwnershipLeaseRead,
)
def get_lease_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        lease = get_durable_write_ownership_lease(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
        )
    except RecoveryDurableWriteOwnershipExecutionNotFound as exc:
        raise _error(exc) from exc
    return RecoveryDurableWriteOwnershipLeaseRead.model_validate(lease)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-write-ownership-route",
    response_model=RecoveryDurableWriteOwnershipRouteRead,
)
def get_route_endpoint(
    claim_id: UUID,
    document_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        route = get_durable_write_ownership_route(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
    except RecoveryDurableWriteOwnershipExecutionNotFound as exc:
        raise _error(exc) from exc
    return RecoveryDurableWriteOwnershipRouteRead.model_validate(route)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-write-ownership-leases/{lease_id}/receipts",
    response_model=list[RecoveryDurableWriteOwnershipReceiptRead],
)
def list_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        receipts = list_durable_write_ownership_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
        )
    except RecoveryDurableWriteOwnershipExecutionNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryDurableWriteOwnershipReceiptRead.model_validate(item) for item in receipts]
