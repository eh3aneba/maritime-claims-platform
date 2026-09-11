from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.object_storage import (
    ObjectStorageError,
    ObjectStorageIntegrityError,
    ObjectStorageNotFound,
    ObjectStoragePreconditionFailed,
)
from app.modules.documents.recovery_dual_write_rehearsal_authorization_models import (
    EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt,
)
from app.modules.documents.recovery_dual_write_rehearsal_authorization_service import (
    RecoveryDualWriteRehearsalAuthorizationConflict,
    RecoveryDualWriteRehearsalAuthorizationNotFound,
    RecoveryDualWriteRehearsalAuthorizationUnavailable,
    _load_snapshot as _load_x_snapshot,
    _matches_snapshot as _matches_x_snapshot,
    get_dual_write_rehearsal_authorization,
)
from app.modules.documents.recovery_dual_write_rehearsal_execution_models import (
    EvidenceRecoveryDualWriteRehearsalExecution,
    EvidenceRecoveryDualWriteRehearsalExecutionReceipt,
)
from app.modules.documents.recovery_promotion_service import _as_utc
from app.modules.documents.recovery_replication_models import EvidenceRecoveryReplica
from app.modules.documents.recovery_replication_service import (
    RecoveryReplicationConflict,
    RecoveryReplicationNotFound,
    RecoveryReplicationUnavailable,
    _build_store,
    _load_document_for_update,
    _snapshot_local,
    _suffix_for_document,
)
from app.modules.documents.recovery_restore_service import _canonical_hash, _utc_iso
from app.modules.documents.recovery_routable_read_cutover_models import EvidenceRecoveryReadPathRoute


class RecoveryDualWriteRehearsalExecutionError(RuntimeError):
    pass


class RecoveryDualWriteRehearsalExecutionNotFound(RecoveryDualWriteRehearsalExecutionError):
    pass


class RecoveryDualWriteRehearsalExecutionConflict(RecoveryDualWriteRehearsalExecutionError):
    pass


