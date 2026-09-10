from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog
from app.modules.documents.models import Document
from app.modules.documents.recovery_durable_read_health_models import (
    EvidenceRecoveryDurableReadHealthQualification,
    EvidenceRecoveryDurableReadHealthQualificationReceipt,
)
from app.modules.documents.recovery_durable_read_routing_models import (
    EvidenceRecoveryDurableReadPromotionLease,
    EvidenceRecoveryDurableReadPromotionReceipt,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_replication_service import (
    RecoveryReplicationConflict,
    RecoveryReplicationUnavailable,
    _assert_replica_matches_source,
    _snapshot_local,
)
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute
from app.modules.documents.recovery_routable_read_cutover_service import (
    RecoveryRoutableReadCutoverConflict,
    RecoveryRoutableReadCutoverNotFound,
    RecoveryRoutableReadCutoverUnavailable,
    _load_replica,
    _read_verified_candidate,
)


class RecoveryDurableReadHealthError(RuntimeError):
    pass


class RecoveryDurableReadHealthNotFound(RecoveryDurableReadHealthError):
    pass


class RecoveryDurableReadHealthConflict(RecoveryDurableReadHealthError):
    pass


class RecoveryDurableReadHealthUnavailable(RecoveryDurableReadHealthError):
    pass


@dataclass(frozen=True)
class DurableReadOperationalEvidence:
    verified_durable_read_count: int
    integrity_failure_count: int
    storage_unavailable_count: int
    route_expired_attempt_count: int
    operational_event_count: int
    health_state: str
    operational_evidence_hash: str


@dataclass(frozen=True)
class DurableReadHealthSnapshot:
    lease: EvidenceRecoveryDurableReadPromotionLease
    activation: EvidenceRecoveryDurableReadPromotionReceipt
    terminal: EvidenceRecoveryDurableReadPromotionReceipt
    document: Document
    route: EvidenceRecoveryReadPathRoute
    terminal_phase: str
    window_started_at: datetime
    window_ended_at: datetime
    evidence: DurableReadOperationalEvidence
    request_snapshot_hash: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _get_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    durable_lease_id: UUID,
) -> EvidenceRecoveryDurableReadPromotionLease:
    lease = db.scalar(
        select(EvidenceRecoveryDurableReadPromotionLease).where(
            EvidenceRecoveryDurableReadPromotionLease.id == durable_lease_id,
            EvidenceRecoveryDurableReadPromotionLease.organization_id == organization_id,
            EvidenceRecoveryDurableReadPromotionLease.claim_id == claim_id,
            EvidenceRecoveryDurableReadPromotionLease.document_id == document_id,
        )
    )
    if lease is None:
        raise RecoveryDurableReadHealthNotFound("Durable recovery read lease not found")
    return lease


def _get_document(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
) -> Document:
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.organization_id == organization_id,
            Document.claim_id == claim_id,
        )
    )
    if document is None or document.deleted_at is not None:
        raise RecoveryDurableReadHealthNotFound("Document not found")
    return document


def _get_route(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
) -> EvidenceRecoveryReadPathRoute:
    route = db.scalar(
        select(EvidenceRecoveryReadPathRoute).where(
            EvidenceRecoveryReadPathRoute.organization_id == organization_id,
            EvidenceRecoveryReadPathRoute.claim_id == claim_id,
            EvidenceRecoveryReadPathRoute.document_id == document_id,
        )
    )
    if route is None:
        raise RecoveryDurableReadHealthNotFound("Recovery read-path route not found")
    return route


