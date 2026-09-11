from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.models import Document
from app.modules.documents.object_storage import ObjectStorageError, ObjectStorageIntegrityError, ObjectStorageNotFound
from app.modules.documents.recovery_dual_write_rehearsal_authorization_models import (
    EvidenceRecoveryDualWriteRehearsalAuthorization,
    EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt,
)
from app.modules.documents.recovery_dual_write_rehearsal_execution_models import (
    EvidenceRecoveryDualWriteRehearsalExecution,
    EvidenceRecoveryDualWriteRehearsalExecutionReceipt,
)
from app.modules.documents.recovery_dual_write_rehearsal_health_models import (
    EvidenceRecoveryDualWriteRehearsalHealthQualification,
    EvidenceRecoveryDualWriteRehearsalHealthReceipt,
)
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
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute


DUAL_WRITE_REHEARSAL_HEALTH_REVIEW_WINDOW = timedelta(minutes=10)


class RecoveryDualWriteRehearsalHealthError(RuntimeError):
    pass


class RecoveryDualWriteRehearsalHealthNotFound(RecoveryDualWriteRehearsalHealthError):
    pass


class RecoveryDualWriteRehearsalHealthConflict(RecoveryDualWriteRehearsalHealthError):
    pass


class RecoveryDualWriteRehearsalHealthUnavailable(RecoveryDualWriteRehearsalHealthError):
    pass


@dataclass(frozen=True)
class RehearsalHealthSnapshot:
    execution: EvidenceRecoveryDualWriteRehearsalExecution
    execution_receipt: EvidenceRecoveryDualWriteRehearsalExecutionReceipt
    authorization: EvidenceRecoveryDualWriteRehearsalAuthorization
    approval_receipt: EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt
    document: Document
    route: EvidenceRecoveryReadPathRoute
    replica: EvidenceRecoveryReplica
    rehearsal_object_key_fingerprint: str
    observed_file_hash: str
    observed_file_size_bytes: int
    remote_etag: str | None
    integrity_proof_hash: str
    request_snapshot_hash: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _execution(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    execution_id: UUID,
) -> EvidenceRecoveryDualWriteRehearsalExecution:
    execution = db.scalar(
        select(EvidenceRecoveryDualWriteRehearsalExecution).where(
            EvidenceRecoveryDualWriteRehearsalExecution.id == execution_id,
            EvidenceRecoveryDualWriteRehearsalExecution.organization_id == organization_id,
            EvidenceRecoveryDualWriteRehearsalExecution.claim_id == claim_id,
            EvidenceRecoveryDualWriteRehearsalExecution.document_id == document_id,
        )
    )
    if execution is None:
        raise RecoveryDualWriteRehearsalHealthNotFound("Phase Y rehearsal execution not found")
    return execution


