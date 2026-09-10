from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog
from app.modules.documents.models import Document
from app.modules.documents.recovery_durable_read_health_models import EvidenceRecoveryDurableReadHealthQualification
from app.modules.documents.recovery_durable_read_renewal_health_models import (
    EvidenceRecoveryDurableReadRenewalHealthQualification,
    EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt,
)
from app.modules.documents.recovery_durable_read_renewal_models import EvidenceRecoveryDurableReadRenewalAuthorization
from app.modules.documents.recovery_durable_read_renewal_routing_models import (
    EvidenceRecoveryDurableReadRenewalLease,
    EvidenceRecoveryDurableReadRenewalReceipt,
)
from app.modules.documents.recovery_durable_read_routing_models import EvidenceRecoveryDurableReadPromotionLease
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

RENEWAL_HEALTH_REVIEW_WINDOW = timedelta(minutes=10)


class RecoveryDurableReadRenewalHealthError(RuntimeError):
    pass


class RecoveryDurableReadRenewalHealthNotFound(RecoveryDurableReadRenewalHealthError):
    pass


class RecoveryDurableReadRenewalHealthConflict(RecoveryDurableReadRenewalHealthError):
    pass


class RecoveryDurableReadRenewalHealthUnavailable(RecoveryDurableReadRenewalHealthError):
    pass


@dataclass(frozen=True)
class RenewalOperationalEvidence:
    verified_durable_read_count: int
    integrity_failure_count: int
    storage_unavailable_count: int
    route_expired_attempt_count: int
    operational_event_count: int
    health_state: str
    operational_evidence_hash: str


@dataclass(frozen=True)
class RenewalHealthSnapshot:
    lease: EvidenceRecoveryDurableReadRenewalLease
    activation: EvidenceRecoveryDurableReadRenewalReceipt
    terminal: EvidenceRecoveryDurableReadRenewalReceipt
    authorization: EvidenceRecoveryDurableReadRenewalAuthorization
    phase_n_health: EvidenceRecoveryDurableReadHealthQualification
    prior_lease: EvidenceRecoveryDurableReadPromotionLease
    document: Document
    route: EvidenceRecoveryReadPathRoute
    terminal_phase: str
    window_started_at: datetime
    window_ended_at: datetime
    evidence: RenewalOperationalEvidence
    request_snapshot_hash: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _get_renewal_lease(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    renewal_lease_id: UUID,
) -> EvidenceRecoveryDurableReadRenewalLease:
    lease = db.scalar(
        select(EvidenceRecoveryDurableReadRenewalLease).where(
            EvidenceRecoveryDurableReadRenewalLease.id == renewal_lease_id,
            EvidenceRecoveryDurableReadRenewalLease.organization_id == organization_id,
            EvidenceRecoveryDurableReadRenewalLease.claim_id == claim_id,
            EvidenceRecoveryDurableReadRenewalLease.document_id == document_id,
        )
    )
    if lease is None:
        raise RecoveryDurableReadRenewalHealthNotFound("Durable recovery read renewal lease not found")
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
        raise RecoveryDurableReadRenewalHealthNotFound("Document not found")
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
        raise RecoveryDurableReadRenewalHealthNotFound("Recovery read-path route not found")
    return route


