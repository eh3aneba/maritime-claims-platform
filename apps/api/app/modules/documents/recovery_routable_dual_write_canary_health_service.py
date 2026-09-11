from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.models import Document
from app.modules.documents.object_storage import ObjectStorageError, ObjectStorageIntegrityError, ObjectStorageNotFound
from app.modules.documents.recovery_dual_write_rehearsal_health_models import EvidenceRecoveryDualWriteRehearsalHealthQualification
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_replication_models import EvidenceRecoveryReplica
from app.modules.documents.recovery_replication_service import (
    RecoveryReplicationConflict,
    RecoveryReplicationNotFound,
    RecoveryReplicationUnavailable,
    _build_store,
    _snapshot_local,
    _suffix_for_document,
)
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso
from app.modules.documents.recovery_routable_dual_write_canary_authorization_models import (
    EvidenceRecoveryRoutableDualWriteCanaryAuthorization,
    EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt,
)
from app.modules.documents.recovery_routable_dual_write_canary_execution_models import (
    EvidenceRecoveryRoutableDualWriteCanaryLease,
    EvidenceRecoveryRoutableDualWriteCanaryReceipt,
    EvidenceRecoveryRoutableDualWriteCanaryRoute,
)
from app.modules.documents.recovery_routable_dual_write_canary_health_models import (
    EvidenceRecoveryRoutableDualWriteCanaryHealthQualification,
    EvidenceRecoveryRoutableDualWriteCanaryHealthReceipt,
)
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute


CANARY_HEALTH_REVIEW_WINDOW = timedelta(minutes=10)


class RecoveryRoutableDualWriteCanaryHealthError(RuntimeError):
    pass


class RecoveryRoutableDualWriteCanaryHealthNotFound(RecoveryRoutableDualWriteCanaryHealthError):
    pass


class RecoveryRoutableDualWriteCanaryHealthConflict(RecoveryRoutableDualWriteCanaryHealthError):
    pass


class RecoveryRoutableDualWriteCanaryHealthUnavailable(RecoveryRoutableDualWriteCanaryHealthError):
    pass


@dataclass(frozen=True)
class CanaryHealthSnapshot:
    lease: EvidenceRecoveryRoutableDualWriteCanaryLease
    activation_receipt: EvidenceRecoveryRoutableDualWriteCanaryReceipt
    terminal_receipt: EvidenceRecoveryRoutableDualWriteCanaryReceipt
    authorization: EvidenceRecoveryRoutableDualWriteCanaryAuthorization
    approval_receipt: EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt
    phase_z: EvidenceRecoveryDualWriteRehearsalHealthQualification
    document: Document
    read_route: EvidenceRecoveryReadPathRoute
    write_route: EvidenceRecoveryRoutableDualWriteCanaryRoute
    replica: EvidenceRecoveryReplica
    observed_file_hash: str
    observed_file_size_bytes: int
    remote_etag: str | None
    integrity_proof_hash: str
    request_snapshot_hash: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _load_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
) -> EvidenceRecoveryRoutableDualWriteCanaryLease:
    lease = db.scalar(
        select(EvidenceRecoveryRoutableDualWriteCanaryLease)
        .where(
            EvidenceRecoveryRoutableDualWriteCanaryLease.id == lease_id,
            EvidenceRecoveryRoutableDualWriteCanaryLease.organization_id == organization_id,
            EvidenceRecoveryRoutableDualWriteCanaryLease.claim_id == claim_id,
            EvidenceRecoveryRoutableDualWriteCanaryLease.document_id == document_id,
        )
        .with_for_update()
    )
    if lease is None:
        raise RecoveryRoutableDualWriteCanaryHealthNotFound("Phase AB canary lease not found")
    if not all(
        (
            lease.status in {"rolled_back", "expired"},
            lease.terminal_by_id is not None,
            lease.terminal_at is not None,
            lease.terminal_reason is not None,
            lease.max_canary_writes == 1,
            lease.canary_executed is True,
            lease.canary_write_verified is True,
            lease.routable_dual_write_active is False,
            lease.local_authoritative is True,
            lease.durable_write_authority_created is False,
            lease.rehearsal_object_routable is False,
            lease.read_path_switched is False,
            lease.write_path_switched is False,
            lease.document_storage_key_mutated is False,
            lease.authoritative_storage_changed is False,
            lease.destructive_action_performed is False,
            lease.s3_copy_performed is False,
            lease.s3_delete_performed is False,
            lease.local_delete_performed is False,
            lease.observed_file_hash == lease.source_file_hash,
            lease.observed_file_size_bytes == lease.source_file_size_bytes,
            _as_utc(lease.terminal_at) >= _as_utc(lease.activated_at),
        )
    ):
        raise RecoveryRoutableDualWriteCanaryHealthConflict(
            "Phase AC requires one completed Phase AB window with clean local-authority rollback"
        )
    return lease