def _execution_receipt(
    db: Session,
    *,
    execution: EvidenceRecoveryDualWriteRehearsalExecution,
) -> EvidenceRecoveryDualWriteRehearsalExecutionReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryDualWriteRehearsalExecutionReceipt).where(
                EvidenceRecoveryDualWriteRehearsalExecutionReceipt.organization_id == execution.organization_id,
                EvidenceRecoveryDualWriteRehearsalExecutionReceipt.claim_id == execution.claim_id,
                EvidenceRecoveryDualWriteRehearsalExecutionReceipt.document_id == execution.document_id,
                EvidenceRecoveryDualWriteRehearsalExecutionReceipt.execution_id == execution.id,
                EvidenceRecoveryDualWriteRehearsalExecutionReceipt.phase == "executed",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryDualWriteRehearsalHealthConflict(
            "Completed Phase Y execution must have exactly one execution receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            receipt.phase_x_authorization_id == execution.phase_x_authorization_id,
            receipt.phase_x_authorization_hash == execution.phase_x_authorization_hash,
            receipt.phase_x_approval_receipt_hash == execution.phase_x_approval_receipt_hash,
            receipt.rehearsal_object_key_fingerprint == execution.rehearsal_object_key_fingerprint,
            receipt.source_file_hash == execution.source_file_hash,
            receipt.source_file_size_bytes == execution.source_file_size_bytes,
            receipt.verification_hash == execution.verification_hash,
            receipt.execution_hash == execution.execution_hash,
            receipt.actor_id == execution.executed_by_id,
            _as_utc(receipt.transitioned_at) == _as_utc(execution.executed_at),
            receipt.rehearsal_executed is True,
            receipt.rehearsal_write_verified is True,
            receipt.rehearsal_object_routable is False,
            receipt.dual_write_active is False,
            receipt.durable_write_authority_created is False,
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
        raise RecoveryDualWriteRehearsalHealthConflict("Phase Y execution receipt lineage is inconsistent")
    return receipt


def _authorization_and_receipt(
    db: Session,
    *,
    execution: EvidenceRecoveryDualWriteRehearsalExecution,
) -> tuple[EvidenceRecoveryDualWriteRehearsalAuthorization, EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt]:
    authorization = db.scalar(
        select(EvidenceRecoveryDualWriteRehearsalAuthorization).where(
            EvidenceRecoveryDualWriteRehearsalAuthorization.id == execution.phase_x_authorization_id,
            EvidenceRecoveryDualWriteRehearsalAuthorization.organization_id == execution.organization_id,
            EvidenceRecoveryDualWriteRehearsalAuthorization.claim_id == execution.claim_id,
            EvidenceRecoveryDualWriteRehearsalAuthorization.document_id == execution.document_id,
        )
    )
    if authorization is None:
        raise RecoveryDualWriteRehearsalHealthNotFound("Phase X authorization not found")
    approval = db.scalar(
        select(EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt).where(
            EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt.id == execution.phase_x_approval_receipt_id,
            EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt.organization_id == execution.organization_id,
            EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt.authorization_id == authorization.id,
            EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt.phase == "approved",
        )
    )
    if approval is None:
        raise RecoveryDualWriteRehearsalHealthConflict("Exact Phase X approval receipt is missing")
    if not all(
        (
            authorization.status == "approved",
            authorization.approved_by_id is not None,
            authorization.approved_at is not None,
            authorization.authorization_expires_at is not None,
            _as_utc(execution.executed_at) < _as_utc(authorization.authorization_expires_at),
            authorization.authorization_hash == execution.phase_x_authorization_hash,
            approval.authorization_hash == execution.phase_x_authorization_hash,
            approval.receipt_hash == execution.phase_x_approval_receipt_hash,
            approval.actor_id == authorization.approved_by_id,
            approval.phase_w_health_qualification_id == authorization.phase_w_health_qualification_id,
            authorization.phase_w_health_qualification_id == execution.phase_w_health_qualification_id,
            authorization.phase_v_transition_lease_id == execution.phase_v_transition_lease_id,
            authorization.phase_u_authorization_id == execution.phase_u_authorization_id,
            authorization.phase_t_health_qualification_id == execution.phase_t_health_qualification_id,
            authorization.replica_id == execution.replica_id,
            authorization.phase_w_health_qualification_hash == execution.phase_w_health_qualification_hash,
            authorization.phase_v_transition_lease_hash == execution.phase_v_transition_lease_hash,
            authorization.phase_u_authorization_hash == execution.phase_u_authorization_hash,
            authorization.phase_t_health_qualification_hash == execution.phase_t_health_qualification_hash,
            authorization.replica_hash == execution.replica_hash,
            authorization.source_file_hash == execution.source_file_hash,
            authorization.source_file_size_bytes == execution.source_file_size_bytes,
            authorization.local_storage_key_fingerprint == execution.local_storage_key_fingerprint,
            authorization.recovery_bucket_fingerprint == execution.recovery_bucket_fingerprint,
            authorization.candidate_storage_key_fingerprint == execution.candidate_storage_key_fingerprint,
            authorization.source_authority_fingerprint == execution.source_authority_fingerprint,
            authorization.candidate_authority_fingerprint == execution.candidate_authority_fingerprint,
            authorization.configuration_fingerprint == execution.configuration_fingerprint,
            authorization.route_version_at_request == execution.route_version_at_execution,
            authorization.rehearsal_executed is False,
            authorization.dual_write_active is False,
            authorization.durable_write_authority_created is False,
            authorization.read_path_switched is False,
            authorization.write_path_switched is False,
            authorization.document_storage_key_mutated is False,
            authorization.authoritative_storage_changed is False,
            authorization.destructive_action_performed is False,
            authorization.s3_copy_performed is False,
            authorization.s3_delete_performed is False,
            authorization.local_delete_performed is False,
        )
    ):
        raise RecoveryDualWriteRehearsalHealthConflict("Phase X/Y authorization lineage is inconsistent")
    return authorization, approval


def _clean_local_route(
    db: Session,
    *,
    execution: EvidenceRecoveryDualWriteRehearsalExecution,
) -> EvidenceRecoveryReadPathRoute:
    route = db.scalar(
        select(EvidenceRecoveryReadPathRoute)
        .where(
            EvidenceRecoveryReadPathRoute.organization_id == execution.organization_id,
            EvidenceRecoveryReadPathRoute.claim_id == execution.claim_id,
            EvidenceRecoveryReadPathRoute.document_id == execution.document_id,
        )
        .with_for_update()
    )
    if route is None:
        raise RecoveryDualWriteRehearsalHealthNotFound("Shared recovery read route not found")
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
            route.route_version == execution.route_version_at_execution,
            route.source_authority_fingerprint == execution.source_authority_fingerprint,
            route.candidate_authority_fingerprint == execution.candidate_authority_fingerprint,
            route.configuration_fingerprint == execution.configuration_fingerprint,
        )
    ):
        raise RecoveryDualWriteRehearsalHealthConflict(
            "Shared route drifted from the clean local authority preserved by Phase Y"
        )
    return route


