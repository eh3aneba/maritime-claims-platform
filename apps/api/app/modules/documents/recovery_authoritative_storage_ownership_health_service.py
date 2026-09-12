from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_authoritative_storage_ownership_execution_models import (
    EvidenceRecoveryAuthoritativeStorageOwnershipLease,
    EvidenceRecoveryAuthoritativeStorageOwnershipReceipt,
    EvidenceRecoveryAuthoritativeStorageOwnershipRoute,
)
from app.modules.documents.recovery_authoritative_storage_ownership_execution_service import (
    RecoveryAuthoritativeStorageOwnershipExecutionConflict,
    RecoveryAuthoritativeStorageOwnershipExecutionNotFound,
    RecoveryAuthoritativeStorageOwnershipExecutionUnavailable,
    _fresh_authorization,
    get_authoritative_storage_ownership_lease,
    get_authoritative_storage_ownership_route,
)
from app.modules.documents.recovery_authoritative_storage_ownership_health_models import (
    EvidenceRecoveryAuthoritativeStorageOwnershipHealthQualification,
    EvidenceRecoveryAuthoritativeStorageOwnershipHealthReceipt,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso


AUTHORITATIVE_STORAGE_OWNERSHIP_HEALTH_REVIEW_WINDOW = timedelta(minutes=10)


class RecoveryAuthoritativeStorageOwnershipHealthError(RuntimeError):
    pass


class RecoveryAuthoritativeStorageOwnershipHealthNotFound(RecoveryAuthoritativeStorageOwnershipHealthError):
    pass


class RecoveryAuthoritativeStorageOwnershipHealthConflict(RecoveryAuthoritativeStorageOwnershipHealthError):
    pass


class RecoveryAuthoritativeStorageOwnershipHealthUnavailable(RecoveryAuthoritativeStorageOwnershipHealthError):
    pass


@dataclass(frozen=True)
class AuthoritativeStorageOwnershipHealthSnapshot:
    lease: EvidenceRecoveryAuthoritativeStorageOwnershipLease
    activation_receipt: EvidenceRecoveryAuthoritativeStorageOwnershipReceipt
    authority_route: EvidenceRecoveryAuthoritativeStorageOwnershipRoute
    authorization: object
    authorization_approval_receipt: object
    phase_ai_qualification: object
    phase_ai_snapshot: object
    integrity_proof_hash: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _active_ak_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    now: datetime | None = None,
) -> AuthoritativeStorageOwnershipHealthSnapshot:
    current = _as_utc(now or _utc_now())
    try:
        lease = get_authoritative_storage_ownership_lease(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
            for_update=True,
        )
    except RecoveryAuthoritativeStorageOwnershipExecutionNotFound as exc:
        raise RecoveryAuthoritativeStorageOwnershipHealthNotFound(str(exc)) from exc

    if not all(
        (
            lease.status == "active",
            lease.ownership_transition_active is True,
            lease.local_authoritative is False,
            lease.recovery_authoritative is True,
            lease.authoritative_storage_changed is True,
            lease.local_evidence_preserved is True,
            lease.storage_write_performed is False,
            lease.read_path_switched is False,
            lease.write_route_mutation_performed is False,
            lease.document_storage_key_mutated is False,
            lease.destructive_action_performed is False,
            lease.physical_disposal_authorized is False,
            lease.s3_put_performed is False,
            lease.s3_copy_performed is False,
            lease.s3_delete_performed is False,
            lease.local_overwrite_performed is False,
            lease.local_move_performed is False,
            lease.local_delete_performed is False,
            lease.terminal_by_id is None,
            lease.terminal_at is None,
            lease.terminal_reason is None,
        )
    ):
        raise RecoveryAuthoritativeStorageOwnershipHealthConflict(
            "Phase AL requires one exact active Phase AK authoritative-storage ownership lease"
        )
    if current >= _as_utc(lease.expires_at):
        raise RecoveryAuthoritativeStorageOwnershipHealthConflict(
            "Phase AK authoritative-storage ownership lease expired before Phase AL qualification"
        )

    receipts = list(
        db.scalars(
            select(EvidenceRecoveryAuthoritativeStorageOwnershipReceipt)
            .where(
                EvidenceRecoveryAuthoritativeStorageOwnershipReceipt.organization_id == organization_id,
                EvidenceRecoveryAuthoritativeStorageOwnershipReceipt.claim_id == claim_id,
                EvidenceRecoveryAuthoritativeStorageOwnershipReceipt.document_id == document_id,
                EvidenceRecoveryAuthoritativeStorageOwnershipReceipt.lease_id == lease.id,
            )
            .order_by(
                EvidenceRecoveryAuthoritativeStorageOwnershipReceipt.transitioned_at.asc(),
                EvidenceRecoveryAuthoritativeStorageOwnershipReceipt.id.asc(),
            )
        ).all()
    )
    if len(receipts) != 1 or receipts[0].phase != "activated":
        raise RecoveryAuthoritativeStorageOwnershipHealthConflict(
            "Phase AL requires exactly one Phase AK activation receipt and no terminal receipt"
        )
    activation = receipts[0]
    if not all(
        (
            activation.authorization_id == lease.authorization_id,
            activation.authorization_hash == lease.authorization_hash,
            activation.authorization_approval_receipt_hash == lease.authorization_approval_receipt_hash,
            activation.phase_ai_health_qualification_hash == lease.phase_ai_health_qualification_hash,
            activation.source_file_hash == lease.source_file_hash,
            activation.source_file_size_bytes == lease.source_file_size_bytes,
            activation.activation_snapshot_hash == lease.activation_snapshot_hash,
            activation.lease_hash == lease.lease_hash,
            activation.from_authority_kind == "local_evidence",
            activation.to_authority_kind == "recovery_storage",
            activation.route_version == lease.authority_route_version_after_activation,
            activation.actor_id == lease.activated_by_id,
            _as_utc(activation.transitioned_at) == _as_utc(lease.activated_at),
            activation.local_authoritative is False,
            activation.recovery_authoritative is True,
            activation.authoritative_storage_changed is True,
            activation.local_evidence_preserved is True,
            activation.storage_write_performed is False,
            activation.read_path_switched is False,
            activation.write_route_mutation_performed is False,
            activation.document_storage_key_mutated is False,
            activation.destructive_action_performed is False,
            activation.physical_disposal_authorized is False,
        )
    ):
        raise RecoveryAuthoritativeStorageOwnershipHealthConflict(
            "Phase AK activation receipt lineage is inconsistent"
        )

    try:
        route = get_authoritative_storage_ownership_route(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
    except RecoveryAuthoritativeStorageOwnershipExecutionNotFound as exc:
        raise RecoveryAuthoritativeStorageOwnershipHealthNotFound(str(exc)) from exc
    if not all(
        (
            route.authority_kind == "recovery_storage",
            route.active_authority_lease_id == lease.id,
            route.route_version == lease.authority_route_version_after_activation,
            route.local_authoritative is False,
            route.recovery_authoritative is True,
            route.authoritative_storage_changed is True,
            route.local_evidence_preserved is True,
            route.storage_write_performed is False,
            route.read_path_switched is False,
            route.write_route_mutation_performed is False,
            route.document_storage_key_mutated is False,
            route.destructive_action_performed is False,
            route.physical_disposal_authorized is False,
        )
    ):
        raise RecoveryAuthoritativeStorageOwnershipHealthConflict(
            "Phase AK authoritative-storage route drifted from exact recovery-storage authority"
        )

    try:
        authorization, approval_receipt, ai_q, ai_snapshot = _fresh_authorization(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=lease.authorization_id,
            require_unexpired=False,
            now=current,
        )
    except RecoveryAuthoritativeStorageOwnershipExecutionUnavailable as exc:
        raise RecoveryAuthoritativeStorageOwnershipHealthUnavailable(str(exc)) from exc
    except RecoveryAuthoritativeStorageOwnershipExecutionNotFound as exc:
        raise RecoveryAuthoritativeStorageOwnershipHealthNotFound(str(exc)) from exc
    except RecoveryAuthoritativeStorageOwnershipExecutionConflict as exc:
        raise RecoveryAuthoritativeStorageOwnershipHealthConflict(str(exc)) from exc

    if authorization.approved_by_id is None:
        raise RecoveryAuthoritativeStorageOwnershipHealthConflict(
            "Phase AJ approval actor is missing from Phase AK lineage"
        )
    if not all(
        (
            authorization.id == lease.authorization_id,
            authorization.authorization_hash == lease.authorization_hash,
            approval_receipt.id == lease.authorization_approval_receipt_id,
            approval_receipt.receipt_hash == lease.authorization_approval_receipt_hash,
            ai_q.id == lease.phase_ai_health_qualification_id,
            ai_q.health_qualification_hash == lease.phase_ai_health_qualification_hash,
            ai_snapshot.lease.id == lease.durable_write_ownership_lease_id,
            ai_snapshot.lease.lease_hash == lease.durable_write_ownership_lease_hash,
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
            authorization.observed_local_hash == lease.source_file_hash,
            authorization.observed_local_size_bytes == lease.source_file_size_bytes,
            authorization.observed_recovery_hash == lease.source_file_hash,
            authorization.observed_recovery_size_bytes == lease.source_file_size_bytes,
            authorization.read_route_version_at_request == lease.read_route_version_at_activation,
            authorization.experimental_write_route_version_at_request == lease.experimental_write_route_version_at_activation,
            authorization.durable_route_version_at_request == lease.durable_route_version_at_activation,
        )
    ):
        raise RecoveryAuthoritativeStorageOwnershipHealthConflict(
            "Phase AL fresh AK→AJ→AI→AH lineage or byte verification drifted"
        )

    integrity_proof_hash = _canonical_hash(
        {
            "authoritative_storage_ownership_lease_id": str(lease.id),
            "lease_hash": lease.lease_hash,
            "activation_receipt_id": str(activation.id),
            "activation_receipt_hash": activation.receipt_hash,
            "authorization_id": str(authorization.id),
            "authorization_hash": authorization.authorization_hash,
            "authorization_approval_receipt_hash": approval_receipt.receipt_hash,
            "phase_ai_health_qualification_id": str(ai_q.id),
            "phase_ai_health_qualification_hash": ai_q.health_qualification_hash,
            "durable_write_ownership_lease_id": str(ai_snapshot.lease.id),
            "durable_write_ownership_lease_hash": ai_snapshot.lease.lease_hash,
            "replica_id": str(authorization.replica_id),
            "replica_hash": authorization.replica_hash,
            "source_file_hash": lease.source_file_hash,
            "source_file_size_bytes": lease.source_file_size_bytes,
            "observed_local_hash": authorization.observed_local_hash,
            "observed_local_size_bytes": authorization.observed_local_size_bytes,
            "observed_recovery_hash": authorization.observed_recovery_hash,
            "observed_recovery_size_bytes": authorization.observed_recovery_size_bytes,
            "observed_recovery_etag": authorization.observed_recovery_etag,
            "authority_route_version": route.route_version,
            "read_route_version": authorization.read_route_version_at_request,
            "experimental_write_route_version": authorization.experimental_write_route_version_at_request,
            "durable_route_version": authorization.durable_route_version_at_request,
            "observed_authority_kind": "recovery_storage",
            "observed_ownership_transition_active": True,
            "observed_local_authoritative": False,
            "observed_recovery_authoritative": True,
            "observed_authoritative_storage_changed": True,
            "local_evidence_preserved": True,
            "physical_disposal_authorized": False,
        }
    )
    return AuthoritativeStorageOwnershipHealthSnapshot(
        lease=lease,
        activation_receipt=activation,
        authority_route=route,
        authorization=authorization,
        authorization_approval_receipt=approval_receipt,
        phase_ai_qualification=ai_q,
        phase_ai_snapshot=ai_snapshot,
        integrity_proof_hash=integrity_proof_hash,
    )


def _request_snapshot_hash(snapshot: AuthoritativeStorageOwnershipHealthSnapshot) -> str:
    lease = snapshot.lease
    a = snapshot.authorization
    return _canonical_hash(
        {
            "authoritative_storage_ownership_lease_id": str(lease.id),
            "lease_hash": lease.lease_hash,
            "activation_receipt_hash": snapshot.activation_receipt.receipt_hash,
            "authorization_hash": a.authorization_hash,
            "authorization_approval_receipt_hash": snapshot.authorization_approval_receipt.receipt_hash,
            "phase_ai_health_qualification_hash": snapshot.phase_ai_qualification.health_qualification_hash,
            "durable_write_ownership_lease_hash": snapshot.phase_ai_snapshot.lease.lease_hash,
            "replica_hash": a.replica_hash,
            "source_file_hash": lease.source_file_hash,
            "source_file_size_bytes": lease.source_file_size_bytes,
            "local_storage_key_fingerprint": lease.local_storage_key_fingerprint,
            "recovery_bucket_fingerprint": lease.recovery_bucket_fingerprint,
            "candidate_storage_key_fingerprint": lease.candidate_storage_key_fingerprint,
            "source_authority_fingerprint": lease.source_authority_fingerprint,
            "candidate_authority_fingerprint": lease.candidate_authority_fingerprint,
            "configuration_fingerprint": lease.configuration_fingerprint,
            "observed_local_hash": a.observed_local_hash,
            "observed_local_size_bytes": a.observed_local_size_bytes,
            "observed_recovery_hash": a.observed_recovery_hash,
            "observed_recovery_size_bytes": a.observed_recovery_size_bytes,
            "observed_recovery_etag": a.observed_recovery_etag,
            "authority_route_version": snapshot.authority_route.route_version,
            "read_route_version": a.read_route_version_at_request,
            "experimental_write_route_version": a.experimental_write_route_version_at_request,
            "durable_route_version": a.durable_route_version_at_request,
            "observed_authority_kind": "recovery_storage",
            "observed_ownership_transition_active": True,
            "observed_local_authoritative": False,
            "observed_recovery_authoritative": True,
            "observed_authoritative_storage_changed": True,
            "integrity_proof_hash": snapshot.integrity_proof_hash,
        }
    )


def _qualification_hash(*, request_snapshot_hash: str, requested_by_id: UUID, requested_at: datetime, review_expires_at: datetime, reason: str) -> str:
    return _canonical_hash(
        {
            "request_snapshot_hash": request_snapshot_hash,
            "requested_by_id": str(requested_by_id),
            "requested_at": _utc_iso(requested_at),
            "review_expires_at": _utc_iso(review_expires_at),
            "request_reason": reason,
            "mode": "phase_al_independent_authoritative_storage_ownership_health",
        }
    )


def _receipt_hash(q, *, phase: str, actor_id: UUID, reason: str, transitioned_at: datetime) -> str:
    return _canonical_hash(
        {
            "health_qualification_id": str(q.id),
            "authoritative_storage_ownership_lease_id": str(q.authoritative_storage_ownership_lease_id),
            "phase": phase,
            "health_state": "healthy",
            "observed_authority_kind": "recovery_storage",
            "observed_ownership_transition_active": True,
            "observed_local_authoritative": False,
            "observed_recovery_authoritative": True,
            "observed_authoritative_storage_changed": True,
            "authority_route_version": q.authority_route_version_at_request,
            "integrity_proof_hash": q.integrity_proof_hash,
            "request_snapshot_hash": q.request_snapshot_hash,
            "health_qualification_hash": q.health_qualification_hash,
            "actor_id": str(actor_id),
            "reason": reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "local_evidence_preserved": True,
            "storage_write_performed": False,
            "route_mutation_performed": False,
            "ownership_mutation_performed": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "destructive_action_performed": False,
            "physical_disposal_authorized": False,
        }
    )


def _add_receipt(db: Session, q, *, phase: str, actor_id: UUID, reason: str, now: datetime):
    receipt = EvidenceRecoveryAuthoritativeStorageOwnershipHealthReceipt(
        organization_id=q.organization_id,
        claim_id=q.claim_id,
        document_id=q.document_id,
        health_qualification_id=q.id,
        authoritative_storage_ownership_lease_id=q.authoritative_storage_ownership_lease_id,
        phase=phase,
        health_state="healthy",
        observed_authority_kind="recovery_storage",
        observed_ownership_transition_active=True,
        observed_local_authoritative=False,
        observed_recovery_authoritative=True,
        observed_authoritative_storage_changed=True,
        authority_route_version=q.authority_route_version_at_request,
        integrity_proof_hash=q.integrity_proof_hash,
        request_snapshot_hash=q.request_snapshot_hash,
        health_qualification_hash=q.health_qualification_hash,
        receipt_hash=_receipt_hash(q, phase=phase, actor_id=actor_id, reason=reason, transitioned_at=now),
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
        local_evidence_preserved=True,
        storage_write_performed=False,
        route_mutation_performed=False,
        ownership_mutation_performed=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        destructive_action_performed=False,
        physical_disposal_authorized=False,
        s3_put_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_overwrite_performed=False,
        local_move_performed=False,
        local_delete_performed=False,
    )
    db.add(receipt)
    db.flush()
    return receipt


def _forbidden_qualifiers(q) -> set[UUID]:
    return {
        q.requested_by_id,
        q.phase_ak_activated_by_id,
        q.phase_aj_requested_by_id,
        q.phase_aj_approved_by_id,
        q.phase_ai_requested_by_id,
        q.phase_ai_qualified_by_id,
        q.phase_ah_activated_by_id,
        q.phase_ag_requested_by_id,
        q.phase_ag_approved_by_id,
        q.phase_af_requested_by_id,
        q.phase_af_qualified_by_id,
        q.phase_ae_activated_by_id,
        q.phase_ad_requested_by_id,
        q.phase_ad_approved_by_id,
    }


def _matches_snapshot(q, snapshot: AuthoritativeStorageOwnershipHealthSnapshot) -> bool:
    lease = snapshot.lease
    a = snapshot.authorization
    return all(
        (
            q.authoritative_storage_ownership_lease_id == lease.id,
            q.authorization_id == lease.authorization_id,
            q.activation_receipt_id == snapshot.activation_receipt.id,
            q.phase_ai_health_qualification_id == lease.phase_ai_health_qualification_id,
            q.durable_write_ownership_lease_id == lease.durable_write_ownership_lease_id,
            q.replica_id == lease.replica_id,
            q.authorization_hash == lease.authorization_hash,
            q.authorization_approval_receipt_hash == lease.authorization_approval_receipt_hash,
            q.activation_receipt_hash == snapshot.activation_receipt.receipt_hash,
            q.activation_snapshot_hash == lease.activation_snapshot_hash,
            q.lease_hash == lease.lease_hash,
            q.phase_ai_health_qualification_hash == lease.phase_ai_health_qualification_hash,
            q.durable_write_ownership_lease_hash == lease.durable_write_ownership_lease_hash,
            q.replica_hash == lease.replica_hash,
            q.source_file_hash == lease.source_file_hash,
            q.source_file_size_bytes == lease.source_file_size_bytes,
            q.local_storage_key_fingerprint == lease.local_storage_key_fingerprint,
            q.recovery_bucket_fingerprint == lease.recovery_bucket_fingerprint,
            q.candidate_storage_key_fingerprint == lease.candidate_storage_key_fingerprint,
            q.source_authority_fingerprint == lease.source_authority_fingerprint,
            q.candidate_authority_fingerprint == lease.candidate_authority_fingerprint,
            q.configuration_fingerprint == lease.configuration_fingerprint,
            q.observed_local_hash == a.observed_local_hash,
            q.observed_local_size_bytes == a.observed_local_size_bytes,
            q.observed_recovery_hash == a.observed_recovery_hash,
            q.observed_recovery_size_bytes == a.observed_recovery_size_bytes,
            q.observed_recovery_etag == a.observed_recovery_etag,
            q.authority_route_version_at_request == snapshot.authority_route.route_version,
            q.read_route_version_at_request == a.read_route_version_at_request,
            q.experimental_write_route_version_at_request == a.experimental_write_route_version_at_request,
            q.durable_route_version_at_request == a.durable_route_version_at_request,
            q.integrity_proof_hash == snapshot.integrity_proof_hash,
            q.request_snapshot_hash == _request_snapshot_hash(snapshot),
        )
    )


def request_authoritative_storage_ownership_health_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
    requested_by_id: UUID,
    reason: str,
    now: datetime | None = None,
):
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryAuthoritativeStorageOwnershipHealthConflict("Phase AL request reason is required")
    current = _as_utc(now or _utc_now())

    existing = db.scalar(
        select(EvidenceRecoveryAuthoritativeStorageOwnershipHealthQualification)
        .where(
            EvidenceRecoveryAuthoritativeStorageOwnershipHealthQualification.organization_id == organization_id,
            EvidenceRecoveryAuthoritativeStorageOwnershipHealthQualification.claim_id == claim_id,
            EvidenceRecoveryAuthoritativeStorageOwnershipHealthQualification.document_id == document_id,
            EvidenceRecoveryAuthoritativeStorageOwnershipHealthQualification.authoritative_storage_ownership_lease_id == lease_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.requested_by_id == requested_by_id and existing.request_reason == normalized_reason:
            return existing, None, "unchanged"
        raise RecoveryAuthoritativeStorageOwnershipHealthConflict(
            "Phase AK lease already has a Phase AL health qualification artifact"
        )

    snapshot = _active_ak_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
        now=current,
    )
    a = snapshot.authorization
    if a.approved_by_id is None:
        raise RecoveryAuthoritativeStorageOwnershipHealthConflict("Phase AJ approval actor is missing")
    request_snapshot_hash = _request_snapshot_hash(snapshot)
    review_expires_at = current + AUTHORITATIVE_STORAGE_OWNERSHIP_HEALTH_REVIEW_WINDOW
    health_hash = _qualification_hash(
        request_snapshot_hash=request_snapshot_hash,
        requested_by_id=requested_by_id,
        requested_at=current,
        review_expires_at=review_expires_at,
        reason=normalized_reason,
    )
    lease = snapshot.lease
    q = EvidenceRecoveryAuthoritativeStorageOwnershipHealthQualification(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        authoritative_storage_ownership_lease_id=lease.id,
        authorization_id=lease.authorization_id,
        activation_receipt_id=snapshot.activation_receipt.id,
        phase_ai_health_qualification_id=lease.phase_ai_health_qualification_id,
        durable_write_ownership_lease_id=lease.durable_write_ownership_lease_id,
        replica_id=lease.replica_id,
        authorization_hash=lease.authorization_hash,
        authorization_approval_receipt_hash=lease.authorization_approval_receipt_hash,
        activation_receipt_hash=snapshot.activation_receipt.receipt_hash,
        activation_snapshot_hash=lease.activation_snapshot_hash,
        lease_hash=lease.lease_hash,
        phase_ai_health_qualification_hash=lease.phase_ai_health_qualification_hash,
        durable_write_ownership_lease_hash=lease.durable_write_ownership_lease_hash,
        replica_hash=lease.replica_hash,
        source_file_hash=lease.source_file_hash,
        source_file_size_bytes=lease.source_file_size_bytes,
        local_storage_key_fingerprint=lease.local_storage_key_fingerprint,
        recovery_bucket_fingerprint=lease.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=lease.candidate_storage_key_fingerprint,
        source_authority_fingerprint=lease.source_authority_fingerprint,
        candidate_authority_fingerprint=lease.candidate_authority_fingerprint,
        configuration_fingerprint=lease.configuration_fingerprint,
        observed_local_hash=a.observed_local_hash,
        observed_local_size_bytes=a.observed_local_size_bytes,
        observed_recovery_hash=a.observed_recovery_hash,
        observed_recovery_size_bytes=a.observed_recovery_size_bytes,
        observed_recovery_etag=a.observed_recovery_etag,
        authority_route_version_at_request=snapshot.authority_route.route_version,
        read_route_version_at_request=a.read_route_version_at_request,
        experimental_write_route_version_at_request=a.experimental_write_route_version_at_request,
        durable_route_version_at_request=a.durable_route_version_at_request,
        observed_authority_kind="recovery_storage",
        observed_ownership_transition_active=True,
        observed_local_authoritative=False,
        observed_recovery_authoritative=True,
        observed_authoritative_storage_changed=True,
        integrity_proof_hash=snapshot.integrity_proof_hash,
        request_snapshot_hash=request_snapshot_hash,
        health_qualification_hash=health_hash,
        health_state="healthy",
        phase_ak_activated_by_id=lease.activated_by_id,
        phase_aj_requested_by_id=a.requested_by_id,
        phase_aj_approved_by_id=a.approved_by_id,
        phase_ai_requested_by_id=a.phase_ai_requested_by_id,
        phase_ai_qualified_by_id=a.phase_ai_qualified_by_id,
        phase_ah_activated_by_id=a.phase_ah_activated_by_id,
        phase_ag_requested_by_id=a.phase_ag_requested_by_id,
        phase_ag_approved_by_id=a.phase_ag_approved_by_id,
        phase_af_requested_by_id=a.phase_af_requested_by_id,
        phase_af_qualified_by_id=a.phase_af_qualified_by_id,
        phase_ae_activated_by_id=a.phase_ae_activated_by_id,
        phase_ad_requested_by_id=a.phase_ad_requested_by_id,
        phase_ad_approved_by_id=a.phase_ad_approved_by_id,
        requested_by_id=requested_by_id,
        requested_at=current,
        review_expires_at=review_expires_at,
        request_reason=normalized_reason,
        status="pending_second_approval",
        local_evidence_preserved=True,
        storage_write_performed=False,
        route_mutation_performed=False,
        ownership_mutation_performed=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        destructive_action_performed=False,
        physical_disposal_authorized=False,
        s3_put_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_overwrite_performed=False,
        local_move_performed=False,
        local_delete_performed=False,
    )
    db.add(q)
    db.flush()
    receipt = _add_receipt(db, q, phase="requested", actor_id=requested_by_id, reason=normalized_reason, now=current)
    return q, receipt, "pending_second_approval"


def get_authoritative_storage_ownership_health_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
    for_update: bool = False,
):
    stmt = select(EvidenceRecoveryAuthoritativeStorageOwnershipHealthQualification).where(
        EvidenceRecoveryAuthoritativeStorageOwnershipHealthQualification.id == qualification_id,
        EvidenceRecoveryAuthoritativeStorageOwnershipHealthQualification.organization_id == organization_id,
        EvidenceRecoveryAuthoritativeStorageOwnershipHealthQualification.claim_id == claim_id,
        EvidenceRecoveryAuthoritativeStorageOwnershipHealthQualification.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    q = db.scalar(stmt)
    if q is None:
        raise RecoveryAuthoritativeStorageOwnershipHealthNotFound(
            "Phase AL authoritative-storage ownership health qualification not found"
        )
    return q


def list_authoritative_storage_ownership_health_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
):
    get_authoritative_storage_ownership_health_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        qualification_id=qualification_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryAuthoritativeStorageOwnershipHealthReceipt)
            .where(
                EvidenceRecoveryAuthoritativeStorageOwnershipHealthReceipt.organization_id == organization_id,
                EvidenceRecoveryAuthoritativeStorageOwnershipHealthReceipt.claim_id == claim_id,
                EvidenceRecoveryAuthoritativeStorageOwnershipHealthReceipt.document_id == document_id,
                EvidenceRecoveryAuthoritativeStorageOwnershipHealthReceipt.health_qualification_id == qualification_id,
            )
            .order_by(EvidenceRecoveryAuthoritativeStorageOwnershipHealthReceipt.transitioned_at)
        ).all()
    )


