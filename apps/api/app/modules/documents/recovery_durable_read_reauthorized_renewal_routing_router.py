from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_durable_read_reauthorized_renewal_routing_schemas import (
    RecoveryDurableReadReauthorizedRenewalLeaseRead,
    RecoveryDurableReadReauthorizedRenewalLeaseReason,
    RecoveryDurableReadReauthorizedRenewalOperationRead,
    RecoveryDurableReadReauthorizedRenewalReceiptRead,
    RecoveryDurableReadReauthorizedRenewalRouteRead,
)
from app.modules.documents.recovery_durable_read_reauthorized_renewal_routing_service import (
    RecoveryDurableReadReauthorizedRenewalRoutingConflict,
    RecoveryDurableReadReauthorizedRenewalRoutingNotFound,
    RecoveryDurableReadReauthorizedRenewalRoutingUnavailable,
    activate_recovery_durable_read_reauthorized_renewal_lease,
    get_recovery_durable_read_reauthorized_renewal_lease,
    list_recovery_durable_read_reauthorized_renewal_receipts,
    prepare_recovery_durable_read_reauthorized_renewal_lease,
    reconcile_recovery_durable_read_reauthorized_renewal_lease,
    rollback_recovery_durable_read_reauthorized_renewal_lease,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-durable-read-reauthorized-renewal-routing"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryDurableReadReauthorizedRenewalRoutingNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryDurableReadReauthorizedRenewalRoutingUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(lease, route) -> dict:
    return {
        "claim_id": str(lease.claim_id),
        "document_id": str(lease.document_id),
        "reauthorization_id": str(lease.reauthorization_id),
        "reauthorization_approval_receipt_id": str(lease.reauthorization_approval_receipt_id),
        "phase_q_health_qualification_id": str(lease.phase_q_health_qualification_id),
        "prior_renewal_lease_id": str(lease.prior_renewal_lease_id),
        "replica_id": str(lease.replica_id),
        "reauthorization_hash": lease.reauthorization_hash,
        "reauthorization_request_snapshot_hash": lease.reauthorization_request_snapshot_hash,
        "reauthorization_integrity_proof_hash": lease.reauthorization_integrity_proof_hash,
        "reauthorization_approval_receipt_hash": lease.reauthorization_approval_receipt_hash,
        "phase_q_health_qualification_hash": lease.phase_q_health_qualification_hash,
        "operational_evidence_hash": lease.operational_evidence_hash,
        "prior_renewal_lease_hash": lease.prior_renewal_lease_hash,
        "prior_lease_snapshot_hash": lease.prior_lease_snapshot_hash,
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
        "active_durable_reauthorized_renewal_lease_id": (
            str(route.active_durable_reauthorized_renewal_lease_id)
            if route.active_durable_reauthorized_renewal_lease_id is not None
            else None
        ),
        "routable_authority_created": lease.routable_authority_created,
        "durable_read_route_created": lease.durable_read_route_created,
        "read_path_switched": lease.read_path_switched,
        "write_path_switched": False,
        "document_storage_key_mutated": False,
        "authoritative_storage_changed": False,
        "destructive_action_performed": False,
        "s3_delete_performed": False,
        "local_delete_performed": False,
    }


def _operation(lease, route, receipt, outcome: str) -> RecoveryDurableReadReauthorizedRenewalOperationRead:
    return RecoveryDurableReadReauthorizedRenewalOperationRead(
        lease=RecoveryDurableReadReauthorizedRenewalLeaseRead.model_validate(lease),
        route=RecoveryDurableReadReauthorizedRenewalRouteRead.model_validate(route),
        receipt=(RecoveryDurableReadReauthorizedRenewalReceiptRead.model_validate(receipt) if receipt is not None else None),
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
        entity_type="evidence_recovery_durable_read_reauthorized_renewal_lease",
        entity_id=lease.id,
        new_values={**_audit_values(lease, route), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
    )


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-renewal-reauthorizations/{authorization_id}/reauthorized-renewal-lease",
    response_model=RecoveryDurableReadReauthorizedRenewalOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def prepare_endpoint(claim_id: UUID, document_id: UUID, authorization_id: UUID, payload: RecoveryDurableReadReauthorizedRenewalLeaseReason, db: Annotated[Session, Depends(get_db)], current_user: RetentionAdminMfa) -> RecoveryDurableReadReauthorizedRenewalOperationRead:
    try:
        lease, route, receipt, outcome = prepare_recovery_durable_read_reauthorized_renewal_lease(
            db, organization_id=current_user.organization_id, claim_id=claim_id, document_id=document_id,
            reauthorization_id=authorization_id, prepared_by_id=current_user.id, reason=payload.reason,
        )
        _write_operation_audit(db, current_user, lease, route, receipt, outcome, {
            "prepared": "EVIDENCE_RECOVERY_DURABLE_READ_REAUTHORIZED_RENEWAL_PREPARED",
            "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_REAUTHORIZED_RENEWAL_PREPARE_REPLAYED",
            "invalidated": "EVIDENCE_RECOVERY_DURABLE_READ_REAUTHORIZED_RENEWAL_INVALIDATED",
        })
        _commit(db, lease, route, receipt)
    except (RecoveryDurableReadReauthorizedRenewalRoutingNotFound, RecoveryDurableReadReauthorizedRenewalRoutingConflict, RecoveryDurableReadReauthorizedRenewalRoutingUnavailable) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Phase S lease conflicts with immutable lineage") from exc
    return _operation(lease, route, receipt, outcome)


@router.post("/{claim_id}/documents/{document_id}/recovery-durable-read-reauthorized-renewal-leases/{lease_id}/activate", response_model=RecoveryDurableReadReauthorizedRenewalOperationRead)
def activate_endpoint(claim_id: UUID, document_id: UUID, lease_id: UUID, payload: RecoveryDurableReadReauthorizedRenewalLeaseReason, db: Annotated[Session, Depends(get_db)], current_user: RetentionAdminMfa) -> RecoveryDurableReadReauthorizedRenewalOperationRead:
    try:
        lease, route, receipt, outcome = activate_recovery_durable_read_reauthorized_renewal_lease(
            db, organization_id=current_user.organization_id, claim_id=claim_id, document_id=document_id,
            lease_id=lease_id, activated_by_id=current_user.id, reason=payload.reason,
        )
        _write_operation_audit(db, current_user, lease, route, receipt, outcome, {
            "activated": "EVIDENCE_RECOVERY_DURABLE_READ_REAUTHORIZED_RENEWAL_ACTIVATED",
            "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_REAUTHORIZED_RENEWAL_ACTIVATION_REPLAYED",
            "expired": "EVIDENCE_RECOVERY_DURABLE_READ_REAUTHORIZED_RENEWAL_EXPIRED",
            "invalidated": "EVIDENCE_RECOVERY_DURABLE_READ_REAUTHORIZED_RENEWAL_INVALIDATED",
        })
        _commit(db, lease, route, receipt)
    except (RecoveryDurableReadReauthorizedRenewalRoutingNotFound, RecoveryDurableReadReauthorizedRenewalRoutingConflict, RecoveryDurableReadReauthorizedRenewalRoutingUnavailable) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(lease, route, receipt, outcome)


@router.post("/{claim_id}/documents/{document_id}/recovery-durable-read-reauthorized-renewal-leases/{lease_id}/rollback", response_model=RecoveryDurableReadReauthorizedRenewalOperationRead)
def rollback_endpoint(claim_id: UUID, document_id: UUID, lease_id: UUID, payload: RecoveryDurableReadReauthorizedRenewalLeaseReason, db: Annotated[Session, Depends(get_db)], current_user: RetentionAdminMfa) -> RecoveryDurableReadReauthorizedRenewalOperationRead:
    try:
        lease, route, receipt, outcome = rollback_recovery_durable_read_reauthorized_renewal_lease(
            db, organization_id=current_user.organization_id, claim_id=claim_id, document_id=document_id,
            lease_id=lease_id, rolled_back_by_id=current_user.id, reason=payload.reason,
        )
        _write_operation_audit(db, current_user, lease, route, receipt, outcome, {
            "rolled_back": "EVIDENCE_RECOVERY_DURABLE_READ_REAUTHORIZED_RENEWAL_ROLLED_BACK",
            "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_REAUTHORIZED_RENEWAL_ROLLBACK_REPLAYED",
        })
        _commit(db, lease, route, receipt)
    except (RecoveryDurableReadReauthorizedRenewalRoutingNotFound, RecoveryDurableReadReauthorizedRenewalRoutingConflict, RecoveryDurableReadReauthorizedRenewalRoutingUnavailable) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(lease, route, receipt, outcome)


@router.post("/{claim_id}/documents/{document_id}/recovery-durable-read-reauthorized-renewal-leases/{lease_id}/reconcile", response_model=RecoveryDurableReadReauthorizedRenewalOperationRead)
def reconcile_endpoint(claim_id: UUID, document_id: UUID, lease_id: UUID, payload: RecoveryDurableReadReauthorizedRenewalLeaseReason, db: Annotated[Session, Depends(get_db)], current_user: RetentionAdminMfa) -> RecoveryDurableReadReauthorizedRenewalOperationRead:
    try:
        lease, route, receipt, outcome = reconcile_recovery_durable_read_reauthorized_renewal_lease(
            db, organization_id=current_user.organization_id, claim_id=claim_id, document_id=document_id,
            lease_id=lease_id, reconciled_by_id=current_user.id, reason=payload.reason,
        )
        _write_operation_audit(db, current_user, lease, route, receipt, outcome, {
            "expired": "EVIDENCE_RECOVERY_DURABLE_READ_REAUTHORIZED_RENEWAL_RECONCILED_EXPIRED",
            "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_REAUTHORIZED_RENEWAL_RECONCILED_HEALTHY",
        })
        _commit(db, lease, route, receipt)
    except (RecoveryDurableReadReauthorizedRenewalRoutingNotFound, RecoveryDurableReadReauthorizedRenewalRoutingConflict, RecoveryDurableReadReauthorizedRenewalRoutingUnavailable) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(lease, route, receipt, outcome)


@router.get("/{claim_id}/documents/{document_id}/recovery-durable-read-reauthorized-renewal-leases/{lease_id}", response_model=RecoveryDurableReadReauthorizedRenewalLeaseRead)
def get_endpoint(claim_id: UUID, document_id: UUID, lease_id: UUID, db: Annotated[Session, Depends(get_db)], current_user: RetentionReader) -> RecoveryDurableReadReauthorizedRenewalLeaseRead:
    try:
        lease = get_recovery_durable_read_reauthorized_renewal_lease(
            db, organization_id=current_user.organization_id, claim_id=claim_id, document_id=document_id, lease_id=lease_id,
        )
    except RecoveryDurableReadReauthorizedRenewalRoutingNotFound as exc:
        raise _error(exc) from exc
    return RecoveryDurableReadReauthorizedRenewalLeaseRead.model_validate(lease)


@router.get("/{claim_id}/documents/{document_id}/recovery-durable-read-reauthorized-renewal-leases/{lease_id}/receipts", response_model=list[RecoveryDurableReadReauthorizedRenewalReceiptRead])
def receipts_endpoint(claim_id: UUID, document_id: UUID, lease_id: UUID, db: Annotated[Session, Depends(get_db)], current_user: RetentionReader) -> list[RecoveryDurableReadReauthorizedRenewalReceiptRead]:
    try:
        receipts = list_recovery_durable_read_reauthorized_renewal_receipts(
            db, organization_id=current_user.organization_id, claim_id=claim_id, document_id=document_id, lease_id=lease_id,
        )
    except RecoveryDurableReadReauthorizedRenewalRoutingNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryDurableReadReauthorizedRenewalReceiptRead.model_validate(item) for item in receipts]