def _load_execution_receipts(db: Session, *, lease: EvidenceRecoveryRoutableDualWriteCanaryLease):
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryRoutableDualWriteCanaryReceipt)
            .where(
                EvidenceRecoveryRoutableDualWriteCanaryReceipt.organization_id == lease.organization_id,
                EvidenceRecoveryRoutableDualWriteCanaryReceipt.claim_id == lease.claim_id,
                EvidenceRecoveryRoutableDualWriteCanaryReceipt.document_id == lease.document_id,
                EvidenceRecoveryRoutableDualWriteCanaryReceipt.canary_lease_id == lease.id,
            )
            .order_by(EvidenceRecoveryRoutableDualWriteCanaryReceipt.transitioned_at.asc())
        ).all()
    )
    activations = [item for item in receipts if item.phase == "activated"]
    terminals = [item for item in receipts if item.phase == lease.status]
    if len(receipts) != 2 or len(activations) != 1 or len(terminals) != 1:
        raise RecoveryRoutableDualWriteCanaryHealthConflict(
            "Completed Phase AB window must have exactly one activation and one matching terminal receipt"
        )
    activation = activations[0]
    terminal = terminals[0]
    common = (
        activation.authorization_id == lease.authorization_id,
        terminal.authorization_id == lease.authorization_id,
        activation.authorization_hash == lease.authorization_hash,
        terminal.authorization_hash == lease.authorization_hash,
        activation.authorization_approval_receipt_hash == lease.authorization_approval_receipt_hash,
        terminal.authorization_approval_receipt_hash == lease.authorization_approval_receipt_hash,
        activation.canary_object_key_fingerprint == lease.canary_object_key_fingerprint,
        terminal.canary_object_key_fingerprint == lease.canary_object_key_fingerprint,
        activation.source_file_hash == lease.source_file_hash,
        terminal.source_file_hash == lease.source_file_hash,
        activation.source_file_size_bytes == lease.source_file_size_bytes,
        terminal.source_file_size_bytes == lease.source_file_size_bytes,
        activation.verification_hash == lease.verification_hash,
        terminal.verification_hash == lease.verification_hash,
        activation.lease_hash == lease.lease_hash,
        terminal.lease_hash == lease.lease_hash,
        activation.canary_executed is True,
        terminal.canary_executed is True,
        activation.canary_write_verified is True,
        terminal.canary_write_verified is True,
        activation.local_authoritative is True,
        terminal.local_authoritative is True,
        activation.durable_write_authority_created is False,
        terminal.durable_write_authority_created is False,
        activation.read_path_switched is False,
        terminal.read_path_switched is False,
        activation.write_path_switched is False,
        terminal.write_path_switched is False,
        activation.document_storage_key_mutated is False,
        terminal.document_storage_key_mutated is False,
        activation.authoritative_storage_changed is False,
        terminal.authoritative_storage_changed is False,
        activation.destructive_action_performed is False,
        terminal.destructive_action_performed is False,
        activation.s3_copy_performed is False,
        terminal.s3_copy_performed is False,
        activation.s3_delete_performed is False,
        terminal.s3_delete_performed is False,
        activation.local_delete_performed is False,
        terminal.local_delete_performed is False,
    )
    if not all(common):
        raise RecoveryRoutableDualWriteCanaryHealthConflict("Phase AB receipt lineage is inconsistent")
    if not all(
        (
            activation.from_write_mode == "local_only",
            activation.to_write_mode == "local_plus_recovery_canary",
            activation.routable_dual_write_active is True,
            activation.actor_id == lease.activated_by_id,
            _as_utc(activation.transitioned_at) == _as_utc(lease.activated_at),
            terminal.from_write_mode == "local_plus_recovery_canary",
            terminal.to_write_mode == "local_only",
            terminal.routable_dual_write_active is False,
            terminal.actor_id == lease.terminal_by_id,
            _as_utc(terminal.transitioned_at) == _as_utc(lease.terminal_at),
        )
    ):
        raise RecoveryRoutableDualWriteCanaryHealthConflict("Phase AB activation/terminal route evidence is inconsistent")
    return activation, terminal