def _terminalize(db: Session, q, *, phase: str, actor_id: UUID, reason: str, now: datetime):
    q.status = phase
    q.terminal_by_id = actor_id
    q.terminal_at = now
    q.terminal_reason = reason
    if phase == "rejected":
        q.rejected_by_id = actor_id
        q.rejected_at = now
        q.rejection_reason = reason
    db.flush()
    receipt = _add_receipt(db, q, phase=phase, actor_id=actor_id, reason=reason, now=now)
    return q, receipt, phase


def qualify_authoritative_storage_ownership_health(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
    qualified_by_id: UUID,
    reason: str,
    now: datetime | None = None,
):
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryAuthoritativeStorageOwnershipHealthConflict("Phase AL qualification reason is required")
    current = _as_utc(now or _utc_now())
    q = get_authoritative_storage_ownership_health_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        qualification_id=qualification_id,
        for_update=True,
    )
    if q.status == "qualified":
        if q.qualified_by_id == qualified_by_id and q.qualification_reason == normalized_reason:
            return q, None, "unchanged"
        raise RecoveryAuthoritativeStorageOwnershipHealthConflict("Phase AL qualification is already terminal")
    if q.status != "pending_second_approval":
        raise RecoveryAuthoritativeStorageOwnershipHealthConflict("Phase AL qualification is already terminal")
    if current >= _as_utc(q.review_expires_at):
        return _terminalize(
            db,
            q,
            phase="expired",
            actor_id=qualified_by_id,
            reason="Phase AL review window expired before qualification",
            now=current,
        )
    if qualified_by_id in _forbidden_qualifiers(q):
        raise RecoveryAuthoritativeStorageOwnershipHealthConflict(
            "Phase AL qualifier must be independent from requester and material AK, AJ, AI, AH, AG, AF, AE and AD actors"
        )

    try:
        snapshot = _active_ak_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=q.authoritative_storage_ownership_lease_id,
            now=current,
        )
    except RecoveryAuthoritativeStorageOwnershipHealthUnavailable:
        raise
    except (RecoveryAuthoritativeStorageOwnershipHealthNotFound, RecoveryAuthoritativeStorageOwnershipHealthConflict) as exc:
        return _terminalize(
            db,
            q,
            phase="invalidated",
            actor_id=qualified_by_id,
            reason=f"Phase AL fresh verification failed: {exc}",
            now=current,
        )
    if not _matches_snapshot(q, snapshot):
        return _terminalize(
            db,
            q,
            phase="invalidated",
            actor_id=qualified_by_id,
            reason="Phase AL request snapshot drifted before qualification",
            now=current,
        )

    q.status = "qualified"
    q.qualified_by_id = qualified_by_id
    q.qualified_at = current
    q.qualification_reason = normalized_reason
    db.flush()
    receipt = _add_receipt(db, q, phase="qualified", actor_id=qualified_by_id, reason=normalized_reason, now=current)
    return q, receipt, "qualified"