def _receipt(
    db: Session,
    *,
    lease: EvidenceRecoveryDurableReadPromotionLease,
    phase: str,
) -> EvidenceRecoveryDurableReadPromotionReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryDurableReadPromotionReceipt).where(
                EvidenceRecoveryDurableReadPromotionReceipt.organization_id == lease.organization_id,
                EvidenceRecoveryDurableReadPromotionReceipt.claim_id == lease.claim_id,
                EvidenceRecoveryDurableReadPromotionReceipt.document_id == lease.document_id,
                EvidenceRecoveryDurableReadPromotionReceipt.durable_lease_id == lease.id,
                EvidenceRecoveryDurableReadPromotionReceipt.phase == phase,
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryDurableReadHealthConflict(
            f"Durable recovery read lease must have exactly one {phase} receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            receipt.authorization_id == lease.authorization_id,
            receipt.lease_snapshot_hash == lease.lease_snapshot_hash,
            receipt.lease_hash == lease.lease_hash,
            receipt.authorization_hash == lease.authorization_hash,
            receipt.write_path_switched is False,
            receipt.document_storage_key_mutated is False,
            receipt.authoritative_storage_changed is False,
            receipt.destructive_action_performed is False,
            receipt.s3_delete_performed is False,
            receipt.local_delete_performed is False,
        )
    ):
        raise RecoveryDurableReadHealthConflict("Durable read receipt lineage is inconsistent")
    return receipt


def _terminal_window(
    lease: EvidenceRecoveryDurableReadPromotionLease,
) -> tuple[str, datetime, datetime]:
    if lease.status not in {"rolled_back", "expired"}:
        raise RecoveryDurableReadHealthConflict(
            "Only a completed durable recovery read window can be health-qualified"
        )
    if lease.activated_by_id is None or lease.activated_at is None:
        raise RecoveryDurableReadHealthConflict("Durable read lease is missing activation lineage")
    if lease.status == "rolled_back":
        if lease.rolled_back_at is None or lease.rolled_back_by_id is None:
            raise RecoveryDurableReadHealthConflict("Rolled-back durable read lease is incomplete")
        ended_at = _as_utc(lease.rolled_back_at)
    else:
        if lease.terminal_at is None or lease.terminal_by_id is None:
            raise RecoveryDurableReadHealthConflict("Expired durable read lease is incomplete")
        ended_at = _as_utc(lease.terminal_at)
    started_at = _as_utc(lease.activated_at)
    if ended_at < started_at:
        raise RecoveryDurableReadHealthConflict("Durable read operational window is temporally invalid")
    return lease.status, started_at, ended_at


def _operational_evidence(
    db: Session,
    *,
    lease: EvidenceRecoveryDurableReadPromotionLease,
    started_at: datetime,
    ended_at: datetime,
) -> DurableReadOperationalEvidence:
    events = list(
        db.scalars(
            select(AuditLog)
            .where(
                AuditLog.organization_id == lease.organization_id,
                AuditLog.entity_type == "document",
                AuditLog.entity_id == lease.document_id,
                AuditLog.action.in_(("DOWNLOAD_DOCUMENT", "DOWNLOAD_DOCUMENT_RECOVERY_FAILED")),
            )
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        ).all()
    )
    matched: list[dict] = []
    verified = 0
    integrity_failures = 0
    unavailable = 0
    expired_attempts = 0
    lease_id = str(lease.id)
    for event in events:
        event_at = _as_utc(event.created_at)
        if event_at < started_at or event_at > ended_at:
            continue
        values = event.new_values or {}
        if values.get("recovery_durable_lease_id") != lease_id:
            continue
        read_source = values.get("read_source")
        failure_class = values.get("failure_class")
        if event.action == "DOWNLOAD_DOCUMENT" and read_source == "recovery-replica-durable":
            verified += 1
        elif event.action == "DOWNLOAD_DOCUMENT_RECOVERY_FAILED":
            if failure_class == "storage_unavailable":
                unavailable += 1
            elif failure_class == "route_expired":
                expired_attempts += 1
            else:
                integrity_failures += 1
        matched.append(
            {
                "audit_id": str(event.id),
                "action": event.action,
                "created_at": _utc_iso(event_at),
                "read_source": read_source,
                "failure_class": failure_class,
            }
        )
    if verified < 1:
        raise RecoveryDurableReadHealthConflict(
            "At least one verified durable recovery read is required for health qualification"
        )
    health_state = "healthy"
    if integrity_failures:
        health_state = "failed"
    elif unavailable:
        health_state = "degraded"
    operational_evidence_hash = _canonical_hash(
        {
            "durable_lease_id": lease_id,
            "window_started_at": _utc_iso(started_at),
            "window_ended_at": _utc_iso(ended_at),
            "verified_durable_read_count": verified,
            "integrity_failure_count": integrity_failures,
            "storage_unavailable_count": unavailable,
            "route_expired_attempt_count": expired_attempts,
            "events": matched,
        }
    )
    return DurableReadOperationalEvidence(
        verified_durable_read_count=verified,
        integrity_failure_count=integrity_failures,
        storage_unavailable_count=unavailable,
        route_expired_attempt_count=expired_attempts,
        operational_event_count=len(matched),
        health_state=health_state,
        operational_evidence_hash=operational_evidence_hash,
    )


