from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.object_storage import (
    ObjectStorageError,
    ObjectStorageIntegrityError,
    ObjectStorageNotFound,
    ObjectStoragePreconditionFailed,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
)
from app.modules.external_document_sources.sftp_checkpoint_advancement_models import (
    ExternalDocumentSourceSftpCheckpointAdvancement,
)
from app.modules.external_document_sources.sftp_checkpoint_advancement_service import (
    _ensure_integrity as _ensure_checkpoint_advancement_integrity,
)
from app.modules.external_document_sources.sftp_file_content_proof_models import (
    ExternalDocumentSourceSftpFileContentProof,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    SftpFileContentReadRequest,
    _active_binding_and_profile,
    _effective_remote_path,
    _ensure_integrity as _ensure_file_content_proof_integrity,
    _load_listing_and_entry,
    _validate_adapter_result,
    get_external_document_source_sftp_file_content_read_adapter,
)
from app.modules.external_document_sources.sftp_generation3_restaging_models import (
    MAX_SFTP_GENERATION3_BYTES,
    SFTP_GENERATION3_CANDIDATE_GENERATION,
    SFTP_GENERATION3_STORAGE_PURPOSE,
    ExternalDocumentSourceSftpGeneration3Restaging,
    ExternalDocumentSourceSftpGeneration3RestagingReceipt,
)
from app.modules.external_document_sources.sftp_quarantine_staging_service import (
    _configured_store,
)
from app.modules.external_document_sources.sftp_successor_change_detection_models import (
    ExternalDocumentSourceSftpSuccessorChangeDetection,
)
from app.modules.external_document_sources.sftp_successor_change_detection_service import (
    _ensure_integrity as _ensure_successor_change_integrity,
)
from app.modules.external_document_sources.sftp_successor_restaging_models import (
    ExternalDocumentSourceSftpSuccessorRestaging,
)
from app.modules.external_document_sources.sftp_successor_restaging_service import (
    _READ_OPERATION_KIND,
    _ensure_integrity as _ensure_successor_restaging_integrity,
    _read_policy_hash,
)

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_AUTH_METHODS = frozenset({"password", "public_key"})
_ALLOWED_LATENCY_CLASSES = frozenset({"fast", "normal", "slow"})
_FALSE_FIELDS = (
    "credential_stored", "session_stored", "raw_response_stored",
    "remote_content_returned", "remote_content_logged", "content_parsed",
    "content_extracted", "remote_list_performed", "remote_stat_performed",
    "remote_write_performed", "remote_rename_performed", "remote_delete_performed",
    "remote_mkdir_performed", "remote_chmod_performed", "remote_chown_performed",
    "remote_touch_performed", "command_executed", "storage_delete_performed",
    "storage_copy_performed", "checkpoint_created", "checkpoint_advanced",
    "subscription_created", "evidence_admitted", "document_created",
    "processing_enqueued", "ai_executed", "claim_mutated",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else _aware(value).isoformat()


def _canonical_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _normalize_text(
    value: str,
    *,
    field: str,
    minimum: int,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise ExternalDocumentSourceValidationError(f"{field} must be a string")
    normalized = " ".join(value.strip().split())
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError(
            f"{field} must contain between {minimum} and {maximum} characters"
        )
    if "\x00" in normalized:
        raise ExternalDocumentSourceValidationError(
            f"{field} contains an invalid character"
        )
    return normalized


def _base_safety(stage: str) -> dict[str, bool]:
    content_verified = stage in {"content_verified", "completed"}
    completed = stage == "completed"
    return {
        "credential_reference_stored": True,
        "upstream_predecessor_checkpoint_completed": True,
        "upstream_change_detection_completed": True,
        "upstream_successor_restaging_completed": True,
        "upstream_checkpoint_advancement_completed": True,
        "upstream_successor_change_detection_completed": True,
        "successor_content_proof_completed": content_verified,
        "secret_resolution_performed": content_verified,
        "provider_network_performed": content_verified,
        "ssh_transport_performed": content_verified,
        "host_key_verification_performed": content_verified,
        "host_key_verified": content_verified,
        "authentication_performed": content_verified,
        "authentication_succeeded": content_verified,
        "sftp_session_opened": content_verified,
        "sftp_session_closed": content_verified,
        "remote_content_transiently_observed": content_verified,
        "remote_read_performed": content_verified,
        "storage_read_performed": completed,
        "storage_write_performed": completed,
        "storage_reconciliation_performed": completed,
        "durable_content_staged": completed,
        "remote_content_stored": completed,
        "generation3_restaging_completed": completed,
        **{field: False for field in _FALSE_FIELDS},
    }


def _storage_key(row: ExternalDocumentSourceSftpGeneration3Restaging) -> str:
    return (
        "external-sftp-content-quarantine-generation3/"
        f"{row.organization_id}/{row.successor_change_detection_id}/"
        f"generation-{SFTP_GENERATION3_CANDIDATE_GENERATION}/{row.id}"
    )


def _scope_hash(
    observation: ExternalDocumentSourceSftpSuccessorChangeDetection,
    advancement: ExternalDocumentSourceSftpCheckpointAdvancement,
    predecessor: ExternalDocumentSourceSftpSuccessorRestaging,
    proof: ExternalDocumentSourceSftpFileContentProof,
    *,
    storage_backend_kind: str,
    storage_object_key_hash: str,
    request_key: str,
) -> str:
    if (
        observation.completion_hash is None
        or observation.observed_projection_hash is None
        or observation.observed_byte_size is None
        or advancement.completion_hash is None
        or predecessor.completion_hash is None
        or predecessor.successor_content_proof_hash is None
    ):
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-P upstream completion facts are incomplete"
        )
    return _canonical_hash({
        "organization_id": str(observation.organization_id),
        "profile_id": str(observation.profile_id),
        "successor_change_detection_id": str(observation.id),
        "successor_change_scope_hash": observation.scope_hash,
        "successor_change_request_hash": observation.request_hash,
        "successor_change_completion_hash": observation.completion_hash,
        "observed_projection_hash": observation.observed_projection_hash,
        "observed_byte_size": observation.observed_byte_size,
        "observed_modified_at": _iso(observation.observed_modified_at),
        "observed_metadata_id_hash": observation.observed_metadata_id_hash,
        "checkpoint_advancement_id": str(advancement.id),
        "successor_checkpoint_state_hash": advancement.successor_checkpoint_state_hash,
        "successor_checkpoint_completion_hash": advancement.completion_hash,
        "predecessor_content_sha256": advancement.content_sha256,
        "predecessor_content_byte_count": advancement.content_byte_count,
        "successor_restaging_id": str(predecessor.id),
        "predecessor_candidate_content_proof_hash": predecessor.successor_content_proof_hash,
        "predecessor_candidate_completion_hash": predecessor.completion_hash,
        "predecessor_storage_object_key_hash": predecessor.storage_object_key_hash,
        "file_content_proof_id": str(proof.id),
        "proof_result_hash": proof.result_hash,
        "listing_entry_hash": proof.listing_entry_hash,
        "read_operation_kind": _READ_OPERATION_KIND,
        "read_policy_hash": _read_policy_hash(),
        "read_adapter_kind": predecessor.read_adapter_kind,
        "candidate_generation": SFTP_GENERATION3_CANDIDATE_GENERATION,
        "storage_backend_kind": storage_backend_kind,
        "storage_purpose": SFTP_GENERATION3_STORAGE_PURPOSE,
        "storage_object_key_hash": storage_object_key_hash,
        "request_key": request_key,
        "directory_list_authorized": False,
        "checkpoint_advance_authorized": False,
        "document_authorized": False,
        "evidence_authorized": False,
    })


def _request_hash(row: ExternalDocumentSourceSftpGeneration3Restaging) -> str:
    return _canonical_hash({
        "restaging_id": str(row.id),
        "scope_hash": row.scope_hash,
        "storage_object_key": row.storage_object_key,
        "requested_by_id": str(row.requested_by_id),
        "request_reason": row.request_reason,
        "requested_at": _iso(row.requested_at),
        **_base_safety("requested"),
    })


def _content_proof_hash(row: ExternalDocumentSourceSftpGeneration3Restaging) -> str:
    if (
        row.content_sha256 is None
        or row.content_byte_count is None
        or row.content_verified_at is None
        or row.content_authentication_method not in _ALLOWED_AUTH_METHODS
        or row.content_latency_class not in _ALLOWED_LATENCY_CLASSES
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 content proof is incomplete"
        )
    return _canonical_hash({
        "restaging_id": str(row.id),
        "scope_hash": row.scope_hash,
        "request_hash": row.request_hash,
        "successor_change_completion_hash": row.successor_change_completion_hash,
        "successor_checkpoint_completion_hash": row.successor_checkpoint_completion_hash,
        "predecessor_candidate_completion_hash": row.predecessor_candidate_completion_hash,
        "read_operation_kind": row.read_operation_kind,
        "read_policy_hash": row.read_policy_hash,
        "read_adapter_kind": row.read_adapter_kind,
        "candidate_generation": row.candidate_generation,
        "content_sha256": row.content_sha256,
        "content_byte_count": row.content_byte_count,
        "content_authentication_method": row.content_authentication_method,
        "content_latency_class": row.content_latency_class,
        "content_verified_at": _iso(row.content_verified_at),
        **_base_safety("content_verified"),
    })


def _completion_hash(row: ExternalDocumentSourceSftpGeneration3Restaging) -> str:
    if (
        row.status != "completed"
        or row.result_status != "generation3_staged_verified"
        or row.completed_at is None
        or row.content_sha256 is None
        or row.content_byte_count is None
        or row.content_proof_hash is None
        or row.stored_etag is None
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 completion facts are incomplete"
        )
    return _canonical_hash({
        "restaging_id": str(row.id),
        "scope_hash": row.scope_hash,
        "request_hash": row.request_hash,
        "result_status": row.result_status,
        "candidate_generation": row.candidate_generation,
        "content_sha256": row.content_sha256,
        "content_byte_count": row.content_byte_count,
        "content_proof_hash": row.content_proof_hash,
        "storage_backend_kind": row.storage_backend_kind,
        "storage_purpose": row.storage_purpose,
        "storage_object_key_hash": row.storage_object_key_hash,
        "stored_etag": row.stored_etag,
        "completed_at": _iso(row.completed_at),
        **_base_safety("completed"),
    })


def _receipt_hash(
    receipt: ExternalDocumentSourceSftpGeneration3RestagingReceipt,
) -> str:
    if receipt.event_type not in {"requested", "content_verified", "completed"}:
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 receipt stage is invalid"
        )
    return _canonical_hash({
        "organization_id": str(receipt.organization_id),
        "restaging_id": str(receipt.restaging_id),
        "sequence_number": receipt.sequence_number,
        "event_type": receipt.event_type,
        "status_after": receipt.status_after,
        "actor_id": str(receipt.actor_id),
        "occurred_at": _iso(receipt.occurred_at),
        "reason": receipt.reason,
        "scope_hash": receipt.scope_hash,
        "decision_hash": receipt.decision_hash,
        "prior_receipt_hash": receipt.prior_receipt_hash,
        **_base_safety(receipt.event_type),
    })


