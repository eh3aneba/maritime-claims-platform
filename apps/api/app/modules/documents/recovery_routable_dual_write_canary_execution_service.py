from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.object_storage import (
    ObjectStorageError,
    ObjectStorageIntegrityError,
    ObjectStorageNotFound,
    ObjectStoragePreconditionFailed,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_replication_models import EvidenceRecoveryReplica
from app.modules.documents.recovery_replication_service import (
    RecoveryReplicationConflict,
    RecoveryReplicationNotFound,
    RecoveryReplicationUnavailable,
    _build_store,
    _load_document_for_update,
    _snapshot_local,
    _suffix_for_document,
)
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso
from app.modules.documents.recovery_routable_dual_write_canary_authorization_models import (
    EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt,
)
from app.modules.documents.recovery_routable_dual_write_canary_authorization_service import (
    RecoveryRoutableDualWriteCanaryAuthorizationConflict,
    RecoveryRoutableDualWriteCanaryAuthorizationNotFound,
    RecoveryRoutableDualWriteCanaryAuthorizationUnavailable,
    _fresh_z,
    _matches_authorization,
    get_recovery_routable_dual_write_canary_authorization,
)
from app.modules.documents.recovery_routable_dual_write_canary_execution_models import (
    EvidenceRecoveryRoutableDualWriteCanaryLease,
    EvidenceRecoveryRoutableDualWriteCanaryReceipt,
    EvidenceRecoveryRoutableDualWriteCanaryRoute,
)


CANARY_WINDOW = timedelta(minutes=10)


class RecoveryRoutableDualWriteCanaryExecutionError(RuntimeError):
    pass


class RecoveryRoutableDualWriteCanaryExecutionNotFound(RecoveryRoutableDualWriteCanaryExecutionError):
    pass


class RecoveryRoutableDualWriteCanaryExecutionConflict(RecoveryRoutableDualWriteCanaryExecutionError):
    pass


class RecoveryRoutableDualWriteCanaryExecutionUnavailable(RecoveryRoutableDualWriteCanaryExecutionError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _approved_receipt(db: Session, *, authorization) -> EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt).where(
                EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt.organization_id == authorization.organization_id,
                EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt.claim_id == authorization.claim_id,
                EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt.document_id == authorization.document_id,
                EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt.authorization_id == authorization.id,
                EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt.phase == "approved",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryRoutableDualWriteCanaryExecutionConflict(
            "Approved Phase AA authorization must have exactly one approved receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            authorization.approved_by_id is not None,
            authorization.approved_at is not None,
            receipt.actor_id == authorization.approved_by_id,
            _as_utc(receipt.transitioned_at) == _as_utc(authorization.approved_at),
            receipt.authorization_hash == authorization.authorization_hash,
            receipt.phase_z_health_qualification_id == authorization.phase_z_health_qualification_id,
            receipt.phase_z_health_qualification_hash == authorization.phase_z_health_qualification_hash,
            receipt.phase_z_health_receipt_hash == authorization.phase_z_health_receipt_hash,
            receipt.request_snapshot_hash == authorization.request_snapshot_hash,
            receipt.storage_write_performed is False,
            receipt.canary_executed is False,
            receipt.routable_dual_write_active is False,
            receipt.durable_write_authority_created is False,
            receipt.rehearsal_object_routable is False,
            receipt.read_path_switched is False,
            receipt.write_path_switched is False,
            receipt.document_storage_key_mutated is False,
            receipt.authoritative_storage_changed is False,
            receipt.destructive_action_performed is False,
            receipt.s3_copy_performed is False,
            receipt.s3_delete_performed is False,
            receipt.local_delete_performed is False,
        )
    ):
        raise RecoveryRoutableDualWriteCanaryExecutionConflict(
            "Phase AA approval receipt lineage is inconsistent"
        )
    return receipt


def _fresh_aa(db: Session, *, organization_id: UUID, claim_id: UUID, document_id: UUID, authorization_id: UUID, now: datetime):
    try:
        a = get_recovery_routable_dual_write_canary_authorization(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
            for_update=True,
        )
    except RecoveryRoutableDualWriteCanaryAuthorizationNotFound as exc:
        raise RecoveryRoutableDualWriteCanaryExecutionNotFound(str(exc)) from exc
    if not all(
        (
            a.status == "approved",
            a.approved_by_id is not None,
            a.approved_at is not None,
            a.authorization_expires_at is not None,
            a.max_canary_windows == 1,
            a.storage_write_performed is False,
            a.canary_executed is False,
            a.routable_dual_write_active is False,
            a.durable_write_authority_created is False,
            a.rehearsal_object_routable is False,
            a.read_path_switched is False,
            a.write_path_switched is False,
            a.document_storage_key_mutated is False,
            a.authoritative_storage_changed is False,
            a.destructive_action_performed is False,
            a.s3_copy_performed is False,
            a.s3_delete_performed is False,
            a.local_delete_performed is False,
        )
    ):
        raise RecoveryRoutableDualWriteCanaryExecutionConflict(
            "Phase AB requires one exact approved Phase AA authorization"
        )
    if now >= _as_utc(a.authorization_expires_at):
        raise RecoveryRoutableDualWriteCanaryExecutionConflict(
            "Phase AA authorization expired before Phase AB activation"
        )
    approval_receipt = _approved_receipt(db, authorization=a)
    try:
        q, z_receipt, snapshot = _fresh_z(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            health_qualification_id=a.phase_z_health_qualification_id,
        )
    except RecoveryRoutableDualWriteCanaryAuthorizationUnavailable as exc:
        raise RecoveryRoutableDualWriteCanaryExecutionUnavailable(str(exc)) from exc
    except RecoveryRoutableDualWriteCanaryAuthorizationNotFound as exc:
        raise RecoveryRoutableDualWriteCanaryExecutionNotFound(str(exc)) from exc
    except RecoveryRoutableDualWriteCanaryAuthorizationConflict as exc:
        raise RecoveryRoutableDualWriteCanaryExecutionConflict(str(exc)) from exc
    if not _matches_authorization(a, q, z_receipt, snapshot):
        raise RecoveryRoutableDualWriteCanaryExecutionConflict(
            "Phase AA snapshot drifted before Phase AB activation"
        )
    route = snapshot.route
    if not all(
        (
            route.route_class == "local_source",
            route.route_authority_kind == "local",
            route.active_lease_id is None,
            route.active_durable_lease_id is None,
            route.active_durable_renewal_lease_id is None,
            route.active_durable_reauthorized_renewal_lease_id is None,
            route.active_read_ownership_transition_lease_id is None,
            route.active_replica_id is None,
            route.read_path_switched is False,
            route.write_path_switched is False,
            route.document_storage_key_mutated is False,
            route.authoritative_storage_changed is False,
            route.destructive_action_performed is False,
        )
    ):
        raise RecoveryRoutableDualWriteCanaryExecutionConflict(
            "Phase AB requires the shared read route to remain exact clean local authority"
        )
    return a, approval_receipt, q, snapshot


def _canary_key(document, authorization_id: UUID) -> str:
    return (
        f"canary/routable-dual-write/{document.organization_id}/{document.claim_id}/"
        f"{document.id}/{authorization_id}{_suffix_for_document(document)}"
    )


def _verify_remote(store, *, storage_key: str, expected_hash: str, expected_size: int):
    try:
        metadata = store.head_object(storage_key=storage_key)
        if metadata.file_hash != expected_hash or metadata.file_size_bytes != expected_size:
            raise RecoveryRoutableDualWriteCanaryExecutionConflict(
                "Phase AB canary object metadata does not match authoritative local evidence"
            )
        payload = store.get_bytes(storage_key=storage_key, expected_sha256=expected_hash)
    except ObjectStorageNotFound as exc:
        raise RecoveryRoutableDualWriteCanaryExecutionConflict(
            "Phase AB canary object disappeared before verification"
        ) from exc
    except ObjectStorageIntegrityError as exc:
        raise RecoveryRoutableDualWriteCanaryExecutionConflict(
            "Phase AB canary object failed integrity verification"
        ) from exc
    except ObjectStorageError as exc:
        raise RecoveryRoutableDualWriteCanaryExecutionUnavailable(
            "Recovery storage verification is temporarily unavailable"
        ) from exc
    if len(payload) != expected_size or hashlib.sha256(payload).hexdigest() != expected_hash:
        raise RecoveryRoutableDualWriteCanaryExecutionConflict(
            "Phase AB canary bytes do not match authoritative local evidence"
        )
    return metadata


def _write_once(store, *, payload: bytes, storage_key: str, expected_hash: str, expected_size: int):
    storage_write_performed = False
    try:
        existing = store.head_object(storage_key=storage_key)
    except ObjectStorageNotFound:
        existing = None
    except ObjectStorageIntegrityError as exc:
        raise RecoveryRoutableDualWriteCanaryExecutionConflict(
            "Existing Phase AB canary object has invalid integrity metadata"
        ) from exc
    except ObjectStorageError as exc:
        raise RecoveryRoutableDualWriteCanaryExecutionUnavailable(
            "Recovery storage canary preflight is temporarily unavailable"
        ) from exc

    if existing is not None:
        if existing.file_hash != expected_hash or existing.file_size_bytes != expected_size:
            raise RecoveryRoutableDualWriteCanaryExecutionConflict(
                "Existing Phase AB canary object conflicts with authoritative local evidence"
            )
    else:
        try:
            store.put_bytes_if_absent(payload, storage_key=storage_key, expected_sha256=expected_hash)
            storage_write_performed = True
        except ObjectStoragePreconditionFailed:
            # A concurrent/retried exact operation may have won the deterministic key.
            # It is reusable only after the same exact byte verification below.
            pass
        except ObjectStorageIntegrityError as exc:
            raise RecoveryRoutableDualWriteCanaryExecutionConflict(
                "Phase AB upload payload failed integrity verification"
            ) from exc
        except ObjectStorageError as exc:
            raise RecoveryRoutableDualWriteCanaryExecutionUnavailable(
                "Recovery storage canary write is temporarily unavailable"
            ) from exc

    metadata = _verify_remote(
        store,
        storage_key=storage_key,
        expected_hash=expected_hash,
        expected_size=expected_size,
    )
    # A second independent HEAD+GET closes the canary with post-write evidence.
    metadata = _verify_remote(
        store,
        storage_key=storage_key,
        expected_hash=expected_hash,
        expected_size=expected_size,
    )
    return metadata, storage_write_performed


def _get_write_route_for_update(db: Session, *, organization_id: UUID, claim_id: UUID, document_id: UUID):
    return db.scalar(
        select(EvidenceRecoveryRoutableDualWriteCanaryRoute)
        .where(
            EvidenceRecoveryRoutableDualWriteCanaryRoute.organization_id == organization_id,
            EvidenceRecoveryRoutableDualWriteCanaryRoute.claim_id == claim_id,
            EvidenceRecoveryRoutableDualWriteCanaryRoute.document_id == document_id,
        )
        .with_for_update()
    )


def _assert_clean_write_route(route) -> None:
    if route is None:
        return
    if not all(
        (
            route.write_mode == "local_only",
            route.active_canary_lease_id is None,
            route.local_authoritative is True,
            route.durable_write_authority_created is False,
            route.rehearsal_object_routable is False,
            route.read_path_switched is False,
            route.write_path_switched is False,
            route.document_storage_key_mutated is False,
            route.authoritative_storage_changed is False,
            route.destructive_action_performed is False,
            route.s3_copy_performed is False,
            route.s3_delete_performed is False,
            route.local_delete_performed is False,
        )
    ):
        raise RecoveryRoutableDualWriteCanaryExecutionConflict(
            "Phase AB write route is not clean local-only authority"
        )


def _receipt_hash(lease, *, phase: str, from_mode: str, to_mode: str, actor_id: UUID, reason: str, transitioned_at: datetime) -> str:
    return _canonical_hash(
        {
            "canary_lease_id": str(lease.id),
            "authorization_id": str(lease.authorization_id),
            "phase": phase,
            "from_write_mode": from_mode,
            "to_write_mode": to_mode,
            "authorization_hash": lease.authorization_hash,
            "authorization_approval_receipt_hash": lease.authorization_approval_receipt_hash,
            "canary_object_key_fingerprint": lease.canary_object_key_fingerprint,
            "source_file_hash": lease.source_file_hash,
            "source_file_size_bytes": lease.source_file_size_bytes,
            "verification_hash": lease.verification_hash,
            "lease_hash": lease.lease_hash,
            "storage_write_performed": lease.storage_write_performed,
            "canary_executed": True,
            "canary_write_verified": True,
            "routable_dual_write_active": phase == "activated",
            "actor_id": str(actor_id),
            "reason": reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "local_authoritative": True,
            "read_path_switched": False,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
        }
    )


def _add_receipt(db: Session, lease, *, phase: str, from_mode: str, to_mode: str, actor_id: UUID, reason: str, now: datetime):
    receipt = EvidenceRecoveryRoutableDualWriteCanaryReceipt(
        organization_id=lease.organization_id,
        claim_id=lease.claim_id,
        document_id=lease.document_id,
        canary_lease_id=lease.id,
        authorization_id=lease.authorization_id,
        phase=phase,
        from_write_mode=from_mode,
        to_write_mode=to_mode,
        authorization_hash=lease.authorization_hash,
        authorization_approval_receipt_hash=lease.authorization_approval_receipt_hash,
        canary_object_key_fingerprint=lease.canary_object_key_fingerprint,
        source_file_hash=lease.source_file_hash,
        source_file_size_bytes=lease.source_file_size_bytes,
        verification_hash=lease.verification_hash,
        lease_hash=lease.lease_hash,
        receipt_hash=_receipt_hash(
            lease,
            phase=phase,
            from_mode=from_mode,
            to_mode=to_mode,
            actor_id=actor_id,
            reason=reason,
            transitioned_at=now,
        ),
        storage_write_performed=lease.storage_write_performed,
        canary_executed=True,
        canary_write_verified=True,
        routable_dual_write_active=phase == "activated",
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
        local_authoritative=True,
        durable_write_authority_created=False,
        rehearsal_object_routable=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )
    db.add(receipt)
    db.flush()
    return receipt


def _activation_receipt(db: Session, lease):
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryRoutableDualWriteCanaryReceipt).where(
                EvidenceRecoveryRoutableDualWriteCanaryReceipt.organization_id == lease.organization_id,
                EvidenceRecoveryRoutableDualWriteCanaryReceipt.canary_lease_id == lease.id,
                EvidenceRecoveryRoutableDualWriteCanaryReceipt.phase == "activated",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryRoutableDualWriteCanaryExecutionConflict(
            "Phase AB lease must have exactly one activation receipt"
        )
    return receipts[0]


def execute_routable_dual_write_canary(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    activated_by_id: UUID,
    reason: str,
    now: datetime | None = None,
):
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryRoutableDualWriteCanaryExecutionConflict("Phase AB activation reason is required")
    current = _as_utc(now or _utc_now())

    try:
        a = get_recovery_routable_dual_write_canary_authorization(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
            for_update=True,
        )
    except RecoveryRoutableDualWriteCanaryAuthorizationNotFound as exc:
        raise RecoveryRoutableDualWriteCanaryExecutionNotFound(str(exc)) from exc

    existing = db.scalar(
        select(EvidenceRecoveryRoutableDualWriteCanaryLease)
        .where(
            EvidenceRecoveryRoutableDualWriteCanaryLease.organization_id == organization_id,
            EvidenceRecoveryRoutableDualWriteCanaryLease.claim_id == claim_id,
            EvidenceRecoveryRoutableDualWriteCanaryLease.document_id == document_id,
            EvidenceRecoveryRoutableDualWriteCanaryLease.authorization_id == authorization_id,
        )
        .with_for_update()
    )
    if existing is not None:
        return existing, _activation_receipt(db, existing), "unchanged"

    # Re-run the complete AA/Z verification only for first execution.
    a, approval_receipt, _q, snapshot = _fresh_aa(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
        now=current,
    )
    if activated_by_id in {
        a.requested_by_id,
        a.approved_by_id,
        a.phase_z_qualified_by_id,
        a.phase_y_executed_by_id,
        a.phase_x_approved_by_id,
    }:
        raise RecoveryRoutableDualWriteCanaryExecutionConflict(
            "Phase AB activator must be independent from the AA governance and prior execution actors"
        )

    try:
        document = _load_document_for_update(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
        local = _snapshot_local(document)
    except RecoveryReplicationNotFound as exc:
        raise RecoveryRoutableDualWriteCanaryExecutionNotFound(str(exc)) from exc
    except RecoveryReplicationConflict as exc:
        raise RecoveryRoutableDualWriteCanaryExecutionConflict(str(exc)) from exc
    if not all(
        (
            local.file_hash == a.source_file_hash,
            local.file_size_bytes == a.source_file_size_bytes,
            local.storage_key_fingerprint == a.local_storage_key_fingerprint,
        )
    ):
        raise RecoveryRoutableDualWriteCanaryExecutionConflict(
            "Authoritative local evidence drifted after Phase AA approval"
        )

    replica = db.scalar(
        select(EvidenceRecoveryReplica).where(
            EvidenceRecoveryReplica.id == a.replica_id,
            EvidenceRecoveryReplica.organization_id == organization_id,
            EvidenceRecoveryReplica.claim_id == claim_id,
            EvidenceRecoveryReplica.document_id == document_id,
        )
    )
    if replica is None or replica.replica_hash != a.replica_hash:
        raise RecoveryRoutableDualWriteCanaryExecutionConflict("Recovery replica lineage drifted")

    write_route = _get_write_route_for_update(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
    )
    _assert_clean_write_route(write_route)
    if write_route is None:
        write_route = EvidenceRecoveryRoutableDualWriteCanaryRoute(
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            write_mode="local_only",
            active_canary_lease_id=None,
            route_version=1,
            changed_by_id=activated_by_id,
            changed_at=current,
            local_authoritative=True,
            durable_write_authority_created=False,
            rehearsal_object_routable=False,
            read_path_switched=False,
            write_path_switched=False,
            document_storage_key_mutated=False,
            authoritative_storage_changed=False,
            destructive_action_performed=False,
            s3_copy_performed=False,
            s3_delete_performed=False,
            local_delete_performed=False,
        )
        db.add(write_route)
        db.flush()

    canary_key = _canary_key(document, a.id)
    if canary_key in {document.storage_key, replica.recovery_storage_key}:
        raise RecoveryRoutableDualWriteCanaryExecutionConflict(
            "Phase AB canary key is not isolated from authoritative or replica evidence"
        )
    canary_key_fingerprint = hashlib.sha256(canary_key.encode("utf-8")).hexdigest()
    try:
        store = _build_store()
    except RecoveryReplicationUnavailable as exc:
        raise RecoveryRoutableDualWriteCanaryExecutionUnavailable(str(exc)) from exc
    if store.sanitized_health_identity.bucket_fingerprint != a.recovery_bucket_fingerprint:
        raise RecoveryRoutableDualWriteCanaryExecutionConflict(
            "Recovery bucket changed after Phase AA approval"
        )
    metadata, storage_write_performed = _write_once(
        store,
        payload=local.payload,
        storage_key=canary_key,
        expected_hash=local.file_hash,
        expected_size=local.file_size_bytes,
    )

    write_route_version = write_route.route_version + 1
    lease_expires_at = current + CANARY_WINDOW
    verification_hash = _canonical_hash(
        {
            "authorization_id": str(a.id),
            "authorization_hash": a.authorization_hash,
            "authorization_approval_receipt_id": str(approval_receipt.id),
            "authorization_approval_receipt_hash": approval_receipt.receipt_hash,
            "canary_object_key_fingerprint": canary_key_fingerprint,
            "source_file_hash": local.file_hash,
            "source_file_size_bytes": local.file_size_bytes,
            "observed_file_hash": metadata.file_hash,
            "observed_file_size_bytes": metadata.file_size_bytes,
            "remote_etag": metadata.etag,
            "read_route_version_at_activation": snapshot.route.route_version,
            "write_route_version_at_activation": write_route_version,
            "storage_write_performed": storage_write_performed,
            "local_authoritative": True,
            "write_mode": "local_plus_recovery_canary",
            "read_path_switched": False,
            "write_path_switched": False,
            "authoritative_storage_changed": False,
        }
    )
    lease_snapshot_hash = _canonical_hash(
        {
            "authorization_request_snapshot_hash": a.request_snapshot_hash,
            "authorization_hash": a.authorization_hash,
            "phase_z_health_qualification_hash": a.phase_z_health_qualification_hash,
            "execution_hash": a.execution_hash,
            "phase_x_authorization_hash": a.phase_x_authorization_hash,
            "replica_hash": a.replica_hash,
            "source_file_hash": local.file_hash,
            "source_file_size_bytes": local.file_size_bytes,
            "canary_object_key_fingerprint": canary_key_fingerprint,
            "verification_hash": verification_hash,
            "read_route_version_at_activation": snapshot.route.route_version,
            "write_route_version_at_activation": write_route_version,
            "lease_expires_at": _utc_iso(lease_expires_at),
        }
    )
    lease_hash = _canonical_hash(
        {
            "lease_snapshot_hash": lease_snapshot_hash,
            "activated_by_id": str(activated_by_id),
            "activated_at": _utc_iso(current),
            "activation_reason": normalized_reason,
            "max_canary_writes": 1,
            "mode": "phase_ab_one_bounded_routable_dual_write_canary",
        }
    )
    lease = EvidenceRecoveryRoutableDualWriteCanaryLease(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=a.id,
        authorization_approval_receipt_id=approval_receipt.id,
        phase_z_health_qualification_id=a.phase_z_health_qualification_id,
        execution_id=a.execution_id,
        phase_x_authorization_id=a.phase_x_authorization_id,
        replica_id=a.replica_id,
        authorization_hash=a.authorization_hash,
        authorization_request_snapshot_hash=a.request_snapshot_hash,
        authorization_approval_receipt_hash=approval_receipt.receipt_hash,
        phase_z_health_qualification_hash=a.phase_z_health_qualification_hash,
        execution_hash=a.execution_hash,
        phase_x_authorization_hash=a.phase_x_authorization_hash,
        replica_hash=a.replica_hash,
        source_file_hash=local.file_hash,
        source_file_size_bytes=local.file_size_bytes,
        local_storage_key_fingerprint=a.local_storage_key_fingerprint,
        recovery_bucket_fingerprint=a.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=a.candidate_storage_key_fingerprint,
        source_authority_fingerprint=a.source_authority_fingerprint,
        candidate_authority_fingerprint=a.candidate_authority_fingerprint,
        configuration_fingerprint=a.configuration_fingerprint,
        read_route_version_at_activation=snapshot.route.route_version,
        write_route_version_at_activation=write_route_version,
        canary_object_key_fingerprint=canary_key_fingerprint,
        observed_file_hash=metadata.file_hash,
        observed_file_size_bytes=metadata.file_size_bytes,
        remote_etag=metadata.etag,
        verification_hash=verification_hash,
        lease_snapshot_hash=lease_snapshot_hash,
        lease_hash=lease_hash,
        status="active",
        max_canary_writes=1,
        storage_write_performed=storage_write_performed,
        canary_executed=True,
        canary_write_verified=True,
        routable_dual_write_active=True,
        activated_by_id=activated_by_id,
        activated_at=current,
        lease_expires_at=lease_expires_at,
        activation_reason=normalized_reason,
        local_authoritative=True,
        durable_write_authority_created=False,
        rehearsal_object_routable=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )
    db.add(lease)
    db.flush()
    write_route.write_mode = "local_plus_recovery_canary"
    write_route.active_canary_lease_id = lease.id
    write_route.route_version = write_route_version
    write_route.changed_by_id = activated_by_id
    write_route.changed_at = current
    db.flush()
    receipt = _add_receipt(
        db,
        lease,
        phase="activated",
        from_mode="local_only",
        to_mode="local_plus_recovery_canary",
        actor_id=activated_by_id,
        reason=normalized_reason,
        now=current,
    )
    return lease, receipt, "activated"


def get_routable_dual_write_canary_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    for_update: bool = False,
):
    stmt = select(EvidenceRecoveryRoutableDualWriteCanaryLease).where(
        EvidenceRecoveryRoutableDualWriteCanaryLease.id == lease_id,
        EvidenceRecoveryRoutableDualWriteCanaryLease.organization_id == organization_id,
        EvidenceRecoveryRoutableDualWriteCanaryLease.claim_id == claim_id,
        EvidenceRecoveryRoutableDualWriteCanaryLease.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    lease = db.scalar(stmt)
    if lease is None:
        raise RecoveryRoutableDualWriteCanaryExecutionNotFound("Phase AB canary lease not found")
    return lease


def rollback_routable_dual_write_canary(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    actor_id: UUID,
    reason: str,
    now: datetime | None = None,
):
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryRoutableDualWriteCanaryExecutionConflict("Phase AB rollback reason is required")
    current = _as_utc(now or _utc_now())
    lease = get_routable_dual_write_canary_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
        for_update=True,
    )
    if lease.status != "active":
        return lease, None, "unchanged"
    route = _get_write_route_for_update(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
    )
    if route is None or not all(
        (
            route.write_mode == "local_plus_recovery_canary",
            route.active_canary_lease_id == lease.id,
            route.local_authoritative is True,
            route.write_path_switched is False,
            route.authoritative_storage_changed is False,
            route.destructive_action_performed is False,
        )
    ):
        raise RecoveryRoutableDualWriteCanaryExecutionConflict(
            "Phase AB cannot safely roll back because the write-route pointer drifted"
        )
    phase = "expired" if current >= _as_utc(lease.lease_expires_at) else "rolled_back"
    terminal_reason = (
        "Phase AB bounded canary window expired and was restored to local-only routing"
        if phase == "expired"
        else normalized_reason
    )
    route.write_mode = "local_only"
    route.active_canary_lease_id = None
    route.route_version += 1
    route.changed_by_id = actor_id
    route.changed_at = current
    lease.status = phase
    lease.routable_dual_write_active = False
    lease.terminal_by_id = actor_id
    lease.terminal_at = current
    lease.terminal_reason = terminal_reason
    db.flush()
    receipt = _add_receipt(
        db,
        lease,
        phase=phase,
        from_mode="local_plus_recovery_canary",
        to_mode="local_only",
        actor_id=actor_id,
        reason=terminal_reason,
        now=current,
    )
    return lease, receipt, phase


def list_routable_dual_write_canary_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
):
    get_routable_dual_write_canary_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryRoutableDualWriteCanaryReceipt)
            .where(
                EvidenceRecoveryRoutableDualWriteCanaryReceipt.organization_id == organization_id,
                EvidenceRecoveryRoutableDualWriteCanaryReceipt.claim_id == claim_id,
                EvidenceRecoveryRoutableDualWriteCanaryReceipt.document_id == document_id,
                EvidenceRecoveryRoutableDualWriteCanaryReceipt.canary_lease_id == lease_id,
            )
            .order_by(EvidenceRecoveryRoutableDualWriteCanaryReceipt.transitioned_at.asc())
        ).all()
    )
