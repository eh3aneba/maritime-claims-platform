from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.service import write_audit_log
from app.modules.claims.retention_router import RetentionAdminMfa, RetentionReader
from app.modules.documents.recovery_routable_read_cutover_schemas import (
    RecoveryReadPathCutoverLeaseRead,
    RecoveryReadPathCutoverOperationRead,
    RecoveryReadPathCutoverReceiptRead,
    RecoveryReadPathRouteRead,
    RecoveryRoutableReadCutoverReason,
)
from app.modules.documents.recovery_routable_read_cutover_service import (
    RecoveryRoutableReadCutoverConflict,
    RecoveryRoutableReadCutoverNotFound,
    RecoveryRoutableReadCutoverUnavailable,
    activate_recovery_routable_read_cutover_lease,
    get_recovery_read_path_route,
    get_recovery_routable_read_cutover_lease,
    list_recovery_routable_read_cutover_receipts,
    prepare_recovery_routable_read_cutover_lease,
    rollback_recovery_routable_read_cutover_lease,
)

router = APIRouter(prefix="/claims", tags=["evidence-recovery-routable-read-cutover"])


def _audit_values(lease, route) -> dict:
    return {
        "claim_id": str(lease.claim_id),
        "document_id": str(lease.document_id),
        "authorization_id": str(lease.authorization_id),
        "authorization_approval_receipt_id": str(lease.authorization_approval_receipt_id),
        "replica_id": str(lease.replica_id),
        "authorization_hash": lease.authorization_hash,
        "authorization_request_snapshot_hash": lease.authorization_request_snapshot_hash,
        "authorization_approval_receipt_hash": lease.authorization_approval_receipt_hash,
        "execution_transition_proof_hash": lease.execution_transition_proof_hash,
        "replica_hash": lease.replica_hash,
        "source_file_hash": lease.source_file_hash,
        "source_file_size_bytes": lease.source_file_size_bytes,
        "recovery_bucket_fingerprint": lease.recovery_bucket_fingerprint,
        "candidate_storage_key_fingerprint": lease.candidate_storage_key_fingerprint,
        "source_authority_fingerprint": lease.source_authority_fingerprint,
        "candidate_authority_fingerprint": lease.candidate_authority_fingerprint,
        "configuration_fingerprint": lease.configuration_fingerprint,
        "lease_snapshot_hash": lease.lease_snapshot_hash,
        "lease_hash": lease.lease_hash,
        "status": lease.status,
        "route_class": route.route_class,
        "route_version": route.route_version,
        "routable_authority_created": lease.routable_authority_created,
        "read_path_switched": lease.read_path_switched,
        "write_path_switched": False,
        "document_storage_key_mutated": False,
        "authoritative_storage_changed": False,
        "destructive_action_performed": False,
        "s3_delete_performed": False,
        "local_delete_performed": False,
    }


def _operation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RecoveryRoutableReadCutoverNotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, RecoveryRoutableReadCutoverConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, RecoveryRoutableReadCutoverUnavailable):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Recovery routable read cutover conflict",
    )