def _receipts(
    db: Session,
    row: ExternalDocumentSourceSftpGeneration3Restaging,
):
    return list(
        db.scalars(
            select(ExternalDocumentSourceSftpGeneration3RestagingReceipt)
            .where(
                ExternalDocumentSourceSftpGeneration3RestagingReceipt.organization_id
                == row.organization_id,
                ExternalDocumentSourceSftpGeneration3RestagingReceipt.restaging_id
                == row.id,
            )
            .order_by(
                ExternalDocumentSourceSftpGeneration3RestagingReceipt.sequence_number.asc()
            )
        ).all()
    )


def _append_receipt(
    db: Session,
    *,
    row: ExternalDocumentSourceSftpGeneration3Restaging,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    decision_hash: str,
) -> None:
    rows = _receipts(db, row)
    receipt = ExternalDocumentSourceSftpGeneration3RestagingReceipt(
        organization_id=row.organization_id,
        restaging_id=row.id,
        sequence_number=len(rows) + 1,
        event_type=event_type,
        status_after=row.status,
        actor_id=actor_id,
        occurred_at=occurred_at,
        reason=row.request_reason,
        scope_hash=row.scope_hash,
        decision_hash=decision_hash,
        prior_receipt_hash=rows[-1].receipt_hash if rows else None,
        receipt_hash="0" * 64,
        **_base_safety(event_type),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()


def _load_lineage(
    db: Session,
    row: ExternalDocumentSourceSftpGeneration3Restaging,
):
    observation = db.scalar(
        select(ExternalDocumentSourceSftpSuccessorChangeDetection).where(
            ExternalDocumentSourceSftpSuccessorChangeDetection.id
            == row.successor_change_detection_id,
            ExternalDocumentSourceSftpSuccessorChangeDetection.organization_id
            == row.organization_id,
            ExternalDocumentSourceSftpSuccessorChangeDetection.profile_id
            == row.profile_id,
        )
    )
    if observation is None:
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-O observation lineage is missing"
        )
    _ensure_successor_change_integrity(db, observation)

    advancement = db.scalar(
        select(ExternalDocumentSourceSftpCheckpointAdvancement).where(
            ExternalDocumentSourceSftpCheckpointAdvancement.id
            == row.checkpoint_advancement_id,
            ExternalDocumentSourceSftpCheckpointAdvancement.organization_id
            == row.organization_id,
            ExternalDocumentSourceSftpCheckpointAdvancement.profile_id
            == row.profile_id,
        )
    )
    if advancement is None:
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-N checkpoint lineage is missing"
        )
    _ensure_checkpoint_advancement_integrity(db, advancement)

    predecessor = db.scalar(
        select(ExternalDocumentSourceSftpSuccessorRestaging).where(
            ExternalDocumentSourceSftpSuccessorRestaging.id
            == row.successor_restaging_id,
            ExternalDocumentSourceSftpSuccessorRestaging.organization_id
            == row.organization_id,
            ExternalDocumentSourceSftpSuccessorRestaging.profile_id
            == row.profile_id,
        )
    )
    if predecessor is None:
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-M successor candidate lineage is missing"
        )
    _ensure_successor_restaging_integrity(db, predecessor, verify_storage=False)

    proof = db.scalar(
        select(ExternalDocumentSourceSftpFileContentProof).where(
            ExternalDocumentSourceSftpFileContentProof.id == row.file_content_proof_id,
            ExternalDocumentSourceSftpFileContentProof.organization_id
            == row.organization_id,
            ExternalDocumentSourceSftpFileContentProof.profile_id == row.profile_id,
        )
    )
    if proof is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP file-content proof lineage is missing"
        )
    _ensure_file_content_proof_integrity(db, proof)
    return observation, advancement, predecessor, proof


