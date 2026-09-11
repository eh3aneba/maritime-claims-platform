from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog
from app.modules.documents.models import Document
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_read_ownership_transition_health_models import (
    EvidenceRecoveryReadOwnershipTransitionHealthQualification,
    EvidenceRecoveryReadOwnershipTransitionHealthReceipt,
)
from app.modules.documents.recovery_read_ownership_transition_routing_models import (
    EvidenceRecoveryReadOwnershipTransitionLease,
    EvidenceRecoveryReadOwnershipTransitionReceipt,
)
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

READ_OWNERSHIP_HEALTH_REVIEW_WINDOW = timedelta(minutes=10)


class RecoveryReadOwnershipTransitionHealthError(RuntimeError):
    pass


class RecoveryReadOwnershipTransitionHealthNotFound(RecoveryReadOwnershipTransitionHealthError):
    pass


class RecoveryReadOwnershipTransitionHealthConflict(RecoveryReadOwnershipTransitionHealthError):
    pass


class RecoveryReadOwnershipTransitionHealthUnavailable(RecoveryReadOwnershipTransitionHealthError):
    pass


@dataclass(frozen=True)
class OperationalEvidence:
    verified_read_count: int
    integrity_failure_count: int
    storage_unavailable_count: int
    route_expired_attempt_count: int
    operational_event_count: int
    health_state: str
    operational_evidence_hash: str


@dataclass(frozen=True)
class HealthSnapshot:
    lease: EvidenceRecoveryReadOwnershipTransitionLease
    activation: EvidenceRecoveryReadOwnershipTransitionReceipt
    terminal: EvidenceRecoveryReadOwnershipTransitionReceipt
    document: Document
    route: EvidenceRecoveryReadPathRoute
    terminal_phase: str
    window_started_at: datetime
    window_ended_at: datetime
    evidence: OperationalEvidence
    request_snapshot_hash: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _get_lease(db: Session, *, organization_id: UUID, claim_id: UUID, document_id: UUID, lease_id: UUID) -> EvidenceRecoveryReadOwnershipTransitionLease:
    lease = db.scalar(select(EvidenceRecoveryReadOwnershipTransitionLease).where(
        EvidenceRecoveryReadOwnershipTransitionLease.id == lease_id,
        EvidenceRecoveryReadOwnershipTransitionLease.organization_id == organization_id,
        EvidenceRecoveryReadOwnershipTransitionLease.claim_id == claim_id,
        EvidenceRecoveryReadOwnershipTransitionLease.document_id == document_id,
    ))
    if lease is None:
        raise RecoveryReadOwnershipTransitionHealthNotFound("Phase V read-ownership transition lease not found")
    return lease


def _get_route(db: Session, *, organization_id: UUID, claim_id: UUID, document_id: UUID) -> EvidenceRecoveryReadPathRoute:
    route = db.scalar(select(EvidenceRecoveryReadPathRoute).where(
        EvidenceRecoveryReadPathRoute.organization_id == organization_id,
        EvidenceRecoveryReadPathRoute.claim_id == claim_id,
        EvidenceRecoveryReadPathRoute.document_id == document_id,
    ))
    if route is None:
        raise RecoveryReadOwnershipTransitionHealthNotFound("Recovery read route not found")
    return route


def _get_document(db: Session, *, organization_id: UUID, claim_id: UUID, document_id: UUID) -> Document:
    document = db.scalar(select(Document).where(
        Document.id == document_id,
        Document.organization_id == organization_id,
        Document.claim_id == claim_id,
    ))
    if document is None or document.deleted_at is not None:
        raise RecoveryReadOwnershipTransitionHealthNotFound("Document not found")
    return document