def _document(
    db: Session,
    *,
    execution: EvidenceRecoveryDualWriteRehearsalExecution,
) -> Document:
    document = db.scalar(
        select(Document)
        .where(
            Document.id == execution.document_id,
            Document.organization_id == execution.organization_id,
            Document.claim_id == execution.claim_id,
        )
        .with_for_update()
    )
    if document is None or document.deleted_at is not None:
        raise RecoveryDualWriteRehearsalHealthNotFound("Document not found")
    return document


def _replica(
    db: Session,
    *,
    execution: EvidenceRecoveryDualWriteRehearsalExecution,
) -> EvidenceRecoveryReplica:
    replica = db.scalar(
        select(EvidenceRecoveryReplica).where(
            EvidenceRecoveryReplica.id == execution.replica_id,
            EvidenceRecoveryReplica.organization_id == execution.organization_id,
            EvidenceRecoveryReplica.claim_id == execution.claim_id,
            EvidenceRecoveryReplica.document_id == execution.document_id,
        )
    )
    if replica is None:
        raise RecoveryDualWriteRehearsalHealthNotFound("Recovery replica not found")
    if not all(
        (
            replica.replica_hash == execution.replica_hash,
            replica.source_file_hash == execution.source_file_hash,
            replica.source_file_size_bytes == execution.source_file_size_bytes,
            replica.source_storage_key_fingerprint == execution.local_storage_key_fingerprint,
            replica.recovery_bucket_fingerprint == execution.recovery_bucket_fingerprint,
            hashlib.sha256(replica.recovery_storage_key.encode("utf-8")).hexdigest()
            == execution.candidate_storage_key_fingerprint,
        )
    ):
        raise RecoveryDualWriteRehearsalHealthConflict("Recovery replica lineage drifted after Phase Y")
    return replica


def _rehearsal_key(document: Document, authorization_id: UUID) -> str:
    return (
        f"rehearsal/dual-write/{document.organization_id}/{document.claim_id}/"
        f"{document.id}/{authorization_id}{_suffix_for_document(document)}"
    )