def _load_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    durable_lease_id: UUID,
) -> DurableReadHealthSnapshot:
    lease = _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        durable_lease_id=durable_lease_id,
    )
    terminal_phase, started_at, ended_at = _terminal_window(lease)
    if any(
        (
            lease.routable_authority_created,
            lease.durable_read_route_created,
            lease.read_path_switched,
            lease.write_path_switched,
            lease.document_storage_key_mutated,
            lease.authoritative_storage_changed,
            lease.destructive_action_performed,
            lease.s3_delete_performed,
            lease.local_delete_performed,
        )
    ):
        raise RecoveryDurableReadHealthConflict(
            "Completed durable read lease did not return to the non-destructive local boundary"
        )

    activation = _receipt(db, lease=lease, phase="activated")
    terminal = _receipt(db, lease=lease, phase=terminal_phase)
    if not all(
        (
            activation.from_route_class == "local_source",
            activation.to_route_class == "recovery_replica",
            activation.route_authority_kind == "durable_promotion",
            activation.routable_authority_created is True,
            activation.durable_read_route_created is True,
            activation.read_path_switched is True,
            activation.actor_id == lease.activated_by_id,
            _as_utc(activation.transitioned_at) == started_at,
            terminal.from_route_class == "recovery_replica",
            terminal.to_route_class == "local_source",
            terminal.route_authority_kind == "local",
            terminal.routable_authority_created is False,
            terminal.durable_read_route_created is False,
            terminal.read_path_switched is False,
            terminal.route_version == activation.route_version + 1,
            _as_utc(terminal.transitioned_at) == ended_at,
        )
    ):
        raise RecoveryDurableReadHealthConflict(
            "Durable read activation/terminal transition proof is inconsistent"
        )

    route = _get_route(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
    )
    if not all(
        (
            route.route_class == "local_source",
            route.route_authority_kind == "local",
            route.active_lease_id is None,
            route.active_durable_lease_id is None,
            route.active_replica_id is None,
            route.read_path_switched is False,
            route.write_path_switched is False,
            route.document_storage_key_mutated is False,
            route.authoritative_storage_changed is False,
            route.destructive_action_performed is False,
            route.route_version == terminal.route_version,
            route.source_authority_fingerprint == lease.source_authority_fingerprint,
            route.candidate_authority_fingerprint == lease.candidate_authority_fingerprint,
            route.configuration_fingerprint == lease.configuration_fingerprint,
        )
    ):
        raise RecoveryDurableReadHealthConflict(
            "Read route is not in the exact clean local state produced by the durable lease"
        )

    document = _get_document(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
    )
    try:
        replica = _load_replica(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            replica_id=lease.replica_id,
        )
        local = _snapshot_local(document)
        _assert_replica_matches_source(replica, local)
        candidate_payload = _read_verified_candidate(replica)
    except RecoveryRoutableReadCutoverNotFound as exc:
        raise RecoveryDurableReadHealthNotFound(str(exc)) from exc
    except (RecoveryRoutableReadCutoverUnavailable, RecoveryReplicationUnavailable) as exc:
        raise RecoveryDurableReadHealthUnavailable(str(exc)) from exc
    except (RecoveryRoutableReadCutoverConflict, RecoveryReplicationConflict, FileNotFoundError) as exc:
        raise RecoveryDurableReadHealthConflict(str(exc)) from exc

    if not all(
        (
            local.file_hash == lease.source_file_hash,
            local.file_size_bytes == lease.source_file_size_bytes,
            local.storage_key_fingerprint == lease.local_storage_key_fingerprint,
            replica.replica_hash == lease.replica_hash,
            replica.recovery_bucket_fingerprint == lease.recovery_bucket_fingerprint,
            hashlib.sha256(replica.recovery_storage_key.encode("utf-8")).hexdigest()
            == lease.candidate_storage_key_fingerprint,
            hashlib.sha256(candidate_payload).hexdigest() == lease.source_file_hash,
            len(candidate_payload) == lease.source_file_size_bytes,
        )
    ):
        raise RecoveryDurableReadHealthConflict(
            "Local or recovery evidence integrity drifted before health qualification"
        )

    evidence = _operational_evidence(
        db,
        lease=lease,
        started_at=started_at,
        ended_at=ended_at,
    )
    request_snapshot_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "durable_lease_id": str(lease.id),
            "durable_lease_hash": lease.lease_hash,
            "lease_snapshot_hash": lease.lease_snapshot_hash,
            "activation_receipt_id": str(activation.id),
            "activation_receipt_hash": activation.receipt_hash,
            "terminal_receipt_id": str(terminal.id),
            "terminal_receipt_hash": terminal.receipt_hash,
            "terminal_phase": terminal_phase,
            "authorization_id": str(lease.authorization_id),
            "authorization_hash": lease.authorization_hash,
            "qualification_id": str(lease.qualification_id),
            "phase_k_qualification_hash": lease.qualification_hash,
            "replica_id": str(lease.replica_id),
            "replica_hash": lease.replica_hash,
            "source_file_hash": lease.source_file_hash,
            "source_file_size_bytes": lease.source_file_size_bytes,
            "local_storage_key_fingerprint": lease.local_storage_key_fingerprint,
            "recovery_bucket_fingerprint": lease.recovery_bucket_fingerprint,
            "candidate_storage_key_fingerprint": lease.candidate_storage_key_fingerprint,
            "source_authority_fingerprint": lease.source_authority_fingerprint,
            "candidate_authority_fingerprint": lease.candidate_authority_fingerprint,
            "configuration_fingerprint": lease.configuration_fingerprint,
            "window_started_at": _utc_iso(started_at),
            "window_ended_at": _utc_iso(ended_at),
            "verified_durable_read_count": evidence.verified_durable_read_count,
            "integrity_failure_count": evidence.integrity_failure_count,
            "storage_unavailable_count": evidence.storage_unavailable_count,
            "route_expired_attempt_count": evidence.route_expired_attempt_count,
            "operational_event_count": evidence.operational_event_count,
            "health_state": evidence.health_state,
            "operational_evidence_hash": evidence.operational_evidence_hash,
            "route_class": route.route_class,
            "route_authority_kind": route.route_authority_kind,
            "route_version": route.route_version,
            "read_path_switched": False,
            "write_path_switched": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
            "mode": "durable_read_operational_health_qualification_only",
        }
    )
    return DurableReadHealthSnapshot(
        lease=lease,
        activation=activation,
        terminal=terminal,
        document=document,
        route=route,
        terminal_phase=terminal_phase,
        window_started_at=started_at,
        window_ended_at=ended_at,
        evidence=evidence,
        request_snapshot_hash=request_snapshot_hash,
    )