def _load_authorization(db: Session, *, lease: EvidenceRecoveryRoutableDualWriteCanaryLease):
    authorization = db.scalar(
        select(EvidenceRecoveryRoutableDualWriteCanaryAuthorization).where(
            EvidenceRecoveryRoutableDualWriteCanaryAuthorization.id == lease.authorization_id,
            EvidenceRecoveryRoutableDualWriteCanaryAuthorization.organization_id == lease.organization_id,
            EvidenceRecoveryRoutableDualWriteCanaryAuthorization.claim_id == lease.claim_id,
            EvidenceRecoveryRoutableDualWriteCanaryAuthorization.document_id == lease.document_id,
        )
    )
    if authorization is None:
        raise RecoveryRoutableDualWriteCanaryHealthNotFound("Phase AA authorization not found")
    approval = db.scalar(
        select(EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt).where(
            EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt.id == lease.authorization_approval_receipt_id,
            EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt.organization_id == lease.organization_id,
            EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt.authorization_id == authorization.id,
            EvidenceRecoveryRoutableDualWriteCanaryAuthorizationReceipt.phase == "approved",
        )
    )
    if approval is None:
        raise RecoveryRoutableDualWriteCanaryHealthConflict("Exact Phase AA approval receipt is missing")
    if not all(
        (
            authorization.status == "approved",
            authorization.approved_by_id is not None,
            authorization.approved_at is not None,
            authorization.authorization_hash == lease.authorization_hash,
            authorization.request_snapshot_hash == lease.authorization_request_snapshot_hash,
            authorization.phase_z_health_qualification_id == lease.phase_z_health_qualification_id,
            authorization.phase_z_health_qualification_hash == lease.phase_z_health_qualification_hash,
            authorization.execution_id == lease.execution_id,
            authorization.execution_hash == lease.execution_hash,
            authorization.phase_x_authorization_id == lease.phase_x_authorization_id,
            authorization.phase_x_authorization_hash == lease.phase_x_authorization_hash,
            authorization.replica_id == lease.replica_id,
            authorization.replica_hash == lease.replica_hash,
            authorization.source_file_hash == lease.source_file_hash,
            authorization.source_file_size_bytes == lease.source_file_size_bytes,
            authorization.local_storage_key_fingerprint == lease.local_storage_key_fingerprint,
            authorization.recovery_bucket_fingerprint == lease.recovery_bucket_fingerprint,
            authorization.candidate_storage_key_fingerprint == lease.candidate_storage_key_fingerprint,
            authorization.source_authority_fingerprint == lease.source_authority_fingerprint,
            authorization.candidate_authority_fingerprint == lease.candidate_authority_fingerprint,
            authorization.configuration_fingerprint == lease.configuration_fingerprint,
            authorization.route_version_at_request == lease.read_route_version_at_activation,
            approval.authorization_hash == lease.authorization_hash,
            approval.receipt_hash == lease.authorization_approval_receipt_hash,
            approval.actor_id == authorization.approved_by_id,
        )
    ):
        raise RecoveryRoutableDualWriteCanaryHealthConflict("Phase AA/AB lineage is inconsistent")
    phase_z = db.scalar(
        select(EvidenceRecoveryDualWriteRehearsalHealthQualification).where(
            EvidenceRecoveryDualWriteRehearsalHealthQualification.id == lease.phase_z_health_qualification_id,
            EvidenceRecoveryDualWriteRehearsalHealthQualification.organization_id == lease.organization_id,
            EvidenceRecoveryDualWriteRehearsalHealthQualification.claim_id == lease.claim_id,
            EvidenceRecoveryDualWriteRehearsalHealthQualification.document_id == lease.document_id,
        )
    )
    if phase_z is None:
        raise RecoveryRoutableDualWriteCanaryHealthNotFound("Phase Z health qualification not found")
    if not all(
        (
            phase_z.status == "qualified",
            phase_z.health_state == "healthy",
            phase_z.health_qualification_hash == lease.phase_z_health_qualification_hash,
            phase_z.qualified_by_id == authorization.phase_z_qualified_by_id,
            phase_z.execution_id == lease.execution_id,
            phase_z.execution_hash == lease.execution_hash,
            phase_z.phase_x_authorization_id == lease.phase_x_authorization_id,
            phase_z.phase_x_authorization_hash == lease.phase_x_authorization_hash,
            phase_z.replica_id == lease.replica_id,
            phase_z.replica_hash == lease.replica_hash,
        )
    ):
        raise RecoveryRoutableDualWriteCanaryHealthConflict("Phase Z/AA/AB lineage is inconsistent")
    return authorization, approval, phase_z


def _load_routes(db: Session, *, lease: EvidenceRecoveryRoutableDualWriteCanaryLease):
    read_route = db.scalar(
        select(EvidenceRecoveryReadPathRoute)
        .where(
            EvidenceRecoveryReadPathRoute.organization_id == lease.organization_id,
            EvidenceRecoveryReadPathRoute.claim_id == lease.claim_id,
            EvidenceRecoveryReadPathRoute.document_id == lease.document_id,
        )
        .with_for_update()
    )
    if read_route is None:
        raise RecoveryRoutableDualWriteCanaryHealthNotFound("Shared read route not found")
    if not all(
        (
            read_route.route_class == "local_source",
            read_route.route_authority_kind == "local",
            read_route.active_lease_id is None,
            read_route.active_durable_lease_id is None,
            read_route.active_durable_renewal_lease_id is None,
            read_route.active_durable_reauthorized_renewal_lease_id is None,
            read_route.active_read_ownership_transition_lease_id is None,
            read_route.active_replica_id is None,
            read_route.read_path_switched is False,
            read_route.write_path_switched is False,
            read_route.document_storage_key_mutated is False,
            read_route.authoritative_storage_changed is False,
            read_route.destructive_action_performed is False,
            read_route.route_version == lease.read_route_version_at_activation,
            read_route.source_authority_fingerprint == lease.source_authority_fingerprint,
            read_route.candidate_authority_fingerprint == lease.candidate_authority_fingerprint,
            read_route.configuration_fingerprint == lease.configuration_fingerprint,
        )
    ):
        raise RecoveryRoutableDualWriteCanaryHealthConflict("Shared read route drifted from clean local authority")

    write_route = db.scalar(
        select(EvidenceRecoveryRoutableDualWriteCanaryRoute)
        .where(
            EvidenceRecoveryRoutableDualWriteCanaryRoute.organization_id == lease.organization_id,
            EvidenceRecoveryRoutableDualWriteCanaryRoute.claim_id == lease.claim_id,
            EvidenceRecoveryRoutableDualWriteCanaryRoute.document_id == lease.document_id,
        )
        .with_for_update()
    )
    if write_route is None:
        raise RecoveryRoutableDualWriteCanaryHealthNotFound("Phase AB write route not found")
    if not all(
        (
            write_route.write_mode == "local_only",
            write_route.active_canary_lease_id is None,
            write_route.route_version == lease.write_route_version_at_activation + 1,
            write_route.local_authoritative is True,
            write_route.durable_write_authority_created is False,
            write_route.rehearsal_object_routable is False,
            write_route.read_path_switched is False,
            write_route.write_path_switched is False,
            write_route.document_storage_key_mutated is False,
            write_route.authoritative_storage_changed is False,
            write_route.destructive_action_performed is False,
            write_route.s3_copy_performed is False,
            write_route.s3_delete_performed is False,
            write_route.local_delete_performed is False,
        )
    ):
        raise RecoveryRoutableDualWriteCanaryHealthConflict("Phase AB write route did not return to exact local-only authority")
    return read_route, write_route