def _lease_receipt(db: Session, *, lease: EvidenceRecoveryReadOwnershipTransitionLease, phase: str) -> EvidenceRecoveryReadOwnershipTransitionReceipt:
    receipts = list(db.scalars(select(EvidenceRecoveryReadOwnershipTransitionReceipt).where(
        EvidenceRecoveryReadOwnershipTransitionReceipt.organization_id == lease.organization_id,
        EvidenceRecoveryReadOwnershipTransitionReceipt.claim_id == lease.claim_id,
        EvidenceRecoveryReadOwnershipTransitionReceipt.document_id == lease.document_id,
        EvidenceRecoveryReadOwnershipTransitionReceipt.transition_lease_id == lease.id,
        EvidenceRecoveryReadOwnershipTransitionReceipt.phase == phase,
    )).all())
    if len(receipts) != 1:
        raise RecoveryReadOwnershipTransitionHealthConflict(f"Phase V lease must have exactly one {phase} receipt")
    receipt = receipts[0]
    if not all((
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
    )):
        raise RecoveryReadOwnershipTransitionHealthConflict("Phase V transition receipt lineage is inconsistent")
    return receipt


def _terminal_window(lease: EvidenceRecoveryReadOwnershipTransitionLease) -> tuple[str, datetime, datetime]:
    if lease.status not in {"rolled_back", "expired"}:
        raise RecoveryReadOwnershipTransitionHealthConflict("Only a completed Phase V window can be health-qualified")
    if lease.activated_by_id is None or lease.activated_at is None:
        raise RecoveryReadOwnershipTransitionHealthConflict("Phase V lease is missing activation lineage")
    if lease.status == "rolled_back":
        if lease.rolled_back_at is None or lease.rolled_back_by_id is None:
            raise RecoveryReadOwnershipTransitionHealthConflict("Rolled-back Phase V lease is incomplete")
        ended_at = _as_utc(lease.rolled_back_at)
    else:
        if lease.terminal_at is None or lease.terminal_by_id is None:
            raise RecoveryReadOwnershipTransitionHealthConflict("Expired Phase V lease is incomplete")
        ended_at = _as_utc(lease.terminal_at)
    started_at = _as_utc(lease.activated_at)
    if ended_at < started_at:
        raise RecoveryReadOwnershipTransitionHealthConflict("Phase V operational window is temporally invalid")
    return lease.status, started_at, ended_at


def _operational_evidence(db: Session, *, lease: EvidenceRecoveryReadOwnershipTransitionLease, started_at: datetime, ended_at: datetime) -> OperationalEvidence:
    events = list(db.scalars(select(AuditLog).where(
        AuditLog.organization_id == lease.organization_id,
        AuditLog.entity_type == "document",
        AuditLog.entity_id == lease.document_id,
        AuditLog.action.in_(("DOWNLOAD_DOCUMENT", "DOWNLOAD_DOCUMENT_RECOVERY_FAILED")),
    ).order_by(AuditLog.created_at.asc(), AuditLog.id.asc())).all())
    matched: list[dict] = []
    verified = integrity = unavailable = expired = 0
    lease_id = str(lease.id)
    start_second = started_at.replace(microsecond=0)
    end_second = ended_at.replace(microsecond=0)
    for event in events:
        event_at = _as_utc(event.created_at)
        if event_at.replace(microsecond=0) < start_second or event_at.replace(microsecond=0) > end_second:
            continue
        values = event.new_values or {}
        if values.get("recovery_read_ownership_transition_lease_id") != lease_id:
            continue
        source = values.get("read_source")
        failure = values.get("failure_class")
        if event.action == "DOWNLOAD_DOCUMENT" and source == "recovery-replica-read-ownership-transition":
            verified += 1
        elif event.action == "DOWNLOAD_DOCUMENT_RECOVERY_FAILED":
            if failure == "storage_unavailable":
                unavailable += 1
            elif failure == "route_expired":
                expired += 1
            else:
                integrity += 1
        matched.append({"audit_id": str(event.id), "action": event.action, "created_at": _utc_iso(event_at), "read_source": source, "failure_class": failure})
    if verified < 1:
        raise RecoveryReadOwnershipTransitionHealthConflict("At least one verified Phase V recovery read is required")
    health_state = "failed" if integrity else ("degraded" if unavailable else "healthy")
    evidence_hash = _canonical_hash({
        "transition_lease_id": lease_id,
        "window_started_at": _utc_iso(started_at),
        "window_ended_at": _utc_iso(ended_at),
        "verified_read_count": verified,
        "integrity_failure_count": integrity,
        "storage_unavailable_count": unavailable,
        "route_expired_attempt_count": expired,
        "events": matched,
    })
    return OperationalEvidence(verified, integrity, unavailable, expired, len(matched), health_state, evidence_hash)


