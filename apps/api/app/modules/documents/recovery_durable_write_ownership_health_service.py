from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_durable_write_ownership_authorization_service import (
    RecoveryDurableWriteOwnershipAuthorizationNotFound,
    get_durable_write_ownership_authorization,
)
from app.modules.documents.recovery_durable_write_ownership_execution_models import (
    EvidenceRecoveryDurableWriteOwnershipLease,
    EvidenceRecoveryDurableWriteOwnershipReceipt,
    EvidenceRecoveryDurableWriteOwnershipRoute,
)
from app.modules.documents.recovery_durable_write_ownership_execution_service import (
    RecoveryDurableWriteOwnershipExecutionConflict,
    RecoveryDurableWriteOwnershipExecutionNotFound,
    RecoveryDurableWriteOwnershipExecutionUnavailable,
    _activation_receipt,
    _approved_ag_receipt,
    _fresh_authorization_snapshot,
    _load_route,
    _route_is_exact_active,
    get_durable_write_ownership_lease,
)
from app.modules.documents.recovery_durable_write_ownership_health_models import (
    EvidenceRecoveryDurableWriteOwnershipHealthQualification,
    EvidenceRecoveryDurableWriteOwnershipHealthReceipt,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso


DURABLE_WRITE_OWNERSHIP_HEALTH_REVIEW_WINDOW = timedelta(minutes=10)


class RecoveryDurableWriteOwnershipHealthError(RuntimeError):
    pass


class RecoveryDurableWriteOwnershipHealthNotFound(RecoveryDurableWriteOwnershipHealthError):
    pass


class RecoveryDurableWriteOwnershipHealthConflict(RecoveryDurableWriteOwnershipHealthError):
    pass


class RecoveryDurableWriteOwnershipHealthUnavailable(RecoveryDurableWriteOwnershipHealthError):
    pass


@dataclass(frozen=True)
class DurableWriteOwnershipHealthSnapshot:
    lease: EvidenceRecoveryDurableWriteOwnershipLease
    activation_receipt: EvidenceRecoveryDurableWriteOwnershipReceipt
    durable_route: EvidenceRecoveryDurableWriteOwnershipRoute
    authorization: object
    approval_receipt: object
    phase_af_qualification: object
    phase_af_receipt: object
    phase_af_snapshot: object
    integrity_proof_hash: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _active_ah_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    lease_id: UUID,
) -> DurableWriteOwnershipHealthSnapshot:
    try:
        lease = get_durable_write_ownership_lease(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=lease_id,
            for_update=True,
        )
    except RecoveryDurableWriteOwnershipExecutionNotFound as exc:
        raise RecoveryDurableWriteOwnershipHealthNotFound(str(exc)) from exc

    if not all(
        (
            lease.status == "active",
            lease.durable_write_ownership_active is True,
            lease.durable_write_authority_created is True,
            lease.write_path_switched is True,
            lease.terminal_by_id is None,
            lease.terminal_at is None,
            lease.terminal_reason is None,
            lease.local_authoritative is True,
            lease.storage_write_performed is False,
            lease.read_path_switched is False,
            lease.document_storage_key_mutated is False,
            lease.authoritative_storage_changed is False,
            lease.destructive_action_performed is False,
            lease.s3_put_performed is False,
            lease.s3_copy_performed is False,
            lease.s3_delete_performed is False,
            lease.local_overwrite_performed is False,
            lease.local_move_performed is False,
            lease.local_delete_performed is False,
        )
    ):
        raise RecoveryDurableWriteOwnershipHealthConflict(
            "Phase AI requires one exact active Phase AH durable write-ownership lease"
        )

    receipts = list(
        db.scalars(
            select(EvidenceRecoveryDurableWriteOwnershipReceipt)
            .where(
                EvidenceRecoveryDurableWriteOwnershipReceipt.organization_id == organization_id,
                EvidenceRecoveryDurableWriteOwnershipReceipt.claim_id == claim_id,
                EvidenceRecoveryDurableWriteOwnershipReceipt.document_id == document_id,
                EvidenceRecoveryDurableWriteOwnershipReceipt.lease_id == lease.id,
            )
            .order_by(
                EvidenceRecoveryDurableWriteOwnershipReceipt.transitioned_at.asc(),
                EvidenceRecoveryDurableWriteOwnershipReceipt.id.asc(),
            )
        ).all()
    )
    if len(receipts) != 1 or receipts[0].phase != "activated":
        raise RecoveryDurableWriteOwnershipHealthConflict(
            "Phase AI requires exactly one Phase AH activation receipt and no terminal receipt"
        )
    try:
        activation = _activation_receipt(db, lease=lease)
    except RecoveryDurableWriteOwnershipExecutionConflict as exc:
        raise RecoveryDurableWriteOwnershipHealthConflict(str(exc)) from exc
    if not all(
        (
            activation.authorization_id == lease.authorization_id,
            activation.authorization_hash == lease.authorization_hash,
            activation.authorization_approval_receipt_hash == lease.authorization_approval_receipt_hash,
            activation.phase_af_health_qualification_hash == lease.phase_af_health_qualification_hash,
            activation.source_file_hash == lease.source_file_hash,
            activation.source_file_size_bytes == lease.source_file_size_bytes,
            activation.activation_snapshot_hash == lease.activation_snapshot_hash,
            activation.lease_hash == lease.lease_hash,
            activation.from_write_mode == "local_only",
            activation.to_write_mode == "recovery_primary",
            activation.route_version == lease.durable_route_version_after_activation,
            activation.durable_write_ownership_active is True,
            activation.durable_write_authority_created is True,
            activation.write_path_switched is True,
            activation.actor_id == lease.activated_by_id,
            _as_utc(activation.transitioned_at) == _as_utc(lease.activated_at),
            activation.local_authoritative is True,
            activation.storage_write_performed is False,
            activation.read_path_switched is False,
            activation.document_storage_key_mutated is False,
            activation.authoritative_storage_changed is False,
            activation.destructive_action_performed is False,
        )
    ):
        raise RecoveryDurableWriteOwnershipHealthConflict(
            "Phase AH activation receipt lineage is inconsistent"
        )

    durable_route = _load_route(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        for_update=True,
    )
    if durable_route is None or not _route_is_exact_active(durable_route, lease):
        raise RecoveryDurableWriteOwnershipHealthConflict(
            "Phase AH durable write route drifted from exact recovery-primary authority"
        )

    try:
        authorization = get_durable_write_ownership_authorization(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=lease.authorization_id,
        )
    except RecoveryDurableWriteOwnershipAuthorizationNotFound as exc:
        raise RecoveryDurableWriteOwnershipHealthNotFound(str(exc)) from exc
    if not all(
        (
            authorization.status == "approved",
            authorization.health_state == "healthy",
            authorization.max_execution_windows == 1,
            authorization.approved_by_id is not None,
            authorization.authorization_hash == lease.authorization_hash,
            authorization.request_snapshot_hash == lease.authorization_request_snapshot_hash,
            authorization.phase_af_health_qualification_id == lease.phase_af_health_qualification_id,
            authorization.phase_af_health_qualification_hash == lease.phase_af_health_qualification_hash,
            authorization.phase_af_health_receipt_hash == lease.phase_af_health_receipt_hash,
            authorization.transition_lease_id == lease.transition_lease_id,
            authorization.transition_lease_hash == lease.transition_lease_hash,
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
        )
    ):
        raise RecoveryDurableWriteOwnershipHealthConflict(
            "Phase AG/AH durable write lineage is inconsistent"
        )
    try:
        approval = _approved_ag_receipt(db, authorization=authorization)
        af_q, af_receipt, af_snapshot = _fresh_authorization_snapshot(db, authorization=authorization)
    except RecoveryDurableWriteOwnershipExecutionUnavailable as exc:
        raise RecoveryDurableWriteOwnershipHealthUnavailable(str(exc)) from exc
    except RecoveryDurableWriteOwnershipExecutionNotFound as exc:
        raise RecoveryDurableWriteOwnershipHealthNotFound(str(exc)) from exc
    except RecoveryDurableWriteOwnershipExecutionConflict as exc:
        raise RecoveryDurableWriteOwnershipHealthConflict(str(exc)) from exc

    if not all(
        (
            approval.id == lease.authorization_approval_receipt_id,
            approval.receipt_hash == lease.authorization_approval_receipt_hash,
            af_q.id == lease.phase_af_health_qualification_id,
            af_q.health_qualification_hash == lease.phase_af_health_qualification_hash,
            af_receipt.receipt_hash == lease.phase_af_health_receipt_hash,
            af_snapshot.lease.id == lease.transition_lease_id,
            af_snapshot.lease.lease_hash == lease.transition_lease_hash,
            af_snapshot.replica.id == lease.replica_id,
            af_snapshot.replica.replica_hash == lease.replica_hash,
            af_snapshot.observed_local_hash == lease.source_file_hash,
            af_snapshot.observed_local_size_bytes == lease.source_file_size_bytes,
            af_snapshot.observed_recovery_hash == lease.source_file_hash,
            af_snapshot.observed_recovery_size_bytes == lease.source_file_size_bytes,
            af_snapshot.read_route.route_version == lease.read_route_version_at_activation,
            af_snapshot.write_route.route_version == lease.experimental_write_route_version_at_activation,
            durable_route.route_version == lease.durable_route_version_after_activation,
        )
    ):
        raise RecoveryDurableWriteOwnershipHealthConflict(
            "Phase AI fresh lineage or byte verification drifted from Phase AH activation"
        )

    integrity_proof_hash = _canonical_hash(
        {
            "durable_write_ownership_lease_id": str(lease.id),
            "lease_hash": lease.lease_hash,
            "activation_receipt_id": str(activation.id),
            "activation_receipt_hash": activation.receipt_hash,
            "authorization_id": str(authorization.id),
            "authorization_hash": authorization.authorization_hash,
            "authorization_approval_receipt_hash": approval.receipt_hash,
            "phase_af_health_qualification_hash": af_q.health_qualification_hash,
            "phase_af_health_receipt_hash": af_receipt.receipt_hash,
            "transition_lease_hash": af_snapshot.lease.lease_hash,
            "replica_hash": af_snapshot.replica.replica_hash,
            "source_file_hash": lease.source_file_hash,
            "source_file_size_bytes": lease.source_file_size_bytes,
            "observed_local_hash": af_snapshot.observed_local_hash,
            "observed_local_size_bytes": af_snapshot.observed_local_size_bytes,
            "observed_recovery_hash": af_snapshot.observed_recovery_hash,
            "observed_recovery_size_bytes": af_snapshot.observed_recovery_size_bytes,
            "observed_recovery_etag": af_snapshot.observed_recovery_etag,
            "read_route_version": af_snapshot.read_route.route_version,
            "experimental_write_route_version": af_snapshot.write_route.route_version,
            "durable_route_version": durable_route.route_version,
            "durable_write_mode": durable_route.write_mode,
            "active_durable_write_ownership_lease_id": str(durable_route.active_durable_write_ownership_lease_id),
            "local_authoritative": True,
        }
    )
    return DurableWriteOwnershipHealthSnapshot(
        lease=lease,
        activation_receipt=activation,
        durable_route=durable_route,
        authorization=authorization,
        approval_receipt=approval,
        phase_af_qualification=af_q,
        phase_af_receipt=af_receipt,
        phase_af_snapshot=af_snapshot,
        integrity_proof_hash=integrity_proof_hash,
    )