def _load_document_and_replica(db: Session, *, lease: EvidenceRecoveryRoutableDualWriteCanaryLease):
    document = db.scalar(
        select(Document)
        .where(
            Document.id == lease.document_id,
            Document.organization_id == lease.organization_id,
            Document.claim_id == lease.claim_id,
        )
        .with_for_update()
    )
    if document is None or document.deleted_at is not None:
        raise RecoveryRoutableDualWriteCanaryHealthNotFound("Document not found")
    try:
        local = _snapshot_local(document)
    except RecoveryReplicationNotFound as exc:
        raise RecoveryRoutableDualWriteCanaryHealthNotFound(str(exc)) from exc
    except (RecoveryReplicationConflict, FileNotFoundError) as exc:
        raise RecoveryRoutableDualWriteCanaryHealthConflict(str(exc)) from exc
    if not all(
        (
            local.file_hash == lease.source_file_hash,
            local.file_size_bytes == lease.source_file_size_bytes,
            local.storage_key_fingerprint == lease.local_storage_key_fingerprint,
        )
    ):
        raise RecoveryRoutableDualWriteCanaryHealthConflict("Authoritative local evidence drifted after Phase AB")
    replica = db.scalar(
        select(EvidenceRecoveryReplica).where(
            EvidenceRecoveryReplica.id == lease.replica_id,
            EvidenceRecoveryReplica.organization_id == lease.organization_id,
            EvidenceRecoveryReplica.claim_id == lease.claim_id,
            EvidenceRecoveryReplica.document_id == lease.document_id,
        )
    )
    if replica is None:
        raise RecoveryRoutableDualWriteCanaryHealthNotFound("Recovery replica not found")
    if not all(
        (
            replica.replica_hash == lease.replica_hash,
            replica.source_file_hash == lease.source_file_hash,
            replica.source_file_size_bytes == lease.source_file_size_bytes,
            replica.source_storage_key_fingerprint == lease.local_storage_key_fingerprint,
            replica.recovery_bucket_fingerprint == lease.recovery_bucket_fingerprint,
            hashlib.sha256(replica.recovery_storage_key.encode("utf-8")).hexdigest() == lease.candidate_storage_key_fingerprint,
        )
    ):
        raise RecoveryRoutableDualWriteCanaryHealthConflict("Recovery replica lineage drifted after Phase AB")
    return document, local, replica


def _fresh_canary_object(*, lease, document, replica):
    key = (
        f"canary/routable-dual-write/{document.organization_id}/{document.claim_id}/"
        f"{document.id}/{lease.authorization_id}{_suffix_for_document(document)}"
    )
    if key in {document.storage_key, replica.recovery_storage_key}:
        raise RecoveryRoutableDualWriteCanaryHealthConflict("Phase AB canary object is not isolated")
    key_fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()
    if key_fingerprint != lease.canary_object_key_fingerprint:
        raise RecoveryRoutableDualWriteCanaryHealthConflict("Phase AB canary key fingerprint drifted")
    try:
        store = _build_store()
    except RecoveryReplicationUnavailable as exc:
        raise RecoveryRoutableDualWriteCanaryHealthUnavailable(str(exc)) from exc
    if store.sanitized_health_identity.bucket_fingerprint != lease.recovery_bucket_fingerprint:
        raise RecoveryRoutableDualWriteCanaryHealthConflict("Recovery bucket changed after Phase AB")
    try:
        metadata = store.head_object(storage_key=key)
        payload = store.get_bytes(storage_key=key, expected_sha256=lease.source_file_hash)
    except ObjectStorageNotFound as exc:
        raise RecoveryRoutableDualWriteCanaryHealthConflict("Phase AB canary object is missing") from exc
    except ObjectStorageIntegrityError as exc:
        raise RecoveryRoutableDualWriteCanaryHealthConflict("Phase AB canary object failed integrity verification") from exc
    except ObjectStorageError as exc:
        raise RecoveryRoutableDualWriteCanaryHealthUnavailable(
            "Recovery storage canary health verification is temporarily unavailable"
        ) from exc
    observed_hash = hashlib.sha256(payload).hexdigest()
    observed_size = len(payload)
    if not all(
        (
            metadata.file_hash == lease.source_file_hash,
            metadata.file_size_bytes == lease.source_file_size_bytes,
            observed_hash == lease.source_file_hash,
            observed_size == lease.source_file_size_bytes,
            lease.observed_file_hash == lease.source_file_hash,
            lease.observed_file_size_bytes == lease.source_file_size_bytes,
            lease.remote_etag is None or metadata.etag == lease.remote_etag,
        )
    ):
        raise RecoveryRoutableDualWriteCanaryHealthConflict("Phase AB canary object bytes or metadata drifted")
    return observed_hash, observed_size, metadata.etag


