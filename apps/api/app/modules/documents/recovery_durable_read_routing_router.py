from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_durable_read_routing_schemas import (
    RecoveryDurableReadPromotionLeaseRead,
    RecoveryDurableReadPromotionLeaseReason,
    RecoveryDurableReadPromotionOperationRead,
    RecoveryDurableReadPromotionReceiptRead,
    RecoveryReadPathRouteRead,
)
from app.modules.documents.recovery_durable_read_routing_service import (
    RecoveryDurableReadRoutingConflict,
    RecoveryDurableReadRoutingNotFound,
    RecoveryDurableReadRoutingUnavailable,
    activate_recovery_durable_read_promotion_lease,
    get_recovery_durable_read_promotion_lease,
    list_recovery_durable_read_promotion_receipts,
    prepare_recovery_durable_read_promotion_lease,
    reconcile_recovery_durable_read_promotion_lease,
    rollback_recovery_durable_read_promotion_lease,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-durable-read-routing"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryDurableReadRoutingNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryDurableReadRoutingUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _audit_values(lease, route) -> dict:
    return {
        "claim_id": str(lease.claim_id),
        "document_id": str(lease.document_id),
        "authorization_id": str(lease.authorization_id),
        "authorization_approval_receipt_id": str(lease.authorization_approval_receipt_id),
        "qualification_id": str(lease.qualification_id),
        "replica_id": str(lease.replica_id),
        "authorization_hash": lease.authorization_hash,
        "authorization_request_snapshot_hash": lease.authorization_request_snapshot_hash,
        "authorization_integrity_proof_hash": lease.authorization_integrity_proof_hash,
        "authorization_approval_receipt_hash": lease.authorization_approval_receipt_hash,
        "qualification_hash": lease.qualification_hash,
        "qualification_bundle_hash": lease.qualification_bundle_hash,
        "replica_hash": lease.replica_hash,
        "source_file_hash": lease.source_file_hash,
        "source_file_size_bytes": lease.source_file_size_bytes,
        "local_storage_key_fingerprint": lease.local_storage_key_fingerprint,
        "recovery_bucket_fingerprint": lease.recovery_bucket_fingerprint,
        "candidate_storage_key_fingerprint": lease.candidate_storage_key_fingerprint,
        "source_authority_fingerprint": lease.source_authority_fingerprint,
        "candidate_authority_fingerprint": lease.candidate_authority_fingerprint,
        "configuration_fingerprint": lease.configuration_fingerprint,
        "lease_snapshot_hash": lease.lease_snapshot_hash,
        "lease_hash": lease.lease_hash,
        "lease_status": lease.status,
        "route_class": route.route_class,
        "route_authority_kind": route.route_authority_kind,
        "route_version": route.route_version,
        "active_durable_lease_id": (
            str(route.active_durable_lease_id)
            if route.active_durable_lease_id is not None
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


def _operation(lease, route, receipt, outcome: str) -> RecoveryDurableReadPromotionOperationRead:
    return RecoveryDurableReadPromotionOperationRead(
        lease=RecoveryDurableReadPromotionLeaseRead.model_validate(lease),
        route=RecoveryReadPathRouteRead.model_validate(route),
        receipt=(
            RecoveryDurableReadPromotionReceiptRead.model_validate(receipt)
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
    "/{claim_id}/documents/{document_id}/recovery-durable-read-promotion-authorizations/{authorization_id}/durable-read-routing-lease",
    response_model=RecoveryDurableReadPromotionOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def prepare_durable_read_routing_lease_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryDurableReadPromotionLeaseReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadPromotionOperationRead:
    try:
        lease, route, receipt, outcome = prepare_recovery_durable_read_promotion_lease(
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
                "prepared": "EVIDENCE_RECOVERY_DURABLE_READ_ROUTE_PREPARED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_ROUTE_PREPARE_REPLAYED",
                "invalidated": "EVIDENCE_RECOVERY_DURABLE_READ_ROUTE_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_durable_read_promotion_lease",
            entity_id=lease.id,
            new_values={
                **_audit_values(lease, route),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        _commit_operation(db, lease, route, receipt)
    except (RecoveryDurableReadRoutingNotFound, RecoveryDurableReadRoutingConflict, RecoveryDurableReadRoutingUnavailable) as exc:
        db.rollback()
        raise _error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Durable read routing lease conflicts with immutable lineage") from exc
    return _operation(lease, route, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-promotion-leases/{lease_id}/activate",
    response_model=RecoveryDurableReadPromotionOperationRead,
)
def activate_durable_read_routing_lease_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    payload: RecoveryDurableReadPromotionLeaseReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadPromotionOperationRead:
    try:
        lease, route, receipt, outcome = activate_recovery_durable_read_promotion_lease(
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
                "activated": "EVIDENCE_RECOVERY_DURABLE_READ_ROUTE_ACTIVATED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_ROUTE_ACTIVATION_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_DURABLE_READ_ROUTE_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_DURABLE_READ_ROUTE_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_durable_read_promotion_lease",
            entity_id=lease.id,
            new_values={
                **_audit_values(lease, route),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        _commit_operation(db, lease, route, receipt)
    except (RecoveryDurableReadRoutingNotFound, RecoveryDurableReadRoutingConflict, RecoveryDurableReadRoutingUnavailable) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(lease, route, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-promotion-leases/{lease_id}/rollback",
    response_model=RecoveryDurableReadPromotionOperationRead,
)
def rollback_durable_read_routing_lease_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    payload: RecoveryDurableReadPromotionLeaseReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadPromotionOperationRead:
    try:
        lease, route, receipt, outcome = rollback_recovery_durable_read_promotion_lease(
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
                "rolled_back": "EVIDENCE_RECOVERY_DURABLE_READ_ROUTE_ROLLED_BACK",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_ROUTE_ROLLBACK_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_durable_read_promotion_lease",
            entity_id=lease.id,
            new_values={
                **_audit_values(lease, route),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        _commit_operation(db, lease, route, receipt)
    except (RecoveryDurableReadRoutingNotFound, RecoveryDurableReadRoutingConflict, RecoveryDurableReadRoutingUnavailable) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(lease, route, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-promotion-leases/{lease_id}/reconcile",
    response_model=RecoveryDurableReadPromotionOperationRead,
)
def reconcile_durable_read_routing_lease_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    payload: RecoveryDurableReadPromotionLeaseReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryDurableReadPromotionOperationRead:
    try:
        lease, route, receipt, outcome = reconcile_recovery_durable_read_promotion_lease(
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
                "expired": "EVIDENCE_RECOVERY_DURABLE_READ_ROUTE_RECONCILED_EXPIRED",
                "unchanged": "EVIDENCE_RECOVERY_DURABLE_READ_ROUTE_RECONCILED_HEALTHY",
            }[outcome],
            entity_type="evidence_recovery_durable_read_promotion_lease",
            entity_id=lease.id,
            new_values={
                **_audit_values(lease, route),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        _commit_operation(db, lease, route, receipt)
    except (RecoveryDurableReadRoutingNotFound, RecoveryDurableReadRoutingConflict, RecoveryDurableReadRoutingUnavailable) as exc:
        db.rollback()
        raise _error(exc) from exc
    return _operation(lease, route, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-promotion-leases/{lease_id}",
    response_model=RecoveryDurableReadPromotionLeaseRead,
)
def get_durable_read_routing_lease_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryDurableReadPromotionLeaseRead:
    try:
        lease = get_recovery_durable_read_promotion_lease(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
        )
    except RecoveryDurableReadRoutingNotFound as exc:
        raise _error(exc) from exc
    return RecoveryDurableReadPromotionLeaseRead.model_validate(lease)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-durable-read-promotion-leases/{lease_id}/receipts",
    response_model=list[RecoveryDurableReadPromotionReceiptRead],
)
def list_durable_read_routing_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RecoveryDurableReadPromotionReceiptRead]:
    try:
        receipts = list_recovery_durable_read_promotion_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
        )
    except RecoveryDurableReadRoutingNotFound as exc:
        raise _error(exc) from exc
    return [RecoveryDurableReadPromotionReceiptRead.model_validate(item) for item in receipts]
