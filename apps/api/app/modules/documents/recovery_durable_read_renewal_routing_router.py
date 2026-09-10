from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_durable_read_renewal_routing_schemas import (
    RecoveryDurableReadRenewalLeaseRead,
    RecoveryDurableReadRenewalLeaseReason,
    RecoveryDurableReadRenewalOperationRead,
    RecoveryDurableReadRenewalReceiptRead,
    RecoveryDurableReadRenewalRouteRead,
)
from app.modules.documents.recovery_durable_read_renewal_routing_service import (
    RecoveryDurableReadRenewalRoutingConflict,
    RecoveryDurableReadRenewalRoutingNotFound,
    RecoveryDurableReadRenewalRoutingUnavailable,
    activate_recovery_durable_read_renewal_lease,
    get_recovery_durable_read_renewal_lease,
    list_recovery_durable_read_renewal_receipts,
    prepare_recovery_durable_read_renewal_lease,
    reconcile_recovery_durable_read_renewal_lease,
    rollback_recovery_durable_read_renewal_lease,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-durable-read-renewal-routing"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryDurableReadRenewalRoutingNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryDurableReadRenewalRoutingUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(lease, route) -> dict:
    return {
        "claim_id": str(lease.claim_id),
        "document_id": str(lease.document_id),
        "authorization_id": str(lease.authorization_id),
        "authorization_approval_receipt_id": str(lease.authorization_approval_receipt_id),
        "health_qualification_id": str(lease.health_qualification_id),
        "prior_durable_lease_id": str(lease.prior_durable_lease_id),
        "replica_id": str(lease.replica_id),
        "authorization_hash": lease.authorization_hash,
        "authorization_request_snapshot_hash": lease.authorization_request_snapshot_hash,
        "authorization_integrity_proof_hash": lease.authorization_integrity_proof_hash,
        "authorization_approval_receipt_hash": lease.authorization_approval_receipt_hash,
        "health_qualification_hash": lease.health_qualification_hash,
        "operational_evidence_hash": lease.operational_evidence_hash,
        "prior_durable_lease_hash": lease.prior_durable_lease_hash,
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
        "active_durable_renewal_lease_id": (
            str(route.active_durable_renewal_lease_id)
            if route.active_durable_renewal_lease_id is not None
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


def _operation(lease, route, receipt, outcome: str) -> RecoveryDurableReadRenewalOperationRead:
    return RecoveryDurableReadRenewalOperationRead(
        lease=RecoveryDurableReadRenewalLeaseRead.model_validate(lease),
        route=RecoveryDurableReadRenewalRouteRead.model_validate(route),
        receipt=(
            RecoveryDurableReadRenewalReceiptRead.model_validate(receipt)
            if receipt is not None
            else None
        ),
        outcome=outcome,
    )


def _commit_operation(db: Session, lease, route, receipt) -> None:
    db.commit()
    db.refresh(lease)
    db.refresh(route)
    if receipt is not None:
        db.refresh(receipt)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-renewal-authorizations/{authorization_id}/durable-read-renewal-lease",
    response_model=RecoveryDurableReadRenewalOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def prepare_durable_read_renewal_lease_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryDurableReadRenewalLeaseReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadRenewalOperationRead:
    try:
        lease, route, receipt, outcome = prepare_recovery_durable_read_renewal_lease(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
            prepared_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "prepared": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_PREPARED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_PREPARE_REPLAYED",
                "invalidated": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_durable_read_renewal_lease",
            entity_id=lease.id,
            new_values={**_audit_values(lease, route), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit_operation(db, lease, route, receipt)
    except (RecoveryDurableReadRenewalRoutingNotFound, RecoveryDurableReadRenewalRoutingConflict, RecoveryDurableReadRenewalRoutingUnavailable) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Durable read renewal lease conflicts with immutable lineage") from exc
    return _operation(lease, route, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-renewal-leases/{lease_id}/activate",
    response_model=RecoveryDurableReadRenewalOperationRead,
)
def activate_durable_read_renewal_lease_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    payload: RecoveryDurableReadRenewalLeaseReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadRenewalOperationRead:
    try:
        lease, route, receipt, outcome = activate_recovery_durable_read_renewal_lease(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
            activated_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "activated": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_ACTIVATED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_ACTIVATION_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_durable_read_renewal_lease",
            entity_id=lease.id,
            new_values={**_audit_values(lease, route), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit_operation(db, lease, route, receipt)
    except (RecoveryDurableReadRenewalRoutingNotFound, RecoveryDurableReadRenewalRoutingConflict, RecoveryDurableReadRenewalRoutingUnavailable) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(lease, route, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-renewal-leases/{lease_id}/rollback",
    response_model=RecoveryDurableReadRenewalOperationRead,
)
def rollback_durable_read_renewal_lease_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    payload: RecoveryDurableReadRenewalLeaseReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadRenewalOperationRead:
    try:
        lease, route, receipt, outcome = rollback_recovery_durable_read_renewal_lease(
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
                "rolled_back": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_ROLLED_BACK",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_ROLLBACK_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_durable_read_renewal_lease",
            entity_id=lease.id,
            new_values={**_audit_values(lease, route), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit_operation(db, lease, route, receipt)
    except (RecoveryDurableReadRenewalRoutingNotFound, RecoveryDurableReadRenewalRoutingConflict, RecoveryDurableReadRenewalRoutingUnavailable) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(lease, route, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-renewal-leases/{lease_id}/reconcile",
    response_model=RecoveryDurableReadRenewalOperationRead,
)
def reconcile_durable_read_renewal_lease_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    payload: RecoveryDurableReadRenewalLeaseReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadRenewalOperationRead:
    try:
        lease, route, receipt, outcome = reconcile_recovery_durable_read_renewal_lease(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
            reconciled_by_id=current_user.id,
            reason=payload.reason,
        )
        write_audit_log(
            db,
            organization_id=current_user.organization_id,
            user_id=current_user.id,
            action={
                "expired": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_RECONCILED_EXPIRED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_RENEWAL_RECONCILED_HEALTHY",
            }[outcome],
            entity_type="evidence_recovery_durable_read_renewal_lease",
            entity_id=lease.id,
            new_values={**_audit_values(lease, route), "receipt_hash": receipt.receipt_hash if receipt else None, "outcome": outcome},
        )
        _commit_operation(db, lease, route, receipt)
    except (RecoveryDurableReadRenewalRoutingNotFound, RecoveryDurableReadRenewalRoutingConflict, RecoveryDurableReadRenewalRoutingUnavailable) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(lease, route, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-renewal-leases/{lease_id}",
    response_model=RecoveryDurableReadRenewalLeaseRead,
)
def get_durable_read_renewal_lease_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryDurableReadRenewalLeaseRead:
    try:
        lease = get_recovery_durable_read_renewal_lease(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
        )
    except RecoveryDurableReadRenewalRoutingNotFound as exc:
        raise _error(exc) from exc
    return RecoveryDurableReadRenewalLeaseRead.model_validate(lease)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-renewal-leases/{lease_id}/receipts",
    response_model=list[RecoveryDurableReadRenewalReceiptRead],
)
def list_durable_read_renewal_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RecoveryDurableReadRenewalReceiptRead]:
    try:
        receipts = list_recovery_durable_read_renewal_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
        )
    except RecoveryDurableReadRenewalRoutingNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryDurableReadRenewalReceiptRead.model_validate(item) for item in receipts]