def _matches_snapshot(
    qualification: EvidenceRecoveryDurableReadHealthQualification,
    snapshot: DurableReadHealthSnapshot,
) -> bool:
    lease = snapshot.lease
    evidence = snapshot.evidence
    return all(
        (
            qualification.durable_lease_id == lease.id,
            qualification.activation_receipt_id == snapshot.activation.id,
            qualification.terminal_receipt_id == snapshot.terminal.id,
            qualification.authorization_id == lease.authorization_id,
            qualification.qualification_id == lease.qualification_id,
            qualification.replica_id == lease.replica_id,
            qualification.durable_lease_hash == lease.lease_hash,
            qualification.lease_snapshot_hash == lease.lease_snapshot_hash,
            qualification.activation_receipt_hash == snapshot.activation.receipt_hash,
            qualification.terminal_receipt_hash == snapshot.terminal.receipt_hash,
            qualification.authorization_hash == lease.authorization_hash,
            qualification.phase_k_qualification_hash == lease.qualification_hash,
            qualification.replica_hash == lease.replica_hash,
            qualification.source_file_hash == lease.source_file_hash,
            qualification.source_file_size_bytes == lease.source_file_size_bytes,
            qualification.local_storage_key_fingerprint == lease.local_storage_key_fingerprint,
            qualification.recovery_bucket_fingerprint == lease.recovery_bucket_fingerprint,
            qualification.candidate_storage_key_fingerprint == lease.candidate_storage_key_fingerprint,
            qualification.source_authority_fingerprint == lease.source_authority_fingerprint,
            qualification.candidate_authority_fingerprint == lease.candidate_authority_fingerprint,
            qualification.configuration_fingerprint == lease.configuration_fingerprint,
            qualification.terminal_phase == snapshot.terminal_phase,
            _as_utc(qualification.window_started_at) == snapshot.window_started_at,
            _as_utc(qualification.window_ended_at) == snapshot.window_ended_at,
            qualification.verified_durable_read_count == evidence.verified_durable_read_count,
            qualification.integrity_failure_count == evidence.integrity_failure_count,
            qualification.storage_unavailable_count == evidence.storage_unavailable_count,
            qualification.route_expired_attempt_count == evidence.route_expired_attempt_count,
            qualification.operational_event_count == evidence.operational_event_count,
            qualification.health_state == evidence.health_state,
            qualification.operational_evidence_hash == evidence.operational_evidence_hash,
            qualification.route_version_at_request == snapshot.route.route_version,
            qualification.request_snapshot_hash == snapshot.request_snapshot_hash,
            qualification.activated_by_id == lease.activated_by_id,
        )
    )