def _load_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
) -> CanaryHealthSnapshot:
    lease = _load_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
    )
    activation, terminal = _load_execution_receipts(db, lease=lease)
    authorization, approval, phase_z = _load_authorization(db, lease=lease)
    read_route, write_route = _load_routes(db, lease=lease)
    document, local, replica = _load_document_and_replica(db, lease=lease)
    observed_hash, observed_size, remote_etag = _fresh_canary_object(
        lease=lease,
        document=document,
        replica=replica,
    )
    integrity_proof_hash = _canonical_hash(
        {
            "canary_lease_id": str(lease.id),
            "lease_hash": lease.lease_hash,
            "lease_snapshot_hash": lease.lease_snapshot_hash,
            "verification_hash": lease.verification_hash,
            "activation_receipt_id": str(activation.id),
            "activation_receipt_hash": activation.receipt_hash,
            "terminal_receipt_id": str(terminal.id),
            "terminal_receipt_hash": terminal.receipt_hash,
            "authorization_id": str(authorization.id),
            "authorization_hash": authorization.authorization_hash,
            "authorization_approval_receipt_hash": approval.receipt_hash,
            "phase_z_health_qualification_hash": phase_z.health_qualification_hash,
            "execution_hash": lease.execution_hash,
            "phase_x_authorization_hash": lease.phase_x_authorization_hash,
            "replica_hash": lease.replica_hash,
            "source_file_hash": local.file_hash,
            "source_file_size_bytes": local.file_size_bytes,
            "local_storage_key_fingerprint": local.storage_key_fingerprint,
            "canary_object_key_fingerprint": lease.canary_object_key_fingerprint,
            "observed_file_hash": observed_hash,
            "observed_file_size_bytes": observed_size,
            "remote_etag": remote_etag,
            "read_route_version": read_route.route_version,
            "write_route_version": write_route.route_version,
            "write_mode": write_route.write_mode,
            "active_canary_lease_id": None,
            "local_authoritative": True,
            "storage_write_performed": False,
            "canary_reactivated": False,
            "routable_dual_write_active": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "authoritative_storage_changed": False,
        }
    )
    request_snapshot_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "canary_lease_id": str(lease.id),
            "lease_hash": lease.lease_hash,
            "authorization_hash": lease.authorization_hash,
            "phase_z_health_qualification_hash": lease.phase_z_health_qualification_hash,
            "execution_hash": lease.execution_hash,
            "phase_x_authorization_hash": lease.phase_x_authorization_hash,
            "replica_hash": lease.replica_hash,
            "source_file_hash": lease.source_file_hash,
            "source_file_size_bytes": lease.source_file_size_bytes,
            "local_storage_key_fingerprint": lease.local_storage_key_fingerprint,
            "recovery_bucket_fingerprint": lease.recovery_bucket_fingerprint,
            "candidate_storage_key_fingerprint": lease.candidate_storage_key_fingerprint,
            "source_authority_fingerprint": lease.source_authority_fingerprint,
            "candidate_authority_fingerprint": lease.candidate_authority_fingerprint,
            "configuration_fingerprint": lease.configuration_fingerprint,
            "canary_object_key_fingerprint": lease.canary_object_key_fingerprint,
            "activation_receipt_hash": activation.receipt_hash,
            "terminal_receipt_hash": terminal.receipt_hash,
            "observed_file_hash": observed_hash,
            "observed_file_size_bytes": observed_size,
            "remote_etag": remote_etag,
            "read_route_version_at_request": read_route.route_version,
            "write_route_version_at_request": write_route.route_version,
            "integrity_proof_hash": integrity_proof_hash,
            "health_state": "healthy",
        }
    )
    return CanaryHealthSnapshot(
        lease=lease,
        activation_receipt=activation,
        terminal_receipt=terminal,
        authorization=authorization,
        approval_receipt=approval,
        phase_z=phase_z,
        document=document,
        read_route=read_route,
        write_route=write_route,
        replica=replica,
        observed_file_hash=observed_hash,
        observed_file_size_bytes=observed_size,
        remote_etag=remote_etag,
        integrity_proof_hash=integrity_proof_hash,
        request_snapshot_hash=request_snapshot_hash,
    )


