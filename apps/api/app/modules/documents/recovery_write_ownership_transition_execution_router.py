from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_write_ownership_transition_authorization_service import (
    RecoveryWriteOwnershipTransitionAuthorizationNotFound,
)
from app.modules.documents.recovery_write_ownership_transition_execution_schemas import (
    RecoveryWriteOwnershipTransitionExecutionReason,
    RecoveryWriteOwnershipTransitionLeaseRead,
    RecoveryWriteOwnershipTransitionOperationRead,
    RecoveryWriteOwnershipTransitionReceiptRead,
)
from app.modules.documents.recovery_write_ownership_transition_execution_service import (
    RecoveryWriteOwnershipTransitionExecutionConflict,
    RecoveryWriteOwnershipTransitionExecutionNotFound,
    RecoveryWriteOwnershipTransitionExecutionUnavailable,
    activate_recovery_write_ownership_transition,
    get_recovery_write_ownership_transition_lease,
    list_recovery_write_ownership_transition_receipts,
    reconcile_recovery_write_ownership_transition,
    rollback_recovery_write_ownership_transition,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-write-ownership-transition-execution"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(
        exc,
        (
            RecoveryWriteOwnershipTransitionExecutionNotFound,
            RecoveryWriteOwnershipTransitionAuthorizationNotFound,
        ),
    ):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryWriteOwnershipTransitionExecutionUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(lease) -> dict:
    return {
        "claim_id": str(lease.claim_id),
        "document_id": str(lease.document_id),
        "authorization_id": str(lease.authorization_id),
        "authorization_approval_receipt_id": str(lease.authorization_approval_receipt_id),
        "phase_ac_health_qualification_id": str(lease.phase_ac_health_qualification_id),
        "canary_lease_id": str(lease.canary_lease_id),
        "replica_id": str(lease.replica_id),
        "authorization_hash": lease.authorization_hash,
        "authorization_approval_receipt_hash": lease.authorization_approval_receipt_hash,
        "activation_snapshot_hash": lease.activation_snapshot_hash,
        "lease_hash": lease.lease_hash,
        "source_file_hash": lease.source_file_hash,
        "source_file_size_bytes": lease.source_file_size_bytes,
        "observed_replica_hash": lease.observed_replica_hash,
        "observed_replica_size_bytes": lease.observed_replica_size_bytes,
        "read_route_version_at_activation": lease.read_route_version_at_activation,
        "write_route_version_before_activation": lease.write_route_version_before_activation,
        "write_route_version_after_activation": lease.write_route_version_after_activation,
        "status": lease.status,
        "route_expires_at": lease.route_expires_at.isoformat(),
        "bounded_write_ownership_transition_active": lease.bounded_write_ownership_transition_active,
        "local_authoritative": True,
        "storage_write_performed": False,
        "durable_write_authority_created": False,
        "read_path_switched": False,
        "write_path_switched": lease.write_path_switched,
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


def _operation(lease, receipt, outcome: str):
    return RecoveryWriteOwnershipTransitionOperationRead(
        lease=RecoveryWriteOwnershipTransitionLeaseRead.model_validate(lease),
        receipt=RecoveryWriteOwnershipTransitionReceiptRead.model_validate(receipt) if receipt else None,
        outcome=outcome,
    )


def _commit(db: Session, lease, receipt) -> None:
    db.commit()
    db.refresh(lease)
    if receipt is not None:
        db.refresh(receipt)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-write-ownership-transition-authorizations/{authorization_id}/activate",
    response_model=RecoveryWriteOwnershipTransitionOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def activate_write_ownership_transition_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryWriteOwnershipTransitionExecutionReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        lease, receipt, outcome = activate_recovery_write_ownership_transition(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
            activated_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "activated": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_ACTIVATED",
                "unchanged": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_ACTIVATION_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_write_ownership_transition_lease",
            entity_id=lease.id,
            new_values={**_audit_values(lease), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, lease, receipt)
    except (
        RecoveryWriteOwnershipTransitionAuthorizationNotFound,
        RecoveryWriteOwnershipTransitionExecutionNotFound,
        RecoveryWriteOwnershipTransitionExecutionConflict,
        RecoveryWriteOwnershipTransitionExecutionUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Phase AE transition conflicts with immutable authorization or route lineage",
        ) from exc
    return _operation(lease, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-write-ownership-transition-leases/{lease_id}/rollback",
    response_model=RecoveryWriteOwnershipTransitionOperationRead,
)
def rollback_write_ownership_transition_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    payload: RecoveryWriteOwnershipTransitionExecutionReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        lease, receipt, outcome = rollback_recovery_write_ownership_transition(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
            rolled_back_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "rolled_back": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_ROLLED_BACK",
                "unchanged": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_ROLLBACK_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_write_ownership_transition_lease",
            entity_id=lease.id,
            new_values={**_audit_values(lease), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, lease, receipt)
    except (
        RecoveryWriteOwnershipTransitionExecutionNotFound,
        RecoveryWriteOwnershipTransitionExecutionConflict,
        RecoveryWriteOwnershipTransitionExecutionUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(lease, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-write-ownership-transition-leases/{lease_id}/reconcile",
    response_model=RecoveryWriteOwnershipTransitionOperationRead,
)
def reconcile_write_ownership_transition_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    payload: RecoveryWriteOwnershipTransitionExecutionReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
):
    try:
        lease, receipt, outcome = reconcile_recovery_write_ownership_transition(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
            actor_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "expired": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_INVALIDATED",
                "unchanged": "EVIDENCE_RECOVERY_WRITE_OWNERSHIP_TRANSITION_RECONCILED_UNCHANGED",
            }[outcome],
            entity_type="evidence_recovery_write_ownership_transition_lease",
            entity_id=lease.id,
            new_values={**_audit_values(lease), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit(db, lease, receipt)
    except (
        RecoveryWriteOwnershipTransitionExecutionNotFound,
        RecoveryWriteOwnershipTransitionExecutionConflict,
        RecoveryWriteOwnershipTransitionExecutionUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(lease, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-write-ownership-transition-leases/{lease_id}",
    response_model=RecoveryWriteOwnershipTransitionLeaseRead,
)
def get_write_ownership_transition_lease_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        lease = get_recovery_write_ownership_transition_lease(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
        )
    except RecoveryWriteOwnershipTransitionExecutionNotFound as exc:
        raise _error(exc) from exc
    return RecoveryWriteOwnershipTransitionLeaseRead.model_validate(lease)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-write-ownership-transition-leases/{lease_id}/receipts",
    response_model=list[RecoveryWriteOwnershipTransitionReceiptRead],
)
def list_write_ownership_transition_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
):
    try:
        receipts = list_recovery_write_ownership_transition_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
        )
    except RecoveryWriteOwnershipTransitionExecutionNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryWriteOwnershipTransitionReceiptRead.model_validate(item) for item in receipts]