def _operation_read(lease, route, receipt, outcome: str) -> RecoveryReadPathCutoverOperationRead:
    return RecoveryReadPathCutoverOperationRead(
        lease=RecoveryReadPathCutoverLeaseRead.model_validate(lease),
        route=RecoveryReadPathRouteRead.model_validate(route),
        receipt=(
            RecoveryReadPathCutoverReceiptRead.model_validate(receipt)
            if receipt is not None
            else None
        ),
        outcome=outcome,
    )


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-read-path-cutover-authorizations/{authorization_id}/cutover-lease",
    response_model=RecoveryReadPathCutoverOperationRead,
    status_code=status.HTTP_201_CREATED,
)
def prepare_routable_read_cutover_endpoint(
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    payload: RecoveryRoutableReadCutoverReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryReadPathCutoverOperationRead:
    try:
        lease, route, receipt, outcome = prepare_recovery_routable_read_cutover_lease(
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
                "prepared": "EVIDENCE_RECOVERY_ROUTABLE_READ_CUTOVER_PREPARED",
                "unchanged": "EVIDENCE_RECOVERY_ROUTABLE_READ_CUTOVER_PREPARE_REPLAYED",
                "invalidated": "EVIDENCE_RECOVERY_ROUTABLE_READ_CUTOVER_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_read_path_cutover_lease",
            entity_id=lease.id,
            new_values={
                **_audit_values(lease, route),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        db.commit()
        db.refresh(lease)
        db.refresh(route)
        if receipt is not None:
            db.refresh(receipt)
    except (
        RecoveryRoutableReadCutoverNotFound,
        RecoveryRoutableReadCutoverConflict,
        RecoveryRoutableReadCutoverUnavailable,
    ) as exc:
        db.rollback()
        raise _operation_error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Routable read cutover conflicts with immutable lineage",
        ) from exc
    return _operation_read(lease, route, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-read-path-cutover-leases/{lease_id}/activate",
    response_model=RecoveryReadPathCutoverOperationRead,
)
def activate_routable_read_cutover_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    payload: RecoveryRoutableReadCutoverReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryReadPathCutoverOperationRead:
    try:
        lease, route, receipt, outcome = activate_recovery_routable_read_cutover_lease(
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
                "activated": "EVIDENCE_RECOVERY_ROUTABLE_READ_CUTOVER_ACTIVATED",
                "unchanged": "EVIDENCE_RECOVERY_ROUTABLE_READ_CUTOVER_ACTIVATION_REPLAYED",
                "expired": "EVIDENCE_RECOVERY_ROUTABLE_READ_CUTOVER_EXPIRED",
                "invalidated": "EVIDENCE_RECOVERY_ROUTABLE_READ_CUTOVER_INVALIDATED",
            }[outcome],
            entity_type="evidence_recovery_read_path_cutover_lease",
            entity_id=lease.id,
            new_values={
                **_audit_values(lease, route),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        db.commit()
        db.refresh(lease)
        db.refresh(route)
        if receipt is not None:
            db.refresh(receipt)
    except (
        RecoveryRoutableReadCutoverNotFound,
        RecoveryRoutableReadCutoverConflict,
        RecoveryRoutableReadCutoverUnavailable,
    ) as exc:
        db.rollback()
        raise _operation_error(exc) from exc
    return _operation_read(lease, route, receipt, outcome)


@router.post(
    "/{claim_id}/documents/{document_id}/recovery-read-path-cutover-leases/{lease_id}/rollback",
    response_model=RecoveryReadPathCutoverOperationRead,
)
def rollback_routable_read_cutover_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    payload: RecoveryRoutableReadCutoverReason,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionAdminMfa,
) -> RecoveryReadPathCutoverOperationRead:
    try:
        lease, route, receipt, outcome = rollback_recovery_routable_read_cutover_lease(
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
                "rolled_back": "EVIDENCE_RECOVERY_ROUTABLE_READ_CUTOVER_ROLLED_BACK",
                "unchanged": "EVIDENCE_RECOVERY_ROUTABLE_READ_CUTOVER_ROLLBACK_REPLAYED",
            }[outcome],
            entity_type="evidence_recovery_read_path_cutover_lease",
            entity_id=lease.id,
            new_values={
                **_audit_values(lease, route),
                "receipt_hash": receipt.receipt_hash if receipt else None,
                "outcome": outcome,
            },
        )
        db.commit()
        db.refresh(lease)
        db.refresh(route)
        if receipt is not None:
            db.refresh(receipt)
    except (
        RecoveryRoutableReadCutoverNotFound,
        RecoveryRoutableReadCutoverConflict,
        RecoveryRoutableReadCutoverUnavailable,
    ) as exc:
        db.rollback()
        raise _operation_error(exc) from exc
    return _operation_read(lease, route, receipt, outcome)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-read-path-cutover-leases/{lease_id}",
    response_model=RecoveryReadPathCutoverLeaseRead,
)
def get_routable_read_cutover_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryReadPathCutoverLeaseRead:
    try:
        lease = get_recovery_routable_read_cutover_lease(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
        )
    except RecoveryRoutableReadCutoverNotFound as exc:
        raise _operation_error(exc) from exc
    return RecoveryReadPathCutoverLeaseRead.model_validate(lease)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-read-path-route",
    response_model=RecoveryReadPathRouteRead,
)
def get_read_path_route_endpoint(
    claim_id: UUID,
    document_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> RecoveryReadPathRouteRead:
    try:
        route = get_recovery_read_path_route(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
    except RecoveryRoutableReadCutoverNotFound as exc:
        raise _operation_error(exc) from exc
    return RecoveryReadPathRouteRead.model_validate(route)


@router.get(
    "/{claim_id}/documents/{document_id}/recovery-read-path-cutover-leases/{lease_id}/receipts",
    response_model=list[RecoveryReadPathCutoverReceiptRead],
)
def list_routable_read_cutover_receipts_endpoint(
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: RetentionReader,
) -> list[RecoveryReadPathCutoverReceiptRead]:
    try:
        receipts = list_recovery_routable_read_cutover_receipts(
            db,
            organization_id=current_user.organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
        )
    except RecoveryRoutableReadCutoverNotFound as exc:
        raise _operation_error(exc) from exc
    return [RecoveryReadPathCutoverReceiptRead.model_validate(item) for item in receipts]