def _matches_snapshot(q: EvidenceRecoveryRoutableDualWriteCanaryHealthQualification, s: CanaryHealthSnapshot) -> bool:
    lease = s.lease
    auth = s.authorization
    return all(
        (
            q.canary_lease_id == lease.id,
            q.authorization_id == lease.authorization_id,
            q.authorization_approval_receipt_id == lease.authorization_approval_receipt_id,
            q.phase_z_health_qualification_id == lease.phase_z_health_qualification_id,
            q.execution_id == lease.execution_id,
            q.phase_x_authorization_id == lease.phase_x_authorization_id,
            q.replica_id == lease.replica_id,
            q.activation_receipt_id == s.activation_receipt.id,
            q.terminal_receipt_id == s.terminal_receipt.id,
            q.authorization_hash == lease.authorization_hash,
            q.authorization_approval_receipt_hash == lease.authorization_approval_receipt_hash,
            q.phase_z_health_qualification_hash == lease.phase_z_health_qualification_hash,
            q.execution_hash == lease.execution_hash,
            q.phase_x_authorization_hash == lease.phase_x_authorization_hash,
            q.replica_hash == lease.replica_hash,
            q.activation_receipt_hash == s.activation_receipt.receipt_hash,
            q.terminal_receipt_hash == s.terminal_receipt.receipt_hash,
            q.verification_hash == lease.verification_hash,
            q.lease_snapshot_hash == lease.lease_snapshot_hash,
            q.lease_hash == lease.lease_hash,
            q.source_file_hash == lease.source_file_hash,
            q.source_file_size_bytes == lease.source_file_size_bytes,
            q.local_storage_key_fingerprint == lease.local_storage_key_fingerprint,
            q.recovery_bucket_fingerprint == lease.recovery_bucket_fingerprint,
            q.candidate_storage_key_fingerprint == lease.candidate_storage_key_fingerprint,
            q.source_authority_fingerprint == lease.source_authority_fingerprint,
            q.candidate_authority_fingerprint == lease.candidate_authority_fingerprint,
            q.configuration_fingerprint == lease.configuration_fingerprint,
            q.canary_object_key_fingerprint == lease.canary_object_key_fingerprint,
            q.observed_file_hash == s.observed_file_hash,
            q.observed_file_size_bytes == s.observed_file_size_bytes,
            q.remote_etag == s.remote_etag,
            q.read_route_version_at_request == s.read_route.route_version,
            q.write_route_version_at_request == s.write_route.route_version,
            q.integrity_proof_hash == s.integrity_proof_hash,
            q.request_snapshot_hash == s.request_snapshot_hash,
            q.phase_ab_activated_by_id == lease.activated_by_id,
            q.phase_aa_requested_by_id == auth.requested_by_id,
            q.phase_aa_approved_by_id == auth.approved_by_id,
            q.phase_z_qualified_by_id == auth.phase_z_qualified_by_id,
            q.phase_y_executed_by_id == auth.phase_y_executed_by_id,
            q.phase_x_approved_by_id == auth.phase_x_approved_by_id,
        )
    )


def _receipt_hash(q, *, phase: str, actor_id: UUID, reason: str, transitioned_at: datetime) -> str:
    return _canonical_hash(
        {
            "health_qualification_id": str(q.id),
            "canary_lease_id": str(q.canary_lease_id),
            "phase": phase,
            "health_state": q.health_state,
            "integrity_proof_hash": q.integrity_proof_hash,
            "request_snapshot_hash": q.request_snapshot_hash,
            "health_qualification_hash": q.health_qualification_hash,
            "actor_id": str(actor_id),
            "reason": reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "local_authoritative": True,
            "storage_write_performed": False,
            "canary_reactivated": False,
            "routable_dual_write_active": False,
            "durable_write_authority_created": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
            "s3_put_performed": False,
            "s3_copy_performed": False,
            "s3_delete_performed": False,
            "local_delete_performed": False,
        }
    )


def _add_receipt(db: Session, q, *, phase: str, actor_id: UUID, reason: str, now: datetime):
    receipt = EvidenceRecoveryRoutableDualWriteCanaryHealthReceipt(
        organization_id=q.organization_id,
        claim_id=q.claim_id,
        document_id=q.document_id,
        health_qualification_id=q.id,
        canary_lease_id=q.canary_lease_id,
        phase=phase,
        health_state=q.health_state,
        integrity_proof_hash=q.integrity_proof_hash,
        request_snapshot_hash=q.request_snapshot_hash,
        health_qualification_hash=q.health_qualification_hash,
        receipt_hash=_receipt_hash(q, phase=phase, actor_id=actor_id, reason=reason, transitioned_at=now),
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
        local_authoritative=True,
        storage_write_performed=False,
        canary_reactivated=False,
        routable_dual_write_active=False,
        durable_write_authority_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_put_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )
    db.add(receipt)
    db.flush()
    return receipt


