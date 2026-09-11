from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog
from app.modules.documents.models import Document
from app.modules.documents.recovery_durable_read_reauthorized_renewal_health_models import (
    EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification,
    EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt,
)
from app.modules.documents.recovery_durable_read_reauthorized_renewal_routing_models import (
    EvidenceRecoveryDurableReadReauthorizedRenewalLease,
    EvidenceRecoveryDurableReadReauthorizedRenewalReceipt,
)
from app.modules.documents.recovery_durable_read_renewal_health_models import (
    EvidenceRecoveryDurableReadRenewalHealthQualification,
)
from app.modules.documents.recovery_durable_read_renewal_reauthorization_models import (
    EvidenceRecoveryDurableReadRenewalReauthorization,
)
from app.modules.documents.recovery_durable_read_renewal_routing_models import (
    EvidenceRecoveryDurableReadRenewalLease,
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

REAUTHORIZED_RENEWAL_HEALTH_REVIEW_WINDOW = timedelta(minutes=10)


class RecoveryDurableReadReauthorizedRenewalHealthError(RuntimeError):
    pass


class RecoveryDurableReadReauthorizedRenewalHealthNotFound(
    RecoveryDurableReadReauthorizedRenewalHealthError
):
    pass


class RecoveryDurableReadReauthorizedRenewalHealthConflict(
    RecoveryDurableReadReauthorizedRenewalHealthError
):
    pass


class RecoveryDurableReadReauthorizedRenewalHealthUnavailable(
    RecoveryDurableReadReauthorizedRenewalHealthError
):
    pass


@dataclass(frozen=True)
class ReauthorizedRenewalOperationalEvidence:
    verified_durable_read_count: int
    integrity_failure_count: int
    storage_unavailable_count: int
    route_expired_attempt_count: int
    operational_event_count: int
    health_state: str
    operational_evidence_hash: str


@dataclass(frozen=True)
class ReauthorizedRenewalHealthSnapshot:
    lease: EvidenceRecoveryDurableReadReauthorizedRenewalLease
    activation: EvidenceRecoveryDurableReadReauthorizedRenewalReceipt
    terminal: EvidenceRecoveryDurableReadReauthorizedRenewalReceipt
    reauthorization: EvidenceRecoveryDurableReadRenewalReauthorization
    phase_q_health: EvidenceRecoveryDurableReadRenewalHealthQualification
    prior_renewal_lease: EvidenceRecoveryDurableReadRenewalLease
    document: Document
    route: EvidenceRecoveryReadPathRoute
    terminal_phase: str
    window_started_at: datetime
    window_ended_at: datetime
    evidence: ReauthorizedRenewalOperationalEvidence
    request_snapshot_hash: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _get_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    reauthorized_renewal_lease_id: UUID,
) -> EvidenceRecoveryDurableReadReauthorizedRenewalLease:
    lease = db.scalar(
        select(EvidenceRecoveryDurableReadReauthorizedRenewalLease).where(
            EvidenceRecoveryDurableReadReauthorizedRenewalLease.id == reauthorized_renewal_lease_id,
            EvidenceRecoveryDurableReadReauthorizedRenewalLease.organization_id == organization_id,
            EvidenceRecoveryDurableReadReauthorizedRenewalLease.claim_id == claim_id,
            EvidenceRecoveryDurableReadReauthorizedRenewalLease.document_id == document_id,
        )
    )
    if lease is None:
        raise RecoveryDurableReadReauthorizedRenewalHealthNotFound(
            "Reauthorized durable recovery read renewal lease not found"
        )
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
        raise RecoveryDurableReadReauthorizedRenewalHealthNotFound("Document not found")
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
        raise RecoveryDurableReadReauthorizedRenewalHealthNotFound(
            "Recovery read-path route not found"
        )
    return route