def _new_receipt(
    *,
    qualification: EvidenceRecoveryDurableReadHealthQualification,
    phase: str,
    actor_id: UUID,
    reason: str,
    transitioned_at: datetime,
) -> EvidenceRecoveryDurableReadHealthQualificationReceipt:
    normalized_reason = reason.strip()
    receipt_hash = _canonical_hash(
        {
            "health_qualification_id": str(qualification.id),
            "durable_lease_id": str(qualification.durable_lease_id),
            "phase": phase,
            "health_state": qualification.health_state,
            "operational_evidence_hash": qualification.operational_evidence_hash,
            "request_snapshot_hash": qualification.request_snapshot_hash,
            "health_qualification_hash": qualification.health_qualification_hash,
            "actor_id": str(actor_id),
            "reason": normalized_reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "routable_authority_created": False,
            "durable_read_route_created": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
            "s3_delete_performed": False,
            "local_delete_performed": False,
        }
    )
    return EvidenceRecoveryDurableReadHealthQualificationReceipt(
        organization_id=qualification.organization_id,
        claim_id=qualification.claim_id,
        document_id=qualification.document_id,
        health_qualification_id=qualification.id,
        durable_lease_id=qualification.durable_lease_id,
        phase=phase,
        health_state=qualification.health_state,
        operational_evidence_hash=qualification.operational_evidence_hash,
        request_snapshot_hash=qualification.request_snapshot_hash,
        health_qualification_hash=qualification.health_qualification_hash,
        receipt_hash=receipt_hash,
        actor_id=actor_id,
        reason=normalized_reason,
        transitioned_at=transitioned_at,
        routable_authority_created=False,
        durable_read_route_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )


