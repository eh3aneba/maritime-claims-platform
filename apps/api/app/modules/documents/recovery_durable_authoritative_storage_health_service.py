from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.recovery_authoritative_storage_ownership_execution_service import (
    RecoveryAuthoritativeStorageOwnershipExecutionConflict,
    RecoveryAuthoritativeStorageOwnershipExecutionNotFound,
    RecoveryAuthoritativeStorageOwnershipExecutionUnavailable,
    _fresh_authorization,
    get_authoritative_storage_ownership_route,
)
from app.modules.documents.recovery_authoritative_storage_ratification_authorization_service import (
    RecoveryAuthoritativeStorageRatificationAuthorizationNotFound,
    get_authoritative_storage_ratification_authorization,
)
from app.modules.documents.recovery_authoritative_storage_ratification_execution_models import (
    EvidenceRecoveryAuthoritativeStorageRatificationReceipt,
)
from app.modules.documents.recovery_authoritative_storage_ratification_execution_service import (
    RecoveryAuthoritativeStorageRatificationExecutionNotFound,
    _approved_am_receipt,
    get_authoritative_storage_ratification,
)
from app.modules.documents.recovery_durable_authoritative_storage_health_models import (
    EvidenceRecoveryDurableAuthoritativeStorageHealthQualification,
    EvidenceRecoveryDurableAuthoritativeStorageHealthReceipt,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso


DURABLE_AUTHORITATIVE_STORAGE_HEALTH_REVIEW_WINDOW = timedelta(minutes=10)


class RecoveryDurableAuthoritativeStorageHealthError(RuntimeError):
    pass


class RecoveryDurableAuthoritativeStorageHealthNotFound(RecoveryDurableAuthoritativeStorageHealthError):
    pass


class RecoveryDurableAuthoritativeStorageHealthConflict(RecoveryDurableAuthoritativeStorageHealthError):
    pass


class RecoveryDurableAuthoritativeStorageHealthUnavailable(RecoveryDurableAuthoritativeStorageHealthError):
    pass


@dataclass(frozen=True)
class DurableAuthoritativeStorageHealthSnapshot:
    ratification: object
    ratification_receipt: EvidenceRecoveryAuthoritativeStorageRatificationReceipt
    authority_route: object
    phase_am_authorization: object
    phase_am_approval_receipt: object
    phase_aj_authorization: object
    phase_ai_qualification: object
    phase_ai_snapshot: object
    integrity_proof_hash: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _ratification_receipt(db: Session, ratification) -> EvidenceRecoveryAuthoritativeStorageRatificationReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryAuthoritativeStorageRatificationReceipt).where(
                EvidenceRecoveryAuthoritativeStorageRatificationReceipt.organization_id == ratification.organization_id,
                EvidenceRecoveryAuthoritativeStorageRatificationReceipt.claim_id == ratification.claim_id,
                EvidenceRecoveryAuthoritativeStorageRatificationReceipt.document_id == ratification.document_id,
                EvidenceRecoveryAuthoritativeStorageRatificationReceipt.ratification_id == ratification.id,
            )
        ).all()
    )
    if len(receipts) != 1 or receipts[0].phase != "ratified":
        raise RecoveryDurableAuthoritativeStorageHealthConflict(
            "Phase AO requires exactly one immutable Phase AN ratified receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            receipt.authorization_id == ratification.authorization_id,
            receipt.authorization_hash == ratification.authorization_hash,
            receipt.authorization_approval_receipt_hash == ratification.authorization_approval_receipt_hash,
            receipt.phase_al_health_qualification_hash == ratification.phase_al_health_qualification_hash,
            receipt.source_file_hash == ratification.source_file_hash,
            receipt.source_file_size_bytes == ratification.source_file_size_bytes,
            receipt.execution_snapshot_hash == ratification.execution_snapshot_hash,
            receipt.ratification_hash == ratification.ratification_hash,
            receipt.route_version == ratification.authority_route_version_after_ratification,
            receipt.from_authority_kind == "recovery_storage",
            receipt.to_authority_kind == "recovery_storage",
            receipt.from_authority_tenure == "bounded_recovery",
            receipt.to_authority_tenure == "durable_recovery",
            receipt.ratification_active is True,
            receipt.durable_authority_created is True,
            receipt.local_authoritative is False,
            receipt.recovery_authoritative is True,
            receipt.authoritative_storage_changed is True,
            receipt.local_evidence_preserved is True,
            receipt.storage_write_performed is False,
            receipt.route_mutation_performed is True,
            receipt.ownership_mutation_performed is True,
            receipt.read_path_switched is False,
            receipt.write_path_switched is False,
            receipt.document_storage_key_mutated is False,
            receipt.destructive_action_performed is False,
            receipt.physical_disposal_authorized is False,
            receipt.s3_put_performed is False,
            receipt.s3_copy_performed is False,
            receipt.s3_delete_performed is False,
            receipt.local_overwrite_performed is False,
            receipt.local_move_performed is False,
            receipt.local_delete_performed is False,
        )
    ):
        raise RecoveryDurableAuthoritativeStorageHealthConflict(
            "Phase AN ratified receipt lineage is inconsistent"
        )
    return receipt