def _lease_receipt(
    db: Session,
    *,
    lease: EvidenceRecoveryDurableReadReauthorizedRenewalLease,
    phase: str,
) -> EvidenceRecoveryDurableReadReauthorizedRenewalReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryDurableReadReauthorizedRenewalReceipt).where(
                EvidenceRecoveryDurableReadReauthorizedRenewalReceipt.organization_id
                == lease.organization_id,
                EvidenceRecoveryDurableReadReauthorizedRenewalReceipt.claim_id == lease.claim_id,
                EvidenceRecoveryDurableReadReauthorizedRenewalReceipt.document_id
                == lease.document_id,
                EvidenceRecoveryDurableReadReauthorizedRenewalReceipt.reauthorized_renewal_lease_id
                == lease.id,
                EvidenceRecoveryDurableReadReauthorizedRenewalReceipt.phase == phase,
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
            f"Phase S lease must have exactly one {phase} receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            receipt.reauthorization_id == lease.reauthorization_id,
            receipt.lease_snapshot_hash == lease.lease_snapshot_hash,
            receipt.lease_hash == lease.lease_hash,
            receipt.reauthorization_hash == lease.reauthorization_hash,
            receipt.write_path_switched is False,
            receipt.document_storage_key_mutated is False,
            receipt.authoritative_storage_changed is False,
            receipt.destructive_action_performed is False,
            receipt.s3_delete_performed is False,
            receipt.local_delete_performed is False,
        )
    ):
        raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
            "Phase S transition receipt lineage is inconsistent"
        )
    return receipt


def _terminal_window(
    lease: EvidenceRecoveryDurableReadReauthorizedRenewalLease,
) -> tuple[str, datetime, datetime]:
    if lease.status not in {"rolled_back", "expired"}:
        raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
            "Only a completed Phase S renewal window can be health-qualified"
        )
    if lease.activated_by_id is None or lease.activated_at is None:
        raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
            "Phase S lease is missing activation lineage"
        )
    if lease.status == "rolled_back":
        if lease.rolled_back_at is None or lease.rolled_back_by_id is None:
            raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
                "Rolled-back Phase S lease is incomplete"
            )
        ended_at = _as_utc(lease.rolled_back_at)
    else:
        if lease.terminal_at is None or lease.terminal_by_id is None:
            raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
                "Expired Phase S lease is incomplete"
            )
        ended_at = _as_utc(lease.terminal_at)
    started_at = _as_utc(lease.activated_at)
    if ended_at < started_at:
        raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
            "Phase S operational window is temporally invalid"
        )
    return lease.status, started_at, ended_at