def _load_snapshot(db: Session, *, organization_id: UUID, claim_id: UUID, document_id: UUID, transition_lease_id: UUID) -> HealthSnapshot:
    lease = _get_lease(db, organization_id=organization_id, claim_id=claim_id, document_id=document_id, lease_id=transition_lease_id)
    terminal_phase, started_at, ended_at = _terminal_window(lease)
    if any((lease.routable_authority_created, lease.durable_read_route_created, lease.read_ownership_authority_created, lease.read_path_switched, lease.write_path_switched, lease.document_storage_key_mutated, lease.authoritative_storage_changed, lease.destructive_action_performed, lease.s3_delete_performed, lease.local_delete_performed)):
        raise RecoveryReadOwnershipTransitionHealthConflict("Completed Phase V lease did not return to clean local boundary")
    activation = _lease_receipt(db, lease=lease, phase="activated")
    terminal = _lease_receipt(db, lease=lease, phase=terminal_phase)
    if not all((
        activation.from_route_class == "local_source",
        activation.to_route_class == "recovery_replica",
        activation.route_authority_kind == "read_ownership_transition",
        activation.routable_authority_created is True,
        activation.durable_read_route_created is True,
        activation.read_ownership_authority_created is True,
        activation.read_path_switched is True,
        activation.actor_id == lease.activated_by_id,
        activation.route_version == lease.route_version_at_prepare + 1,
        _as_utc(activation.transitioned_at) == started_at,
        terminal.from_route_class == "recovery_replica",
        terminal.to_route_class == "local_source",
        terminal.route_authority_kind == "local",
        terminal.routable_authority_created is False,
        terminal.durable_read_route_created is False,
        terminal.read_ownership_authority_created is False,
        terminal.read_path_switched is False,
        terminal.route_version == activation.route_version + 1,
        _as_utc(terminal.transitioned_at) == ended_at,
    )):
        raise RecoveryReadOwnershipTransitionHealthConflict("Phase V activation/terminal proof is inconsistent")
    route = _get_route(db, organization_id=organization_id, claim_id=claim_id, document_id=document_id)
    if not all((
        route.route_class == "local_source", route.route_authority_kind == "local",
        route.active_lease_id is None, route.active_durable_lease_id is None,
        route.active_durable_renewal_lease_id is None, route.active_durable_reauthorized_renewal_lease_id is None,
        route.active_read_ownership_transition_lease_id is None, route.active_replica_id is None,
        route.read_path_switched is False, route.write_path_switched is False,
        route.document_storage_key_mutated is False, route.authoritative_storage_changed is False,
        route.destructive_action_performed is False, route.route_version == terminal.route_version,
        route.source_authority_fingerprint == lease.source_authority_fingerprint,
        route.candidate_authority_fingerprint == lease.candidate_authority_fingerprint,
        route.configuration_fingerprint == lease.configuration_fingerprint,
    )):
        raise RecoveryReadOwnershipTransitionHealthConflict("Shared route is not the exact clean local state produced by Phase V")
    document = _get_document(db, organization_id=organization_id, claim_id=claim_id, document_id=document_id)
    try:
        replica = _load_replica(db, organization_id=organization_id, claim_id=claim_id, document_id=document_id, replica_id=lease.replica_id)
        local = _snapshot_local(document)
        _assert_replica_matches_source(replica, local)
        candidate = _read_verified_candidate(replica)
    except RecoveryRoutableReadCutoverNotFound as exc:
        raise RecoveryReadOwnershipTransitionHealthNotFound(str(exc)) from exc
    except (RecoveryRoutableReadCutoverUnavailable, RecoveryReplicationUnavailable) as exc:
        raise RecoveryReadOwnershipTransitionHealthUnavailable(str(exc)) from exc
    except (RecoveryRoutableReadCutoverConflict, RecoveryReplicationConflict, FileNotFoundError) as exc:
        raise RecoveryReadOwnershipTransitionHealthConflict(str(exc)) from exc
    if not all((
        local.file_hash == lease.source_file_hash,
        local.file_size_bytes == lease.source_file_size_bytes,
        local.storage_key_fingerprint == lease.local_storage_key_fingerprint,
        replica.replica_hash == lease.replica_hash,
        replica.recovery_bucket_fingerprint == lease.recovery_bucket_fingerprint,
        hashlib.sha256(replica.recovery_storage_key.encode("utf-8")).hexdigest() == lease.candidate_storage_key_fingerprint,
        hashlib.sha256(candidate).hexdigest() == lease.source_file_hash,
        len(candidate) == lease.source_file_size_bytes,
    )):
        raise RecoveryReadOwnershipTransitionHealthConflict("Local or recovery evidence integrity drifted before Phase W qualification")
    evidence = _operational_evidence(db, lease=lease, started_at=started_at, ended_at=ended_at)
    request_hash = _canonical_hash({
        "organization_id": str(organization_id), "claim_id": str(claim_id), "document_id": str(document_id),
        "transition_lease_id": str(lease.id), "transition_lease_hash": lease.lease_hash,
        "lease_snapshot_hash": lease.lease_snapshot_hash, "activation_receipt_id": str(activation.id),
        "activation_receipt_hash": activation.receipt_hash, "terminal_receipt_id": str(terminal.id),
        "terminal_receipt_hash": terminal.receipt_hash, "terminal_phase": terminal_phase,
        "authorization_id": str(lease.authorization_id), "authorization_hash": lease.authorization_hash,
        "phase_t_health_qualification_id": str(lease.phase_t_health_qualification_id),
        "phase_t_health_qualification_hash": lease.phase_t_health_qualification_hash,
        "replica_id": str(lease.replica_id), "replica_hash": lease.replica_hash,
        "source_file_hash": lease.source_file_hash, "source_file_size_bytes": lease.source_file_size_bytes,
        "source_authority_fingerprint": lease.source_authority_fingerprint,
        "candidate_authority_fingerprint": lease.candidate_authority_fingerprint,
        "configuration_fingerprint": lease.configuration_fingerprint,
        "window_started_at": _utc_iso(started_at), "window_ended_at": _utc_iso(ended_at),
        "verified_read_count": evidence.verified_read_count,
        "integrity_failure_count": evidence.integrity_failure_count,
        "storage_unavailable_count": evidence.storage_unavailable_count,
        "route_expired_attempt_count": evidence.route_expired_attempt_count,
        "operational_event_count": evidence.operational_event_count,
        "health_state": evidence.health_state, "operational_evidence_hash": evidence.operational_evidence_hash,
        "route_version": route.route_version,
    })
    return HealthSnapshot(lease, activation, terminal, document, route, terminal_phase, started_at, ended_at, evidence, request_hash)