def _lineage_facts_valid(
    row: ExternalDocumentSourceSftpGeneration3Restaging,
    observation: ExternalDocumentSourceSftpSuccessorChangeDetection,
    advancement: ExternalDocumentSourceSftpCheckpointAdvancement,
    predecessor: ExternalDocumentSourceSftpSuccessorRestaging,
    proof: ExternalDocumentSourceSftpFileContentProof,
) -> bool:
    return (
        observation.result_status == "changed"
        and observation.observed_projection_hash is not None
        and observation.observed_byte_size is not None
        and observation.completion_hash is not None
        and row.checkpoint_advancement_id == observation.checkpoint_advancement_id
        and row.checkpoint_advancement_id == advancement.id
        and row.successor_restaging_id == observation.successor_restaging_id
        and row.successor_restaging_id == advancement.successor_restaging_id
        and row.successor_restaging_id == predecessor.id
        and row.predecessor_checkpoint_id == observation.predecessor_checkpoint_id
        and row.predecessor_checkpoint_id == advancement.predecessor_checkpoint_id
        and row.predecessor_checkpoint_id == predecessor.checkpoint_id
        and row.change_detection_id == observation.change_detection_id
        and row.change_detection_id == advancement.change_detection_id
        and row.change_detection_id == predecessor.change_detection_id
        and row.quarantine_staging_id == advancement.quarantine_staging_id
        and row.quarantine_staging_id == predecessor.quarantine_staging_id
        and row.file_content_proof_id == advancement.file_content_proof_id
        and row.file_content_proof_id == predecessor.file_content_proof_id
        and row.file_content_proof_id == proof.id
        and row.directory_listing_id == advancement.directory_listing_id
        and row.directory_listing_id == predecessor.directory_listing_id
        and row.directory_listing_id == proof.directory_listing_id
        and row.listing_entry_id == advancement.listing_entry_id
        and row.listing_entry_id == predecessor.listing_entry_id
        and row.listing_entry_id == proof.listing_entry_id
        and row.session_activation_id == predecessor.session_activation_id
        and row.credential_reference_binding_id
        == predecessor.credential_reference_binding_id
        and row.provider_kind == "sftp"
        and row.profile_hash == observation.profile_hash
        and row.profile_hash == advancement.profile_hash
        and row.profile_hash == predecessor.profile_hash
        and row.locator_hash == predecessor.locator_hash
        and row.authentication_kind == predecessor.authentication_kind
        and row.reference_backend == predecessor.reference_backend
        and row.destination_hostname == predecessor.destination_hostname
        and row.destination_port == predecessor.destination_port
        and row.pinned_host_key_fingerprint
        == predecessor.pinned_host_key_fingerprint
        and row.remote_root_path_hash == predecessor.remote_root_path_hash
        and row.successor_checkpoint_state_hash
        == advancement.successor_checkpoint_state_hash
        and row.successor_checkpoint_completion_hash == advancement.completion_hash
        and row.predecessor_content_sha256 == advancement.content_sha256
        and row.predecessor_content_byte_count == advancement.content_byte_count
        and row.predecessor_content_sha256 == predecessor.successor_content_sha256
        and row.predecessor_content_byte_count
        == predecessor.successor_content_byte_count
        and row.predecessor_storage_object_key_hash
        == predecessor.storage_object_key_hash
        and row.predecessor_candidate_completion_hash == predecessor.completion_hash
        and row.successor_change_scope_hash == observation.scope_hash
        and row.successor_change_request_hash == observation.request_hash
        and row.successor_change_completion_hash == observation.completion_hash
        and row.observed_projection_hash == observation.observed_projection_hash
        and row.observed_byte_size == observation.observed_byte_size
        and (
            (row.observed_modified_at is None)
            == (observation.observed_modified_at is None)
        )
        and (
            row.observed_modified_at is None
            or _aware(row.observed_modified_at)
            == _aware(observation.observed_modified_at)
        )
        and row.observed_metadata_id_hash == observation.observed_metadata_id_hash
        and row.listing_entry_hash == proof.listing_entry_hash
        and row.read_operation_kind == _READ_OPERATION_KIND
        and row.read_policy_hash == _read_policy_hash()
        and row.read_adapter_kind == predecessor.read_adapter_kind
        and row.read_adapter_kind == proof.read_adapter_kind
        and row.candidate_generation == SFTP_GENERATION3_CANDIDATE_GENERATION
        and row.storage_backend_kind == predecessor.storage_backend_kind
        and row.storage_purpose == SFTP_GENERATION3_STORAGE_PURPOSE
        and row.storage_object_key == _storage_key(row)
        and row.storage_object_key_hash
        == hashlib.sha256(row.storage_object_key.encode("utf-8")).hexdigest()
    )