def _request_snapshot_hash(snapshot: DurableWriteOwnershipHealthSnapshot) -> str:
    lease = snapshot.lease
    af = snapshot.phase_af_snapshot
    return _canonical_hash(
        {
            "durable_write_ownership_lease_id": str(lease.id),
            "lease_hash": lease.lease_hash,
            "activation_receipt_hash": snapshot.activation_receipt.receipt_hash,
            "authorization_hash": snapshot.authorization.authorization_hash,
            "authorization_approval_receipt_hash": snapshot.approval_receipt.receipt_hash,
            "phase_af_health_qualification_hash": snapshot.phase_af_qualification.health_qualification_hash,
            "phase_af_health_receipt_hash": snapshot.phase_af_receipt.receipt_hash,
            "transition_lease_hash": af.lease.lease_hash,
            "replica_hash": af.replica.replica_hash,
            "source_file_hash": lease.source_file_hash,
            "source_file_size_bytes": lease.source_file_size_bytes,
            "local_storage_key_fingerprint": lease.local_storage_key_fingerprint,
            "recovery_bucket_fingerprint": lease.recovery_bucket_fingerprint,
            "candidate_storage_key_fingerprint": lease.candidate_storage_key_fingerprint,
            "source_authority_fingerprint": lease.source_authority_fingerprint,
            "candidate_authority_fingerprint": lease.candidate_authority_fingerprint,
            "configuration_fingerprint": lease.configuration_fingerprint,
            "observed_local_hash": af.observed_local_hash,
            "observed_local_size_bytes": af.observed_local_size_bytes,
            "observed_recovery_hash": af.observed_recovery_hash,
            "observed_recovery_size_bytes": af.observed_recovery_size_bytes,
            "observed_recovery_etag": af.observed_recovery_etag,
            "read_route_version": af.read_route.route_version,
            "experimental_write_route_version": af.write_route.route_version,
            "durable_route_version": snapshot.durable_route.route_version,
            "observed_durable_write_mode": "recovery_primary",
            "observed_durable_write_ownership_active": True,
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
            "mode": "phase_ai_independent_durable_write_ownership_health",
        }
    )