def request_routable_dual_write_canary_health_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    canary_lease_id: UUID,
    requested_by_id: UUID,
    reason: str,
    now: datetime | None = None,
):
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryRoutableDualWriteCanaryHealthConflict("Phase AC request reason is required")
    current = _as_utc(now or _utc_now())
    snapshot = _load_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=canary_lease_id,
    )
    existing = db.scalar(
        select(EvidenceRecoveryRoutableDualWriteCanaryHealthQualification)
        .where(
            EvidenceRecoveryRoutableDualWriteCanaryHealthQualification.organization_id == organization_id,
            EvidenceRecoveryRoutableDualWriteCanaryHealthQualification.claim_id == claim_id,
            EvidenceRecoveryRoutableDualWriteCanaryHealthQualification.document_id == document_id,
            EvidenceRecoveryRoutableDualWriteCanaryHealthQualification.canary_lease_id == canary_lease_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if (
            existing.requested_by_id == requested_by_id
            and existing.request_reason == normalized_reason
            and _matches_snapshot(existing, snapshot)
        ):
            return existing, None, "unchanged"
        raise RecoveryRoutableDualWriteCanaryHealthConflict("Phase AC qualification already exists for this Phase AB lease")
    lease = snapshot.lease
    auth = snapshot.authorization
    health_hash = _canonical_hash(
        {
            "request_snapshot_hash": snapshot.request_snapshot_hash,
            "integrity_proof_hash": snapshot.integrity_proof_hash,
            "canary_lease_id": str(lease.id),
            "lease_hash": lease.lease_hash,
            "requested_by_id": str(requested_by_id),
            "requested_at": _utc_iso(current),
            "request_reason": normalized_reason,
            "review_expires_at": _utc_iso(current + CANARY_HEALTH_REVIEW_WINDOW),
            "health_state": "healthy",
            "mode": "phase_ac_completed_routable_dual_write_canary_health",
        }
    )
    q = EvidenceRecoveryRoutableDualWriteCanaryHealthQualification(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        canary_lease_id=lease.id,
        authorization_id=lease.authorization_id,
        authorization_approval_receipt_id=lease.authorization_approval_receipt_id,
        phase_z_health_qualification_id=lease.phase_z_health_qualification_id,
        execution_id=lease.execution_id,
        phase_x_authorization_id=lease.phase_x_authorization_id,
        replica_id=lease.replica_id,
        activation_receipt_id=snapshot.activation_receipt.id,
        terminal_receipt_id=snapshot.terminal_receipt.id,
        authorization_hash=lease.authorization_hash,
        authorization_approval_receipt_hash=lease.authorization_approval_receipt_hash,
        phase_z_health_qualification_hash=lease.phase_z_health_qualification_hash,
        execution_hash=lease.execution_hash,
        phase_x_authorization_hash=lease.phase_x_authorization_hash,
        replica_hash=lease.replica_hash,
        activation_receipt_hash=snapshot.activation_receipt.receipt_hash,
        terminal_receipt_hash=snapshot.terminal_receipt.receipt_hash,
        verification_hash=lease.verification_hash,
        lease_snapshot_hash=lease.lease_snapshot_hash,
        lease_hash=lease.lease_hash,
        source_file_hash=lease.source_file_hash,
        source_file_size_bytes=lease.source_file_size_bytes,
        local_storage_key_fingerprint=lease.local_storage_key_fingerprint,
        recovery_bucket_fingerprint=lease.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=lease.candidate_storage_key_fingerprint,
        source_authority_fingerprint=lease.source_authority_fingerprint,
        candidate_authority_fingerprint=lease.candidate_authority_fingerprint,
        configuration_fingerprint=lease.configuration_fingerprint,
        canary_object_key_fingerprint=lease.canary_object_key_fingerprint,
        observed_file_hash=snapshot.observed_file_hash,
        observed_file_size_bytes=snapshot.observed_file_size_bytes,
        remote_etag=snapshot.remote_etag,
        read_route_version_at_request=snapshot.read_route.route_version,
        write_route_version_at_request=snapshot.write_route.route_version,
        integrity_proof_hash=snapshot.integrity_proof_hash,
        request_snapshot_hash=snapshot.request_snapshot_hash,
        health_qualification_hash=health_hash,
        health_state="healthy",
        phase_ab_activated_by_id=lease.activated_by_id,
        phase_aa_requested_by_id=auth.requested_by_id,
        phase_aa_approved_by_id=auth.approved_by_id,
        phase_z_qualified_by_id=auth.phase_z_qualified_by_id,
        phase_y_executed_by_id=auth.phase_y_executed_by_id,
        phase_x_approved_by_id=auth.phase_x_approved_by_id,
        requested_by_id=requested_by_id,
        requested_at=current,
        review_expires_at=current + CANARY_HEALTH_REVIEW_WINDOW,
        request_reason=normalized_reason,
        status="pending_second_approval",
        local_authoritative=True,
        storage_write_performed=False,
        canary_reactivated=False,
        routable_dual_write_active=False,
        durable_write_authority_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_put_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )
    db.add(q)
    db.flush()
    receipt = _add_receipt(db, q, phase="requested", actor_id=requested_by_id, reason=normalized_reason, now=current)
    return q, receipt, "pending_second_approval"


def get_routable_dual_write_canary_health_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    for_update: bool = False,
):
    stmt = select(EvidenceRecoveryRoutableDualWriteCanaryHealthQualification).where(
        EvidenceRecoveryRoutableDualWriteCanaryHealthQualification.id == health_qualification_id,
        EvidenceRecoveryRoutableDualWriteCanaryHealthQualification.organization_id == organization_id,
        EvidenceRecoveryRoutableDualWriteCanaryHealthQualification.claim_id == claim_id,
        EvidenceRecoveryRoutableDualWriteCanaryHealthQualification.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    q = db.scalar(stmt)
    if q is None:
        raise RecoveryRoutableDualWriteCanaryHealthNotFound("Phase AC health qualification not found")
    return q


def _terminalize(db: Session, q, *, phase: str, actor_id: UUID, reason: str, now: datetime):
    q.status = phase
    q.terminal_by_id = actor_id
    q.terminal_at = now
    q.terminal_reason = reason
    db.flush()
    return _add_receipt(db, q, phase=phase, actor_id=actor_id, reason=reason, now=now)


def qualify_routable_dual_write_canary_health(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    qualified_by_id: UUID,
    reason: str,
    now: datetime | None = None,
):
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryRoutableDualWriteCanaryHealthConflict("Phase AC qualification reason is required")
    current = _as_utc(now or _utc_now())
    q = get_routable_dual_write_canary_health_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        health_qualification_id=health_qualification_id,
        for_update=True,
    )
    if q.status != "pending_second_approval":
        return q, None, "unchanged"
    if current >= _as_utc(q.review_expires_at):
        receipt = _terminalize(
            db,
            q,
            phase="expired",
            actor_id=qualified_by_id,
            reason="Phase AC independent review window expired",
            now=current,
        )
        return q, receipt, "expired"
    if qualified_by_id in {
        q.requested_by_id,
        q.phase_ab_activated_by_id,
        q.phase_aa_requested_by_id,
        q.phase_aa_approved_by_id,
        q.phase_z_qualified_by_id,
        q.phase_y_executed_by_id,
        q.phase_x_approved_by_id,
    }:
        raise RecoveryRoutableDualWriteCanaryHealthConflict(
            "Phase AC qualifier must be independent from requester, Phase AB activator and prior governance actors"
        )
    try:
        snapshot = _load_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=q.canary_lease_id,
        )
    except RecoveryRoutableDualWriteCanaryHealthUnavailable:
        raise
    except (RecoveryRoutableDualWriteCanaryHealthNotFound, RecoveryRoutableDualWriteCanaryHealthConflict) as exc:
        receipt = _terminalize(
            db,
            q,
            phase="invalidated",
            actor_id=qualified_by_id,
            reason=f"Phase AC fresh verification invalidated: {exc}",
            now=current,
        )
        return q, receipt, "invalidated"
    if not _matches_snapshot(q, snapshot):
        receipt = _terminalize(
            db,
            q,
            phase="invalidated",
            actor_id=qualified_by_id,
            reason="Phase AC request snapshot drifted before independent qualification",
            now=current,
        )
        return q, receipt, "invalidated"
    q.status = "qualified"
    q.qualified_by_id = qualified_by_id
    q.qualified_at = current
    q.qualification_reason = normalized_reason
    db.flush()
    receipt = _add_receipt(db, q, phase="qualified", actor_id=qualified_by_id, reason=normalized_reason, now=current)
    return q, receipt, "qualified"