def _load_lineage(
    db: Session,
    *,
    lease: EvidenceRecoveryDurableReadReauthorizedRenewalLease,
) -> tuple[
    EvidenceRecoveryDurableReadRenewalReauthorization,
    EvidenceRecoveryDurableReadRenewalHealthQualification,
    EvidenceRecoveryDurableReadRenewalLease,
]:
    reauthorization = db.scalar(
        select(EvidenceRecoveryDurableReadRenewalReauthorization).where(
            EvidenceRecoveryDurableReadRenewalReauthorization.id == lease.reauthorization_id,
            EvidenceRecoveryDurableReadRenewalReauthorization.organization_id
            == lease.organization_id,
            EvidenceRecoveryDurableReadRenewalReauthorization.claim_id == lease.claim_id,
            EvidenceRecoveryDurableReadRenewalReauthorization.document_id == lease.document_id,
        )
    )
    phase_q = db.scalar(
        select(EvidenceRecoveryDurableReadRenewalHealthQualification).where(
            EvidenceRecoveryDurableReadRenewalHealthQualification.id
            == lease.phase_q_health_qualification_id,
            EvidenceRecoveryDurableReadRenewalHealthQualification.organization_id
            == lease.organization_id,
            EvidenceRecoveryDurableReadRenewalHealthQualification.claim_id == lease.claim_id,
            EvidenceRecoveryDurableReadRenewalHealthQualification.document_id
            == lease.document_id,
        )
    )
    prior_lease = db.scalar(
        select(EvidenceRecoveryDurableReadRenewalLease).where(
            EvidenceRecoveryDurableReadRenewalLease.id == lease.prior_renewal_lease_id,
            EvidenceRecoveryDurableReadRenewalLease.organization_id == lease.organization_id,
            EvidenceRecoveryDurableReadRenewalLease.claim_id == lease.claim_id,
            EvidenceRecoveryDurableReadRenewalLease.document_id == lease.document_id,
        )
    )
    if reauthorization is None or phase_q is None or prior_lease is None:
        raise RecoveryDurableReadReauthorizedRenewalHealthNotFound(
            "Phase S upstream R/Q/P lineage not found"
        )

    if not all(
        (
            reauthorization.status == "approved",
            reauthorization.approved_by_id is not None,
            reauthorization.id == lease.reauthorization_id,
            reauthorization.authorization_hash == lease.reauthorization_hash,
            reauthorization.request_snapshot_hash == lease.reauthorization_request_snapshot_hash,
            reauthorization.integrity_proof_hash == lease.reauthorization_integrity_proof_hash,
            reauthorization.phase_q_health_qualification_id
            == lease.phase_q_health_qualification_id,
            reauthorization.phase_q_health_qualification_hash
            == lease.phase_q_health_qualification_hash,
            reauthorization.operational_evidence_hash == lease.operational_evidence_hash,
            reauthorization.renewal_lease_id == lease.prior_renewal_lease_id,
            reauthorization.renewal_lease_hash == lease.prior_renewal_lease_hash,
            reauthorization.lease_snapshot_hash == lease.prior_lease_snapshot_hash,
            reauthorization.replica_id == lease.replica_id,
            reauthorization.replica_hash == lease.replica_hash,
            reauthorization.source_file_hash == lease.source_file_hash,
            reauthorization.source_file_size_bytes == lease.source_file_size_bytes,
            reauthorization.local_storage_key_fingerprint
            == lease.local_storage_key_fingerprint,
            reauthorization.recovery_bucket_fingerprint
            == lease.recovery_bucket_fingerprint,
            reauthorization.candidate_storage_key_fingerprint
            == lease.candidate_storage_key_fingerprint,
            reauthorization.source_authority_fingerprint
            == lease.source_authority_fingerprint,
            reauthorization.candidate_authority_fingerprint
            == lease.candidate_authority_fingerprint,
            reauthorization.configuration_fingerprint == lease.configuration_fingerprint,
            reauthorization.approved_by_id == lease.reauthorization_approved_by_id,
            reauthorization.phase_q_qualified_by_id == lease.phase_q_qualified_by_id,
            reauthorization.renewal_activated_by_id
            == lease.prior_renewal_activated_by_id,
            phase_q.status == "qualified",
            phase_q.health_state == "healthy",
            phase_q.id == lease.phase_q_health_qualification_id,
            phase_q.health_qualification_hash == lease.phase_q_health_qualification_hash,
            phase_q.operational_evidence_hash == lease.operational_evidence_hash,
            phase_q.renewal_lease_id == lease.prior_renewal_lease_id,
            phase_q.qualified_by_id == lease.phase_q_qualified_by_id,
            prior_lease.status in {"rolled_back", "expired"},
            prior_lease.id == lease.prior_renewal_lease_id,
            prior_lease.lease_hash == lease.prior_renewal_lease_hash,
            prior_lease.lease_snapshot_hash == lease.prior_lease_snapshot_hash,
            prior_lease.replica_id == lease.replica_id,
            prior_lease.replica_hash == lease.replica_hash,
            prior_lease.activated_by_id == lease.prior_renewal_activated_by_id,
        )
    ):
        raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
            "Phase R/Q/P lineage no longer matches Phase S"
        )

    for item in (reauthorization, phase_q, prior_lease):
        if any(
            (
                item.routable_authority_created,
                item.durable_read_route_created,
                item.read_path_switched,
                item.write_path_switched,
                item.document_storage_key_mutated,
                item.authoritative_storage_changed,
                item.destructive_action_performed,
                item.s3_delete_performed,
                item.local_delete_performed,
            )
        ):
            raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
                "Upstream Phase R/Q/P evidence crossed its terminal safety boundary"
            )
    return reauthorization, phase_q, prior_lease