def _matches_snapshot(q: EvidenceRecoveryReadOwnershipTransitionHealthQualification, s: HealthSnapshot) -> bool:
    l, e = s.lease, s.evidence
    return all((q.transition_lease_id == l.id, q.transition_lease_hash == l.lease_hash, q.lease_snapshot_hash == l.lease_snapshot_hash,
        q.activation_receipt_id == s.activation.id, q.activation_receipt_hash == s.activation.receipt_hash,
        q.terminal_receipt_id == s.terminal.id, q.terminal_receipt_hash == s.terminal.receipt_hash,
        q.authorization_id == l.authorization_id, q.authorization_hash == l.authorization_hash,
        q.phase_t_health_qualification_id == l.phase_t_health_qualification_id,
        q.phase_t_health_qualification_hash == l.phase_t_health_qualification_hash,
        q.replica_id == l.replica_id, q.replica_hash == l.replica_hash,
        q.source_file_hash == l.source_file_hash, q.source_file_size_bytes == l.source_file_size_bytes,
        q.terminal_phase == s.terminal_phase, _as_utc(q.window_started_at) == s.window_started_at,
        _as_utc(q.window_ended_at) == s.window_ended_at, q.verified_read_count == e.verified_read_count,
        q.integrity_failure_count == e.integrity_failure_count, q.storage_unavailable_count == e.storage_unavailable_count,
        q.route_expired_attempt_count == e.route_expired_attempt_count, q.operational_event_count == e.operational_event_count,
        q.health_state == e.health_state, q.operational_evidence_hash == e.operational_evidence_hash,
        q.route_version_at_request == s.route.route_version, q.request_snapshot_hash == s.request_snapshot_hash,
        q.transition_activated_by_id == l.activated_by_id, q.authorization_approved_by_id == l.authorization_approved_by_id))