def reject_routable_dual_write_canary_health(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    rejected_by_id: UUID,
    reason: str,
    now: datetime | None = None,
):
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryRoutableDualWriteCanaryHealthConflict("Phase AC rejection reason is required")
    current = _as_utc(now or _utc_now())
    q = get_routable_dual_write_canary_health_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        health_qualification_id=health_qualification_id,
        for_update=True,
    )
    if q.status != "pending_second_approval":
        return q, None, "unchanged"
    if current >= _as_utc(q.review_expires_at):
        receipt = _terminalize(
            db,
            q,
            phase="expired",
            actor_id=rejected_by_id,
            reason="Phase AC independent review window expired",
            now=current,
        )
        return q, receipt, "expired"
    q.status = "rejected"
    q.rejected_by_id = rejected_by_id
    q.rejected_at = current
    q.rejection_reason = normalized_reason
    db.flush()
    receipt = _add_receipt(db, q, phase="rejected", actor_id=rejected_by_id, reason=normalized_reason, now=current)
    return q, receipt, "rejected"


def list_routable_dual_write_canary_health_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
):
    get_routable_dual_write_canary_health_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        health_qualification_id=health_qualification_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryRoutableDualWriteCanaryHealthReceipt)
            .where(
                EvidenceRecoveryRoutableDualWriteCanaryHealthReceipt.organization_id == organization_id,
                EvidenceRecoveryRoutableDualWriteCanaryHealthReceipt.claim_id == claim_id,
                EvidenceRecoveryRoutableDualWriteCanaryHealthReceipt.document_id == document_id,
                EvidenceRecoveryRoutableDualWriteCanaryHealthReceipt.health_qualification_id == health_qualification_id,
            )
            .order_by(
                EvidenceRecoveryRoutableDualWriteCanaryHealthReceipt.transitioned_at.asc(),
                EvidenceRecoveryRoutableDualWriteCanaryHealthReceipt.id.asc(),
            )
        ).all()
    )