def _operational_evidence(
    db: Session,
    *,
    lease: EvidenceRecoveryDurableReadReauthorizedRenewalLease,
    started_at: datetime,
    ended_at: datetime,
) -> ReauthorizedRenewalOperationalEvidence:
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
    start_second = started_at.replace(microsecond=0)
    end_second = ended_at.replace(microsecond=0)
    for event in events:
        event_at = _as_utc(event.created_at)
        event_second = event_at.replace(microsecond=0)
        if event_second < start_second or event_second > end_second:
            continue
        values = event.new_values or {}
        if values.get("recovery_durable_reauthorized_renewal_lease_id") != lease_id:
            continue
        read_source = values.get("read_source")
        failure_class = values.get("failure_class")
        if (
            event.action == "DOWNLOAD_DOCUMENT"
            and read_source == "recovery-replica-durable-reauthorized-renewal"
        ):
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
        raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
            "At least one verified Phase S recovery read is required for health qualification"
        )
    health_state = "healthy"
    if integrity_failures:
        health_state = "failed"
    elif unavailable:
        health_state = "degraded"
    operational_evidence_hash = _canonical_hash(
        {
            "reauthorized_renewal_lease_id": lease_id,
            "window_started_at": _utc_iso(started_at),
            "window_ended_at": _utc_iso(ended_at),
            "verified_durable_read_count": verified,
            "integrity_failure_count": integrity_failures,
            "storage_unavailable_count": unavailable,
            "route_expired_attempt_count": expired_attempts,
            "events": matched,
        }
    )
    return ReauthorizedRenewalOperationalEvidence(
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
    reauthorized_renewal_lease_id: UUID,
) -> ReauthorizedRenewalHealthSnapshot:
    lease = _get_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        reauthorized_renewal_lease_id=reauthorized_renewal_lease_id,
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
        raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
            "Completed Phase S lease did not return to the clean local boundary"
        )

    reauthorization, phase_q, prior_lease = _load_lineage(db, lease=lease)
    activation = _lease_receipt(db, lease=lease, phase="activated")
    terminal = _lease_receipt(db, lease=lease, phase=terminal_phase)
    if not all(
        (
            activation.from_route_class == "local_source",
            activation.to_route_class == "recovery_replica",
            activation.route_authority_kind == "durable_reauthorized_renewal",
            activation.routable_authority_created is True,
            activation.durable_read_route_created is True,
            activation.read_path_switched is True,
            activation.actor_id == lease.activated_by_id,
            activation.route_version == lease.route_version_at_prepare + 1,
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
        raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
            "Phase S activation/terminal transition proof is inconsistent"
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
            route.active_durable_renewal_lease_id is None,
            route.active_durable_reauthorized_renewal_lease_id is None,
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
        raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
            "Shared read route is not in the exact clean local state produced by Phase S"
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
        raise RecoveryDurableReadReauthorizedRenewalHealthNotFound(str(exc)) from exc
    except (RecoveryRoutableReadCutoverUnavailable, RecoveryReplicationUnavailable) as exc:
        raise RecoveryDurableReadReauthorizedRenewalHealthUnavailable(str(exc)) from exc
    except (RecoveryRoutableReadCutoverConflict, RecoveryReplicationConflict, FileNotFoundError) as exc:
        raise RecoveryDurableReadReauthorizedRenewalHealthConflict(str(exc)) from exc

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
        raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
            "Local or recovery evidence integrity drifted before Phase T qualification"
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
            "reauthorized_renewal_lease_id": str(lease.id),
            "reauthorized_renewal_lease_hash": lease.lease_hash,
            "lease_snapshot_hash": lease.lease_snapshot_hash,
            "activation_receipt_id": str(activation.id),
            "activation_receipt_hash": activation.receipt_hash,
            "terminal_receipt_id": str(terminal.id),
            "terminal_receipt_hash": terminal.receipt_hash,
            "terminal_phase": terminal_phase,
            "reauthorization_id": str(reauthorization.id),
            "reauthorization_hash": reauthorization.authorization_hash,
            "phase_q_health_qualification_id": str(phase_q.id),
            "phase_q_health_qualification_hash": phase_q.health_qualification_hash,
            "prior_renewal_lease_id": str(prior_lease.id),
            "prior_renewal_lease_hash": prior_lease.lease_hash,
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
            "route_version": route.route_version,
            "mode": "non_routable_phase_s_reauthorized_renewal_health_qualification",
            "routable_authority_created": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
        }
    )
    return ReauthorizedRenewalHealthSnapshot(
        lease=lease,
        activation=activation,
        terminal=terminal,
        reauthorization=reauthorization,
        phase_q_health=phase_q,
        prior_renewal_lease=prior_lease,
        document=document,
        route=route,
        terminal_phase=terminal_phase,
        window_started_at=started_at,
        window_ended_at=ended_at,
        evidence=evidence,
        request_snapshot_hash=request_snapshot_hash,
    )