def _invalidate(
    db: Session,
    *,
    qualification: EvidenceRecoveryDurableReadHealthQualification,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryDurableReadHealthQualificationReceipt:
    qualification.status = "invalidated"
    qualification.terminal_by_id = actor_id
    qualification.terminal_at = now
    qualification.terminal_reason = reason
    receipt = _new_receipt(
        qualification=qualification,
        phase="invalidated",
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
    )
    db.add(receipt)
    db.flush()
    return receipt


def request_durable_read_health_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    durable_lease_id: UUID,
    requested_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryDurableReadHealthQualification, EvidenceRecoveryDurableReadHealthQualificationReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadHealthConflict("Health qualification request reason is required")
    current_time = _as_utc(now or _utc_now())
    snapshot = _load_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        durable_lease_id=durable_lease_id,
    )
    existing = db.scalar(
        select(EvidenceRecoveryDurableReadHealthQualification)
        .where(
            EvidenceRecoveryDurableReadHealthQualification.organization_id == organization_id,
            EvidenceRecoveryDurableReadHealthQualification.durable_lease_id == durable_lease_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.status == "pending_second_approval" and not _matches_snapshot(existing, snapshot):
            receipt = _invalidate(
                db,
                qualification=existing,
                actor_id=requested_by_id,
                reason="Durable read health evidence drifted before request replay",
                now=current_time,
            )
            return existing, receipt, "invalidated"
        return existing, None, "unchanged"

    lease = snapshot.lease
    evidence = snapshot.evidence
    health_qualification_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "durable_lease_id": str(durable_lease_id),
            "request_snapshot_hash": snapshot.request_snapshot_hash,
            "operational_evidence_hash": evidence.operational_evidence_hash,
            "health_state": evidence.health_state,
            "requested_by_id": str(requested_by_id),
            "requested_at": _utc_iso(current_time),
            "request_reason": normalized_reason,
            "mode": "non_routable_durable_read_health_qualification",
        }
    )
    qualification = EvidenceRecoveryDurableReadHealthQualification(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        durable_lease_id=lease.id,
        activation_receipt_id=snapshot.activation.id,
        terminal_receipt_id=snapshot.terminal.id,
        authorization_id=lease.authorization_id,
        qualification_id=lease.qualification_id,
        replica_id=lease.replica_id,
        durable_lease_hash=lease.lease_hash,
        lease_snapshot_hash=lease.lease_snapshot_hash,
        activation_receipt_hash=snapshot.activation.receipt_hash,
        terminal_receipt_hash=snapshot.terminal.receipt_hash,
        authorization_hash=lease.authorization_hash,
        phase_k_qualification_hash=lease.qualification_hash,
        replica_hash=lease.replica_hash,
        source_file_hash=lease.source_file_hash,
        source_file_size_bytes=lease.source_file_size_bytes,
        local_storage_key_fingerprint=lease.local_storage_key_fingerprint,
        recovery_bucket_fingerprint=lease.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=lease.candidate_storage_key_fingerprint,
        source_authority_fingerprint=lease.source_authority_fingerprint,
        candidate_authority_fingerprint=lease.candidate_authority_fingerprint,
        configuration_fingerprint=lease.configuration_fingerprint,
        terminal_phase=snapshot.terminal_phase,
        window_started_at=snapshot.window_started_at,
        window_ended_at=snapshot.window_ended_at,
        verified_durable_read_count=evidence.verified_durable_read_count,
        integrity_failure_count=evidence.integrity_failure_count,
        storage_unavailable_count=evidence.storage_unavailable_count,
        route_expired_attempt_count=evidence.route_expired_attempt_count,
        operational_event_count=evidence.operational_event_count,
        health_state=evidence.health_state,
        operational_evidence_hash=evidence.operational_evidence_hash,
        route_version_at_request=snapshot.route.route_version,
        request_snapshot_hash=snapshot.request_snapshot_hash,
        health_qualification_hash=health_qualification_hash,
        activated_by_id=lease.activated_by_id,
        requested_by_id=requested_by_id,
        requested_at=current_time,
        request_reason=normalized_reason,
        status="pending_second_approval",
        routable_authority_created=False,
        durable_read_route_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )
    db.add(qualification)
    db.flush()
    receipt = _new_receipt(
        qualification=qualification,
        phase="requested",
        actor_id=requested_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return qualification, receipt, "pending_second_approval"


def _get_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    for_update: bool = False,
) -> EvidenceRecoveryDurableReadHealthQualification:
    stmt = select(EvidenceRecoveryDurableReadHealthQualification).where(
        EvidenceRecoveryDurableReadHealthQualification.id == health_qualification_id,
        EvidenceRecoveryDurableReadHealthQualification.organization_id == organization_id,
        EvidenceRecoveryDurableReadHealthQualification.claim_id == claim_id,
        EvidenceRecoveryDurableReadHealthQualification.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    qualification = db.scalar(stmt)
    if qualification is None:
        raise RecoveryDurableReadHealthNotFound("Durable read health qualification not found")
    return qualification


def qualify_durable_read_health(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    qualified_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryDurableReadHealthQualification, EvidenceRecoveryDurableReadHealthQualificationReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadHealthConflict("Health qualification approval reason is required")
    current_time = _as_utc(now or _utc_now())
    qualification = _get_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        health_qualification_id=health_qualification_id,
        for_update=True,
    )
    if qualification.status in {"qualified", "degraded"}:
        return qualification, None, "unchanged"
    if qualification.status != "pending_second_approval":
        raise RecoveryDurableReadHealthConflict("Only a pending health qualification can be assessed")
    if qualification.requested_by_id == qualified_by_id:
        raise RecoveryDurableReadHealthConflict(
            "Health qualification requires a different Admin from the requester"
        )
    if qualification.activated_by_id == qualified_by_id:
        raise RecoveryDurableReadHealthConflict(
            "Health qualifier must differ from the Phase M durable-route activator"
        )
    try:
        snapshot = _load_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            durable_lease_id=qualification.durable_lease_id,
        )
    except (RecoveryDurableReadHealthNotFound, RecoveryDurableReadHealthConflict) as exc:
        receipt = _invalidate(
            db,
            qualification=qualification,
            actor_id=qualified_by_id,
            reason=f"Fresh durable read health preflight failed: {type(exc).__name__}",
            now=current_time,
        )
        return qualification, receipt, "invalidated"
    if not _matches_snapshot(qualification, snapshot):
        receipt = _invalidate(
            db,
            qualification=qualification,
            actor_id=qualified_by_id,
            reason="Durable read health snapshot drifted before second approval",
            now=current_time,
        )
        return qualification, receipt, "invalidated"

    outcome = "qualified" if qualification.health_state == "healthy" else "degraded"
    qualification.status = outcome
    qualification.qualified_by_id = qualified_by_id
    qualification.qualified_at = current_time
    qualification.qualification_reason = normalized_reason
    receipt = _new_receipt(
        qualification=qualification,
        phase=outcome,
        actor_id=qualified_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return qualification, receipt, outcome


def reject_durable_read_health(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    rejected_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryDurableReadHealthQualification, EvidenceRecoveryDurableReadHealthQualificationReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadHealthConflict("Health qualification rejection reason is required")
    current_time = _as_utc(now or _utc_now())
    qualification = _get_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        health_qualification_id=health_qualification_id,
        for_update=True,
    )
    if qualification.status == "rejected":
        return qualification, None, "unchanged"
    if qualification.status != "pending_second_approval":
        raise RecoveryDurableReadHealthConflict("Only a pending health qualification can be rejected")
    qualification.status = "rejected"
    qualification.rejected_by_id = rejected_by_id
    qualification.rejected_at = current_time
    qualification.rejection_reason = normalized_reason
    receipt = _new_receipt(
        qualification=qualification,
        phase="rejected",
        actor_id=rejected_by_id,
        reason=normalized_reason,
        transitioned_at=current_time,
    )
    db.add(receipt)
    db.flush()
    return qualification, receipt, "rejected"


def get_durable_read_health_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
) -> EvidenceRecoveryDurableReadHealthQualification:
    return _get_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        health_qualification_id=health_qualification_id,
    )


def list_durable_read_health_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
) -> list[EvidenceRecoveryDurableReadHealthQualificationReceipt]:
    _get_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        health_qualification_id=health_qualification_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryDurableReadHealthQualificationReceipt)
            .where(
                EvidenceRecoveryDurableReadHealthQualificationReceipt.organization_id == organization_id,
                EvidenceRecoveryDurableReadHealthQualificationReceipt.claim_id == claim_id,
                EvidenceRecoveryDurableReadHealthQualificationReceipt.document_id == document_id,
                EvidenceRecoveryDurableReadHealthQualificationReceipt.health_qualification_id == health_qualification_id,
            )
            .order_by(
                EvidenceRecoveryDurableReadHealthQualificationReceipt.transitioned_at.asc(),
                EvidenceRecoveryDurableReadHealthQualificationReceipt.created_at.asc(),
                EvidenceRecoveryDurableReadHealthQualificationReceipt.id.asc(),
            )
        ).all()
    )