def _verify_storage_object(
    store,
    row: ExternalDocumentSourceSftpGeneration3Restaging,
):
    if row.content_sha256 is None or row.content_byte_count is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 content proof is not available for storage reconciliation"
        )
    try:
        metadata = store.head_object(storage_key=row.storage_object_key)
        digest = metadata.file_hash.lower()
        byte_count = metadata.file_size_bytes
        if (
            not _HEX_64.fullmatch(digest)
            or digest != row.content_sha256
            or digest == row.predecessor_content_sha256
            or byte_count != row.content_byte_count
            or byte_count != row.observed_byte_size
            or byte_count < 0
            or byte_count > MAX_SFTP_GENERATION3_BYTES
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP generation-3 quarantine object does not match the committed content proof"
            )
        payload = store.get_bytes(
            storage_key=row.storage_object_key,
            expected_sha256=digest,
        )
        if (
            len(payload) != byte_count
            or hashlib.sha256(payload).hexdigest() != digest
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP generation-3 quarantine object failed digest reconciliation"
            )
        del payload
        return metadata
    except (ObjectStorageNotFound, ExternalDocumentSourceConflictError):
        raise
    except (ObjectStorageError, ObjectStorageIntegrityError):
        raise ExternalDocumentSourceConflictError(
            "Governed SFTP generation-3 quarantine verification failed"
        ) from None