def _matches_snapshot(
    qualification: EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification,
    snapshot: ReauthorizedRenewalHealthSnapshot,
) -> bool:
    lease = snapshot.lease
    evidence = snapshot.evidence
    return all(
        (
            qualification.reauthorized_renewal_lease_id == lease.id,
            qualification.activation_receipt_id == snapshot.activation.id,
            qualification.terminal_receipt_id == snapshot.terminal.id,
            qualification.reauthorization_id == snapshot.reauthorization.id,
            qualification.phase_q_health_qualification_id == snapshot.phase_q_health.id,
            qualification.prior_renewal_lease_id == snapshot.prior_renewal_lease.id,
            qualification.replica_id == lease.replica_id,
            qualification.reauthorized_renewal_lease_hash == lease.lease_hash,
            qualification.lease_snapshot_hash == lease.lease_snapshot_hash,
            qualification.activation_receipt_hash == snapshot.activation.receipt_hash,
            qualification.terminal_receipt_hash == snapshot.terminal.receipt_hash,
            qualification.reauthorization_hash == snapshot.reauthorization.authorization_hash,
            qualification.phase_q_health_qualification_hash
            == snapshot.phase_q_health.health_qualification_hash,
            qualification.prior_renewal_lease_hash == snapshot.prior_renewal_lease.lease_hash,
            qualification.replica_hash == lease.replica_hash,
            qualification.source_file_hash == lease.source_file_hash,
            qualification.source_file_size_bytes == lease.source_file_size_bytes,
            qualification.local_storage_key_fingerprint == lease.local_storage_key_fingerprint,
            qualification.recovery_bucket_fingerprint == lease.recovery_bucket_fingerprint,
            qualification.candidate_storage_key_fingerprint
            == lease.candidate_storage_key_fingerprint,
            qualification.source_authority_fingerprint == lease.source_authority_fingerprint,
            qualification.candidate_authority_fingerprint
            == lease.candidate_authority_fingerprint,
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
            qualification.reauthorized_renewal_activated_by_id == lease.activated_by_id,
            qualification.reauthorization_approved_by_id
            == lease.reauthorization_approved_by_id,
            qualification.phase_q_qualified_by_id == lease.phase_q_qualified_by_id,
            qualification.prior_renewal_activated_by_id
            == lease.prior_renewal_activated_by_id,
        )
    )