def _fresh_rehearsal_object(
    *,
    execution: EvidenceRecoveryDualWriteRehearsalExecution,
    document: Document,
    replica: EvidenceRecoveryReplica,
):
    key = _rehearsal_key(document, execution.phase_x_authorization_id)
    if key in {document.storage_key, replica.recovery_storage_key}:
        raise RecoveryDualWriteRehearsalHealthConflict("Phase Y rehearsal object is not isolated")
    key_fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()
    if key_fingerprint != execution.rehearsal_object_key_fingerprint:
        raise RecoveryDualWriteRehearsalHealthConflict("Phase Y rehearsal object key fingerprint drifted")
    try:
        store = _build_store()
    except RecoveryReplicationUnavailable as exc:
        raise RecoveryDualWriteRehearsalHealthUnavailable(str(exc)) from exc
    if store.sanitized_health_identity.bucket_fingerprint != execution.recovery_bucket_fingerprint:
        raise RecoveryDualWriteRehearsalHealthConflict("Recovery bucket changed after Phase Y")
    try:
        metadata = store.head_object(storage_key=key)
        payload = store.get_bytes(storage_key=key, expected_sha256=execution.source_file_hash)
    except ObjectStorageNotFound as exc:
        raise RecoveryDualWriteRehearsalHealthConflict("Phase Y rehearsal object is missing") from exc
    except ObjectStorageIntegrityError as exc:
        raise RecoveryDualWriteRehearsalHealthConflict("Phase Y rehearsal object failed integrity verification") from exc
    except ObjectStorageError as exc:
        raise RecoveryDualWriteRehearsalHealthUnavailable(
            "Recovery storage health verification is temporarily unavailable"
        ) from exc
    observed_hash = hashlib.sha256(payload).hexdigest()
    observed_size = len(payload)
    if not all(
        (
            metadata.file_hash == execution.source_file_hash,
            metadata.file_size_bytes == execution.source_file_size_bytes,
            observed_hash == execution.source_file_hash,
            observed_size == execution.source_file_size_bytes,
            execution.observed_file_hash == execution.source_file_hash,
            execution.observed_file_size_bytes == execution.source_file_size_bytes,
            execution.remote_etag is None or metadata.etag == execution.remote_etag,
        )
    ):
        raise RecoveryDualWriteRehearsalHealthConflict("Phase Y rehearsal object bytes or metadata drifted")
    return key_fingerprint, observed_hash, observed_size, metadata.etag