def _durable_an_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    ratification_id: UUID,
    now: datetime | None = None,
) -> DurableAuthoritativeStorageHealthSnapshot:
    current = _as_utc(now or _utc_now())
    try:
        r = get_authoritative_storage_ratification(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            ratification_id=ratification_id,
            for_update=True,
        )
    except RecoveryAuthoritativeStorageRatificationExecutionNotFound as exc:
        raise RecoveryDurableAuthoritativeStorageHealthNotFound(str(exc)) from exc

    if not all(
        (
            r.status == "ratified",
            r.authority_kind == "recovery_storage",
            r.authority_tenure == "durable_recovery",
            r.ratification_active is True,
            r.durable_authority_created is True,
            r.local_authoritative is False,
            r.recovery_authoritative is True,
            r.authoritative_storage_changed is True,
            r.local_evidence_preserved is True,
            r.storage_write_performed is False,
            r.route_mutation_performed is True,
            r.ownership_mutation_performed is True,
            r.read_path_switched is False,
            r.write_path_switched is False,
            r.document_storage_key_mutated is False,
            r.destructive_action_performed is False,
            r.physical_disposal_authorized is False,
            r.s3_put_performed is False,
            r.s3_copy_performed is False,
            r.s3_delete_performed is False,
            r.local_overwrite_performed is False,
            r.local_move_performed is False,
            r.local_delete_performed is False,
            r.observed_local_hash == r.source_file_hash,
            r.observed_local_size_bytes == r.source_file_size_bytes,
            r.observed_recovery_hash == r.source_file_hash,
            r.observed_recovery_size_bytes == r.source_file_size_bytes,
        )
    ):
        raise RecoveryDurableAuthoritativeStorageHealthConflict(
            "Phase AO requires one exact active durable Phase AN ratification"
        )

    receipt = _ratification_receipt(db, r)
    try:
        route = get_authoritative_storage_ownership_route(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
    except RecoveryAuthoritativeStorageOwnershipExecutionNotFound as exc:
        raise RecoveryDurableAuthoritativeStorageHealthNotFound(str(exc)) from exc
    if not all(
        (
            route.authority_kind == "recovery_storage",
            route.authority_tenure == "durable_recovery",
            route.active_authority_lease_id is None,
            route.durable_ratification_id == r.id,
            route.route_version == r.authority_route_version_after_ratification,
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
            route.s3_put_performed is False,
            route.s3_copy_performed is False,
            route.s3_delete_performed is False,
            route.local_overwrite_performed is False,
            route.local_move_performed is False,
            route.local_delete_performed is False,
        )
    ):
        raise RecoveryDurableAuthoritativeStorageHealthConflict(
            "Phase AO durable authoritative-storage route drifted from Phase AN ratification"
        )

    try:
        am = get_authoritative_storage_ratification_authorization(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=r.authorization_id,
            for_update=True,
        )
    except RecoveryAuthoritativeStorageRatificationAuthorizationNotFound as exc:
        raise RecoveryDurableAuthoritativeStorageHealthNotFound(str(exc)) from exc
    if not all(
        (
            am.status == "approved",
            am.health_state == "healthy",
            am.ratification_authorized is True,
            am.max_execution_windows == 1,
            am.approved_by_id is not None,
            am.authorization_hash == r.authorization_hash,
            am.phase_al_health_qualification_id == r.phase_al_health_qualification_id,
            am.phase_al_health_qualification_hash == r.phase_al_health_qualification_hash,
            am.phase_al_health_receipt_hash == r.phase_al_health_receipt_hash,
            am.phase_al_integrity_proof_hash == r.phase_al_integrity_proof_hash,
            am.authoritative_storage_ownership_lease_id == r.authoritative_storage_ownership_lease_id,
            am.authoritative_storage_ownership_lease_hash == r.authoritative_storage_ownership_lease_hash,
            am.phase_aj_authorization_id == r.phase_aj_authorization_id,
            am.phase_aj_authorization_hash == r.phase_aj_authorization_hash,
            am.phase_ai_health_qualification_id == r.phase_ai_health_qualification_id,
            am.phase_ai_health_qualification_hash == r.phase_ai_health_qualification_hash,
            am.durable_write_ownership_lease_id == r.durable_write_ownership_lease_id,
            am.durable_write_ownership_lease_hash == r.durable_write_ownership_lease_hash,
            am.replica_id == r.replica_id,
            am.replica_hash == r.replica_hash,
            am.source_file_hash == r.source_file_hash,
            am.source_file_size_bytes == r.source_file_size_bytes,
            am.local_storage_key_fingerprint == r.local_storage_key_fingerprint,
            am.recovery_bucket_fingerprint == r.recovery_bucket_fingerprint,
            am.candidate_storage_key_fingerprint == r.candidate_storage_key_fingerprint,
            am.source_authority_fingerprint == r.source_authority_fingerprint,
            am.candidate_authority_fingerprint == r.candidate_authority_fingerprint,
            am.configuration_fingerprint == r.configuration_fingerprint,
        )
    ):
        raise RecoveryDurableAuthoritativeStorageHealthConflict(
            "Phase AO AM→AL→AK ratification lineage drifted"
        )
    try:
        am_approval = _approved_am_receipt(db, authorization=am)
    except Exception as exc:
        raise RecoveryDurableAuthoritativeStorageHealthConflict(str(exc)) from exc
    if am_approval.id != r.authorization_approval_receipt_id or am_approval.receipt_hash != r.authorization_approval_receipt_hash:
        raise RecoveryDurableAuthoritativeStorageHealthConflict(
            "Phase AO Phase AM approval receipt drifted from Phase AN ratification"
        )

    try:
        aj, _aj_approval, ai_q, ai_snapshot = _fresh_authorization(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=r.phase_aj_authorization_id,
            require_unexpired=False,
            now=current,
        )
    except RecoveryAuthoritativeStorageOwnershipExecutionUnavailable as exc:
        raise RecoveryDurableAuthoritativeStorageHealthUnavailable(str(exc)) from exc
    except RecoveryAuthoritativeStorageOwnershipExecutionNotFound as exc:
        raise RecoveryDurableAuthoritativeStorageHealthNotFound(str(exc)) from exc
    except RecoveryAuthoritativeStorageOwnershipExecutionConflict as exc:
        raise RecoveryDurableAuthoritativeStorageHealthConflict(str(exc)) from exc

    if not all(
        (
            aj.authorization_hash == r.phase_aj_authorization_hash,
            ai_q.id == r.phase_ai_health_qualification_id,
            ai_q.health_qualification_hash == r.phase_ai_health_qualification_hash,
            ai_snapshot.lease.id == r.durable_write_ownership_lease_id,
            ai_snapshot.lease.lease_hash == r.durable_write_ownership_lease_hash,
            aj.replica_id == r.replica_id,
            aj.replica_hash == r.replica_hash,
            aj.source_file_hash == r.source_file_hash,
            aj.source_file_size_bytes == r.source_file_size_bytes,
            aj.local_storage_key_fingerprint == r.local_storage_key_fingerprint,
            aj.recovery_bucket_fingerprint == r.recovery_bucket_fingerprint,
            aj.candidate_storage_key_fingerprint == r.candidate_storage_key_fingerprint,
            aj.source_authority_fingerprint == r.source_authority_fingerprint,
            aj.candidate_authority_fingerprint == r.candidate_authority_fingerprint,
            aj.configuration_fingerprint == r.configuration_fingerprint,
            aj.observed_local_hash == r.source_file_hash,
            aj.observed_local_size_bytes == r.source_file_size_bytes,
            aj.observed_recovery_hash == r.source_file_hash,
            aj.observed_recovery_size_bytes == r.source_file_size_bytes,
            aj.read_route_version_at_request == r.read_route_version_at_ratification,
            aj.experimental_write_route_version_at_request == r.experimental_write_route_version_at_ratification,
            aj.durable_route_version_at_request == r.durable_route_version_at_ratification,
        )
    ):
        raise RecoveryDurableAuthoritativeStorageHealthConflict(
            "Phase AO fresh AJ→AI→AH lineage or source-byte verification drifted"
        )

    integrity_proof_hash = _canonical_hash(
        {
            "ratification_id": str(r.id),
            "ratification_hash": r.ratification_hash,
            "ratification_receipt_id": str(receipt.id),
            "ratification_receipt_hash": receipt.receipt_hash,
            "phase_am_authorization_id": str(am.id),
            "phase_am_authorization_hash": am.authorization_hash,
            "phase_am_approval_receipt_hash": am_approval.receipt_hash,
            "phase_al_health_qualification_id": str(r.phase_al_health_qualification_id),
            "phase_al_health_qualification_hash": r.phase_al_health_qualification_hash,
            "phase_al_health_receipt_hash": r.phase_al_health_receipt_hash,
            "phase_al_integrity_proof_hash": r.phase_al_integrity_proof_hash,
            "authoritative_storage_ownership_lease_id": str(r.authoritative_storage_ownership_lease_id),
            "authoritative_storage_ownership_lease_hash": r.authoritative_storage_ownership_lease_hash,
            "phase_aj_authorization_id": str(aj.id),
            "phase_aj_authorization_hash": aj.authorization_hash,
            "phase_ai_health_qualification_id": str(ai_q.id),
            "phase_ai_health_qualification_hash": ai_q.health_qualification_hash,
            "durable_write_ownership_lease_id": str(ai_snapshot.lease.id),
            "durable_write_ownership_lease_hash": ai_snapshot.lease.lease_hash,
            "replica_id": str(r.replica_id),
            "replica_hash": r.replica_hash,
            "source_file_hash": r.source_file_hash,
            "source_file_size_bytes": r.source_file_size_bytes,
            "observed_local_hash": aj.observed_local_hash,
            "observed_local_size_bytes": aj.observed_local_size_bytes,
            "observed_recovery_hash": aj.observed_recovery_hash,
            "observed_recovery_size_bytes": aj.observed_recovery_size_bytes,
            "observed_recovery_etag": aj.observed_recovery_etag,
            "authority_route_version": route.route_version,
            "read_route_version": aj.read_route_version_at_request,
            "experimental_write_route_version": aj.experimental_write_route_version_at_request,
            "durable_route_version": aj.durable_route_version_at_request,
            "observed_authority_kind": "recovery_storage",
            "observed_authority_tenure": "durable_recovery",
            "observed_ratification_active": True,
            "observed_durable_authority_created": True,
            "observed_local_authoritative": False,
            "observed_recovery_authoritative": True,
            "observed_authoritative_storage_changed": True,
            "local_evidence_preserved": True,
            "physical_disposal_authorized": False,
        }
    )
    return DurableAuthoritativeStorageHealthSnapshot(
        ratification=r,
        ratification_receipt=receipt,
        authority_route=route,
        phase_am_authorization=am,
        phase_am_approval_receipt=am_approval,
        phase_aj_authorization=aj,
        phase_ai_qualification=ai_q,
        phase_ai_snapshot=ai_snapshot,
        integrity_proof_hash=integrity_proof_hash,
    )


def _request_snapshot_hash(snapshot: DurableAuthoritativeStorageHealthSnapshot) -> str:
    r = snapshot.ratification
    aj = snapshot.phase_aj_authorization
    return _canonical_hash(
        {
            "ratification_id": str(r.id),
            "ratification_hash": r.ratification_hash,
            "ratification_receipt_hash": snapshot.ratification_receipt.receipt_hash,
            "phase_am_authorization_hash": snapshot.phase_am_authorization.authorization_hash,
            "phase_am_approval_receipt_hash": snapshot.phase_am_approval_receipt.receipt_hash,
            "phase_al_health_qualification_hash": r.phase_al_health_qualification_hash,
            "phase_al_health_receipt_hash": r.phase_al_health_receipt_hash,
            "phase_al_integrity_proof_hash": r.phase_al_integrity_proof_hash,
            "authoritative_storage_ownership_lease_hash": r.authoritative_storage_ownership_lease_hash,
            "phase_aj_authorization_hash": aj.authorization_hash,
            "phase_ai_health_qualification_hash": snapshot.phase_ai_qualification.health_qualification_hash,
            "durable_write_ownership_lease_hash": snapshot.phase_ai_snapshot.lease.lease_hash,
            "replica_hash": r.replica_hash,
            "source_file_hash": r.source_file_hash,
            "source_file_size_bytes": r.source_file_size_bytes,
            "local_storage_key_fingerprint": r.local_storage_key_fingerprint,
            "recovery_bucket_fingerprint": r.recovery_bucket_fingerprint,
            "candidate_storage_key_fingerprint": r.candidate_storage_key_fingerprint,
            "source_authority_fingerprint": r.source_authority_fingerprint,
            "candidate_authority_fingerprint": r.candidate_authority_fingerprint,
            "configuration_fingerprint": r.configuration_fingerprint,
            "observed_local_hash": aj.observed_local_hash,
            "observed_local_size_bytes": aj.observed_local_size_bytes,
            "observed_recovery_hash": aj.observed_recovery_hash,
            "observed_recovery_size_bytes": aj.observed_recovery_size_bytes,
            "observed_recovery_etag": aj.observed_recovery_etag,
            "authority_route_version": snapshot.authority_route.route_version,
            "read_route_version": aj.read_route_version_at_request,
            "experimental_write_route_version": aj.experimental_write_route_version_at_request,
            "durable_route_version": aj.durable_route_version_at_request,
            "observed_authority_kind": "recovery_storage",
            "observed_authority_tenure": "durable_recovery",
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
            "mode": "phase_ao_independent_durable_authoritative_storage_health",
        }
    )


def _receipt_hash(q, *, phase: str, actor_id: UUID, reason: str, transitioned_at: datetime) -> str:
    return _canonical_hash(
        {
            "health_qualification_id": str(q.id),
            "ratification_id": str(q.ratification_id),
            "phase": phase,
            "health_state": "healthy",
            "observed_authority_kind": "recovery_storage",
            "observed_authority_tenure": "durable_recovery",
            "observed_ratification_active": True,
            "observed_durable_authority_created": True,
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
    receipt = EvidenceRecoveryDurableAuthoritativeStorageHealthReceipt(
        organization_id=q.organization_id,
        claim_id=q.claim_id,
        document_id=q.document_id,
        health_qualification_id=q.id,
        ratification_id=q.ratification_id,
        phase=phase,
        health_state="healthy",
        observed_authority_kind="recovery_storage",
        observed_authority_tenure="durable_recovery",
        observed_ratification_active=True,
        observed_durable_authority_created=True,
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
        q.phase_an_executed_by_id,
        q.phase_am_requested_by_id,
        q.phase_am_approved_by_id,
        q.phase_al_requested_by_id,
        q.phase_al_qualified_by_id,
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


def _matches_snapshot(q, snapshot: DurableAuthoritativeStorageHealthSnapshot) -> bool:
    r = snapshot.ratification
    am = snapshot.phase_am_authorization
    aj = snapshot.phase_aj_authorization
    return all(
        (
            q.ratification_id == r.id,
            q.ratification_receipt_id == snapshot.ratification_receipt.id,
            q.phase_am_authorization_id == am.id,
            q.phase_al_health_qualification_id == r.phase_al_health_qualification_id,
            q.authoritative_storage_ownership_lease_id == r.authoritative_storage_ownership_lease_id,
            q.phase_aj_authorization_id == aj.id,
            q.phase_ai_health_qualification_id == snapshot.phase_ai_qualification.id,
            q.durable_write_ownership_lease_id == snapshot.phase_ai_snapshot.lease.id,
            q.replica_id == r.replica_id,
            q.ratification_hash == r.ratification_hash,
            q.ratification_receipt_hash == snapshot.ratification_receipt.receipt_hash,
            q.phase_am_authorization_hash == am.authorization_hash,
            q.phase_am_approval_receipt_hash == snapshot.phase_am_approval_receipt.receipt_hash,
            q.phase_al_health_qualification_hash == r.phase_al_health_qualification_hash,
            q.phase_al_health_receipt_hash == r.phase_al_health_receipt_hash,
            q.phase_al_integrity_proof_hash == r.phase_al_integrity_proof_hash,
            q.authoritative_storage_ownership_lease_hash == r.authoritative_storage_ownership_lease_hash,
            q.phase_aj_authorization_hash == aj.authorization_hash,
            q.phase_ai_health_qualification_hash == snapshot.phase_ai_qualification.health_qualification_hash,
            q.durable_write_ownership_lease_hash == snapshot.phase_ai_snapshot.lease.lease_hash,
            q.replica_hash == r.replica_hash,
            q.source_file_hash == r.source_file_hash,
            q.source_file_size_bytes == r.source_file_size_bytes,
            q.local_storage_key_fingerprint == r.local_storage_key_fingerprint,
            q.recovery_bucket_fingerprint == r.recovery_bucket_fingerprint,
            q.candidate_storage_key_fingerprint == r.candidate_storage_key_fingerprint,
            q.source_authority_fingerprint == r.source_authority_fingerprint,
            q.candidate_authority_fingerprint == r.candidate_authority_fingerprint,
            q.configuration_fingerprint == r.configuration_fingerprint,
            q.observed_local_hash == aj.observed_local_hash,
            q.observed_local_size_bytes == aj.observed_local_size_bytes,
            q.observed_recovery_hash == aj.observed_recovery_hash,
            q.observed_recovery_size_bytes == aj.observed_recovery_size_bytes,
            q.observed_recovery_etag == aj.observed_recovery_etag,
            q.authority_route_version_at_request == snapshot.authority_route.route_version,
            q.read_route_version_at_request == aj.read_route_version_at_request,
            q.experimental_write_route_version_at_request == aj.experimental_write_route_version_at_request,
            q.durable_route_version_at_request == aj.durable_route_version_at_request,
            q.integrity_proof_hash == snapshot.integrity_proof_hash,
            q.request_snapshot_hash == _request_snapshot_hash(snapshot),
        )
    )


def request_durable_authoritative_storage_health_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    ratification_id: UUID,
    requested_by_id: UUID,
    reason: str,
    now: datetime | None = None,
):
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDurableAuthoritativeStorageHealthConflict("Phase AO request reason is required")
    current = _as_utc(now or _utc_now())

    existing = db.scalar(
        select(EvidenceRecoveryDurableAuthoritativeStorageHealthQualification)
        .where(
            EvidenceRecoveryDurableAuthoritativeStorageHealthQualification.organization_id == organization_id,
            EvidenceRecoveryDurableAuthoritativeStorageHealthQualification.claim_id == claim_id,
            EvidenceRecoveryDurableAuthoritativeStorageHealthQualification.document_id == document_id,
            EvidenceRecoveryDurableAuthoritativeStorageHealthQualification.ratification_id == ratification_id,
        )
        .with_for_update()
    )
    if existing is not None:
        if existing.requested_by_id == requested_by_id and existing.request_reason == normalized_reason:
            return existing, None, "unchanged"
        raise RecoveryDurableAuthoritativeStorageHealthConflict(
            "Phase AN ratification already has a Phase AO health qualification artifact"
        )

    snapshot = _durable_an_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        ratification_id=ratification_id,
        now=current,
    )
    r = snapshot.ratification
    am = snapshot.phase_am_authorization
    aj = snapshot.phase_aj_authorization
    if am.approved_by_id is None:
        raise RecoveryDurableAuthoritativeStorageHealthConflict("Phase AM approval actor is missing")
    request_snapshot_hash = _request_snapshot_hash(snapshot)
    review_expires_at = current + DURABLE_AUTHORITATIVE_STORAGE_HEALTH_REVIEW_WINDOW
    health_hash = _qualification_hash(
        request_snapshot_hash=request_snapshot_hash,
        requested_by_id=requested_by_id,
        requested_at=current,
        review_expires_at=review_expires_at,
        reason=normalized_reason,
    )
    q = EvidenceRecoveryDurableAuthoritativeStorageHealthQualification(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        ratification_id=r.id,
        ratification_receipt_id=snapshot.ratification_receipt.id,
        phase_am_authorization_id=am.id,
        phase_al_health_qualification_id=r.phase_al_health_qualification_id,
        authoritative_storage_ownership_lease_id=r.authoritative_storage_ownership_lease_id,
        phase_aj_authorization_id=aj.id,
        phase_ai_health_qualification_id=snapshot.phase_ai_qualification.id,
        durable_write_ownership_lease_id=snapshot.phase_ai_snapshot.lease.id,
        replica_id=r.replica_id,
        ratification_hash=r.ratification_hash,
        ratification_receipt_hash=snapshot.ratification_receipt.receipt_hash,
        phase_am_authorization_hash=am.authorization_hash,
        phase_am_approval_receipt_hash=snapshot.phase_am_approval_receipt.receipt_hash,
        phase_al_health_qualification_hash=r.phase_al_health_qualification_hash,
        phase_al_health_receipt_hash=r.phase_al_health_receipt_hash,
        phase_al_integrity_proof_hash=r.phase_al_integrity_proof_hash,
        authoritative_storage_ownership_lease_hash=r.authoritative_storage_ownership_lease_hash,
        phase_aj_authorization_hash=aj.authorization_hash,
        phase_ai_health_qualification_hash=snapshot.phase_ai_qualification.health_qualification_hash,
        durable_write_ownership_lease_hash=snapshot.phase_ai_snapshot.lease.lease_hash,
        replica_hash=r.replica_hash,
        source_file_hash=r.source_file_hash,
        source_file_size_bytes=r.source_file_size_bytes,
        local_storage_key_fingerprint=r.local_storage_key_fingerprint,
        recovery_bucket_fingerprint=r.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=r.candidate_storage_key_fingerprint,
        source_authority_fingerprint=r.source_authority_fingerprint,
        candidate_authority_fingerprint=r.candidate_authority_fingerprint,
        configuration_fingerprint=r.configuration_fingerprint,
        observed_local_hash=aj.observed_local_hash,
        observed_local_size_bytes=aj.observed_local_size_bytes,
        observed_recovery_hash=aj.observed_recovery_hash,
        observed_recovery_size_bytes=aj.observed_recovery_size_bytes,
        observed_recovery_etag=aj.observed_recovery_etag,
        authority_route_version_at_request=snapshot.authority_route.route_version,
        read_route_version_at_request=aj.read_route_version_at_request,
        experimental_write_route_version_at_request=aj.experimental_write_route_version_at_request,
        durable_route_version_at_request=aj.durable_route_version_at_request,
        observed_authority_kind="recovery_storage",
        observed_authority_tenure="durable_recovery",
        observed_ratification_active=True,
        observed_durable_authority_created=True,
        observed_local_authoritative=False,
        observed_recovery_authoritative=True,
        observed_authoritative_storage_changed=True,
        integrity_proof_hash=snapshot.integrity_proof_hash,
        request_snapshot_hash=request_snapshot_hash,
        health_qualification_hash=health_hash,
        health_state="healthy",
        phase_an_executed_by_id=r.executed_by_id,
        phase_am_requested_by_id=am.requested_by_id,
        phase_am_approved_by_id=am.approved_by_id,
        phase_al_requested_by_id=am.phase_al_requested_by_id,
        phase_al_qualified_by_id=am.phase_al_qualified_by_id,
        phase_ak_activated_by_id=am.phase_ak_activated_by_id,
        phase_aj_requested_by_id=am.phase_aj_requested_by_id,
        phase_aj_approved_by_id=am.phase_aj_approved_by_id,
        phase_ai_requested_by_id=am.phase_ai_requested_by_id,
        phase_ai_qualified_by_id=am.phase_ai_qualified_by_id,
        phase_ah_activated_by_id=am.phase_ah_activated_by_id,
        phase_ag_requested_by_id=am.phase_ag_requested_by_id,
        phase_ag_approved_by_id=am.phase_ag_approved_by_id,
        phase_af_requested_by_id=am.phase_af_requested_by_id,
        phase_af_qualified_by_id=am.phase_af_qualified_by_id,
        phase_ae_activated_by_id=am.phase_ae_activated_by_id,
        phase_ad_requested_by_id=am.phase_ad_requested_by_id,
        phase_ad_approved_by_id=am.phase_ad_approved_by_id,
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


def get_durable_authoritative_storage_health_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
    for_update: bool = False,
):
    stmt = select(EvidenceRecoveryDurableAuthoritativeStorageHealthQualification).where(
        EvidenceRecoveryDurableAuthoritativeStorageHealthQualification.id == qualification_id,
        EvidenceRecoveryDurableAuthoritativeStorageHealthQualification.organization_id == organization_id,
        EvidenceRecoveryDurableAuthoritativeStorageHealthQualification.claim_id == claim_id,
        EvidenceRecoveryDurableAuthoritativeStorageHealthQualification.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    q = db.scalar(stmt)
    if q is None:
        raise RecoveryDurableAuthoritativeStorageHealthNotFound(
            "Phase AO durable authoritative-storage health qualification not found"
        )
    return q


def list_durable_authoritative_storage_health_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    qualification_id: UUID,
):
    get_durable_authoritative_storage_health_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        qualification_id=qualification_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryDurableAuthoritativeStorageHealthReceipt)
            .where(
                EvidenceRecoveryDurableAuthoritativeStorageHealthReceipt.organization_id == organization_id,
                EvidenceRecoveryDurableAuthoritativeStorageHealthReceipt.claim_id == claim_id,
                EvidenceRecoveryDurableAuthoritativeStorageHealthReceipt.document_id == document_id,
                EvidenceRecoveryDurableAuthoritativeStorageHealthReceipt.health_qualification_id == qualification_id,
            )
            .order_by(EvidenceRecoveryDurableAuthoritativeStorageHealthReceipt.transitioned_at)
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


def qualify_durable_authoritative_storage_health(
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
        raise RecoveryDurableAuthoritativeStorageHealthConflict("Phase AO qualification reason is required")
    current = _as_utc(now or _utc_now())
    q = get_durable_authoritative_storage_health_qualification(
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
        raise RecoveryDurableAuthoritativeStorageHealthConflict("Phase AO qualification is already terminal")
    if q.status != "pending_second_approval":
        raise RecoveryDurableAuthoritativeStorageHealthConflict("Phase AO qualification is already terminal")
    if current >= _as_utc(q.review_expires_at):
        return _terminalize(
            db,
            q,
            phase="expired",
            actor_id=qualified_by_id,
            reason="Phase AO review window expired before qualification",
            now=current,
        )
    if qualified_by_id in _forbidden_qualifiers(q):
        raise RecoveryDurableAuthoritativeStorageHealthConflict(
            "Phase AO qualifier must be independent from requester, AN executor and material AM, AL, AK, AJ, AI, AH, AG, AF, AE and AD actors"
        )

    try:
        snapshot = _durable_an_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            ratification_id=q.ratification_id,
            now=current,
        )
    except RecoveryDurableAuthoritativeStorageHealthUnavailable:
        raise
    except (RecoveryDurableAuthoritativeStorageHealthNotFound, RecoveryDurableAuthoritativeStorageHealthConflict) as exc:
        return _terminalize(
            db,
            q,
            phase="invalidated",
            actor_id=qualified_by_id,
            reason=f"Phase AO fresh verification failed: {exc}",
            now=current,
        )
    if not _matches_snapshot(q, snapshot):
        return _terminalize(
            db,
            q,
            phase="invalidated",
            actor_id=qualified_by_id,
            reason="Phase AO request snapshot drifted before qualification",
            now=current,
        )

    q.status = "qualified"
    q.qualified_by_id = qualified_by_id
    q.qualified_at = current
    q.qualification_reason = normalized_reason
    db.flush()
    receipt = _add_receipt(db, q, phase="qualified", actor_id=qualified_by_id, reason=normalized_reason, now=current)
    return q, receipt, "qualified"


def reject_durable_authoritative_storage_health(
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
        raise RecoveryDurableAuthoritativeStorageHealthConflict("Phase AO rejection reason is required")
    current = _as_utc(now or _utc_now())
    q = get_durable_authoritative_storage_health_qualification(
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
        raise RecoveryDurableAuthoritativeStorageHealthConflict("Phase AO qualification is already terminal")
    if q.status != "pending_second_approval":
        raise RecoveryDurableAuthoritativeStorageHealthConflict("Phase AO qualification is already terminal")
    if current >= _as_utc(q.review_expires_at):
        return _terminalize(
            db,
            q,
            phase="expired",
            actor_id=rejected_by_id,
            reason="Phase AO review window expired before rejection",
            now=current,
        )
    if rejected_by_id == q.requested_by_id:
        raise RecoveryDurableAuthoritativeStorageHealthConflict(
            "Phase AO rejection requires an actor independent from the requester"
        )
    return _terminalize(
        db,
        q,
        phase="rejected",
        actor_id=rejected_by_id,
        reason=normalized_reason,
        now=current,
    )