def _new_receipt(
    *,
    qualification: EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification,
    phase: str,
    actor_id: UUID,
    reason: str,
    transitioned_at: datetime,
) -> EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt:
    normalized_reason = reason.strip()
    receipt_hash = _canonical_hash(
        {
            "health_qualification_id": str(qualification.id),
            "reauthorized_renewal_lease_id": str(
                qualification.reauthorized_renewal_lease_id
            ),
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
    return EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt(
        organization_id=qualification.organization_id,
        claim_id=qualification.claim_id,
        document_id=qualification.document_id,
        health_qualification_id=qualification.id,
        reauthorized_renewal_lease_id=qualification.reauthorized_renewal_lease_id,
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


def _terminalize(
    db: Session,
    *,
    qualification: EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification,
    phase: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt:
    qualification.status = phase
    qualification.terminal_by_id = actor_id
    qualification.terminal_at = now
    qualification.terminal_reason = reason
    receipt = _new_receipt(
        qualification=qualification,
        phase=phase,
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
    )
    db.add(receipt)
    db.flush()
    return receipt


def _get_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    for_update: bool = False,
) -> EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification:
    stmt = select(EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification).where(
        EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification.id
        == health_qualification_id,
        EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification.organization_id
        == organization_id,
        EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification.claim_id == claim_id,
        EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification.document_id
        == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    qualification = db.scalar(stmt)
    if qualification is None:
        raise RecoveryDurableReadReauthorizedRenewalHealthNotFound(
            "Reauthorized renewal health qualification not found"
        )
    return qualification


def request_durable_read_reauthorized_renewal_health_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    reauthorized_renewal_lease_id: UUID,
    requested_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification,
    EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
            "Reauthorized renewal health qualification request reason is required"
        )
    current_time = _as_utc(now or _utc_now())
    existing = db.scalar(
        select(EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification)
        .where(
            EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification.organization_id
            == organization_id,
            EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification.reauthorized_renewal_lease_id
            == reauthorized_renewal_lease_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.requested_by_id != requested_by_id or existing.request_reason != normalized_reason:
            raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
                "Phase T request replay must use the original requester and reason"
            )
        if (
            existing.status == "pending_second_approval"
            and current_time >= _as_utc(existing.review_expires_at)
        ):
            receipt = _terminalize(
                db,
                qualification=existing,
                phase="expired",
                actor_id=requested_by_id,
                reason="Phase T second-approval window expired",
                now=current_time,
            )
            return existing, receipt, "expired"
        if existing.status != "pending_second_approval":
            return existing, None, "unchanged"
        snapshot = _load_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            reauthorized_renewal_lease_id=reauthorized_renewal_lease_id,
        )
        if not _matches_snapshot(existing, snapshot):
            receipt = _terminalize(
                db,
                qualification=existing,
                phase="invalidated",
                actor_id=requested_by_id,
                reason="Phase S health evidence drifted before request replay",
                now=current_time,
            )
            return existing, receipt, "invalidated"
        return existing, None, "unchanged"

    snapshot = _load_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        reauthorized_renewal_lease_id=reauthorized_renewal_lease_id,
    )
    lease = snapshot.lease
    evidence = snapshot.evidence
    review_expires_at = current_time + REAUTHORIZED_RENEWAL_HEALTH_REVIEW_WINDOW
    health_qualification_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "reauthorized_renewal_lease_id": str(reauthorized_renewal_lease_id),
            "request_snapshot_hash": snapshot.request_snapshot_hash,
            "operational_evidence_hash": evidence.operational_evidence_hash,
            "health_state": evidence.health_state,
            "requested_by_id": str(requested_by_id),
            "requested_at": _utc_iso(current_time),
            "review_expires_at": _utc_iso(review_expires_at),
            "request_reason": normalized_reason,
            "mode": "non_routable_phase_s_reauthorized_renewal_health_qualification",
        }
    )
    qualification = EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        reauthorized_renewal_lease_id=lease.id,
        activation_receipt_id=snapshot.activation.id,
        terminal_receipt_id=snapshot.terminal.id,
        reauthorization_id=snapshot.reauthorization.id,
        phase_q_health_qualification_id=snapshot.phase_q_health.id,
        prior_renewal_lease_id=snapshot.prior_renewal_lease.id,
        replica_id=lease.replica_id,
        reauthorized_renewal_lease_hash=lease.lease_hash,
        lease_snapshot_hash=lease.lease_snapshot_hash,
        activation_receipt_hash=snapshot.activation.receipt_hash,
        terminal_receipt_hash=snapshot.terminal.receipt_hash,
        reauthorization_hash=snapshot.reauthorization.authorization_hash,
        phase_q_health_qualification_hash=snapshot.phase_q_health.health_qualification_hash,
        prior_renewal_lease_hash=snapshot.prior_renewal_lease.lease_hash,
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
        reauthorized_renewal_activated_by_id=lease.activated_by_id,
        reauthorization_approved_by_id=lease.reauthorization_approved_by_id,
        phase_q_qualified_by_id=lease.phase_q_qualified_by_id,
        prior_renewal_activated_by_id=lease.prior_renewal_activated_by_id,
        requested_by_id=requested_by_id,
        requested_at=current_time,
        review_expires_at=review_expires_at,
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