def _renewal_receipt(
    db: Session,
    *,
    lease: EvidenceRecoveryDurableReadRenewalLease,
    phase: str,
) -> EvidenceRecoveryDurableReadRenewalReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryDurableReadRenewalReceipt).where(
                EvidenceRecoveryDurableReadRenewalReceipt.organization_id == lease.organization_id,
                EvidenceRecoveryDurableReadRenewalReceipt.claim_id == lease.claim_id,
                EvidenceRecoveryDurableReadRenewalReceipt.document_id == lease.document_id,
                EvidenceRecoveryDurableReadRenewalReceipt.renewal_lease_id == lease.id,
                EvidenceRecoveryDurableReadRenewalReceipt.phase == phase,
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryDurableReadRenewalHealthConflict(
            f"Phase P renewal lease must have exactly one {phase} receipt"
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
        raise RecoveryDurableReadRenewalHealthConflict("Phase P renewal receipt lineage is inconsistent")
    return receipt


def _terminal_window(lease: EvidenceRecoveryDurableReadRenewalLease) -> tuple[str, datetime, datetime]:
    if lease.status not in {"rolled_back", "expired"}:
        raise RecoveryDurableReadRenewalHealthConflict(
            "Only a completed Phase P renewal window can be health-qualified"
        )
    if lease.activated_by_id is None or lease.activated_at is None:
        raise RecoveryDurableReadRenewalHealthConflict(
            "Phase P renewal lease is missing activation lineage"
        )
    if lease.status == "rolled_back":
        if lease.rolled_back_at is None or lease.rolled_back_by_id is None:
            raise RecoveryDurableReadRenewalHealthConflict("Rolled-back Phase P renewal lease is incomplete")
        ended_at = _as_utc(lease.rolled_back_at)
    else:
        if lease.terminal_at is None or lease.terminal_by_id is None:
            raise RecoveryDurableReadRenewalHealthConflict("Expired Phase P renewal lease is incomplete")
        ended_at = _as_utc(lease.terminal_at)
    started_at = _as_utc(lease.activated_at)
    if ended_at < started_at:
        raise RecoveryDurableReadRenewalHealthConflict("Phase P operational window is temporally invalid")
    return lease.status, started_at, ended_at


def _load_lineage(
    db: Session,
    *,
    lease: EvidenceRecoveryDurableReadRenewalLease,
) -> tuple[
    EvidenceRecoveryDurableReadRenewalAuthorization,
    EvidenceRecoveryDurableReadHealthQualification,
    EvidenceRecoveryDurableReadPromotionLease,
]:
    authorization = db.scalar(
        select(EvidenceRecoveryDurableReadRenewalAuthorization).where(
            EvidenceRecoveryDurableReadRenewalAuthorization.id == lease.authorization_id,
            EvidenceRecoveryDurableReadRenewalAuthorization.organization_id == lease.organization_id,
            EvidenceRecoveryDurableReadRenewalAuthorization.claim_id == lease.claim_id,
            EvidenceRecoveryDurableReadRenewalAuthorization.document_id == lease.document_id,
        )
    )
    phase_n_health = db.scalar(
        select(EvidenceRecoveryDurableReadHealthQualification).where(
            EvidenceRecoveryDurableReadHealthQualification.id == lease.health_qualification_id,
            EvidenceRecoveryDurableReadHealthQualification.organization_id == lease.organization_id,
            EvidenceRecoveryDurableReadHealthQualification.claim_id == lease.claim_id,
            EvidenceRecoveryDurableReadHealthQualification.document_id == lease.document_id,
        )
    )
    prior_lease = db.scalar(
        select(EvidenceRecoveryDurableReadPromotionLease).where(
            EvidenceRecoveryDurableReadPromotionLease.id == lease.prior_durable_lease_id,
            EvidenceRecoveryDurableReadPromotionLease.organization_id == lease.organization_id,
            EvidenceRecoveryDurableReadPromotionLease.claim_id == lease.claim_id,
            EvidenceRecoveryDurableReadPromotionLease.document_id == lease.document_id,
        )
    )
    if authorization is None or phase_n_health is None or prior_lease is None:
        raise RecoveryDurableReadRenewalHealthNotFound("Phase P upstream renewal lineage not found")
    if not all(
        (
            authorization.status == "approved",
            authorization.approved_by_id is not None,
            authorization.id == lease.authorization_id,
            authorization.authorization_hash == lease.authorization_hash,
            authorization.request_snapshot_hash == lease.authorization_request_snapshot_hash,
            authorization.integrity_proof_hash == lease.authorization_integrity_proof_hash,
            authorization.health_qualification_id == lease.health_qualification_id,
            authorization.health_qualification_hash == lease.health_qualification_hash,
            authorization.operational_evidence_hash == lease.operational_evidence_hash,
            authorization.durable_lease_id == lease.prior_durable_lease_id,
            authorization.durable_lease_hash == lease.prior_durable_lease_hash,
            authorization.lease_snapshot_hash == lease.prior_lease_snapshot_hash,
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
            authorization.approved_by_id == lease.authorization_approved_by_id,
            authorization.durable_activated_by_id == lease.prior_durable_activated_by_id,
            phase_n_health.status == "qualified",
            phase_n_health.health_state == "healthy",
            phase_n_health.id == lease.health_qualification_id,
            phase_n_health.health_qualification_hash == lease.health_qualification_hash,
            phase_n_health.operational_evidence_hash == lease.operational_evidence_hash,
            phase_n_health.durable_lease_id == lease.prior_durable_lease_id,
            prior_lease.status in {"rolled_back", "expired"},
            prior_lease.id == lease.prior_durable_lease_id,
            prior_lease.lease_hash == lease.prior_durable_lease_hash,
            prior_lease.lease_snapshot_hash == lease.prior_lease_snapshot_hash,
            prior_lease.replica_id == lease.replica_id,
            prior_lease.replica_hash == lease.replica_hash,
            prior_lease.activated_by_id == lease.prior_durable_activated_by_id,
        )
    ):
        raise RecoveryDurableReadRenewalHealthConflict("Phase O/N/M lineage no longer matches Phase P")
    upstream = (authorization, phase_n_health, prior_lease)
    for item in upstream:
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
            raise RecoveryDurableReadRenewalHealthConflict(
                "Upstream Phase O/N/M evidence crossed its non-routable/local terminal safety boundary"
            )
    return upstream


def _operational_evidence(
    db: Session,
    *,
    lease: EvidenceRecoveryDurableReadRenewalLease,
    started_at: datetime,
    ended_at: datetime,
) -> RenewalOperationalEvidence:
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
        if values.get("recovery_durable_renewal_lease_id") != lease_id:
            continue
        read_source = values.get("read_source")
        failure_class = values.get("failure_class")
        if event.action == "DOWNLOAD_DOCUMENT" and read_source == "recovery-replica-durable-renewal":
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
        raise RecoveryDurableReadRenewalHealthConflict(
            "At least one verified Phase P recovery read is required for renewal health qualification"
        )
    health_state = "healthy"
    if integrity_failures:
        health_state = "failed"
    elif unavailable:
        health_state = "degraded"
    operational_evidence_hash = _canonical_hash(
        {
            "renewal_lease_id": lease_id,
            "window_started_at": _utc_iso(started_at),
            "window_ended_at": _utc_iso(ended_at),
            "verified_durable_read_count": verified,
            "integrity_failure_count": integrity_failures,
            "storage_unavailable_count": unavailable,
            "route_expired_attempt_count": expired_attempts,
            "events": matched,
        }
    )
    return RenewalOperationalEvidence(
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
    renewal_lease_id: UUID,
) -> RenewalHealthSnapshot:
    lease = _get_renewal_lease(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        renewal_lease_id=renewal_lease_id,
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
        raise RecoveryDurableReadRenewalHealthConflict(
            "Completed Phase P renewal lease did not return to the clean local boundary"
        )

    authorization, phase_n_health, prior_lease = _load_lineage(db, lease=lease)
    activation = _renewal_receipt(db, lease=lease, phase="activated")
    terminal = _renewal_receipt(db, lease=lease, phase=terminal_phase)
    if not all(
        (
            activation.from_route_class == "local_source",
            activation.to_route_class == "recovery_replica",
            activation.route_authority_kind == "durable_renewal",
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
        raise RecoveryDurableReadRenewalHealthConflict(
            "Phase P activation/terminal transition proof is inconsistent"
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
        raise RecoveryDurableReadRenewalHealthConflict(
            "Shared read route is not in the exact clean local state produced by Phase P"
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
        raise RecoveryDurableReadRenewalHealthNotFound(str(exc)) from exc
    except (RecoveryRoutableReadCutoverUnavailable, RecoveryReplicationUnavailable) as exc:
        raise RecoveryDurableReadRenewalHealthUnavailable(str(exc)) from exc
    except (RecoveryRoutableReadCutoverConflict, RecoveryReplicationConflict, FileNotFoundError) as exc:
        raise RecoveryDurableReadRenewalHealthConflict(str(exc)) from exc

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
        raise RecoveryDurableReadRenewalHealthConflict(
            "Local or recovery evidence integrity drifted before Phase Q qualification"
        )

    evidence = _operational_evidence(db, lease=lease, started_at=started_at, ended_at=ended_at)
    request_snapshot_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "renewal_lease_id": str(lease.id),
            "renewal_lease_hash": lease.lease_hash,
            "lease_snapshot_hash": lease.lease_snapshot_hash,
            "activation_receipt_id": str(activation.id),
            "activation_receipt_hash": activation.receipt_hash,
            "terminal_receipt_id": str(terminal.id),
            "terminal_receipt_hash": terminal.receipt_hash,
            "terminal_phase": terminal_phase,
            "authorization_id": str(authorization.id),
            "authorization_hash": authorization.authorization_hash,
            "phase_n_health_qualification_id": str(phase_n_health.id),
            "phase_n_health_qualification_hash": phase_n_health.health_qualification_hash,
            "prior_durable_lease_id": str(prior_lease.id),
            "prior_durable_lease_hash": prior_lease.lease_hash,
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
            "mode": "non_routable_durable_read_renewal_health_qualification",
            "routable_authority_created": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
        }
    )
    return RenewalHealthSnapshot(
        lease=lease,
        activation=activation,
        terminal=terminal,
        authorization=authorization,
        phase_n_health=phase_n_health,
        prior_lease=prior_lease,
        document=document,
        route=route,
        terminal_phase=terminal_phase,
        window_started_at=started_at,
        window_ended_at=ended_at,
        evidence=evidence,
        request_snapshot_hash=request_snapshot_hash,
    )


def _matches_snapshot(
    qualification: EvidenceRecoveryDurableReadRenewalHealthQualification,
    snapshot: RenewalHealthSnapshot,
) -> bool:
    lease = snapshot.lease
    evidence = snapshot.evidence
    return all(
        (
            qualification.renewal_lease_id == lease.id,
            qualification.activation_receipt_id == snapshot.activation.id,
            qualification.terminal_receipt_id == snapshot.terminal.id,
            qualification.authorization_id == snapshot.authorization.id,
            qualification.phase_n_health_qualification_id == snapshot.phase_n_health.id,
            qualification.prior_durable_lease_id == snapshot.prior_lease.id,
            qualification.replica_id == lease.replica_id,
            qualification.renewal_lease_hash == lease.lease_hash,
            qualification.lease_snapshot_hash == lease.lease_snapshot_hash,
            qualification.activation_receipt_hash == snapshot.activation.receipt_hash,
            qualification.terminal_receipt_hash == snapshot.terminal.receipt_hash,
            qualification.authorization_hash == snapshot.authorization.authorization_hash,
            qualification.phase_n_health_qualification_hash == snapshot.phase_n_health.health_qualification_hash,
            qualification.prior_durable_lease_hash == snapshot.prior_lease.lease_hash,
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
            qualification.renewal_activated_by_id == lease.activated_by_id,
            qualification.renewal_authorization_approved_by_id == lease.authorization_approved_by_id,
            qualification.prior_durable_activated_by_id == lease.prior_durable_activated_by_id,
        )
    )


def _new_receipt(
    *,
    qualification: EvidenceRecoveryDurableReadRenewalHealthQualification,
    phase: str,
    actor_id: UUID,
    reason: str,
    transitioned_at: datetime,
) -> EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt:
    normalized_reason = reason.strip()
    receipt_hash = _canonical_hash(
        {
            "health_qualification_id": str(qualification.id),
            "renewal_lease_id": str(qualification.renewal_lease_id),
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
    return EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt(
        organization_id=qualification.organization_id,
        claim_id=qualification.claim_id,
        document_id=qualification.document_id,
        health_qualification_id=qualification.id,
        renewal_lease_id=qualification.renewal_lease_id,
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
    qualification: EvidenceRecoveryDurableReadRenewalHealthQualification,
    phase: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
) -> EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt:
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
) -> EvidenceRecoveryDurableReadRenewalHealthQualification:
    stmt = select(EvidenceRecoveryDurableReadRenewalHealthQualification).where(
        EvidenceRecoveryDurableReadRenewalHealthQualification.id == health_qualification_id,
        EvidenceRecoveryDurableReadRenewalHealthQualification.organization_id == organization_id,
        EvidenceRecoveryDurableReadRenewalHealthQualification.claim_id == claim_id,
        EvidenceRecoveryDurableReadRenewalHealthQualification.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    qualification = db.scalar(stmt)
    if qualification is None:
        raise RecoveryDurableReadRenewalHealthNotFound("Durable read renewal health qualification not found")
    return qualification


def request_durable_read_renewal_health_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    renewal_lease_id: UUID,
    requested_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryDurableReadRenewalHealthQualification, EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadRenewalHealthConflict("Renewal health qualification request reason is required")
    current_time = _as_utc(now or _utc_now())
    existing = db.scalar(
        select(EvidenceRecoveryDurableReadRenewalHealthQualification)
        .where(
            EvidenceRecoveryDurableReadRenewalHealthQualification.organization_id == organization_id,
            EvidenceRecoveryDurableReadRenewalHealthQualification.renewal_lease_id == renewal_lease_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.requested_by_id != requested_by_id or existing.request_reason != normalized_reason:
            raise RecoveryDurableReadRenewalHealthConflict(
                "Phase Q request replay must use the original requester and reason"
            )
        if existing.status == "pending_second_approval" and current_time >= _as_utc(existing.review_expires_at):
            receipt = _terminalize(
                db,
                qualification=existing,
                phase="expired",
                actor_id=requested_by_id,
                reason="Phase Q second-approval window expired",
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
            renewal_lease_id=renewal_lease_id,
        )
        if not _matches_snapshot(existing, snapshot):
            receipt = _terminalize(
                db,
                qualification=existing,
                phase="invalidated",
                actor_id=requested_by_id,
                reason="Phase P renewal health evidence drifted before request replay",
                now=current_time,
            )
            return existing, receipt, "invalidated"
        return existing, None, "unchanged"

    snapshot = _load_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        renewal_lease_id=renewal_lease_id,
    )
    lease = snapshot.lease
    evidence = snapshot.evidence
    review_expires_at = current_time + RENEWAL_HEALTH_REVIEW_WINDOW
    health_qualification_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "renewal_lease_id": str(renewal_lease_id),
            "request_snapshot_hash": snapshot.request_snapshot_hash,
            "operational_evidence_hash": evidence.operational_evidence_hash,
            "health_state": evidence.health_state,
            "requested_by_id": str(requested_by_id),
            "requested_at": _utc_iso(current_time),
            "review_expires_at": _utc_iso(review_expires_at),
            "request_reason": normalized_reason,
            "mode": "non_routable_phase_p_renewal_health_qualification",
        }
    )
    qualification = EvidenceRecoveryDurableReadRenewalHealthQualification(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        renewal_lease_id=lease.id,
        activation_receipt_id=snapshot.activation.id,
        terminal_receipt_id=snapshot.terminal.id,
        authorization_id=snapshot.authorization.id,
        phase_n_health_qualification_id=snapshot.phase_n_health.id,
        prior_durable_lease_id=snapshot.prior_lease.id,
        replica_id=lease.replica_id,
        renewal_lease_hash=lease.lease_hash,
        lease_snapshot_hash=lease.lease_snapshot_hash,
        activation_receipt_hash=snapshot.activation.receipt_hash,
        terminal_receipt_hash=snapshot.terminal.receipt_hash,
        authorization_hash=snapshot.authorization.authorization_hash,
        phase_n_health_qualification_hash=snapshot.phase_n_health.health_qualification_hash,
        prior_durable_lease_hash=snapshot.prior_lease.lease_hash,
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
        renewal_activated_by_id=lease.activated_by_id,
        renewal_authorization_approved_by_id=lease.authorization_approved_by_id,
        prior_durable_activated_by_id=lease.prior_durable_activated_by_id,
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


def qualify_durable_read_renewal_health(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    qualified_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryDurableReadRenewalHealthQualification, EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadRenewalHealthConflict("Renewal health qualification reason is required")
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
        raise RecoveryDurableReadRenewalHealthConflict("Only a pending Phase Q qualification can be assessed")
    if current_time >= _as_utc(qualification.review_expires_at):
        receipt = _terminalize(
            db,
            qualification=qualification,
            phase="expired",
            actor_id=qualified_by_id,
            reason="Phase Q second-approval window expired",
            now=current_time,
        )
        return qualification, receipt, "expired"
    if qualified_by_id in {
        qualification.requested_by_id,
        qualification.renewal_activated_by_id,
        qualification.renewal_authorization_approved_by_id,
        qualification.prior_durable_activated_by_id,
    }:
        raise RecoveryDurableReadRenewalHealthConflict(
            "Phase Q qualifier must be independent from the requester and prior routing/authorization actors"
        )
    try:
        snapshot = _load_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            renewal_lease_id=qualification.renewal_lease_id,
        )
    except RecoveryDurableReadRenewalHealthUnavailable:
        raise
    except (RecoveryDurableReadRenewalHealthNotFound, RecoveryDurableReadRenewalHealthConflict) as exc:
        receipt = _terminalize(
            db,
            qualification=qualification,
            phase="invalidated",
            actor_id=qualified_by_id,
            reason=f"Fresh Phase Q preflight failed: {type(exc).__name__}",
            now=current_time,
        )
        return qualification, receipt, "invalidated"
    if not _matches_snapshot(qualification, snapshot):
        receipt = _terminalize(
            db,
            qualification=qualification,
            phase="invalidated",
            actor_id=qualified_by_id,
            reason="Phase P renewal health snapshot drifted before second approval",
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


def reject_durable_read_renewal_health(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    rejected_by_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> tuple[EvidenceRecoveryDurableReadRenewalHealthQualification, EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt | None, str]:
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableReadRenewalHealthConflict("Renewal health rejection reason is required")
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
        raise RecoveryDurableReadRenewalHealthConflict("Only a pending Phase Q qualification can be rejected")
    if current_time >= _as_utc(qualification.review_expires_at):
        receipt = _terminalize(
            db,
            qualification=qualification,
            phase="expired",
            actor_id=rejected_by_id,
            reason="Phase Q second-approval window expired",
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


def get_durable_read_renewal_health_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
) -> EvidenceRecoveryDurableReadRenewalHealthQualification:
    return _get_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        health_qualification_id=health_qualification_id,
    )


def list_durable_read_renewal_health_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
) -> list[EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt]:
    _get_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        health_qualification_id=health_qualification_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt)
            .where(
                EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt.organization_id == organization_id,
                EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt.claim_id == claim_id,
                EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt.document_id == document_id,
                EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt.health_qualification_id == health_qualification_id,
            )
            .order_by(
                EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt.transitioned_at.asc(),
                EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt.created_at.asc(),
                EvidenceRecoveryDurableReadRenewalHealthQualificationReceipt.id.asc(),
            )
        ).all()
    )
