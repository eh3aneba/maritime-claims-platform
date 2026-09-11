from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_read_ownership_transition_routing_schemas import (
    RecoveryReadOwnershipTransitionLeaseRead,
    RecoveryReadOwnershipTransitionLeaseReason,
    RecoveryReadOwnershipTransitionOperationRead,
    RecoveryReadOwnershipTransitionReceiptRead,
    RecoveryReadOwnershipTransitionRouteRead,
)
from app.modules.documents.recovery_read_ownership_transition_routing_service import (
    RecoveryReadOwnershipTransitionRoutingConflict,
    RecoveryReadOwnershipTransitionRoutingNotFound,
    RecoveryReadOwnershipTransitionRoutingUnavailable,
    activate_recovery_read_ownership_transition_lease,
    get_recovery_read_ownership_transition_lease,
    list_recovery_read_ownership_transition_receipts,
    prepare_recovery_read_ownership_transition_lease,
    reconcile_recovery_read_ownership_transition_lease,
    rollback_recovery_read_ownership_transition_lease,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-read-ownership-transition-routing"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryReadOwnershipTransitionRoutingNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryReadOwnershipTransitionRoutingUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(lease, route) -> dict:
    return {
        "claim_id": str(lease.claim_id),
        "document_id": str(lease.document_id),
        "authorization_id": str(lease.authorization_id),
        "authorization_approval_receipt_id": str(lease.authorization_approval_receipt_id),
        "phase_t_health_qualification_id": str(lease.phase_t_health_qualification_id),
        "replica_id": str(lease.replica_id),
        "authorization_hash": lease.authorization_hash,
        "authorization_request_snapshot_hash": lease.authorization_request_snapshot_hash,
        "authorization_integrity_proof_hash": lease.authorization_integrity_proof_hash,
        "authorization_approval_receipt_hash": lease.authorization_approval_receipt_hash,
        "phase_t_health_qualification_hash": lease.phase_t_health_qualification_hash,
        "operational_evidence_hash": lease.operational_evidence_hash,
        "replica_hash": lease.replica_hash,
        "source_file_hash": lease.source_file_hash,
        "source_file_size_bytes": lease.source_file_size_bytes,
        "local_storage_key_fingerprint": lease.local_storage_key_fingerprint,
        "recovery_bucket_fingerprint": lease.recovery_bucket_fingerprint,
        "candidate_storage_key_fingerprint": lease.candidate_storage_key_fingerprint,
        "source_authority_fingerprint": lease.source_authority_fingerprint,
        "candidate_authority_fingerprint": lease.candidate_authority_fingerprint,
        "configuration_fingerprint": lease.configuration_fingerprint,
        "integrity_proof_hash": lease.integrity_proof_hash,
        "lease_snapshot_hash": lease.lease_snapshot_hash,
        "lease_hash": lease.lease_hash,
        "lease_status": lease.status,
        "route_class": route.route_class,
        "route_authority_kind": route.route_authority_kind,
        "route_version": route.route_version,
        "active_read_ownership_transition_lease_id": (
            str(route.active_read_ownership_transition_lease_id)
            if route.active_read_ownership_transition_lease_id is not None
            else None
        ),
        "routable_authority_created": lease.routable_authority_created,
        "durable_read_route_created": lease.durable_read_route_created,
        "read_ownership_authority_created": lease.read_ownership_authority_created,
        "read_path_switched": lease.read_path_switched,
        "write_path_switched": False,
        "document_storage_key_mutated": False,
        "authoritative_storage_changed": False,
        "destructive_action_performed": False,
        "s3_delete_performed": False,
        "local_delete_performed": False,
    }


def _operation(lease, route, receipt, outcome: str) -> RecoveryReadOwnershipTransitionOperationRead:
    return RecoveryReadOwnershipTransitionOperationRead(
        lease=RecoveryReadOwnershipTransitionLeaseRead.model_validate(lease),
        route=RecoveryReadOwnershipTransitionRouteRead.model_validate(route),
        receipt=(RecoveryReadOwnershipTransitionReceiptRead.model_validate(receipt) if receipt is not None else None),
        outcome=outcome,
    )


def _commit(db: Session, lease, route, receipt) -> None:
    db.commit()
    db.refresh(lease)
    db.refresh(route)
    if receipt is not None:
        db.refresh(receipt)


def _write_operation_audit(db: Session, current_user, lease, route, receipt, outcome: str, actions: dict[str, str]) -> None:
    write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action=actions[outcome],
        entity_type="evidence_recovery_read_ownership_transition_lease",
        entity_id=lease.id,
        new_values={
            **_audit_values(lease, route),
            "receipt_hash": receipt.receipt_hash if receipt else None,
            "outcome": outcome,
        },
    )


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-read-ownership-transition-authorizations/{authorization_id}/transition-lease",
    response_model=RecoveryReadOwnershipTransitionOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def prepare_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryReadOwnershipTransitionLeaseReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryReadOwnershipTransitionOperationRead:
    try:
        lease, route, receipt, outcome = prepare_recovery_read_ownership_transition_lease(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
            prepared_by_id=current_user.id,
            reason=payload.reason,
        )
        _write_operation_audit(db, current_user, lease, route, receipt, outcome, {
            "prepared": "EVIDENCE_RECOVERY_READ_OWNERSHIP_TRANSITION_PREPARED",
            "unchanged": "EVIDENCE_RECOVERY_READ_OWNERSHIP_TRANSITION_PREPARE_REPLAYED",
        })
        _commit(db, lease, route, receipt)
    except (
        RecoveryReadOwnershipTransitionRoutingNotFound,
        RecoveryReadOwnershipTransitionRoutingConflict,
        RecoveryReadOwnershipTransitionRoutingUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase V lease conflicts with immutable lineage") from exc
    return _operation(lease, route, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-read-ownership-transition-leases/{lease_id}/activate",
    response_model=RecoveryReadOwnershipTransitionOperationRead,
)
def activate_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    payload: RecoveryReadOwnershipTransitionLeaseReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryReadOwnershipTransitionOperationRead:
    try:
        lease, route, receipt, outcome = activate_recovery_read_ownership_transition_lease(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
            activated_by_id=current_user.id,
            reason=payload.reason,
        )
        _write_operation_audit(db, current_user, lease, route, receipt, outcome, {
            "activated": "EVIDENCE_RECOVERY_READ_OWNERSHIP_TRANSITION_ACTIVATED",
            "unchanged": "EVIDENCE_RECOVERY_READ_OWNERSHIP_TRANSITION_ACTIVATION_REPLAYED",
            "expired": "EVIDENCE_RECOVERY_READ_OWNERSHIP_TRANSITION_EXPIRED",
            "invalidated": "EVIDENCE_RECOVERY_READ_OWNERSHIP_TRANSITION_INVALIDATED",
        })
        _commit(db, lease, route, receipt)
    except (
        RecoveryReadOwnershipTransitionRoutingNotFound,
        RecoveryReadOwnershipTransitionRoutingConflict,
        RecoveryReadOwnershipTransitionRoutingUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(lease, route, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-read-ownership-transition-leases/{lease_id}/rollback",
    response_model=RecoveryReadOwnershipTransitionOperationRead,
)
def rollback_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    payload: RecoveryReadOwnershipTransitionLeaseReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryReadOwnershipTransitionOperationRead:
    try:
        lease, route, receipt, outcome = rollback_recovery_read_ownership_transition_lease(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
            rolled_back_by_id=current_user.id,
            reason=payload.reason,
        )
        _write_operation_audit(db, current_user, lease, route, receipt, outcome, {
            "rolled_back": "EVIDENCE_RECOVERY_READ_OWNERSHIP_TRANSITION_ROLLED_BACK",
            "unchanged": "EVIDENCE_RECOVERY_READ_OWNERSHIP_TRANSITION_ROLLBACK_REPLAYED",
        })
        _commit(db, lease, route, receipt)
    except (
        RecoveryReadOwnershipTransitionRoutingNotFound,
        RecoveryReadOwnershipTransitionRoutingConflict,
        RecoveryReadOwnershipTransitionRoutingUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(lease, route, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-read-ownership-transition-leases/{lease_id}/reconcile",
    response_model=RecoveryReadOwnershipTransitionOperationRead,
)
def reconcile_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    payload: RecoveryReadOwnershipTransitionLeaseReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryReadOwnershipTransitionOperationRead:
    try:
        lease, route, receipt, outcome = reconcile_recovery_read_ownership_transition_lease(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
            reconciled_by_id=current_user.id,
            reason=payload.reason,
        )
        _write_operation_audit(db, current_user, lease, route, receipt, outcome, {
            "expired": "EVIDENCE_RECOVERY_READ_OWNERSHIP_TRANSITION_RECONCILED_EXPIRED",
            "unchanged": "EVIDENCE_RECOVERY_READ_OWNERSHIP_TRANSITION_RECONCILED_HEALTHY",
        })
        _commit(db, lease, route, receipt)
    except (
        RecoveryReadOwnershipTransitionRoutingNotFound,
        RecoveryReadOwnershipTransitionRoutingConflict,
        RecoveryReadOwnershipTransitionRoutingUnavailable,
    ) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(lease, route, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-read-ownership-transition-leases/{lease_id}",
    response_model=RecoveryReadOwnershipTransitionLeaseRead,
)
def get_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryReadOwnershipTransitionLeaseRead:
    try:
        lease = get_recovery_read_ownership_transition_lease(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
        )
    except RecoveryReadOwnershipTransitionRoutingNotFound as exc:
        raise _error(exc) from exc
    return RecoveryReadOwnershipTransitionLeaseRead.model_validate(lease)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-read-ownership-transition-leases/{lease_id}/receipts",
    response_model=list[RecoveryReadOwnershipTransitionReceiptRead],
)
def receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RecoveryReadOwnershipTransitionReceiptRead]:
    try:
        receipts = list_recovery_read_ownership_transition_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
        )
    except RecoveryReadOwnershipTransitionRoutingNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryReadOwnershipTransitionReceiptRead.model_validate(item) for item in receipts]
