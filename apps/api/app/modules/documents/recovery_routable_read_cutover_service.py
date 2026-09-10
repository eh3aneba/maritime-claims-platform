from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.models import Document
from app.modules.documents.object_storage import (
    ObjectStorageError,
    ObjectStorageIntegrityError,
    ObjectStorageNotFound,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_read_path_cutover_models import (
    EvidenceRecoveryReadPathCutoverAuthorization,
    EvidenceRecoveryReadPathCutoverAuthorizationReceipt,
)
from app.modules.documents.recovery_read_path_cutover_service import (
    RecoveryReadPathCutoverAuthorizationConflict,
    RecoveryReadPathCutoverAuthorizationNotFound,
    RecoveryReadPathCutoverAuthorizationUnavailable,
    _get_authorization,
    _load_authorization_snapshot,
    _matches_snapshot as _matches_authorization_snapshot,
)
from app.modules.documents.recovery_replication_models import EvidenceRecoveryReplica
from app.modules.documents.recovery_replication_service import (
    RecoveryReplicationConflict,
    RecoveryReplicationUnavailable,
    _assert_replica_matches_source,
    _build_store,
    _snapshot_local,
)
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso
from app.modules.documents.recovery_routable_read_cutover_models import (
    EvidenceRecoveryReadPathCutoverLease,
    EvidenceRecoveryReadPathCutoverReceipt,
    EvidenceRecoveryReadPathRoute,
)

ROUTABLE_READ_CUTOVER_LEASE_WINDOW = timedelta(minutes=10)


class RecoveryRoutableReadCutoverError(RuntimeError):
    pass


class RecoveryRoutableReadCutoverNotFound(RecoveryRoutableReadCutoverError):
    pass


class RecoveryRoutableReadCutoverConflict(RecoveryRoutableReadCutoverError):
    pass


class RecoveryRoutableReadCutoverUnavailable(RecoveryRoutableReadCutoverError):
    pass


@dataclass(frozen=True)
class RoutableReadCutoverSnapshot:
    authorization_id: UUID
    authorization_approval_receipt_id: UUID
    replica_id: UUID
    authorization_hash: str
    authorization_request_snapshot_hash: str
    authorization_approval_receipt_hash: str
    execution_transition_proof_hash: str
    replica_hash: str
    source_file_hash: str
    source_file_size_bytes: int
    recovery_bucket_fingerprint: str
    candidate_storage_key_fingerprint: str
    source_authority_fingerprint: str
    candidate_authority_fingerprint: str
    configuration_fingerprint: str
    lease_snapshot_hash: str
    authorization_approved_by_id: UUID
    authorization_expires_at: datetime
    candidate_payload: bytes


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _authorization_approval_receipt(
    db: Session,
    authorization: EvidenceRecoveryReadPathCutoverAuthorization,
) -> EvidenceRecoveryReadPathCutoverAuthorizationReceipt:
    receipt = db.scalar(
        select(EvidenceRecoveryReadPathCutoverAuthorizationReceipt)
        .where(
            EvidenceRecoveryReadPathCutoverAuthorizationReceipt.organization_id
            == authorization.organization_id,
            EvidenceRecoveryReadPathCutoverAuthorizationReceipt.claim_id
            == authorization.claim_id,
            EvidenceRecoveryReadPathCutoverAuthorizationReceipt.document_id
            == authorization.document_id,
            EvidenceRecoveryReadPathCutoverAuthorizationReceipt.authorization_id
            == authorization.id,
            EvidenceRecoveryReadPathCutoverAuthorizationReceipt.phase == "approved",
        )
        .order_by(
            EvidenceRecoveryReadPathCutoverAuthorizationReceipt.transitioned_at.desc(),
            EvidenceRecoveryReadPathCutoverAuthorizationReceipt.created_at.desc(),
            EvidenceRecoveryReadPathCutoverAuthorizationReceipt.id.desc(),
        )
        .limit(1)
    )
    if receipt is None:
        raise RecoveryRoutableReadCutoverConflict(
            "Approved read-path cutover authorization has no approval receipt"
        )
    if not all(
        (
            receipt.execution_lease_id == authorization.execution_lease_id,
            receipt.request_snapshot_hash == authorization.request_snapshot_hash,
            receipt.authorization_hash == authorization.authorization_hash,
            receipt.execution_transition_proof_hash
            == authorization.execution_transition_proof_hash,
            receipt.routable_authority_created is False,
            receipt.read_path_switched is False,
            receipt.authoritative_storage_changed is False,
            receipt.destructive_action_performed is False,
        )
    ):
        raise RecoveryRoutableReadCutoverConflict(
            "Read-path cutover authorization approval receipt lineage is inconsistent"
        )
    return receipt


def _load_document(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    for_update: bool = False,
) -> Document:
    stmt = select(Document).where(
        Document.id == document_id,
        Document.organization_id == organization_id,
        Document.claim_id == claim_id,
        Document.deleted_at.is_(None),
    )
    if for_update:
        stmt = stmt.with_for_update()
    document = db.scalar(stmt)
    if document is None:
        raise RecoveryRoutableReadCutoverNotFound("Document not found")
    return document


def _load_replica(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    replica_id: UUID,
) -> EvidenceRecoveryReplica:
    replica = db.scalar(
        select(EvidenceRecoveryReplica).where(
            EvidenceRecoveryReplica.id == replica_id,
            EvidenceRecoveryReplica.organization_id == organization_id,
            EvidenceRecoveryReplica.claim_id == claim_id,
            EvidenceRecoveryReplica.document_id == document_id,
        )
    )
    if replica is None:
        raise RecoveryRoutableReadCutoverNotFound("Recovery replica not found")
    return replica


def _read_verified_candidate(replica: EvidenceRecoveryReplica) -> bytes:
    try:
        store = _build_store()
        if (
            store.sanitized_health_identity.bucket_fingerprint
            != replica.recovery_bucket_fingerprint
        ):
            raise RecoveryRoutableReadCutoverConflict(
                "Configured recovery bucket drifted from the pinned replica"
            )
        metadata = store.head_object(storage_key=replica.recovery_storage_key)
        if (
            metadata.file_hash != replica.source_file_hash
            or metadata.file_size_bytes != replica.source_file_size_bytes
        ):
            raise RecoveryRoutableReadCutoverConflict(
                "Recovery candidate metadata drifted from the pinned evidence hash"
            )
        payload = store.get_bytes(
            storage_key=replica.recovery_storage_key,
            expected_sha256=replica.source_file_hash,
        )
    except RecoveryRoutableReadCutoverError:
        raise
    except ObjectStorageNotFound as exc:
        raise RecoveryRoutableReadCutoverConflict(
            "Recovery candidate object is missing"
        ) from exc
    except ObjectStorageIntegrityError as exc:
        raise RecoveryRoutableReadCutoverConflict(
            "Recovery candidate failed integrity verification"
        ) from exc
    except (ObjectStorageError, RecoveryReplicationUnavailable) as exc:
        raise RecoveryRoutableReadCutoverUnavailable(
            "Recovery candidate storage is unavailable"
        ) from exc
    if len(payload) != replica.source_file_size_bytes:
        raise RecoveryRoutableReadCutoverConflict(
            "Recovery candidate byte length drifted from the pinned evidence size"
        )
    return payload


def _load_cutover_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    now: datetime | None = None,
) -> RoutableReadCutoverSnapshot:
    current_time = _as_utc(now or _utc_now())
    try:
        authorization = _get_authorization(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
        )
        if (
            authorization.status != "approved"
            or authorization.approved_by_id is None
            or authorization.approved_at is None
        ):
            raise RecoveryRoutableReadCutoverConflict(
                "Only an approved read-path cutover authorization can prepare a routable lease"
            )
        if current_time >= _as_utc(authorization.authorization_expires_at):
            raise RecoveryRoutableReadCutoverConflict(
                "Approved read-path cutover authorization is outside its bounded window"
            )
        if any(
            (
                authorization.routable_authority_created,
                authorization.read_path_switched,
                authorization.document_storage_key_mutated,
                authorization.active_backend_changed,
                authorization.authoritative_storage_changed,
                authorization.destructive_action_performed,
                authorization.s3_delete_performed,
                authorization.local_delete_performed,
            )
        ):
            raise RecoveryRoutableReadCutoverConflict(
                "Read-path cutover authorization crossed its non-routable safety boundary"
            )

        authorization_snapshot = _load_authorization_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            execution_lease_id=authorization.execution_lease_id,
            now=current_time,
        )
        if not _matches_authorization_snapshot(authorization, authorization_snapshot):
            raise RecoveryRoutableReadCutoverConflict(
                "Read-path cutover authorization lineage drifted before routable cutover"
            )
        approval = _authorization_approval_receipt(db, authorization)

        document = _load_document(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
        replica = _load_replica(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            replica_id=authorization.replica_id,
        )
        local_snapshot = _snapshot_local(document)
        _assert_replica_matches_source(replica, local_snapshot)
        candidate_payload = _read_verified_candidate(replica)
        candidate_storage_key_fingerprint = hashlib.sha256(
            replica.recovery_storage_key.encode("utf-8")
        ).hexdigest()
        lease_snapshot_hash = _canonical_hash(
            {
                "organization_id": str(organization_id),
                "claim_id": str(claim_id),
                "document_id": str(document_id),
                "authorization_id": str(authorization.id),
                "authorization_hash": authorization.authorization_hash,
                "authorization_request_snapshot_hash": authorization.request_snapshot_hash,
                "authorization_approval_receipt_id": str(approval.id),
                "authorization_approval_receipt_hash": approval.receipt_hash,
                "execution_transition_proof_hash": authorization.execution_transition_proof_hash,
                "replica_id": str(replica.id),
                "replica_hash": replica.replica_hash,
                "source_file_hash": replica.source_file_hash,
                "source_file_size_bytes": replica.source_file_size_bytes,
                "recovery_bucket_fingerprint": replica.recovery_bucket_fingerprint,
                "candidate_storage_key_fingerprint": candidate_storage_key_fingerprint,
                "source_authority_fingerprint": authorization.source_authority_fingerprint,
                "candidate_authority_fingerprint": authorization.candidate_authority_fingerprint,
                "configuration_fingerprint": authorization.configuration_fingerprint,
                "mode": "reversible_routable_read_cutover",
                "write_path_switched": False,
                "document_storage_key_mutated": False,
                "authoritative_storage_changed": False,
            }
        )
        return RoutableReadCutoverSnapshot(
            authorization_id=authorization.id,
            authorization_approval_receipt_id=approval.id,
            replica_id=replica.id,
            authorization_hash=authorization.authorization_hash,
            authorization_request_snapshot_hash=authorization.request_snapshot_hash,
            authorization_approval_receipt_hash=approval.receipt_hash,
            execution_transition_proof_hash=authorization.execution_transition_proof_hash,
            replica_hash=replica.replica_hash,
            source_file_hash=replica.source_file_hash,
            source_file_size_bytes=replica.source_file_size_bytes,
            recovery_bucket_fingerprint=replica.recovery_bucket_fingerprint,
            candidate_storage_key_fingerprint=candidate_storage_key_fingerprint,
            source_authority_fingerprint=authorization.source_authority_fingerprint,
            candidate_authority_fingerprint=authorization.candidate_authority_fingerprint,
            configuration_fingerprint=authorization.configuration_fingerprint,
            lease_snapshot_hash=lease_snapshot_hash,
            authorization_approved_by_id=authorization.approved_by_id,
            authorization_expires_at=_as_utc(authorization.authorization_expires_at),
            candidate_payload=candidate_payload,
        )
    except RecoveryRoutableReadCutoverError:
        raise
    except RecoveryReadPathCutoverAuthorizationNotFound as exc:
        raise RecoveryRoutableReadCutoverNotFound(str(exc)) from exc
    except RecoveryReadPathCutoverAuthorizationConflict as exc:
        raise RecoveryRoutableReadCutoverConflict(str(exc)) from exc
    except RecoveryReadPathCutoverAuthorizationUnavailable as exc:
        raise RecoveryRoutableReadCutoverUnavailable(str(exc)) from exc
    except RecoveryReplicationConflict as exc:
        raise RecoveryRoutableReadCutoverConflict(str(exc)) from exc


def _matches_snapshot(
    lease: EvidenceRecoveryReadPathCutoverLease,
    snapshot: RoutableReadCutoverSnapshot,
) -> bool:
    return all(
        (
            lease.authorization_id == snapshot.authorization_id,
            lease.authorization_approval_receipt_id
            == snapshot.authorization_approval_receipt_id,
            lease.replica_id == snapshot.replica_id,
            lease.authorization_hash == snapshot.authorization_hash,
            lease.authorization_request_snapshot_hash
            == snapshot.authorization_request_snapshot_hash,
            lease.authorization_approval_receipt_hash
            == snapshot.authorization_approval_receipt_hash,
            lease.execution_transition_proof_hash
            == snapshot.execution_transition_proof_hash,
            lease.replica_hash == snapshot.replica_hash,
            lease.source_file_hash == snapshot.source_file_hash,
            lease.source_file_size_bytes == snapshot.source_file_size_bytes,
            lease.recovery_bucket_fingerprint == snapshot.recovery_bucket_fingerprint,
            lease.candidate_storage_key_fingerprint
            == snapshot.candidate_storage_key_fingerprint,
            lease.source_authority_fingerprint
            == snapshot.source_authority_fingerprint,
            lease.candidate_authority_fingerprint
            == snapshot.candidate_authority_fingerprint,
            lease.configuration_fingerprint == snapshot.configuration_fingerprint,
            lease.lease_snapshot_hash == snapshot.lease_snapshot_hash,
            lease.authorization_approved_by_id
            == snapshot.authorization_approved_by_id,
        )
    )


def _get_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    for_update: bool = False,
) -> EvidenceRecoveryReadPathCutoverLease:
    stmt = select(EvidenceRecoveryReadPathCutoverLease).where(
        EvidenceRecoveryReadPathCutoverLease.id == lease_id,
        EvidenceRecoveryReadPathCutoverLease.organization_id == organization_id,
        EvidenceRecoveryReadPathCutoverLease.claim_id == claim_id,
        EvidenceRecoveryReadPathCutoverLease.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    lease = db.scalar(stmt)
    if lease is None:
        raise RecoveryRoutableReadCutoverNotFound(
            "Recovery read-path cutover lease not found"
        )
    return lease


def _get_route(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    for_update: bool = False,
    required: bool = True,
) -> EvidenceRecoveryReadPathRoute | None:
    stmt = select(EvidenceRecoveryReadPathRoute).where(
        EvidenceRecoveryReadPathRoute.organization_id == organization_id,
        EvidenceRecoveryReadPathRoute.claim_id == claim_id,
        EvidenceRecoveryReadPathRoute.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    route = db.scalar(stmt)
    if route is None and required:
        raise RecoveryRoutableReadCutoverNotFound("Recovery read-path route not found")
    return route


def _route_matches_snapshot(
    route: EvidenceRecoveryReadPathRoute,
    snapshot: RoutableReadCutoverSnapshot,
) -> bool:
    return all(
        (
            route.source_authority_fingerprint
            == snapshot.source_authority_fingerprint,
            route.candidate_authority_fingerprint
            == snapshot.candidate_authority_fingerprint,
            route.configuration_fingerprint == snapshot.configuration_fingerprint,
            route.write_path_switched is False,
            route.document_storage_key_mutated is False,
            route.authoritative_storage_changed is False,
            route.destructive_action_performed is False,
        )
    )


def _new_receipt(
    *,
    lease: EvidenceRecoveryReadPathCutoverLease,
    phase: str,
    from_route_class: str,
    to_route_class: str,
    route_version: int,
    actor_id: UUID,
    reason: str,
    transitioned_at: datetime,
) -> EvidenceRecoveryReadPathCutoverReceipt:
    normalized_reason = reason.strip()
    switched = to_route_class == "recovery_replica"
    receipt_hash = _canonical_hash(
        {
            "cutover_lease_id": str(lease.id),
            "authorization_id": str(lease.authorization_id),
            "phase": phase,
            "from_route_class": from_route_class,
            "to_route_class": to_route_class,
            "route_version": route_version,
            "lease_snapshot_hash": lease.lease_snapshot_hash,
            "lease_hash": lease.lease_hash,
            "authorization_hash": lease.authorization_hash,
            "actor_id": str(actor_id),
            "reason": normalized_reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "routable_authority_created": switched,
            "read_path_switched": switched,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
        }
    )
    return EvidenceRecoveryReadPathCutoverReceipt(
        organization_id=lease.organization_id,
        claim_id=lease.claim_id,
        document_id=lease.document_id,
        cutover_lease_id=lease.id,
        authorization_id=lease.authorization_id,
        phase=phase,
        from_route_class=from_route_class,
        to_route_class=to_route_class,
        route_version=route_version,
        lease_snapshot_hash=lease.lease_snapshot_hash,
        lease_hash=lease.lease_hash,
        authorization_hash=lease.authorization_hash,
        receipt_hash=receipt_hash,
        actor_id=actor_id,
        reason=normalized_reason,
        transitioned_at=transitioned_at,
        routable_authority_created=switched,
        read_path_switched=switched,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
    )


def _terminalize_prepared(
    db: Session,
    *,
    lease: EvidenceRecoveryReadPathCutoverLease,
    route: EvidenceRecoveryReadPathRoute,
    status: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryReadPathCutoverReceipt:
    if route.route_class != "local_source" or route.active_lease_id is not None:
        raise RecoveryRoutableReadCutoverConflict(
            "Prepared cutover lease cannot terminalize while recovery routing is active"
        )
    lease.status = status
    lease.terminal_by_id = actor_id
    lease.terminal_at = now
    lease.terminal_reason = reason
    lease.routable_authority_created = False
    lease.read_path_switched = False
    receipt = _new_receipt(
        lease=lease,
        phase=status,
        from_route_class="local_source",
        to_route_class="local_source",
        route_version=route.route_version,
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
    )
    db.add(receipt)
    db.flush()
    return receipt


def prepare_recovery_routable_read_cutover_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    prepared_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryReadPathCutoverLease,
    EvidenceRecoveryReadPathRoute,
    EvidenceRecoveryReadPathCutoverReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryRoutableReadCutoverConflict(
            "Routable read cutover lease preparation reason is required"
        )
    current_time = _as_utc(now or _utc_now())
    snapshot = _load_cutover_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=authorization_id,
        now=current_time,
    )
    existing = db.scalar(
        select(EvidenceRecoveryReadPathCutoverLease)
        .where(
            EvidenceRecoveryReadPathCutoverLease.organization_id == organization_id,
            EvidenceRecoveryReadPathCutoverLease.claim_id == claim_id,
            EvidenceRecoveryReadPathCutoverLease.document_id == document_id,
            EvidenceRecoveryReadPathCutoverLease.authorization_id == authorization_id,
        )
        .with_for_update()
    )
    if existing is not None:
        route = _get_route(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            for_update=True,
        )
        assert route is not None
        if _matches_snapshot(existing, snapshot):
            if existing.status == "activated":
                if not (
                    route.route_class == "recovery_replica"
                    and route.active_lease_id == existing.id
                    and route.active_replica_id == existing.replica_id
                    and _route_matches_snapshot(route, snapshot)
                ):
                    raise RecoveryRoutableReadCutoverConflict(
                        "Active read cutover lease no longer matches the routing record"
                    )
                return existing, route, None, "unchanged"
            if existing.status in {"prepared", "rolled_back"}:
                if not (
                    route.route_class == "local_source"
                    and route.active_lease_id is None
                    and route.active_replica_id is None
                    and _route_matches_snapshot(route, snapshot)
                ):
                    raise RecoveryRoutableReadCutoverConflict(
                        "Read cutover lease replay no longer matches local routing"
                    )
                return existing, route, None, "unchanged"
        if existing.status == "prepared":
            receipt = _terminalize_prepared(
                db,
                lease=existing,
                route=route,
                status="invalidated",
                actor_id=prepared_by_id,
                reason="Routable read cutover lineage drifted before preparation replay",
                now=current_time,
            )
            return existing, route, receipt, "invalidated"
        raise RecoveryRoutableReadCutoverConflict(
            "A terminal routable read cutover lease already exists for this authorization"
        )

    route = _get_route(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        for_update=True,
        required=False,
    )
    if route is None:
        route = EvidenceRecoveryReadPathRoute(
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            route_class="local_source",
            active_lease_id=None,
            active_replica_id=None,
            source_authority_fingerprint=snapshot.source_authority_fingerprint,
            candidate_authority_fingerprint=snapshot.candidate_authority_fingerprint,
            configuration_fingerprint=snapshot.configuration_fingerprint,
            route_version=1,
            changed_by_id=prepared_by_id,
            changed_at=current_time,
            read_path_switched=False,
            write_path_switched=False,
            document_storage_key_mutated=False,
            authoritative_storage_changed=False,
            destructive_action_performed=False,
        )
        db.add(route)
        db.flush()
    elif not (
        route.route_class == "local_source"
        and route.active_lease_id is None
        and route.active_replica_id is None
        and route.read_path_switched is False
        and _route_matches_snapshot(route, snapshot)
    ):
        raise RecoveryRoutableReadCutoverConflict(
            "Document read route is not in a clean local-source state"
        )

    expires_at = min(
        current_time + ROUTABLE_READ_CUTOVER_LEASE_WINDOW,
        snapshot.authorization_expires_at,
    )
    if expires_at <= current_time:
        raise RecoveryRoutableReadCutoverConflict(
            "Routable read cutover lease window is not available"
        )
    lease_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "authorization_id": str(authorization_id),
            "lease_snapshot_hash": snapshot.lease_snapshot_hash,
            "prepared_by_id": str(prepared_by_id),
            "prepared_at": _utc_iso(current_time),
            "lease_expires_at": _utc_iso(expires_at),
            "mode": "reversible_routable_read_cutover_lease",
            "write_path_switched": False,
            "document_storage_key_mutated": False,
        }
    )
    lease = EvidenceRecoveryReadPathCutoverLease(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authorization_id=snapshot.authorization_id,
        authorization_approval_receipt_id=snapshot.authorization_approval_receipt_id,
        replica_id=snapshot.replica_id,
        authorization_hash=snapshot.authorization_hash,
        authorization_request_snapshot_hash=snapshot.authorization_request_snapshot_hash,
        authorization_approval_receipt_hash=snapshot.authorization_approval_receipt_hash,
        execution_transition_proof_hash=snapshot.execution_transition_proof_hash,
        replica_hash=snapshot.replica_hash,
        source_file_hash=snapshot.source_file_hash,
        source_file_size_bytes=snapshot.source_file_size_bytes,
        recovery_bucket_fingerprint=snapshot.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=snapshot.candidate_storage_key_fingerprint,
        source_authority_fingerprint=snapshot.source_authority_fingerprint,
        candidate_authority_fingerprint=snapshot.candidate_authority_fingerprint,
        configuration_fingerprint=snapshot.configuration_fingerprint,
        lease_snapshot_hash=snapshot.lease_snapshot_hash,
        lease_hash=lease_hash,
        status="prepared",
        lease_expires_at=expires_at,
        authorization_approved_by_id=snapshot.authorization_approved_by_id,
        prepared_by_id=prepared_by_id,
        prepared_at=current_time,
        preparation_reason=normalized_reason,
        routable_authority_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )
    db.add(lease)
    db.flush()
    receipt = _new_receipt(
        lease=lease,
        phase="prepared",
        from_route_class="local_source",
        to_route_class="local_source",
        route_version=route.route_version,
        actor_id=prepared_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return lease, route, receipt, "prepared"


def activate_recovery_routable_read_cutover_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    activated_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryReadPathCutoverLease,
    EvidenceRecoveryReadPathRoute,
    EvidenceRecoveryReadPathCutoverReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryRoutableReadCutoverConflict(
            "Routable read cutover activation reason is required"
        )
    current_time = _as_utc(now or _utc_now())
    lease = _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
        for_update=True,
    )
    route = _get_route(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        for_update=True,
    )
    assert route is not None
    if lease.status == "activated":
        if route.route_class != "recovery_replica" or route.active_lease_id != lease.id:
            raise RecoveryRoutableReadCutoverConflict(
                "Activated lease is inconsistent with the active read route"
            )
        return lease, route, None, "unchanged"
    if lease.status != "prepared":
        raise RecoveryRoutableReadCutoverConflict(
            "Only a prepared routable read cutover lease can be activated"
        )
    if lease.prepared_by_id == activated_by_id:
        raise RecoveryRoutableReadCutoverConflict(
            "Read cutover activation requires a different Admin from the preparer"
        )
    if lease.authorization_approved_by_id == activated_by_id:
        raise RecoveryRoutableReadCutoverConflict(
            "Read cutover activator must differ from the authorization approver"
        )
    if current_time >= _as_utc(lease.lease_expires_at):
        receipt = _terminalize_prepared(
            db,
            lease=lease,
            route=route,
            status="expired",
            actor_id=activated_by_id,
            reason="Routable read cutover activation window expired",
            now=current_time,
        )
        return lease, route, receipt, "expired"
    try:
        snapshot = _load_cutover_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=lease.authorization_id,
            now=current_time,
        )
    except (
        RecoveryRoutableReadCutoverConflict,
        RecoveryRoutableReadCutoverNotFound,
    ) as exc:
        receipt = _terminalize_prepared(
            db,
            lease=lease,
            route=route,
            status="invalidated",
            actor_id=activated_by_id,
            reason=f"Fresh routable read cutover preflight failed: {type(exc).__name__}",
            now=current_time,
        )
        return lease, route, receipt, "invalidated"
    if not _matches_snapshot(lease, snapshot) or not _route_matches_snapshot(route, snapshot):
        receipt = _terminalize_prepared(
            db,
            lease=lease,
            route=route,
            status="invalidated",
            actor_id=activated_by_id,
            reason="Routable read cutover lineage drifted before activation",
            now=current_time,
        )
        return lease, route, receipt, "invalidated"
    if not (
        route.route_class == "local_source"
        and route.active_lease_id is None
        and route.active_replica_id is None
        and route.read_path_switched is False
    ):
        raise RecoveryRoutableReadCutoverConflict(
            "Document read route is not available for activation"
        )

    lease.status = "activated"
    lease.activated_by_id = activated_by_id
    lease.activated_at = current_time
    lease.activation_reason = normalized_reason
    lease.routable_authority_created = True
    lease.read_path_switched = True

    route.route_class = "recovery_replica"
    route.active_lease_id = lease.id
    route.active_replica_id = lease.replica_id
    route.route_version += 1
    route.changed_by_id = activated_by_id
    route.changed_at = current_time
    route.read_path_switched = True

    receipt = _new_receipt(
        lease=lease,
        phase="activated",
        from_route_class="local_source",
        to_route_class="recovery_replica",
        route_version=route.route_version,
        actor_id=activated_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return lease, route, receipt, "activated"


def rollback_recovery_routable_read_cutover_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    rolled_back_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryReadPathCutoverLease,
    EvidenceRecoveryReadPathRoute,
    EvidenceRecoveryReadPathCutoverReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryRoutableReadCutoverConflict(
            "Routable read cutover rollback reason is required"
        )
    current_time = _as_utc(now or _utc_now())
    lease = _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
        for_update=True,
    )
    route = _get_route(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        for_update=True,
    )
    assert route is not None
    if lease.status == "rolled_back":
        if route.route_class != "local_source" or route.active_lease_id is not None:
            raise RecoveryRoutableReadCutoverConflict(
                "Rolled-back lease is inconsistent with the local read route"
            )
        return lease, route, None, "unchanged"
    if lease.status != "activated":
        raise RecoveryRoutableReadCutoverConflict(
            "Only an activated routable read cutover lease can be rolled back"
        )
    if not (
        route.route_class == "recovery_replica"
        and route.active_lease_id == lease.id
        and route.active_replica_id == lease.replica_id
        and route.read_path_switched is True
    ):
        raise RecoveryRoutableReadCutoverConflict(
            "Active read route does not match the lease being rolled back"
        )

    route.route_class = "local_source"
    route.active_lease_id = None
    route.active_replica_id = None
    route.route_version += 1
    route.changed_by_id = rolled_back_by_id
    route.changed_at = current_time
    route.read_path_switched = False

    lease.status = "rolled_back"
    lease.rolled_back_by_id = rolled_back_by_id
    lease.rolled_back_at = current_time
    lease.rollback_reason = normalized_reason
    lease.routable_authority_created = False
    lease.read_path_switched = False

    receipt = _new_receipt(
        lease=lease,
        phase="rolled_back",
        from_route_class="recovery_replica",
        to_route_class="local_source",
        route_version=route.route_version,
        actor_id=rolled_back_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return lease, route, receipt, "rolled_back"


def resolve_recovery_document_read(
    db: Session,
    *,
    document: Document,
    now: datetime | None = None,
) -> tuple[bytes | None, str]:
    route = _get_route(
        db,
        organization_id=document.organization_id,
        claim_id=document.claim_id,
        document_id=document.id,
        required=False,
    )
    if route is None:
        return None, "local-source"
    if route.route_class == "local_source":
        if (
            route.active_lease_id is not None
            or route.active_replica_id is not None
            or route.read_path_switched
        ):
            raise RecoveryRoutableReadCutoverConflict(
                "Local read route contains inconsistent active recovery authority"
            )
        return None, "local-source"
    if not (
        route.route_class == "recovery_replica"
        and route.active_lease_id is not None
        and route.active_replica_id is not None
        and route.read_path_switched
        and route.write_path_switched is False
        and route.document_storage_key_mutated is False
        and route.authoritative_storage_changed is False
        and route.destructive_action_performed is False
    ):
        raise RecoveryRoutableReadCutoverConflict(
            "Active recovery read route is structurally inconsistent"
        )

    current_time = _as_utc(now or _utc_now())
    lease = _get_lease(
        db,
        organization_id=document.organization_id,
        claim_id=document.claim_id,
        document_id=document.id,
        lease_id=route.active_lease_id,
    )
    if not (
        lease.status == "activated"
        and lease.read_path_switched
        and lease.routable_authority_created
        and lease.write_path_switched is False
        and lease.document_storage_key_mutated is False
        and lease.authoritative_storage_changed is False
        and lease.destructive_action_performed is False
        and lease.replica_id == route.active_replica_id
    ):
        raise RecoveryRoutableReadCutoverConflict(
            "Active recovery read route is not backed by a valid activated lease"
        )
    if current_time >= _as_utc(lease.lease_expires_at):
        raise RecoveryRoutableReadCutoverConflict(
            "Active recovery read route lease expired; rollback is required"
        )

    snapshot = _load_cutover_snapshot(
        db,
        organization_id=document.organization_id,
        claim_id=document.claim_id,
        document_id=document.id,
        authorization_id=lease.authorization_id,
        now=current_time,
    )
    if not _matches_snapshot(lease, snapshot) or not _route_matches_snapshot(route, snapshot):
        raise RecoveryRoutableReadCutoverConflict(
            "Active recovery read route lineage drifted; rollback is required"
        )
    if route.active_replica_id != snapshot.replica_id:
        raise RecoveryRoutableReadCutoverConflict(
            "Active recovery read route points to the wrong replica"
        )
    return snapshot.candidate_payload, "recovery-replica"


def get_recovery_routable_read_cutover_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
) -> EvidenceRecoveryReadPathCutoverLease:
    return _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
    )


def get_recovery_read_path_route(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
) -> EvidenceRecoveryReadPathRoute:
    route = _get_route(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
    )
    assert route is not None
    return route


def list_recovery_routable_read_cutover_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
) -> list[EvidenceRecoveryReadPathCutoverReceipt]:
    _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryReadPathCutoverReceipt)
            .where(
                EvidenceRecoveryReadPathCutoverReceipt.organization_id == organization_id,
                EvidenceRecoveryReadPathCutoverReceipt.claim_id == claim_id,
                EvidenceRecoveryReadPathCutoverReceipt.document_id == document_id,
                EvidenceRecoveryReadPathCutoverReceipt.cutover_lease_id == lease_id,
            )
            .order_by(
                EvidenceRecoveryReadPathCutoverReceipt.transitioned_at.asc(),
                EvidenceRecoveryReadPathCutoverReceipt.created_at.asc(),
                EvidenceRecoveryReadPathCutoverReceipt.id.asc(),
            )
        ).all()
    )