def qualify_durable_read_reauthorized_renewal_health(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    qualified_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification,
    EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
            "Reauthorized renewal health qualification reason is required"
        )
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
        raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
            "Only a pending Phase T qualification can be assessed"
        )
    if current_time >= _as_utc(qualification.review_expires_at):
        receipt = _terminalize(
            db,
            qualification=qualification,
            phase="expired",
            actor_id=qualified_by_id,
            reason="Phase T second-approval window expired",
            now=current_time,
        )
        return qualification, receipt, "expired"
    if qualified_by_id in {
        qualification.requested_by_id,
        qualification.reauthorized_renewal_activated_by_id,
        qualification.reauthorization_approved_by_id,
        qualification.phase_q_qualified_by_id,
        qualification.prior_renewal_activated_by_id,
    }:
        raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
            "Phase T qualifier must be independent from the requester and Phase S/R/Q/P actors"
        )
    try:
        snapshot = _load_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            reauthorized_renewal_lease_id=qualification.reauthorized_renewal_lease_id,
        )
    except RecoveryDurableReadReauthorizedRenewalHealthUnavailable:
        raise
    except (
        RecoveryDurableReadReauthorizedRenewalHealthNotFound,
        RecoveryDurableReadReauthorizedRenewalHealthConflict,
    ) as exc:
        receipt = _terminalize(
            db,
            qualification=qualification,
            phase="invalidated",
            actor_id=qualified_by_id,
            reason=f"Fresh Phase T preflight failed: {type(exc).__name__}",
            now=current_time,
        )
        return qualification, receipt, "invalidated"
    if not _matches_snapshot(qualification, snapshot):
        receipt = _terminalize(
            db,
            qualification=qualification,
            phase="invalidated",
            actor_id=qualified_by_id,
            reason="Phase S health snapshot drifted before second approval",
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


def reject_durable_read_reauthorized_renewal_health(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    rejected_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[
    EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification,
    EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt | None,
    str,
]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
            "Reauthorized renewal health rejection reason is required"
        )
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
        raise RecoveryDurableReadReauthorizedRenewalHealthConflict(
            "Only a pending Phase T qualification can be rejected"
        )
    if current_time >= _as_utc(qualification.review_expires_at):
        receipt = _terminalize(
            db,
            qualification=qualification,
            phase="expired",
            actor_id=rejected_by_id,
            reason="Phase T second-approval window expired",
            now=current_time,
        )
        return qualification, receipt, "expired"
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


def get_durable_read_reauthorized_renewal_health_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
) -> EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualification:
    return _get_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        health_qualification_id=health_qualification_id,
    )


def list_durable_read_reauthorized_renewal_health_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
) -> list[EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt]:
    _get_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        health_qualification_id=health_qualification_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt)
            .where(
                EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt.organization_id
                == organization_id,
                EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt.claim_id
                == claim_id,
                EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt.document_id
                == document_id,
                EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt.health_qualification_id
                == health_qualification_id,
            )
            .order_by(
                EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt.transitioned_at.asc(),
                EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt.created_at.asc(),
                EvidenceRecoveryDurableReadReauthorizedRenewalHealthQualificationReceipt.id.asc(),
            )
        ).all()
    )