class RecoveryDualWriteRehearsalExecutionUnavailable(RecoveryDualWriteRehearsalExecutionError):
    pass


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _approved_receipt(
    db: Session,
    *,
    authorization,
) -> EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt:
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt).where(
                EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt.organization_id == authorization.organization_id,
                EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt.claim_id == authorization.claim_id,
                EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt.document_id == authorization.document_id,
                EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt.authorization_id == authorization.id,
                EvidenceRecoveryDualWriteRehearsalAuthorizationReceipt.phase == "approved",
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryDualWriteRehearsalExecutionConflict(
            "Approved Phase X authorization must have exactly one approved receipt"
        )
    receipt = receipts[0]
    if not all(
        (
            authorization.approved_by_id is not None,
            authorization.approved_at is not None,
            receipt.actor_id == authorization.approved_by_id,
            _as_utc(receipt.transitioned_at) == _as_utc(authorization.approved_at),
            receipt.authorization_hash == authorization.authorization_hash,
            receipt.phase_w_health_qualification_id == authorization.phase_w_health_qualification_id,
            receipt.health_state == authorization.health_state == "healthy",
            receipt.operational_evidence_hash == authorization.operational_evidence_hash,
            receipt.integrity_proof_hash == authorization.integrity_proof_hash,
            receipt.request_snapshot_hash == authorization.request_snapshot_hash,
            receipt.rehearsal_executed is False,
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
        raise RecoveryDualWriteRehearsalExecutionConflict(
            "Phase X approval receipt lineage is inconsistent"
        )
    return receipt


def _lock_clean_local_route(db: Session, *, authorization) -> EvidenceRecoveryReadPathRoute:
    route = db.scalar(
        select(EvidenceRecoveryReadPathRoute)
        .where(
            EvidenceRecoveryReadPathRoute.organization_id == authorization.organization_id,
            EvidenceRecoveryReadPathRoute.claim_id == authorization.claim_id,
            EvidenceRecoveryReadPathRoute.document_id == authorization.document_id,
        )
        .with_for_update()
    )
    if route is None:
        raise RecoveryDualWriteRehearsalExecutionConflict("Shared evidence read route is missing")
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
            route.route_version == authorization.route_version_at_request,
            route.source_authority_fingerprint == authorization.source_authority_fingerprint,
            route.candidate_authority_fingerprint == authorization.candidate_authority_fingerprint,
            route.configuration_fingerprint == authorization.configuration_fingerprint,
        )
    ):
        raise RecoveryDualWriteRehearsalExecutionConflict(
            "Shared evidence route drifted from the approved Phase X local-authority snapshot"
        )
    return route


def _rehearsal_key(document, authorization_id: UUID) -> str:
    return (
        f"rehearsal/dual-write/{document.organization_id}/{document.claim_id}/"
        f"{document.id}/{authorization_id}{_suffix_for_document(document)}"
    )


def _verify_isolated_object(store, *, storage_key: str, expected_hash: str, expected_size: int):
    try:
        metadata = store.head_object(storage_key=storage_key)
        if metadata.file_hash != expected_hash or metadata.file_size_bytes != expected_size:
            raise RecoveryDualWriteRehearsalExecutionConflict(
                "Isolated rehearsal object metadata does not match authoritative local evidence"
            )
        payload = store.get_bytes(storage_key=storage_key, expected_sha256=expected_hash)
    except ObjectStorageNotFound as exc:
        raise RecoveryDualWriteRehearsalExecutionConflict(
            "Isolated rehearsal object disappeared before verification"
        ) from exc
    except ObjectStorageIntegrityError as exc:
        raise RecoveryDualWriteRehearsalExecutionConflict(
            "Isolated rehearsal object failed integrity verification"
        ) from exc
    except ObjectStorageError as exc:
        raise RecoveryDualWriteRehearsalExecutionUnavailable(
            "Recovery storage verification is temporarily unavailable"
        ) from exc
    if len(payload) != expected_size or hashlib.sha256(payload).hexdigest() != expected_hash:
        raise RecoveryDualWriteRehearsalExecutionConflict(
            "Isolated rehearsal object bytes do not match authoritative local evidence"
        )
    return metadata


def _head_before_put(store, *, payload: bytes, storage_key: str, expected_hash: str, expected_size: int):
    conditional_write_performed = False
    try:
        existing = store.head_object(storage_key=storage_key)
    except ObjectStorageNotFound:
        existing = None
    except ObjectStorageIntegrityError as exc:
        raise RecoveryDualWriteRehearsalExecutionConflict(
            "Existing isolated rehearsal object has invalid integrity metadata"
        ) from exc
    except ObjectStorageError as exc:
        raise RecoveryDualWriteRehearsalExecutionUnavailable(
            "Recovery storage preflight is temporarily unavailable"
        ) from exc

    if existing is not None:
        if existing.file_hash != expected_hash or existing.file_size_bytes != expected_size:
            raise RecoveryDualWriteRehearsalExecutionConflict(
                "Existing isolated rehearsal object conflicts with approved evidence"
            )
    else:
        try:
            store.put_bytes_if_absent(
                payload,
                storage_key=storage_key,
                expected_sha256=expected_hash,
            )
            conditional_write_performed = True
        except ObjectStoragePreconditionFailed:
            # A concurrent retry won the deterministic isolated key. Never overwrite;
            # the winning bytes must pass the same exact post-write verification.
            pass
        except ObjectStorageIntegrityError as exc:
            raise RecoveryDualWriteRehearsalExecutionConflict(
                "Rehearsal upload payload failed integrity verification"
            ) from exc
        except ObjectStorageError as exc:
            raise RecoveryDualWriteRehearsalExecutionUnavailable(
                "Recovery storage rehearsal write is temporarily unavailable"
            ) from exc

    metadata = _verify_isolated_object(
        store,
        storage_key=storage_key,
        expected_hash=expected_hash,
        expected_size=expected_size,
    )
    return metadata, conditional_write_performed


def _execution_receipt(db: Session, execution: EvidenceRecoveryDualWriteRehearsalExecution):
    receipts = list(
        db.scalars(
            select(EvidenceRecoveryDualWriteRehearsalExecutionReceipt).where(
                EvidenceRecoveryDualWriteRehearsalExecutionReceipt.execution_id == execution.id,
                EvidenceRecoveryDualWriteRehearsalExecutionReceipt.organization_id == execution.organization_id,
            )
        ).all()
    )
    if len(receipts) != 1:
        raise RecoveryDualWriteRehearsalExecutionConflict(
            "Completed Phase Y execution must have exactly one immutable receipt"
        )
    return receipts[0]


def execute_dual_write_rehearsal(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    authorization_id: UUID,
    executed_by_id: UUID,
    reason: str,
    now: datetime | None = None,
):
    normalized_reason = reason.strip()
    if len(normalized_reason) < 8:
        raise RecoveryDualWriteRehearsalExecutionConflict("Phase Y execution reason is required")
    current = _as_utc(now or _utc_now())

    try:
        authorization = get_dual_write_rehearsal_authorization(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            authorization_id=authorization_id,
            for_update=True,
        )
    except RecoveryDualWriteRehearsalAuthorizationNotFound as exc:
        raise RecoveryDualWriteRehearsalExecutionNotFound(str(exc)) from exc

    existing = db.scalar(
        select(EvidenceRecoveryDualWriteRehearsalExecution)
        .where(
            EvidenceRecoveryDualWriteRehearsalExecution.organization_id == organization_id,
            EvidenceRecoveryDualWriteRehearsalExecution.claim_id == claim_id,
            EvidenceRecoveryDualWriteRehearsalExecution.document_id == document_id,
            EvidenceRecoveryDualWriteRehearsalExecution.phase_x_authorization_id == authorization_id,
        )
        .with_for_update()
    )
    if existing is not None:
        return existing, _execution_receipt(db, existing), "unchanged"

    if not all(
        (
            authorization.status == "approved",
            authorization.authorization_expires_at is not None,
            authorization.approved_by_id is not None,
            authorization.approved_at is not None,
            authorization.max_rehearsal_writes == 1,
        )
    ):
        raise RecoveryDualWriteRehearsalExecutionConflict(
            "Phase Y requires one exact approved Phase X authorization"
        )
    if current >= _as_utc(authorization.authorization_expires_at):
        raise RecoveryDualWriteRehearsalExecutionConflict(
            "Phase X authorization expired before Phase Y execution"
        )
    approval_receipt = _approved_receipt(db, authorization=authorization)

    try:
        x_snapshot = _load_x_snapshot(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            phase_w_health_qualification_id=authorization.phase_w_health_qualification_id,
        )
    except RecoveryDualWriteRehearsalAuthorizationUnavailable as exc:
        raise RecoveryDualWriteRehearsalExecutionUnavailable(str(exc)) from exc
    except RecoveryDualWriteRehearsalAuthorizationNotFound as exc:
        raise RecoveryDualWriteRehearsalExecutionNotFound(str(exc)) from exc
    except RecoveryDualWriteRehearsalAuthorizationConflict as exc:
        raise RecoveryDualWriteRehearsalExecutionConflict(str(exc)) from exc
    if not _matches_x_snapshot(authorization, x_snapshot):
        raise RecoveryDualWriteRehearsalExecutionConflict(
            "Phase X lineage drifted before Phase Y execution"
        )

    route = _lock_clean_local_route(db, authorization=authorization)
    try:
        document = _load_document_for_update(
            db,
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
        )
        local = _snapshot_local(document)
    except RecoveryReplicationNotFound as exc:
        raise RecoveryDualWriteRehearsalExecutionNotFound(str(exc)) from exc
    except RecoveryReplicationConflict as exc:
        raise RecoveryDualWriteRehearsalExecutionConflict(str(exc)) from exc

    if not all(
        (
            local.file_hash == authorization.source_file_hash,
            local.file_size_bytes == authorization.source_file_size_bytes,
            local.storage_key_fingerprint == authorization.local_storage_key_fingerprint,
        )
    ):
        raise RecoveryDualWriteRehearsalExecutionConflict(
            "Authoritative local evidence drifted after Phase X approval"
        )

    replica = db.scalar(
        select(EvidenceRecoveryReplica).where(
            EvidenceRecoveryReplica.id == authorization.replica_id,
            EvidenceRecoveryReplica.organization_id == organization_id,
            EvidenceRecoveryReplica.claim_id == claim_id,
            EvidenceRecoveryReplica.document_id == document_id,
        )
    )
    if replica is None or replica.replica_hash != authorization.replica_hash:
        raise RecoveryDualWriteRehearsalExecutionConflict("Recovery replica lineage drifted")

    isolated_key = _rehearsal_key(document, authorization.id)
    if isolated_key in {document.storage_key, replica.recovery_storage_key}:
        raise RecoveryDualWriteRehearsalExecutionConflict(
            "Rehearsal object key is not isolated from authoritative or candidate evidence"
        )
    key_fingerprint = hashlib.sha256(isolated_key.encode("utf-8")).hexdigest()

    try:
        store = _build_store()
    except RecoveryReplicationUnavailable as exc:
        raise RecoveryDualWriteRehearsalExecutionUnavailable(str(exc)) from exc
    if store.sanitized_health_identity.bucket_fingerprint != authorization.recovery_bucket_fingerprint:
        raise RecoveryDualWriteRehearsalExecutionConflict(
            "Recovery bucket changed after Phase X approval"
        )

    metadata, conditional_write_performed = _head_before_put(
        store,
        payload=local.payload,
        storage_key=isolated_key,
        expected_hash=local.file_hash,
        expected_size=local.file_size_bytes,
    )
    # Explicit second HEAD + GET closes the operation with post-write evidence,
    # including when a racing retry created the deterministic isolated object.
    metadata = _verify_isolated_object(
        store,
        storage_key=isolated_key,
        expected_hash=local.file_hash,
        expected_size=local.file_size_bytes,
    )

    verification_hash = _canonical_hash(
        {
            "phase_x_authorization_id": str(authorization.id),
            "phase_x_authorization_hash": authorization.authorization_hash,
            "phase_x_approval_receipt_id": str(approval_receipt.id),
            "phase_x_approval_receipt_hash": approval_receipt.receipt_hash,
            "rehearsal_object_key_fingerprint": key_fingerprint,
            "source_file_hash": local.file_hash,
            "source_file_size_bytes": local.file_size_bytes,
            "observed_file_hash": metadata.file_hash,
            "observed_file_size_bytes": metadata.file_size_bytes,
            "remote_etag": metadata.etag,
            "route_version_at_execution": route.route_version,
            "conditional_write_performed": conditional_write_performed,
            "rehearsal_object_routable": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
        }
    )
    execution_hash = _canonical_hash(
        {
            "organization_id": str(organization_id),
            "claim_id": str(claim_id),
            "document_id": str(document_id),
            "phase_x_authorization_id": str(authorization.id),
            "phase_x_authorization_hash": authorization.authorization_hash,
            "verification_hash": verification_hash,
            "executed_by_id": str(executed_by_id),
            "executed_at": _utc_iso(current),
            "execution_reason": normalized_reason,
            "max_rehearsal_writes": 1,
            "mode": "phase_y_bounded_non_routable_dual_write_rehearsal",
        }
    )
    execution = EvidenceRecoveryDualWriteRehearsalExecution(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        phase_x_authorization_id=authorization.id,
        phase_x_approval_receipt_id=approval_receipt.id,
        phase_w_health_qualification_id=authorization.phase_w_health_qualification_id,
        phase_v_transition_lease_id=authorization.phase_v_transition_lease_id,
        phase_u_authorization_id=authorization.phase_u_authorization_id,
        phase_t_health_qualification_id=authorization.phase_t_health_qualification_id,
        replica_id=authorization.replica_id,
        phase_x_authorization_hash=authorization.authorization_hash,
        phase_x_approval_receipt_hash=approval_receipt.receipt_hash,
        phase_w_health_qualification_hash=authorization.phase_w_health_qualification_hash,
        phase_v_transition_lease_hash=authorization.phase_v_transition_lease_hash,
        phase_u_authorization_hash=authorization.phase_u_authorization_hash,
        phase_t_health_qualification_hash=authorization.phase_t_health_qualification_hash,
        replica_hash=authorization.replica_hash,
        source_file_hash=local.file_hash,
        source_file_size_bytes=local.file_size_bytes,
        local_storage_key_fingerprint=authorization.local_storage_key_fingerprint,
        recovery_bucket_fingerprint=authorization.recovery_bucket_fingerprint,
        candidate_storage_key_fingerprint=authorization.candidate_storage_key_fingerprint,
        source_authority_fingerprint=authorization.source_authority_fingerprint,
        candidate_authority_fingerprint=authorization.candidate_authority_fingerprint,
        configuration_fingerprint=authorization.configuration_fingerprint,
        route_version_at_execution=route.route_version,
        rehearsal_object_key_fingerprint=key_fingerprint,
        observed_file_hash=metadata.file_hash,
        observed_file_size_bytes=metadata.file_size_bytes,
        remote_etag=metadata.etag,
        verification_hash=verification_hash,
        execution_hash=execution_hash,
        max_rehearsal_writes=1,
        conditional_write_performed=conditional_write_performed,
        status="executed",
        executed_by_id=executed_by_id,
        executed_at=current,
        execution_reason=normalized_reason,
        rehearsal_executed=True,
        rehearsal_write_verified=True,
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
    db.add(execution)
    db.flush()
    receipt_hash = _canonical_hash(
        {
            "execution_id": str(execution.id),
            "phase_x_authorization_id": str(authorization.id),
            "phase_x_authorization_hash": authorization.authorization_hash,
            "phase_x_approval_receipt_hash": approval_receipt.receipt_hash,
            "rehearsal_object_key_fingerprint": key_fingerprint,
            "source_file_hash": local.file_hash,
            "source_file_size_bytes": local.file_size_bytes,
            "verification_hash": verification_hash,
            "execution_hash": execution_hash,
            "conditional_write_performed": conditional_write_performed,
            "actor_id": str(executed_by_id),
            "reason": normalized_reason,
            "transitioned_at": _utc_iso(current),
            "rehearsal_object_routable": False,
            "dual_write_active": False,
            "read_path_switched": False,
            "write_path_switched": False,
            "document_storage_key_mutated": False,
            "authoritative_storage_changed": False,
            "destructive_action_performed": False,
        }
    )
    receipt = EvidenceRecoveryDualWriteRehearsalExecutionReceipt(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        execution_id=execution.id,
        phase_x_authorization_id=authorization.id,
        phase="executed",
        phase_x_authorization_hash=authorization.authorization_hash,
        phase_x_approval_receipt_hash=approval_receipt.receipt_hash,
        rehearsal_object_key_fingerprint=key_fingerprint,
        source_file_hash=local.file_hash,
        source_file_size_bytes=local.file_size_bytes,
        verification_hash=verification_hash,
        execution_hash=execution_hash,
        receipt_hash=receipt_hash,
        conditional_write_performed=conditional_write_performed,
        actor_id=executed_by_id,
        reason=normalized_reason,
        transitioned_at=current,
        rehearsal_executed=True,
        rehearsal_write_verified=True,
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
    return execution, receipt, "executed"


def get_dual_write_rehearsal_execution(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    execution_id: UUID,
):
    execution = db.scalar(
        select(EvidenceRecoveryDualWriteRehearsalExecution).where(
            EvidenceRecoveryDualWriteRehearsalExecution.id == execution_id,
            EvidenceRecoveryDualWriteRehearsalExecution.organization_id == organization_id,
            EvidenceRecoveryDualWriteRehearsalExecution.claim_id == claim_id,
            EvidenceRecoveryDualWriteRehearsalExecution.document_id == document_id,
        )
    )
    if execution is None:
        raise RecoveryDualWriteRehearsalExecutionNotFound("Phase Y rehearsal execution not found")
    return execution


def list_dual_write_rehearsal_execution_receipts(
    db: Session,
    *,
    organization_id: UUID,
    claim_id: UUID,
    document_id: UUID,
    execution_id: UUID,
):
    execution = get_dual_write_rehearsal_execution(
        db,
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        execution_id=execution_id,
    )
    return [_execution_receipt(db, execution)]