def _new_receipt(q: EvidenceRecoveryReadOwnershipTransitionHealthQualification, *, phase: str, actor_id: UUID, reason: str, now: datetime) -> EvidenceRecoveryReadOwnershipTransitionHealthReceipt:
    receipt_hash = _canonical_hash({"health_qualification_id": str(q.id), "transition_lease_id": str(q.transition_lease_id), "phase": phase,
        "health_state": q.health_state, "operational_evidence_hash": q.operational_evidence_hash,
        "request_snapshot_hash": q.request_snapshot_hash, "health_qualification_hash": q.health_qualification_hash,
        "actor_id": str(actor_id), "reason": reason, "transitioned_at": _utc_iso(now)})
    return EvidenceRecoveryReadOwnershipTransitionHealthReceipt(
        organization_id=q.organization_id, claim_id=q.claim_id, document_id=q.document_id,
        health_qualification_id=q.id, transition_lease_id=q.transition_lease_id, phase=phase,
        health_state=q.health_state, operational_evidence_hash=q.operational_evidence_hash,
        request_snapshot_hash=q.request_snapshot_hash, health_qualification_hash=q.health_qualification_hash,
        receipt_hash=receipt_hash, actor_id=actor_id, reason=reason, transitioned_at=now,
        routable_authority_created=False, durable_read_route_created=False, read_ownership_authority_created=False,
        read_path_switched=False, write_path_switched=False, document_storage_key_mutated=False,
        authoritative_storage_changed=False, destructive_action_performed=False, s3_delete_performed=False, local_delete_performed=False)