def _load_snapshot(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    execution_id: UUID,
) -> RehearsalHealthSnapshot:
    execution = _execution(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        execution_id=execution_id,
    )
    if not all(
        (
            execution.status == "executed",
            execution.max_rehearsal_writes == 1,
            execution.rehearsal_executed is True,
            execution.rehearsal_write_verified is True,
            execution.rehearsal_object_routable is False,
            execution.dual_write_active is False,
            execution.durable_write_authority_created is False,
            execution.read_path_switched is False,
            execution.write_path_switched is False,
            execution.document_storage_key_mutated is False,
            execution.authoritative_storage_changed is False,
            execution.destructive_action_performed is False,
            execution.s3_copy_performed is False,
            execution.s3_delete_performed is False,
            execution.local_delete_performed is False,
        )
    ):
        raise RecoveryDualWriteRehearsalHealthConflict("Phase Y execution crossed its safety boundary")
    execution_receipt = _execution_receipt(db, execution=execution)
    authorization, approval_receipt = _authorization_and_receipt(db, execution=execution)
    route = _clean_local_route(db, execution=execution)
    document = _document(db, execution=execution)
    try:
        local = _snapshot_local(document)
    except RecoveryReplicationNotFound as exc:
        raise RecoveryDualWriteRehearsalHealthNotFound(str(exc)) from exc
    except (RecoveryReplicationConflict, FileNotFoundError) as exc:
        raise RecoveryDualWriteRehearsalHealthConflict(str(exc)) from exc
    if not all(
        (
            local.file_hash == execution.source_file_hash,
            local.file_size_bytes == execution.source_file_size_bytes,
            local.storage_key_fingerprint == execution.local_storage_key_fingerprint,
        )
    ):
        raise RecoveryDualWriteRehearsalHealthConflict("Authoritative local evidence drifted after Phase Y")
    replica = _replica(db, execution=execution)
    key_fingerprint, observed_hash, observed_size, remote_etag = _fresh_rehearsal_object(
        execution=execution,
        document=document,
        replica=replica,
    )
    integrity_proof_hash = _canonical_hash(
        {
            "execution_id": str(execution.id),
            "execution_hash": execution.execution_hash,
            "execution_verification_hash": execution.verification_hash,
            "execution_receipt_id": str(execution_receipt.id),
            "execution_receipt_hash": execution_receipt.receipt_hash,
            "phase_x_authorization_id": str(authorization.id),
            "phase_x_authorization_hash": authorization.authorization_hash,
            "phase_x_approval_receipt_id": str(approval_receipt.id),
            "phase_x_approval_receipt_hash": approval_receipt.receipt_hash,
            "source_file_hash": local.file_hash,
            "source_file_size_bytes": local.file_size_bytes,
            "local_storage_key_fingerprint": local.storage_key_fingerprint,
            "recovery_bucket_fingerprint": execution.recovery_bucket_fingerprint,
            "rehearsal_object_key_fingerprint": key_fingerprint,
            "observed_file_hash": observed_hash,
            "observed_file_size_bytes": observed_size,
            "remote_etag": remote_etag,
            "route_version": route.route_version,
            "source_authority_fingerprint": route.source_authority_fingerprint,
            "candidate_authority_fingerprint": route.candidate_authority_fingerprint,
            "configuration_fingerprint": route.configuration_fingerprint,
            "storage_write_performed": False,
            "routable_dual_write_authority_created": False,
            "rehearsal_object_routable": False,
            "dual_write_active": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
        }
    )
    request_snapshot_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "execution_id": str(execution.id),
            "execution_hash": execution.execution_hash,
            "verification_hash": execution.verification_hash,
            "execution_receipt_hash": execution_receipt.receipt_hash,
            "phase_x_authorization_hash": execution.phase_x_authorization_hash,
            "phase_x_approval_receipt_hash": execution.phase_x_approval_receipt_hash,
            "phase_w_health_qualification_hash": execution.phase_w_health_qualification_hash,
            "phase_v_transition_lease_hash": execution.phase_v_transition_lease_hash,
            "phase_u_authorization_hash": execution.phase_u_authorization_hash,
            "phase_t_health_qualification_hash": execution.phase_t_health_qualification_hash,
            "replica_hash": execution.replica_hash,
            "source_file_hash": execution.source_file_hash,
            "source_file_size_bytes": execution.source_file_size_bytes,
            "local_storage_key_fingerprint": execution.local_storage_key_fingerprint,
            "recovery_bucket_fingerprint": execution.recovery_bucket_fingerprint,
            "candidate_storage_key_fingerprint": execution.candidate_storage_key_fingerprint,
            "source_authority_fingerprint": execution.source_authority_fingerprint,
            "candidate_authority_fingerprint": execution.candidate_authority_fingerprint,
            "configuration_fingerprint": execution.configuration_fingerprint,
            "route_version_at_request": route.route_version,
            "rehearsal_object_key_fingerprint": key_fingerprint,
            "observed_file_hash": observed_hash,
            "observed_file_size_bytes": observed_size,
            "remote_etag": remote_etag,
            "integrity_proof_hash": integrity_proof_hash,
            "health_state": "healthy",
        }
    )
    return RehearsalHealthSnapshot(
        execution=execution,
        execution_receipt=execution_receipt,
        authorization=authorization,
        approval_receipt=approval_receipt,
        document=document,
        route=route,
        replica=replica,
        rehearsal_object_key_fingerprint=key_fingerprint,
        observed_file_hash=observed_hash,
        observed_file_size_bytes=observed_size,
        remote_etag=remote_etag,
        integrity_proof_hash=integrity_proof_hash,
        request_snapshot_hash=request_snapshot_hash,
    )