def _ensure_integrity(
    db: Session,
    row: ExternalDocumentSourceSftpGeneration3Restaging,
    *,
    verify_storage: bool,
) -> None:
    observation, advancement, predecessor, proof = _load_lineage(db, row)
    if not _lineage_facts_valid(row, observation, advancement, predecessor, proof):
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 restaging lineage drifted"
        )
    if (
        row.observed_byte_size < 0
        or row.observed_byte_size > MAX_SFTP_GENERATION3_BYTES
    ):
        raise ExternalDocumentSourceConflictError(
            "Observed SFTP file exceeds the generation-3 restaging byte bound"
        )

    expected_scope = _scope_hash(
        observation,
        advancement,
        predecessor,
        proof,
        storage_backend_kind=row.storage_backend_kind,
        storage_object_key_hash=row.storage_object_key_hash,
        request_key=row.request_key,
    )
    if row.scope_hash != expected_scope or row.request_hash != _request_hash(row):
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 restaging request integrity failed"
        )

    receipts = _receipts(db, row)
    expected_stages = {
        "requested": ["requested"],
        "content_verified": ["requested", "content_verified"],
        "completed": ["requested", "content_verified", "completed"],
    }
    if row.status not in expected_stages or len(receipts) != len(expected_stages[row.status]):
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 receipt chain is incomplete"
        )
    prior = None
    for idx, (receipt, stage) in enumerate(
        zip(receipts, expected_stages[row.status], strict=True),
        start=1,
    ):
        decision = (
            row.request_hash
            if stage == "requested"
            else row.content_proof_hash
            if stage == "content_verified"
            else row.completion_hash
        )
        occurred = (
            row.requested_at
            if stage == "requested"
            else row.content_verified_at
            if stage == "content_verified"
            else row.completed_at
        )
        if (
            receipt.sequence_number != idx
            or receipt.event_type != stage
            or receipt.status_after != stage
            or receipt.actor_id != row.requested_by_id
            or occurred is None
            or _aware(receipt.occurred_at) != _aware(occurred)
            or receipt.reason != row.request_reason
            or receipt.scope_hash != row.scope_hash
            or receipt.decision_hash != decision
            or receipt.prior_receipt_hash != prior
            or receipt.receipt_hash != _receipt_hash(receipt)
        ):
            raise ExternalDocumentSourceConflictError(
                "SFTP generation-3 receipt integrity failed"
            )
        for field, expected in _base_safety(stage).items():
            if bool(getattr(receipt, field)) != expected:
                raise ExternalDocumentSourceConflictError(
                    "SFTP generation-3 receipt safety boundary drifted"
                )
        prior = receipt.receipt_hash

    if row.status == "requested":
        if any(value is not None for value in (
            row.result_status, row.content_sha256, row.content_byte_count,
            row.content_authentication_method, row.content_latency_class,
            row.content_proof_hash, row.content_verified_at, row.stored_etag,
            row.completed_at, row.completion_hash,
        )):
            raise ExternalDocumentSourceConflictError(
                "SFTP generation-3 requested lifecycle drifted"
            )
        for field, expected in _base_safety("requested").items():
            if bool(getattr(row, field)) != expected:
                raise ExternalDocumentSourceConflictError(
                    "SFTP generation-3 requested safety boundary drifted"
                )
        return

    if (
        row.content_sha256 is None
        or not _HEX_64.fullmatch(row.content_sha256)
        or row.content_sha256 == row.predecessor_content_sha256
        or row.content_byte_count != row.observed_byte_size
        or row.content_authentication_method not in _ALLOWED_AUTH_METHODS
        or row.content_latency_class not in _ALLOWED_LATENCY_CLASSES
        or row.content_proof_hash != _content_proof_hash(row)
        or row.content_verified_at is None
        or _aware(row.content_verified_at) < _aware(row.requested_at)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 content proof integrity failed"
        )

    if row.status == "content_verified":
        if any(value is not None for value in (
            row.result_status, row.stored_etag, row.completed_at, row.completion_hash
        )):
            raise ExternalDocumentSourceConflictError(
                "SFTP generation-3 content-verified lifecycle drifted"
            )
        for field, expected in _base_safety("content_verified").items():
            if bool(getattr(row, field)) != expected:
                raise ExternalDocumentSourceConflictError(
                    "SFTP generation-3 content-verified safety boundary drifted"
                )
        return

    if (
        row.status != "completed"
        or row.result_status != "generation3_staged_verified"
        or row.stored_etag is None
        or row.completed_at is None
        or _aware(row.completed_at) < _aware(row.content_verified_at)
        or row.completion_hash != _completion_hash(row)
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 completion integrity failed"
        )
    for field, expected in _base_safety("completed").items():
        if bool(getattr(row, field)) != expected:
            raise ExternalDocumentSourceConflictError(
                "SFTP generation-3 completed safety boundary drifted"
            )
    if verify_storage:
        metadata = _verify_storage_object(_configured_store(), row)
        if metadata.etag != row.stored_etag:
            raise ExternalDocumentSourceConflictError(
                "SFTP generation-3 stored-object ETag drifted"
            )


def _complete_from_storage(
    db: Session,
    row: ExternalDocumentSourceSftpGeneration3Restaging,
    *,
    metadata,
    completed_at: datetime,
) -> None:
    row.status = "completed"
    row.result_status = "generation3_staged_verified"
    row.stored_etag = metadata.etag
    row.completed_at = completed_at
    for field, value in _base_safety("completed").items():
        setattr(row, field, value)
    row.completion_hash = _completion_hash(row)
    _append_receipt(
        db,
        row=row,
        event_type="completed",
        actor_id=row.requested_by_id,
        occurred_at=completed_at,
        decision_hash=row.completion_hash,
    )
    db.flush()
    _ensure_integrity(db, row, verify_storage=False)