def request_recovery_read_ownership_transition_health_qualification(db: Session, *, organization_id: UUID, claim_id: UUID, document_id: UUID, transition_lease_id: UUID, requested_by_id: UUID, reason: str, now: datetime | None = None):
    reason = reason.strip()
    if len(reason) < 8:
        raise RecoveryReadOwnershipTransitionHealthConflict("Phase W request reason is required")
    current = _as_utc(now or _utc_now())
    existing = db.scalar(select(EvidenceRecoveryReadOwnershipTransitionHealthQualification).where(
        EvidenceRecoveryReadOwnershipTransitionHealthQualification.organization_id == organization_id,
        EvidenceRecoveryReadOwnershipTransitionHealthQualification.transition_lease_id == transition_lease_id,
    ).with_for_update())
    if existing is not None:
        if existing.requested_by_id != requested_by_id or existing.request_reason != reason:
            raise RecoveryReadOwnershipTransitionHealthConflict("Phase W request replay must use original requester and reason")
        return existing, None, "unchanged"
    s = _load_snapshot(db, organization_id=organization_id, claim_id=claim_id, document_id=document_id, transition_lease_id=transition_lease_id)
    l, e = s.lease, s.evidence
    qualification_hash = _canonical_hash({"request_snapshot_hash": s.request_snapshot_hash, "requested_by_id": str(requested_by_id), "requested_at": _utc_iso(current), "review_expires_at": _utc_iso(current + READ_OWNERSHIP_HEALTH_REVIEW_WINDOW), "mode": "phase_w_non_routable_read_ownership_health"})
    q = EvidenceRecoveryReadOwnershipTransitionHealthQualification(
        organization_id=organization_id, claim_id=claim_id, document_id=document_id, transition_lease_id=l.id,
        activation_receipt_id=s.activation.id, terminal_receipt_id=s.terminal.id, authorization_id=l.authorization_id,
        phase_t_health_qualification_id=l.phase_t_health_qualification_id, replica_id=l.replica_id,
        transition_lease_hash=l.lease_hash, lease_snapshot_hash=l.lease_snapshot_hash,
        activation_receipt_hash=s.activation.receipt_hash, terminal_receipt_hash=s.terminal.receipt_hash,
        authorization_hash=l.authorization_hash, phase_t_health_qualification_hash=l.phase_t_health_qualification_hash,
        replica_hash=l.replica_hash, source_file_hash=l.source_file_hash, source_file_size_bytes=l.source_file_size_bytes,
        local_storage_key_fingerprint=l.local_storage_key_fingerprint, recovery_bucket_fingerprint=l.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=l.candidate_storage_key_fingerprint, source_authority_fingerprint=l.source_authority_fingerprint,
        candidate_authority_fingerprint=l.candidate_authority_fingerprint, configuration_fingerprint=l.configuration_fingerprint,
        terminal_phase=s.terminal_phase, window_started_at=s.window_started_at, window_ended_at=s.window_ended_at,
        verified_read_count=e.verified_read_count, integrity_failure_count=e.integrity_failure_count,
        storage_unavailable_count=e.storage_unavailable_count, route_expired_attempt_count=e.route_expired_attempt_count,
        operational_event_count=e.operational_event_count, health_state=e.health_state, operational_evidence_hash=e.operational_evidence_hash,
        route_version_at_request=s.route.route_version, request_snapshot_hash=s.request_snapshot_hash,
        health_qualification_hash=qualification_hash, transition_activated_by_id=l.activated_by_id,
        authorization_approved_by_id=l.authorization_approved_by_id, requested_by_id=requested_by_id, requested_at=current,
        review_expires_at=current + READ_OWNERSHIP_HEALTH_REVIEW_WINDOW, request_reason=reason, status="pending_second_approval",
        routable_authority_created=False, durable_read_route_created=False, read_ownership_authority_created=False,
        read_path_switched=False, write_path_switched=False, document_storage_key_mutated=False,
        authoritative_storage_changed=False, destructive_action_performed=False, s3_delete_performed=False, local_delete_performed=False)
    db.add(q); db.flush()
    receipt = _new_receipt(q, phase="requested", actor_id=requested_by_id, reason=reason, now=current)
    db.add(receipt); db.flush()
    return q, receipt, "pending_second_approval"


def qualify_recovery_read_ownership_transition_health(db: Session, *, organization_id: UUID, claim_id: UUID, document_id: UUID, health_qualification_id: UUID, qualified_by_id: UUID, reason: str, now: datetime | None = None):
    reason = reason.strip(); current = _as_utc(now or _utc_now())
    q = get_recovery_read_ownership_transition_health_qualification(db, organization_id=organization_id, claim_id=claim_id, document_id=document_id, health_qualification_id=health_qualification_id, for_update=True)
    if q.status in {"qualified", "degraded"}:
        if q.qualified_by_id == qualified_by_id and q.qualification_reason == reason:
            return q, None, "unchanged"
        raise RecoveryReadOwnershipTransitionHealthConflict("Phase W qualification replay does not match")
    if q.status != "pending_second_approval":
        raise RecoveryReadOwnershipTransitionHealthConflict("Only pending Phase W evidence can be qualified")
    if qualified_by_id in {q.requested_by_id, q.transition_activated_by_id, q.authorization_approved_by_id}:
        raise RecoveryReadOwnershipTransitionHealthConflict("Phase W qualifier must be independent from requester, Phase V activator and Phase U approver")
    if current >= _as_utc(q.review_expires_at):
        q.status="expired"; q.terminal_by_id=qualified_by_id; q.terminal_at=current; q.terminal_reason="Phase W review window expired"
        receipt=_new_receipt(q, phase="expired", actor_id=qualified_by_id, reason=q.terminal_reason, now=current); db.add(receipt); db.flush(); return q,receipt,"expired"
    s = _load_snapshot(db, organization_id=organization_id, claim_id=claim_id, document_id=document_id, transition_lease_id=q.transition_lease_id)
    if not _matches_snapshot(q, s):
        q.status="invalidated"; q.terminal_by_id=qualified_by_id; q.terminal_at=current; q.terminal_reason="Phase V lineage or operational evidence drifted"
        receipt=_new_receipt(q, phase="invalidated", actor_id=qualified_by_id, reason=q.terminal_reason, now=current); db.add(receipt); db.flush(); return q,receipt,"invalidated"
    outcome = "qualified" if q.health_state == "healthy" else "degraded"
    q.status=outcome; q.qualified_by_id=qualified_by_id; q.qualified_at=current; q.qualification_reason=reason
    receipt=_new_receipt(q, phase=outcome, actor_id=qualified_by_id, reason=reason, now=current); db.add(receipt); db.flush(); return q,receipt,outcome