def _matches_snapshot(
    q: EvidenceRecoveryDualWriteRehearsalHealthQualification,
    s: RehearsalHealthSnapshot,
) -> bool:
    e = s.execution
    return all(
        (
            q.execution_id == e.id,
            q.execution_receipt_id == s.execution_receipt.id,
            q.phase_x_authorization_id == e.phase_x_authorization_id,
            q.phase_x_approval_receipt_id == e.phase_x_approval_receipt_id,
            q.phase_w_health_qualification_id == e.phase_w_health_qualification_id,
            q.phase_v_transition_lease_id == e.phase_v_transition_lease_id,
            q.phase_u_authorization_id == e.phase_u_authorization_id,
            q.phase_t_health_qualification_id == e.phase_t_health_qualification_id,
            q.replica_id == e.replica_id,
            q.execution_hash == e.execution_hash,
            q.verification_hash == e.verification_hash,
            q.execution_receipt_hash == s.execution_receipt.receipt_hash,
            q.phase_x_authorization_hash == e.phase_x_authorization_hash,
            q.phase_x_approval_receipt_hash == e.phase_x_approval_receipt_hash,
            q.phase_w_health_qualification_hash == e.phase_w_health_qualification_hash,
            q.phase_v_transition_lease_hash == e.phase_v_transition_lease_hash,
            q.phase_u_authorization_hash == e.phase_u_authorization_hash,
            q.phase_t_health_qualification_hash == e.phase_t_health_qualification_hash,
            q.replica_hash == e.replica_hash,
            q.source_file_hash == e.source_file_hash,
            q.source_file_size_bytes == e.source_file_size_bytes,
            q.local_storage_key_fingerprint == e.local_storage_key_fingerprint,
            q.recovery_bucket_fingerprint == e.recovery_bucket_fingerprint,
            q.candidate_storage_key_fingerprint == e.candidate_storage_key_fingerprint,
            q.source_authority_fingerprint == e.source_authority_fingerprint,
            q.candidate_authority_fingerprint == e.candidate_authority_fingerprint,
            q.configuration_fingerprint == e.configuration_fingerprint,
            q.route_version_at_request == s.route.route_version,
            q.rehearsal_object_key_fingerprint == s.rehearsal_object_key_fingerprint,
            q.observed_file_hash == s.observed_file_hash,
            q.observed_file_size_bytes == s.observed_file_size_bytes,
            q.remote_etag == s.remote_etag,
            q.integrity_proof_hash == s.integrity_proof_hash,
            q.request_snapshot_hash == s.request_snapshot_hash,
            q.phase_y_executed_by_id == e.executed_by_id,
            q.phase_x_approved_by_id == s.authorization.approved_by_id,
        )
    )


def _receipt_hash(q, *, phase: str, actor_id: UUID, reason: str, transitioned_at: datetime) -> str:
    return _canonical_hash(
        {
            "health_qualification_id": str(q.id),
            "execution_id": str(q.execution_id),
            "phase": phase,
            "health_state": q.health_state,
            "integrity_proof_hash": q.integrity_proof_hash,
            "request_snapshot_hash": q.request_snapshot_hash,
            "health_qualification_hash": q.health_qualification_hash,
            "actor_id": str(actor_id),
            "reason": reason,
            "transitioned_at": _utc_iso(transitioned_at),
            "storage_write_performed": False,
            "routable_dual_write_authority_created": False,
            "rehearsal_object_routable": False,
            "dual_write_active": False,
            "durable_write_authority_created": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
            "s3_copy_performed": False,
            "s3_delete_performed": False,
            "local_delete_performed": False,
        }
    )