def _receipt_hash(q, *, phase: str, actor_id: UUID, reason: str, transitioned_at: datetime) -> str:
    return _canonical_hash(
        {
            "health_qualification_id": str(q.id),
            "durable_write_ownership_lease_id": str(q.durable_write_ownership_lease_id),
            "phase": phase,
            "health_state": "healthy",
            "observed_durable_write_mode": "recovery_primary",
            "observed_durable_write_ownership_active": True,
            "durable_route_version": q.durable_route_version_at_request,
            "integrity_proof_hash": q.integrity_proof_hash,
            "request_snapshot_hash": q.request_snapshot_hash,
            "health_qualification_hash": q.health_qualification_hash,
            "actor_id": str(actor_id),
            "reason": reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "local_authoritative": True,
            "storage_write_performed": False,
            "route_mutation_performed": False,
            "durable_write_authority_created": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
        }
    )


def _add_receipt(db: Session, q, *, phase: str, actor_id: UUID, reason: str, now: datetime):
    receipt = EvidenceRecoveryDurableWriteOwnershipHealthReceipt(
        organization_id=q.organization_id,
        claim_id=q.claim_id,
        document_id=q.document_id,
        health_qualification_id=q.id,
        durable_write_ownership_lease_id=q.durable_write_ownership_lease_id,
        phase=phase,
        health_state="healthy",
        observed_durable_write_mode="recovery_primary",
        observed_durable_write_ownership_active=True,
        durable_route_version=q.durable_route_version_at_request,
        integrity_proof_hash=q.integrity_proof_hash,
        request_snapshot_hash=q.request_snapshot_hash,
        health_qualification_hash=q.health_qualification_hash,
        receipt_hash=_receipt_hash(q, phase=phase, actor_id=actor_id, reason=reason, transitioned_at=now),
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
        local_authoritative=True,
        storage_write_performed=False,
        route_mutation_performed=False,
        durable_write_authority_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
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


def _matches_snapshot(q, snapshot: DurableWriteOwnershipHealthSnapshot) -> bool:
    lease = snapshot.lease
    af = snapshot.phase_af_snapshot
    return all(
        (
            q.durable_write_ownership_lease_id == lease.id,
            q.authorization_id == lease.authorization_id,
            q.authorization_approval_receipt_id == lease.authorization_approval_receipt_id,
            q.phase_af_health_qualification_id == lease.phase_af_health_qualification_id,
            q.transition_lease_id == lease.transition_lease_id,
            q.replica_id == lease.replica_id,
            q.activation_receipt_id == snapshot.activation_receipt.id,
            q.authorization_hash == lease.authorization_hash,
            q.authorization_approval_receipt_hash == lease.authorization_approval_receipt_hash,
            q.phase_af_health_qualification_hash == lease.phase_af_health_qualification_hash,
            q.phase_af_health_receipt_hash == lease.phase_af_health_receipt_hash,
            q.transition_lease_hash == lease.transition_lease_hash,
            q.replica_hash == lease.replica_hash,
            q.activation_receipt_hash == snapshot.activation_receipt.receipt_hash,
            q.activation_snapshot_hash == lease.activation_snapshot_hash,
            q.lease_hash == lease.lease_hash,
            q.source_file_hash == lease.source_file_hash,
            q.source_file_size_bytes == lease.source_file_size_bytes,
            q.local_storage_key_fingerprint == lease.local_storage_key_fingerprint,
            q.recovery_bucket_fingerprint == lease.recovery_bucket_fingerprint,
            q.candidate_storage_key_fingerprint == lease.candidate_storage_key_fingerprint,
            q.source_authority_fingerprint == lease.source_authority_fingerprint,
            q.candidate_authority_fingerprint == lease.candidate_authority_fingerprint,
            q.configuration_fingerprint == lease.configuration_fingerprint,
            q.observed_local_hash == af.observed_local_hash,
            q.observed_local_size_bytes == af.observed_local_size_bytes,
            q.observed_recovery_hash == af.observed_recovery_hash,
            q.observed_recovery_size_bytes == af.observed_recovery_size_bytes,
            q.observed_recovery_etag == af.observed_recovery_etag,
            q.read_route_version_at_request == af.read_route.route_version,
            q.experimental_write_route_version_at_request == af.write_route.route_version,
            q.durable_route_version_at_request == snapshot.durable_route.route_version,
            q.integrity_proof_hash == snapshot.integrity_proof_hash,
            q.request_snapshot_hash == _request_snapshot_hash(snapshot),
            q.observed_durable_write_mode == "recovery_primary",
            q.observed_durable_write_ownership_active is True,
        )
    )


def _forbidden_reviewers(q) -> set[UUID]:
    return {
        q.requested_by_id,
        q.phase_ah_activated_by_id,
        q.phase_ag_requested_by_id,
        q.phase_ag_approved_by_id,
        q.phase_af_requested_by_id,
        q.phase_af_qualified_by_id,
        q.phase_ae_activated_by_id,
        q.phase_ad_requested_by_id,
        q.phase_ad_approved_by_id,
        q.phase_ac_qualified_by_id,
        q.phase_ab_activated_by_id,
        q.phase_aa_requested_by_id,
        q.phase_aa_approved_by_id,
        q.phase_z_qualified_by_id,
        q.phase_y_executed_by_id,
        q.phase_x_approved_by_id,
    }


def request_durable_write_ownership_health_qualification(
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
        raise RecoveryDurableWriteOwnershipHealthConflict("Phase AI request reason is required")
    current = _as_utc(now or _utc_now())
    snapshot = _active_ah_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        lease_id=lease_id,
    )
    existing = db.scalar(
        select(EvidenceRecoveryDurableWriteOwnershipHealthQualification)
        .where(
            EvidenceRecoveryDurableWriteOwnershipHealthQualification.organization_id == organization_id,
            EvidenceRecoveryDurableWriteOwnershipHealthQualification.claim_id == claim_id,
            EvidenceRecoveryDurableWriteOwnershipHealthQualification.document_id == document_id,
            EvidenceRecoveryDurableWriteOwnershipHealthQualification.durable_write_ownership_lease_id == lease_id,
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
        raise RecoveryDurableWriteOwnershipHealthConflict(
            "Phase AI health qualification already exists for this Phase AH lease"
        )

    lease = snapshot.lease
    authorization = snapshot.authorization
    af = snapshot.phase_af_snapshot
    request_hash = _request_snapshot_hash(snapshot)
    review_expires_at = current + DURABLE_WRITE_OWNERSHIP_HEALTH_REVIEW_WINDOW
    health_hash = _qualification_hash(
        request_snapshot_hash=request_hash,
        requested_by_id=requested_by_id,
        requested_at=current,
        review_expires_at=review_expires_at,
        reason=normalized_reason,
    )
    q = EvidenceRecoveryDurableWriteOwnershipHealthQualification(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        durable_write_ownership_lease_id=lease.id,
        authorization_id=lease.authorization_id,
        authorization_approval_receipt_id=lease.authorization_approval_receipt_id,
        phase_af_health_qualification_id=lease.phase_af_health_qualification_id,
        transition_lease_id=lease.transition_lease_id,
        replica_id=lease.replica_id,
        activation_receipt_id=snapshot.activation_receipt.id,
        authorization_hash=lease.authorization_hash,
        authorization_approval_receipt_hash=lease.authorization_approval_receipt_hash,
        phase_af_health_qualification_hash=lease.phase_af_health_qualification_hash,
        phase_af_health_receipt_hash=lease.phase_af_health_receipt_hash,
        transition_lease_hash=lease.transition_lease_hash,
        replica_hash=lease.replica_hash,
        activation_receipt_hash=snapshot.activation_receipt.receipt_hash,
        activation_snapshot_hash=lease.activation_snapshot_hash,
        lease_hash=lease.lease_hash,
        source_file_hash=lease.source_file_hash,
        source_file_size_bytes=lease.source_file_size_bytes,
        local_storage_key_fingerprint=lease.local_storage_key_fingerprint,
        recovery_bucket_fingerprint=lease.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=lease.candidate_storage_key_fingerprint,
        source_authority_fingerprint=lease.source_authority_fingerprint,
        candidate_authority_fingerprint=lease.candidate_authority_fingerprint,
        configuration_fingerprint=lease.configuration_fingerprint,
        observed_local_hash=af.observed_local_hash,
        observed_local_size_bytes=af.observed_local_size_bytes,
        observed_recovery_hash=af.observed_recovery_hash,
        observed_recovery_size_bytes=af.observed_recovery_size_bytes,
        observed_recovery_etag=af.observed_recovery_etag,
        read_route_version_at_request=af.read_route.route_version,
        experimental_write_route_version_at_request=af.write_route.route_version,
        durable_route_version_at_request=snapshot.durable_route.route_version,
        observed_durable_write_mode="recovery_primary",
        observed_durable_write_ownership_active=True,
        integrity_proof_hash=snapshot.integrity_proof_hash,
        request_snapshot_hash=request_hash,
        health_qualification_hash=health_hash,
        health_state="healthy",
        phase_ah_activated_by_id=lease.activated_by_id,
        phase_ag_requested_by_id=authorization.requested_by_id,
        phase_ag_approved_by_id=authorization.approved_by_id,
        phase_af_requested_by_id=authorization.phase_af_requested_by_id,
        phase_af_qualified_by_id=authorization.phase_af_qualified_by_id,
        phase_ae_activated_by_id=authorization.phase_ae_activated_by_id,
        phase_ad_requested_by_id=authorization.phase_ad_requested_by_id,
        phase_ad_approved_by_id=authorization.phase_ad_approved_by_id,
        phase_ac_qualified_by_id=authorization.phase_ac_qualified_by_id,
        phase_ab_activated_by_id=authorization.phase_ab_activated_by_id,
        phase_aa_requested_by_id=authorization.phase_aa_requested_by_id,
        phase_aa_approved_by_id=authorization.phase_aa_approved_by_id,
        phase_z_qualified_by_id=authorization.phase_z_qualified_by_id,
        phase_y_executed_by_id=authorization.phase_y_executed_by_id,
        phase_x_approved_by_id=authorization.phase_x_approved_by_id,
        requested_by_id=requested_by_id,
        requested_at=current,
        review_expires_at=review_expires_at,
        request_reason=normalized_reason,
        status="pending_second_approval",
        local_authoritative=True,
        storage_write_performed=False,
        route_mutation_performed=False,
        durable_write_authority_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
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


def get_durable_write_ownership_health_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
    for_update: bool = False,
):
    stmt = select(EvidenceRecoveryDurableWriteOwnershipHealthQualification).where(
        EvidenceRecoveryDurableWriteOwnershipHealthQualification.id == qualification_id,
        EvidenceRecoveryDurableWriteOwnershipHealthQualification.organization_id == organization_id,
        EvidenceRecoveryDurableWriteOwnershipHealthQualification.claim_id == claim_id,
        EvidenceRecoveryDurableWriteOwnershipHealthQualification.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    q = db.scalar(stmt)
    if q is None:
        raise RecoveryDurableWriteOwnershipHealthNotFound(
            "Phase AI durable write-ownership health qualification not found"
        )
    return q


def _terminalize(db: Session, q, *, phase: str, actor_id: UUID, reason: str, now: datetime):
    q.status = phase
    q.terminal_by_id = actor_id
    q.terminal_at = now
    q.terminal_reason = reason
    db.flush()
    return _add_receipt(db, q, phase=phase, actor_id=actor_id, reason=reason, now=now)


def qualify_durable_write_ownership_health(
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
        raise RecoveryDurableWriteOwnershipHealthConflict("Phase AI qualification reason is required")
    current = _as_utc(now or _utc_now())
    q = get_durable_write_ownership_health_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        qualification_id=qualification_id,
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
            reason="Phase AI independent review window expired",
            now=current,
        )
        return q, receipt, "expired"
    if qualified_by_id in _forbidden_reviewers(q):
        raise RecoveryDurableWriteOwnershipHealthConflict(
            "Phase AI qualifier must be independent from requester, AH/AG/AF/AE actors and upstream governance actors"
        )
    try:
        snapshot = _active_ah_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            lease_id=q.durable_write_ownership_lease_id,
        )
    except RecoveryDurableWriteOwnershipHealthUnavailable:
        raise
    except (RecoveryDurableWriteOwnershipHealthNotFound, RecoveryDurableWriteOwnershipHealthConflict) as exc:
        receipt = _terminalize(
            db,
            q,
            phase="invalidated",
            actor_id=qualified_by_id,
            reason=f"Phase AI fresh verification invalidated: {exc}",
            now=current,
        )
        return q, receipt, "invalidated"
    if not _matches_snapshot(q, snapshot):
        receipt = _terminalize(
            db,
            q,
            phase="invalidated",
            actor_id=qualified_by_id,
            reason="Phase AI request snapshot drifted before independent qualification",
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


def reject_durable_write_ownership_health(
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
        raise RecoveryDurableWriteOwnershipHealthConflict("Phase AI rejection reason is required")
    current = _as_utc(now or _utc_now())
    q = get_durable_write_ownership_health_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        qualification_id=qualification_id,
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
            reason="Phase AI independent review window expired",
            now=current,
        )
        return q, receipt, "expired"
    if rejected_by_id in _forbidden_reviewers(q):
        raise RecoveryDurableWriteOwnershipHealthConflict(
            "Phase AI reviewer must be independent from requester, AH/AG/AF/AE actors and upstream governance actors"
        )
    q.status = "rejected"
    q.rejected_by_id = rejected_by_id
    q.rejected_at = current
    q.rejection_reason = normalized_reason
    db.flush()
    receipt = _add_receipt(db, q, phase="rejected", actor_id=rejected_by_id, reason=normalized_reason, now=current)
    return q, receipt, "rejected"


def list_durable_write_ownership_health_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
):
    get_durable_write_ownership_health_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        qualification_id=qualification_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryDurableWriteOwnershipHealthReceipt)
            .where(
                EvidenceRecoveryDurableWriteOwnershipHealthReceipt.organization_id == organization_id,
                EvidenceRecoveryDurableWriteOwnershipHealthReceipt.claim_id == claim_id,
                EvidenceRecoveryDurableWriteOwnershipHealthReceipt.document_id == document_id,
                EvidenceRecoveryDurableWriteOwnershipHealthReceipt.health_qualification_id == qualification_id,
            )
            .order_by(
                EvidenceRecoveryDurableWriteOwnershipHealthReceipt.transitioned_at.asc(),
                EvidenceRecoveryDurableWriteOwnershipHealthReceipt.id.asc(),
            )
        ).all()
    )