def reject_recovery_read_ownership_transition_health(db: Session, *, organization_id: UUID, claim_id: UUID, document_id: UUID, health_qualification_id: UUID, rejected_by_id: UUID, reason: str, now: datetime | None = None):
    reason=reason.strip(); current=_as_utc(now or _utc_now())
    q=get_recovery_read_ownership_transition_health_qualification(db, organization_id=organization_id, claim_id=claim_id, document_id=document_id, health_qualification_id=health_qualification_id, for_update=True)
    if q.status == "rejected":
        if q.rejected_by_id == rejected_by_id and q.rejection_reason == reason: return q,None,"unchanged"
        raise RecoveryReadOwnershipTransitionHealthConflict("Phase W rejection replay does not match")
    if q.status != "pending_second_approval": raise RecoveryReadOwnershipTransitionHealthConflict("Only pending Phase W evidence can be rejected")
    if current >= _as_utc(q.review_expires_at):
        q.status="expired"; q.terminal_by_id=rejected_by_id; q.terminal_at=current; q.terminal_reason="Phase W review window expired"
        receipt=_new_receipt(q, phase="expired", actor_id=rejected_by_id, reason=q.terminal_reason, now=current); db.add(receipt); db.flush(); return q,receipt,"expired"
    q.status="rejected"; q.rejected_by_id=rejected_by_id; q.rejected_at=current; q.rejection_reason=reason
    receipt=_new_receipt(q, phase="rejected", actor_id=rejected_by_id, reason=reason, now=current); db.add(receipt); db.flush(); return q,receipt,"rejected"


def get_recovery_read_ownership_transition_health_qualification(db: Session, *, organization_id: UUID, claim_id: UUID, document_id: UUID, health_qualification_id: UUID, for_update: bool=False) -> EvidenceRecoveryReadOwnershipTransitionHealthQualification:
    stmt=select(EvidenceRecoveryReadOwnershipTransitionHealthQualification).where(
        EvidenceRecoveryReadOwnershipTransitionHealthQualification.id == health_qualification_id,
        EvidenceRecoveryReadOwnershipTransitionHealthQualification.organization_id == organization_id,
        EvidenceRecoveryReadOwnershipTransitionHealthQualification.claim_id == claim_id,
        EvidenceRecoveryReadOwnershipTransitionHealthQualification.document_id == document_id)
    if for_update: stmt=stmt.with_for_update()
    q=db.scalar(stmt)
    if q is None: raise RecoveryReadOwnershipTransitionHealthNotFound("Phase W health qualification not found")
    return q


def list_recovery_read_ownership_transition_health_receipts(db: Session, *, organization_id: UUID, claim_id: UUID, document_id: UUID, health_qualification_id: UUID):
    get_recovery_read_ownership_transition_health_qualification(db, organization_id=organization_id, claim_id=claim_id, document_id=document_id, health_qualification_id=health_qualification_id)
    return list(db.scalars(select(EvidenceRecoveryReadOwnershipTransitionHealthReceipt).where(
        EvidenceRecoveryReadOwnershipTransitionHealthReceipt.organization_id == organization_id,
        EvidenceRecoveryReadOwnershipTransitionHealthReceipt.claim_id == claim_id,
        EvidenceRecoveryReadOwnershipTransitionHealthReceipt.document_id == document_id,
        EvidenceRecoveryReadOwnershipTransitionHealthReceipt.health_qualification_id == health_qualification_id,
    ).order_by(EvidenceRecoveryReadOwnershipTransitionHealthReceipt.transitioned_at.asc())).all())