def _add_receipt(
    db: Session,
    q: EvidenceRecoveryDualWriteRehearsalHealthQualification,
    *,
    phase: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
):
    receipt = EvidenceRecoveryDualWriteRehearsalHealthReceipt(
        organization_id=q.organization_id,
        claim_id=q.claim_id,
        document_id=q.document_id,
        health_qualification_id=q.id,
        execution_id=q.execution_id,
        phase=phase,
        health_state=q.health_state,
        integrity_proof_hash=q.integrity_proof_hash,
        request_snapshot_hash=q.request_snapshot_hash,
        health_qualification_hash=q.health_qualification_hash,
        receipt_hash=_receipt_hash(q, phase=phase, actor_id=actor_id, reason=reason, transitioned_at=now),
        actor_id=actor_id,
        reason=reason,
        transitioned_at=now,
        storage_write_performed=False,
        routable_dual_write_authority_created=False,
        rehearsal_object_routable=False,
        dual_write_active=False,
        durable_write_authority_created=False,
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


def request_recovery_dual_write_rehearsal_health_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    execution_id: UUID,
    requested_by_id: UUID,
    reason: str,
    now: datetime | None = None,
):
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDualWriteRehearsalHealthConflict("Phase Z request reason is required")
    current = _as_utc(now or _utc_now())
    snapshot = _load_snapshot(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        execution_id=execution_id,
    )
    existing = db.scalar(
        select(EvidenceRecoveryDualWriteRehearsalHealthQualification)
        .where(
            EvidenceRecoveryDualWriteRehearsalHealthQualification.organization_id == organization_id,
            EvidenceRecoveryDualWriteRehearsalHealthQualification.claim_id == claim_id,
            EvidenceRecoveryDualWriteRehearsalHealthQualification.document_id == document_id,
            EvidenceRecoveryDualWriteRehearsalHealthQualification.execution_id == execution_id,
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
        raise RecoveryDualWriteRehearsalHealthConflict("Phase Z qualification already exists for this Phase Y execution")
    e = snapshot.execution
    health_hash = _canonical_hash(
        {
            "request_snapshot_hash": snapshot.request_snapshot_hash,
            "integrity_proof_hash": snapshot.integrity_proof_hash,
            "execution_id": str(e.id),
            "execution_hash": e.execution_hash,
            "requested_by_id": str(requested_by_id),
            "requested_at": _utc_iso(current),
            "request_reason": normalized_reason,
            "review_expires_at": _utc_iso(current + DUAL_WRITE_REHEARSAL_HEALTH_REVIEW_WINDOW),
            "health_state": "healthy",
            "mode": "phase_z_non_routable_dual_write_rehearsal_health",
        }
    )
    q = EvidenceRecoveryDualWriteRehearsalHealthQualification(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        execution_id=e.id,
        execution_receipt_id=snapshot.execution_receipt.id,
        phase_x_authorization_id=e.phase_x_authorization_id,
        phase_x_approval_receipt_id=e.phase_x_approval_receipt_id,
        phase_w_health_qualification_id=e.phase_w_health_qualification_id,
        phase_v_transition_lease_id=e.phase_v_transition_lease_id,
        phase_u_authorization_id=e.phase_u_authorization_id,
        phase_t_health_qualification_id=e.phase_t_health_qualification_id,
        replica_id=e.replica_id,
        execution_hash=e.execution_hash,
        verification_hash=e.verification_hash,
        execution_receipt_hash=snapshot.execution_receipt.receipt_hash,
        phase_x_authorization_hash=e.phase_x_authorization_hash,
        phase_x_approval_receipt_hash=e.phase_x_approval_receipt_hash,
        phase_w_health_qualification_hash=e.phase_w_health_qualification_hash,
        phase_v_transition_lease_hash=e.phase_v_transition_lease_hash,
        phase_u_authorization_hash=e.phase_u_authorization_hash,
        phase_t_health_qualification_hash=e.phase_t_health_qualification_hash,
        replica_hash=e.replica_hash,
        source_file_hash=e.source_file_hash,
        source_file_size_bytes=e.source_file_size_bytes,
        local_storage_key_fingerprint=e.local_storage_key_fingerprint,
        recovery_bucket_fingerprint=e.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=e.candidate_storage_key_fingerprint,
        source_authority_fingerprint=e.source_authority_fingerprint,
        candidate_authority_fingerprint=e.candidate_authority_fingerprint,
        configuration_fingerprint=e.configuration_fingerprint,
        route_version_at_request=snapshot.route.route_version,
        rehearsal_object_key_fingerprint=snapshot.rehearsal_object_key_fingerprint,
        observed_file_hash=snapshot.observed_file_hash,
        observed_file_size_bytes=snapshot.observed_file_size_bytes,
        remote_etag=snapshot.remote_etag,
        integrity_proof_hash=snapshot.integrity_proof_hash,
        request_snapshot_hash=snapshot.request_snapshot_hash,
        health_qualification_hash=health_hash,
        health_state="healthy",
        phase_y_executed_by_id=e.executed_by_id,
        phase_x_approved_by_id=snapshot.authorization.approved_by_id,
        requested_by_id=requested_by_id,
        requested_at=current,
        review_expires_at=current + DUAL_WRITE_REHEARSAL_HEALTH_REVIEW_WINDOW,
        request_reason=normalized_reason,
        status="pending_second_approval",
        storage_write_performed=False,
        routable_dual_write_authority_created=False,
        rehearsal_object_routable=False,
        dual_write_active=False,
        durable_write_authority_created=False,
        read_path_switched=False,
        write_path_switched=False,
        document_storage_key_mutated=False,
        authoritative_storage_changed=False,
        destructive_action_performed=False,
        s3_copy_performed=False,
        s3_delete_performed=False,
        local_delete_performed=False,
    )
    db.add(q)
    db.flush()
    receipt = _add_receipt(db, q, phase="requested", actor_id=requested_by_id, reason=normalized_reason, now=current)
    return q, receipt, "pending_second_approval"


def get_recovery_dual_write_rehearsal_health_qualification(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
    for_update: bool = False,
):
    stmt = select(EvidenceRecoveryDualWriteRehearsalHealthQualification).where(
        EvidenceRecoveryDualWriteRehearsalHealthQualification.id == health_qualification_id,
        EvidenceRecoveryDualWriteRehearsalHealthQualification.organization_id == organization_id,
        EvidenceRecoveryDualWriteRehearsalHealthQualification.claim_id == claim_id,
        EvidenceRecoveryDualWriteRehearsalHealthQualification.document_id == document_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    q = db.scalar(stmt)
    if q is None:
        raise RecoveryDualWriteRehearsalHealthNotFound("Phase Z health qualification not found")
    return q


def _terminalize(
    db: Session,
    q: EvidenceRecoveryDualWriteRehearsalHealthQualification,
    *,
    phase: str,
    actor_id: UUID,
    reason: str,
    now: datetime,
):
    q.status = phase
    q.terminal_by_id = actor_id
    q.terminal_at = now
    q.terminal_reason = reason
    db.flush()
    return _add_receipt(db, q, phase=phase, actor_id=actor_id, reason=reason, now=now)


def qualify_recovery_dual_write_rehearsal_health(
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
        raise RecoveryDualWriteRehearsalHealthConflict("Phase Z qualification reason is required")
    current = _as_utc(now or _utc_now())
    q = get_recovery_dual_write_rehearsal_health_qualification(
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
            reason="Phase Z independent review window expired",
            now=current,
        )
        return q, receipt, "expired"
    if qualified_by_id in {q.requested_by_id, q.phase_y_executed_by_id, q.phase_x_approved_by_id}:
        raise RecoveryDualWriteRehearsalHealthConflict(
            "Phase Z qualifier must be independent from requester, Phase Y executor and Phase X approver"
        )
    try:
        snapshot = _load_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            execution_id=q.execution_id,
        )
    except RecoveryDualWriteRehearsalHealthUnavailable:
        raise
    except (RecoveryDualWriteRehearsalHealthNotFound, RecoveryDualWriteRehearsalHealthConflict) as exc:
        receipt = _terminalize(
            db,
            q,
            phase="invalidated",
            actor_id=qualified_by_id,
            reason=f"Phase Z fresh verification invalidated: {exc}",
            now=current,
        )
        return q, receipt, "invalidated"
    if not _matches_snapshot(q, snapshot):
        receipt = _terminalize(
            db,
            q,
            phase="invalidated",
            actor_id=qualified_by_id,
            reason="Phase Z request snapshot drifted before independent qualification",
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


def reject_recovery_dual_write_rehearsal_health(
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
        raise RecoveryDualWriteRehearsalHealthConflict("Phase Z rejection reason is required")
    current = _as_utc(now or _utc_now())
    q = get_recovery_dual_write_rehearsal_health_qualification(
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
            reason="Phase Z independent review window expired",
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


def list_recovery_dual_write_rehearsal_health_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    health_qualification_id: UUID,
):
    get_recovery_dual_write_rehearsal_health_qualification(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        health_qualification_id=health_qualification_id,
    )
    return list(
        db.scalars(
            select(EvidenceRecoveryDualWriteRehearsalHealthReceipt)
            .where(
                EvidenceRecoveryDualWriteRehearsalHealthReceipt.organization_id == organization_id,
                EvidenceRecoveryDualWriteRehearsalHealthReceipt.claim_id == claim_id,
                EvidenceRecoveryDualWriteRehearsalHealthReceipt.document_id == document_id,
                EvidenceRecoveryDualWriteRehearsalHealthReceipt.health_qualification_id == health_qualification_id,
            )
            .order_by(EvidenceRecoveryDualWriteRehearsalHealthReceipt.transitioned_at.asc(), EvidenceRecoveryDualWriteRehearsalHealthReceipt.id.asc())
        ).all()
    )