def reject_authoritative_storage_ownership_health(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
    rejected_by_id: UUID,
    reason: str,
    now: datetime | None = None,
):
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryAuthoritativeStorageOwnershipHealthConflict("Phase AL rejection reason is required")
    current = _as_utc(now or _utc_now())
    q = get_authoritative_storage_ownership_health_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        qualification_id=qualification_id,
        for_update=True,
    )
    if q.status == "rejected":
        if q.rejected_by_id == rejected_by_id and q.rejection_reason == normalized_reason:
            return q, None, "unchanged"
        raise RecoveryAuthoritativeStorageOwnershipHealthConflict("Phase AL qualification is already terminal")
    if q.status != "pending_second_approval":
        raise RecoveryAuthoritativeStorageOwnershipHealthConflict("Phase AL qualification is already terminal")
    if current >= _as_utc(q.review_expires_at):
        return _terminalize(
            db,
            q,
            phase="expired",
            actor_id=rejected_by_id,
            reason="Phase AL review window expired before rejection",
            now=current,
        )
    if rejected_by_id == q.requested_by_id:
        raise RecoveryAuthoritativeStorageOwnershipHealthConflict(
            "Phase AL rejection requires an actor independent from the requester"
        )
    return _terminalize(
        db,
        q,
        phase="rejected",
        actor_id=rejected_by_id,
        reason=normalized_reason,
        now=current,
    )