def _get_observation(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    observation_id: UUID,
    for_update: bool = False,
):
    stmt = select(ExternalDocumentSourceSftpSuccessorChangeDetection).where(
        ExternalDocumentSourceSftpSuccessorChangeDetection.id == observation_id,
        ExternalDocumentSourceSftpSuccessorChangeDetection.organization_id
        == organization_id,
        ExternalDocumentSourceSftpSuccessorChangeDetection.profile_id == profile_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        raise ExternalDocumentSourceNotFoundError(
            "Phase 17.6-O SFTP successor change detection not found"
        )
    _ensure_successor_change_integrity(db, row)
    return row


def execute_external_document_source_sftp_generation3_restaging(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    successor_change_detection_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    normalized_key = _normalize_text(
        request_key, field="request_key", minimum=1, maximum=128
    )
    normalized_reason = _normalize_text(
        request_reason, field="reason", minimum=8, maximum=2000
    )
    store = _configured_store()
    backend = getattr(store.sanitized_health_identity, "backend", None)
    if not isinstance(backend, str) or not _SAFE_IDENTIFIER.fullmatch(backend):
        raise ExternalDocumentSourceConflictError(
            "Governed SFTP generation-3 storage backend identity is invalid"
        )

    existing = db.scalar(
        select(ExternalDocumentSourceSftpGeneration3Restaging)
        .where(
            ExternalDocumentSourceSftpGeneration3Restaging.organization_id
            == organization_id,
            ExternalDocumentSourceSftpGeneration3Restaging.profile_id == profile_id,
            ExternalDocumentSourceSftpGeneration3Restaging.successor_change_detection_id
            == successor_change_detection_id,
        )
        .with_for_update()
    )
    if existing is not None:
        _ensure_integrity(
            db,
            existing,
            verify_storage=existing.status == "completed",
        )
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError(
                "Conflicting replay or second consumption for SFTP generation-3 restaging"
            )
        if existing.status == "completed":
            return existing, "unchanged"
        row = existing
        observation, advancement, predecessor, proof = _load_lineage(db, row)
    else:
        collision = db.scalar(
            select(ExternalDocumentSourceSftpGeneration3Restaging).where(
                ExternalDocumentSourceSftpGeneration3Restaging.organization_id
                == organization_id,
                ExternalDocumentSourceSftpGeneration3Restaging.profile_id == profile_id,
                ExternalDocumentSourceSftpGeneration3Restaging.request_key
                == normalized_key,
            )
        )
        if collision is not None:
            raise ExternalDocumentSourceConflictError(
                "Conflicting replay for SFTP generation-3 restaging request_key"
            )

        observation = _get_observation(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            observation_id=successor_change_detection_id,
            for_update=True,
        )
        if (
            observation.result_status != "changed"
            or observation.observed_projection_hash is None
            or observation.observed_byte_size is None
        ):
            raise ExternalDocumentSourceConflictError(
                "Only an exact completed Phase 17.6-O changed observation is eligible for generation-3 restaging"
            )
        if (
            observation.observed_byte_size < 0
            or observation.observed_byte_size > MAX_SFTP_GENERATION3_BYTES
        ):
            raise ExternalDocumentSourceConflictError(
                "Changed SFTP file exceeds the Phase 17.6-P byte bound"
            )

        advancement = db.scalar(
            select(ExternalDocumentSourceSftpCheckpointAdvancement).where(
                ExternalDocumentSourceSftpCheckpointAdvancement.id
                == observation.checkpoint_advancement_id,
                ExternalDocumentSourceSftpCheckpointAdvancement.organization_id
                == organization_id,
                ExternalDocumentSourceSftpCheckpointAdvancement.profile_id
                == profile_id,
            )
        )
        if advancement is None:
            raise ExternalDocumentSourceConflictError(
                "Phase 17.6-N checkpoint lineage is missing"
            )
        _ensure_checkpoint_advancement_integrity(db, advancement)

        predecessor = db.scalar(
            select(ExternalDocumentSourceSftpSuccessorRestaging).where(
                ExternalDocumentSourceSftpSuccessorRestaging.id
                == observation.successor_restaging_id,
                ExternalDocumentSourceSftpSuccessorRestaging.organization_id
                == organization_id,
                ExternalDocumentSourceSftpSuccessorRestaging.profile_id == profile_id,
            )
        )
        if predecessor is None:
            raise ExternalDocumentSourceConflictError(
                "Phase 17.6-M successor candidate lineage is missing"
            )
        _ensure_successor_restaging_integrity(db, predecessor, verify_storage=False)
        if backend != predecessor.storage_backend_kind:
            raise ExternalDocumentSourceConflictError(
                "Phase 17.6-P governed storage backend drifted from Phase 17.6-M"
            )

        proof = db.scalar(
            select(ExternalDocumentSourceSftpFileContentProof).where(
                ExternalDocumentSourceSftpFileContentProof.id
                == predecessor.file_content_proof_id,
                ExternalDocumentSourceSftpFileContentProof.organization_id
                == organization_id,
                ExternalDocumentSourceSftpFileContentProof.profile_id == profile_id,
            )
        )
        if proof is None:
            raise ExternalDocumentSourceConflictError(
                "SFTP file-content proof lineage is missing"
            )
        _ensure_file_content_proof_integrity(db, proof)

        current = _aware(now or _utc_now())
        row = ExternalDocumentSourceSftpGeneration3Restaging(
            id=uuid4(),
            organization_id=organization_id,
            profile_id=profile_id,
            successor_change_detection_id=observation.id,
            checkpoint_advancement_id=advancement.id,
            successor_restaging_id=predecessor.id,
            predecessor_checkpoint_id=advancement.predecessor_checkpoint_id,
            change_detection_id=advancement.change_detection_id,
            quarantine_staging_id=predecessor.quarantine_staging_id,
            file_content_proof_id=proof.id,
            directory_listing_id=predecessor.directory_listing_id,
            listing_entry_id=predecessor.listing_entry_id,
            session_activation_id=predecessor.session_activation_id,
            credential_reference_binding_id=predecessor.credential_reference_binding_id,
            provider_kind="sftp",
            profile_hash=observation.profile_hash,
            locator_hash=predecessor.locator_hash,
            authentication_kind=predecessor.authentication_kind,
            reference_backend=predecessor.reference_backend,
            destination_hostname=predecessor.destination_hostname,
            destination_port=predecessor.destination_port,
            pinned_host_key_fingerprint=predecessor.pinned_host_key_fingerprint,
            remote_root_path_hash=predecessor.remote_root_path_hash,
            successor_checkpoint_state_hash=advancement.successor_checkpoint_state_hash,
            successor_checkpoint_completion_hash=advancement.completion_hash,
            predecessor_content_sha256=advancement.content_sha256,
            predecessor_content_byte_count=advancement.content_byte_count,
            predecessor_storage_object_key_hash=predecessor.storage_object_key_hash,
            predecessor_candidate_completion_hash=predecessor.completion_hash,
            successor_change_scope_hash=observation.scope_hash,
            successor_change_request_hash=observation.request_hash,
            successor_change_completion_hash=observation.completion_hash,
            observed_projection_hash=observation.observed_projection_hash,
            observed_byte_size=observation.observed_byte_size,
            observed_modified_at=(
                _aware(observation.observed_modified_at)
                if observation.observed_modified_at is not None
                else None
            ),
            observed_metadata_id_hash=observation.observed_metadata_id_hash,
            listing_entry_hash=proof.listing_entry_hash,
            read_operation_kind=_READ_OPERATION_KIND,
            read_policy_hash=_read_policy_hash(),
            read_adapter_kind=predecessor.read_adapter_kind,
            candidate_generation=SFTP_GENERATION3_CANDIDATE_GENERATION,
            storage_backend_kind=backend,
            storage_purpose=SFTP_GENERATION3_STORAGE_PURPOSE,
            storage_object_key="pending",
            storage_object_key_hash="0" * 64,
            request_key=normalized_key,
            scope_hash="0" * 64,
            request_hash="0" * 64,
            status="requested",
            result_status=None,
            content_sha256=None,
            content_byte_count=None,
            content_authentication_method=None,
            content_latency_class=None,
            content_proof_hash=None,
            content_verified_at=None,
            stored_etag=None,
            requested_by_id=requested_by_id,
            request_reason=normalized_reason,
            requested_at=current,
            completed_at=None,
            completion_hash=None,
            **_base_safety("requested"),
        )
        db.add(row)
        db.flush()
        row.storage_object_key = _storage_key(row)
        row.storage_object_key_hash = hashlib.sha256(
            row.storage_object_key.encode("utf-8")
        ).hexdigest()
        row.scope_hash = _scope_hash(
            observation,
            advancement,
            predecessor,
            proof,
            storage_backend_kind=backend,
            storage_object_key_hash=row.storage_object_key_hash,
            request_key=normalized_key,
        )
        row.request_hash = _request_hash(row)
        _append_receipt(
            db,
            row=row,
            event_type="requested",
            actor_id=requested_by_id,
            occurred_at=current,
            decision_hash=row.request_hash,
        )
        _ensure_integrity(db, row, verify_storage=False)

        # Persist the replay/recovery anchor before any external I/O.
        db.commit()
        row = db.scalar(
            select(ExternalDocumentSourceSftpGeneration3Restaging)
            .where(
                ExternalDocumentSourceSftpGeneration3Restaging.id == row.id,
                ExternalDocumentSourceSftpGeneration3Restaging.organization_id
                == organization_id,
                ExternalDocumentSourceSftpGeneration3Restaging.profile_id == profile_id,
            )
            .with_for_update()
        )
        if row is None:
            raise ExternalDocumentSourceConflictError(
                "SFTP generation-3 recovery anchor disappeared"
            )
        _ensure_integrity(db, row, verify_storage=row.status == "completed")
        if row.status == "completed":
            return row, "unchanged"
        observation, advancement, predecessor, proof = _load_lineage(db, row)

    if row.status == "content_verified":
        try:
            metadata = _verify_storage_object(store, row)
        except ObjectStorageNotFound:
            metadata = None
        if metadata is not None:
            completed_at = max(_aware(row.content_verified_at), _utc_now())
            _complete_from_storage(
                db,
                row,
                metadata=metadata,
                completed_at=completed_at,
            )
            return row, "completed"

    listing, entry = _load_listing_and_entry(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        listing_id=proof.directory_listing_id,
        entry_id=proof.listing_entry_id,
        for_update=False,
    )
    binding, normalized = _active_binding_and_profile(db, listing)
    if (
        binding.id != row.credential_reference_binding_id
        or listing.id != row.directory_listing_id
        or entry.id != row.listing_entry_id
        or entry.entry_kind != "file"
    ):
        raise ExternalDocumentSourceConflictError(
            "SFTP generation-3 active path/credential lineage drifted"
        )
    adapter = get_external_document_source_sftp_file_content_read_adapter()
    if adapter is None:
        raise ExternalDocumentSourceConflictError(
            "SFTP content-read adapter is unavailable for Phase 17.6-P"
        )
    if getattr(adapter, "adapter_kind", None) != row.read_adapter_kind:
        raise ExternalDocumentSourceConflictError(
            "Phase 17.6-P SFTP reread adapter drifted from prior verified lineage"
        )

    request = SftpFileContentReadRequest(
        hostname=listing.destination_hostname,
        port=listing.destination_port,
        username=normalized["username"],
        pinned_host_key_fingerprint=listing.pinned_host_key_fingerprint,
        authentication_kind=binding.authentication_kind,
        reference_backend=binding.reference_backend,
        reference_namespace=binding.reference_namespace,
        reference_name=binding.reference_name,
        reference_version=binding.reference_version,
        remote_root_path=normalized["remote_root_path"],
        entry_relative_path=entry.relative_path,
        effective_remote_path=_effective_remote_path(
            normalized["remote_root_path"],
            entry.relative_path,
        ),
    )

    transient_result = None
    payload: bytes | None = None
    try:
        try:
            transient_result = adapter.read_content(request)
        except Exception:
            raise ExternalDocumentSourceConflictError(
                "SFTP generation-3 successor reread failed"
            ) from None

        payload, authentication_method, latency_class = _validate_adapter_result(
            transient_result,
            expected_auth_kind=binding.authentication_kind,
            declared_byte_size=observation.observed_byte_size,
        )
        digest = hashlib.sha256(payload).hexdigest()
        byte_count = len(payload)
        if (
            byte_count != observation.observed_byte_size
            or byte_count > MAX_SFTP_GENERATION3_BYTES
        ):
            raise ExternalDocumentSourceConflictError(
                "Phase 17.6-P reread does not match the Phase 17.6-O observed byte size"
            )
        if digest == advancement.content_sha256:
            raise ExternalDocumentSourceConflictError(
                "Phase 17.6-P reread produced the generation-2 checkpoint digest; no generation-3 content version exists"
            )
        if authentication_method != proof.authentication_method:
            raise ExternalDocumentSourceConflictError(
                "Phase 17.6-P authentication method drifted from the prior content-proof lineage"
            )

        if row.status == "requested":
            content_verified_at = max(_aware(row.requested_at), _utc_now())
            row.status = "content_verified"
            row.content_sha256 = digest
            row.content_byte_count = byte_count
            row.content_authentication_method = authentication_method
            row.content_latency_class = latency_class
            row.content_verified_at = content_verified_at
            for field, value in _base_safety("content_verified").items():
                setattr(row, field, value)
            row.content_proof_hash = _content_proof_hash(row)
            _append_receipt(
                db,
                row=row,
                event_type="content_verified",
                actor_id=requested_by_id,
                occurred_at=content_verified_at,
                decision_hash=row.content_proof_hash,
            )
            db.flush()
            _ensure_integrity(db, row, verify_storage=False)

            # Critical boundary: content proof is durable before first PUT.
            db.commit()

            # Re-acquire the execution lock after the proof commit. This closes
            # the commit/PUT race: a concurrent replay that wins this lock
            # becomes the sole reconciler, and this caller will observe its
            # completed state instead of issuing a duplicate provider read/PUT.
            row = db.scalar(
                select(ExternalDocumentSourceSftpGeneration3Restaging)
                .where(
                    ExternalDocumentSourceSftpGeneration3Restaging.id == row.id,
                    ExternalDocumentSourceSftpGeneration3Restaging.organization_id
                    == organization_id,
                    ExternalDocumentSourceSftpGeneration3Restaging.profile_id
                    == profile_id,
                )
                .with_for_update()
            )
            if row is None:
                raise ExternalDocumentSourceConflictError(
                    "SFTP generation-3 content-proof anchor disappeared"
                )
            _ensure_integrity(
                db,
                row,
                verify_storage=row.status == "completed",
            )
            if row.status == "completed":
                return row, "unchanged"
            if row.status != "content_verified":
                raise ExternalDocumentSourceConflictError(
                    "SFTP generation-3 content-proof lifecycle changed unexpectedly"
                )
        else:
            if (
                row.status != "content_verified"
                or digest != row.content_sha256
                or byte_count != row.content_byte_count
                or authentication_method != row.content_authentication_method
                or latency_class != row.content_latency_class
            ):
                raise ExternalDocumentSourceConflictError(
                    "SFTP generation-3 recovery reread no longer matches the committed content proof"
                )

        try:
            store.put_bytes_if_absent(
                payload,
                storage_key=row.storage_object_key,
                expected_sha256=row.content_sha256,
            )
        except ObjectStoragePreconditionFailed:
            pass
        except ObjectStorageError:
            raise ExternalDocumentSourceConflictError(
                "Governed SFTP generation-3 quarantine storage write failed"
            ) from None
    finally:
        if payload is not None:
            del payload
        if transient_result is not None:
            del transient_result

    metadata = _verify_storage_object(store, row)
    completed_at = max(_aware(row.content_verified_at), _utc_now())
    _complete_from_storage(
        db,
        row,
        metadata=metadata,
        completed_at=completed_at,
    )
    return row, "completed"


def get_external_document_source_sftp_generation3_restaging(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    restaging_id: UUID,
):
    row = db.scalar(
        select(ExternalDocumentSourceSftpGeneration3Restaging).where(
            ExternalDocumentSourceSftpGeneration3Restaging.id == restaging_id,
            ExternalDocumentSourceSftpGeneration3Restaging.organization_id
            == organization_id,
            ExternalDocumentSourceSftpGeneration3Restaging.profile_id == profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceNotFoundError(
            "SFTP generation-3 restaging execution not found"
        )
    _ensure_integrity(
        db,
        row,
        verify_storage=row.status == "completed",
    )
    return row


def list_external_document_source_sftp_generation3_restaging_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    restaging_id: UUID,
):
    row = get_external_document_source_sftp_generation3_restaging(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        restaging_id=restaging_id,
    )
    return _receipts(db, row)
