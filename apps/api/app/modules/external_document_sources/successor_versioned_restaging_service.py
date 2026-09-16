from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.object_storage import (
    ObjectStorageError,
    ObjectStorageIntegrityError,
    ObjectStorageNotFound,
    ObjectStoragePreconditionFailed,
)
from app.modules.external_document_sources.credential_reference_health_service import CredentialReferenceLocator
from app.modules.external_document_sources.remote_content_staging_service import _configured_store
from app.modules.external_document_sources.remote_file_content_read_service import (
    _ALLOWED_LATENCY_CLASSES,
    _READ_ADAPTERS,
    _active_binding,
    _endpoint_policy_hash,
    _normalize_hash,
    _normalize_media_type,
    _read_policy,
)
from app.modules.external_document_sources.remote_metadata_listing_models import (
    ExternalDocumentSourceRemoteMetadataListingExecution,
    ExternalDocumentSourceRemoteMetadataListingItem,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
    _ensure_profile_integrity,
    _get_profile,
)
from app.modules.external_document_sources.successor_change_detection_models import (
    ExternalDocumentSourceSuccessorChangeDetectionExecution,
)
from app.modules.external_document_sources.successor_change_detection_service import (
    _ensure_integrity as _ensure_successor_change_integrity,
)
from app.modules.external_document_sources.successor_versioned_restaging_models import (
    MAX_SUCCESSOR_VERSIONED_RESTAGING_BYTES,
    SUCCESSOR_CANDIDATE_GENERATION,
    SUCCESSOR_VERSIONED_STORAGE_PURPOSE,
    ExternalDocumentSourceSuccessorVersionedRestagingExecution,
    ExternalDocumentSourceSuccessorVersionedRestagingReceipt,
)

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


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
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _normalize_text(value: str, *, field: str, minimum: int, maximum: int) -> str:
    normalized = " ".join(value.strip().split())
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError(
            f"{field} must contain between {minimum} and {maximum} characters"
        )
    if "\x00" in normalized:
        raise ExternalDocumentSourceValidationError(f"{field} contains an invalid character")
    return normalized


def _base_safety(stage: str) -> dict[str, bool]:
    content_verified = stage in {"content_verified", "completed"}
    completed = stage == "completed"
    return {
        "credential_reference_stored": True,
        "credential_reference_resolution_performed": True,
        "activation_authorization_consumed": True,
        "upstream_token_acquisition_completed": True,
        "upstream_provider_client_health_completed": True,
        "upstream_remote_metadata_listing_completed": True,
        "upstream_remote_file_content_read_completed": True,
        "upstream_remote_content_staging_completed": True,
        "upstream_sync_checkpoint_completed": True,
        "upstream_change_detection_completed": True,
        "upstream_versioned_restaging_completed": True,
        "upstream_checkpoint_generation_advance_completed": True,
        "upstream_successor_change_detection_completed": True,
        "provider_client_constructed": content_verified,
        "remote_content_transiently_observed": content_verified,
        "remote_read_performed": content_verified,
        "storage_read_performed": completed,
        "storage_write_performed": completed,
        "durable_content_staged": completed,
        "remote_content_stored": completed,
        "successor_versioned_restaging_completed": completed,
        "credential_stored": False,
        "oauth_authorization_code_stored": False,
        "access_token_stored": False,
        "refresh_token_stored": False,
        "id_token_stored": False,
        "client_secret_stored": False,
        "private_key_stored": False,
        "provider_client_stored": False,
        "provider_response_body_stored": False,
        "remote_content_returned": False,
        "remote_content_logged": False,
        "content_parsed": False,
        "content_extracted": False,
        "remote_list_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "storage_delete_performed": False,
        "checkpoint_created": False,
        "checkpoint_advanced": False,
        "sync_executed": False,
        "subscription_created": False,
        "evidence_admitted": False,
        "document_created": False,
        "claim_mutated": False,
    }


def _storage_key(execution: ExternalDocumentSourceSuccessorVersionedRestagingExecution) -> str:
    return (
        f"external-remote-content-versioned-quarantine/{execution.organization_id}/"
        f"{execution.successor_change_detection_execution_id}/generation-{SUCCESSOR_CANDIDATE_GENERATION}/{execution.id}"
    )


def _scope_hash(
    change: ExternalDocumentSourceSuccessorChangeDetectionExecution,
    *,
    read_operation_kind: str,
    read_adapter_kind: str,
    endpoint_policy_hash: str,
    storage_backend_kind: str,
    storage_object_key_hash: str,
    request_key: str,
) -> str:
    if (
        change.completion_hash is None
        or change.observed_projection_hash is None
        or change.observed_provider_item_id_hash is None
    ):
        raise ExternalDocumentSourceConflictError("Phase S changed observation completion facts are incomplete")
    return _canonical_hash(
        {
            "organization_id": str(change.organization_id),
            "profile_id": str(change.profile_id),
            "successor_change_detection_execution_id": str(change.id),
            "checkpoint_generation_execution_id": str(change.checkpoint_generation_execution_id),
            "versioned_restaging_execution_id": str(change.versioned_restaging_execution_id),
            "predecessor_sync_checkpoint_execution_id": str(change.predecessor_sync_checkpoint_execution_id),
            "change_detection_execution_id": str(change.change_detection_execution_id),
            "listing_execution_id": str(change.listing_execution_id),
            "metadata_item_id": str(change.metadata_item_id),
            "provider_kind": change.provider_kind,
            "profile_hash": change.profile_hash,
            "successor_change_scope_hash": change.scope_hash,
            "successor_change_request_hash": change.request_hash,
            "successor_change_completion_hash": change.completion_hash,
            "successor_checkpoint_state_hash": change.successor_checkpoint_state_hash,
            "successor_checkpoint_completion_hash": change.successor_checkpoint_completion_hash,
            "observed_projection_hash": change.observed_projection_hash,
            "observed_provider_item_id_hash": change.observed_provider_item_id_hash,
            "observed_version_token_hash": change.observed_version_token_hash,
            "observed_byte_size": change.observed_byte_size,
            "observed_mime_type_class": change.observed_mime_type_class,
            "read_operation_kind": read_operation_kind,
            "read_adapter_kind": read_adapter_kind,
            "endpoint_policy_hash": endpoint_policy_hash,
            "candidate_generation": SUCCESSOR_CANDIDATE_GENERATION,
            "storage_backend_kind": storage_backend_kind,
            "storage_purpose": SUCCESSOR_VERSIONED_STORAGE_PURPOSE,
            "storage_object_key_hash": storage_object_key_hash,
            "request_key": request_key,
        }
    )


def _request_hash(execution: ExternalDocumentSourceSuccessorVersionedRestagingExecution) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "requested_by_id": str(execution.requested_by_id),
            "request_reason": execution.request_reason,
            "requested_at": _iso(execution.requested_at),
            **_base_safety("requested"),
        }
    )


def _content_proof_hash(execution: ExternalDocumentSourceSuccessorVersionedRestagingExecution) -> str:
    if (
        execution.content_sha256 is None
        or execution.content_byte_count is None
        or execution.content_verified_at is None
        or execution.content_latency_class not in _ALLOWED_LATENCY_CLASSES
    ):
        raise ExternalDocumentSourceConflictError("Successor versioned restaging content proof is incomplete")
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "request_hash": execution.request_hash,
            "content_sha256": execution.content_sha256,
            "content_byte_count": execution.content_byte_count,
            "content_media_type_class": execution.content_media_type_class,
            "content_version_token_hash": execution.content_version_token_hash,
            "content_latency_class": execution.content_latency_class,
            "content_verified_at": _iso(execution.content_verified_at),
            **_base_safety("content_verified"),
        }
    )


def _completion_hash(execution: ExternalDocumentSourceSuccessorVersionedRestagingExecution) -> str:
    if (
        execution.completed_at is None
        or execution.result_status != "staged_candidate_verified"
        or execution.content_proof_hash is None
    ):
        raise ExternalDocumentSourceConflictError("Successor versioned restaging completion facts are incomplete")
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "request_hash": execution.request_hash,
            "content_proof_hash": execution.content_proof_hash,
            "result_status": execution.result_status,
            "candidate_generation": execution.candidate_generation,
            "storage_backend_kind": execution.storage_backend_kind,
            "storage_purpose": execution.storage_purpose,
            "storage_object_key_hash": execution.storage_object_key_hash,
            "stored_etag": execution.stored_etag,
            "completed_at": _iso(execution.completed_at),
            **_base_safety("completed"),
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceSuccessorVersionedRestagingReceipt) -> str:
    return _canonical_hash(
        {
            "organization_id": str(receipt.organization_id),
            "execution_id": str(receipt.execution_id),
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
        }
    )


def _receipts(db: Session, execution: ExternalDocumentSourceSuccessorVersionedRestagingExecution):
    return list(
        db.scalars(
            select(ExternalDocumentSourceSuccessorVersionedRestagingReceipt)
            .where(
                ExternalDocumentSourceSuccessorVersionedRestagingReceipt.organization_id == execution.organization_id,
                ExternalDocumentSourceSuccessorVersionedRestagingReceipt.execution_id == execution.id,
            )
            .order_by(ExternalDocumentSourceSuccessorVersionedRestagingReceipt.sequence_number.asc())
        ).all()
    )


def _append_receipt(
    db: Session,
    *,
    execution: ExternalDocumentSourceSuccessorVersionedRestagingExecution,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    decision_hash: str,
) -> None:
    rows = _receipts(db, execution)
    receipt = ExternalDocumentSourceSuccessorVersionedRestagingReceipt(
        organization_id=execution.organization_id,
        execution_id=execution.id,
        sequence_number=len(rows) + 1,
        event_type=event_type,
        status_after=execution.status,
        actor_id=actor_id,
        occurred_at=occurred_at,
        reason=execution.request_reason,
        scope_hash=execution.scope_hash,
        decision_hash=decision_hash,
        prior_receipt_hash=rows[-1].receipt_hash if rows else None,
        **_base_safety(event_type),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()


def _get_successor_change(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
    for_update: bool = False,
) -> ExternalDocumentSourceSuccessorChangeDetectionExecution:
    stmt = select(ExternalDocumentSourceSuccessorChangeDetectionExecution).where(
        ExternalDocumentSourceSuccessorChangeDetectionExecution.id == execution_id,
        ExternalDocumentSourceSuccessorChangeDetectionExecution.organization_id == organization_id,
        ExternalDocumentSourceSuccessorChangeDetectionExecution.profile_id == profile_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        raise ExternalDocumentSourceNotFoundError("Phase S successor change-detection execution not found")
    _ensure_successor_change_integrity(db, row)
    return row


def _listing_and_item(
    db: Session,
    change: ExternalDocumentSourceSuccessorChangeDetectionExecution,
):
    listing = db.scalar(
        select(ExternalDocumentSourceRemoteMetadataListingExecution).where(
            ExternalDocumentSourceRemoteMetadataListingExecution.id == change.listing_execution_id,
            ExternalDocumentSourceRemoteMetadataListingExecution.organization_id == change.organization_id,
            ExternalDocumentSourceRemoteMetadataListingExecution.profile_id == change.profile_id,
        )
    )
    if listing is None:
        raise ExternalDocumentSourceConflictError("Phase T metadata-listing lineage is missing")
    item = db.scalar(
        select(ExternalDocumentSourceRemoteMetadataListingItem).where(
            ExternalDocumentSourceRemoteMetadataListingItem.id == change.metadata_item_id,
            ExternalDocumentSourceRemoteMetadataListingItem.organization_id == change.organization_id,
            ExternalDocumentSourceRemoteMetadataListingItem.execution_id == listing.id,
        )
    )
    if item is None:
        raise ExternalDocumentSourceConflictError("Phase T metadata-item lineage is missing")
    if (
        item.item_kind != "file"
        or change.observed_provider_item_id_hash is None
        or hashlib.sha256(item.provider_item_id.encode("utf-8")).hexdigest()
        != change.observed_provider_item_id_hash
    ):
        raise ExternalDocumentSourceConflictError("Phase S exact file identity is not eligible for successor restaging")
    return listing, item


def _get_execution(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    row = db.scalar(
        select(ExternalDocumentSourceSuccessorVersionedRestagingExecution).where(
            ExternalDocumentSourceSuccessorVersionedRestagingExecution.id == execution_id,
            ExternalDocumentSourceSuccessorVersionedRestagingExecution.organization_id == organization_id,
            ExternalDocumentSourceSuccessorVersionedRestagingExecution.profile_id == profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceNotFoundError("Successor versioned restaging execution not found")
    return row


def _validate_content_result(
    result,
    policy,
    change: ExternalDocumentSourceSuccessorChangeDetectionExecution,
):
    if getattr(result, "read", None) is not True:
        failure_code = getattr(result, "failure_code", None)
        raise ExternalDocumentSourceConflictError(
            f"Successor versioned restaging remote content read failed ({failure_code or 'invalid_result'})"
        )
    if getattr(result, "failure_code", None) is not None or type(getattr(result, "content", None)) is not bytes:
        raise ExternalDocumentSourceConflictError(
            "Successor versioned restaging content adapter returned an invalid successful result"
        )
    payload = result.content
    if len(payload) > policy.max_content_bytes or len(payload) > MAX_SUCCESSOR_VERSIONED_RESTAGING_BYTES:
        raise ExternalDocumentSourceConflictError(
            "Successor versioned restaging remote content exceeded the byte bound"
        )
    if change.observed_byte_size is not None and len(payload) != change.observed_byte_size:
        raise ExternalDocumentSourceConflictError(
            "Successor versioned restaging byte count no longer matches the Phase S observation"
        )
    latency = getattr(result, "latency_class", None)
    if latency not in _ALLOWED_LATENCY_CLASSES:
        raise ExternalDocumentSourceConflictError(
            "Successor versioned restaging adapter returned an invalid latency class"
        )
    media = _normalize_media_type(getattr(result, "media_type_class", None))
    expected_media = _normalize_media_type(change.observed_mime_type_class)
    if media is not None and expected_media is not None and media != expected_media:
        raise ExternalDocumentSourceConflictError(
            "Successor versioned restaging media type no longer matches the Phase S observation"
        )
    media = media or expected_media
    version = _normalize_hash(
        getattr(result, "observed_version_token_hash", None),
        field="Observed version-token hash",
    )
    expected_version = _normalize_hash(
        change.observed_version_token_hash,
        field="Phase S observed version-token hash",
    )
    if expected_version is not None and version != expected_version:
        raise ExternalDocumentSourceConflictError(
            "Successor versioned restaging version no longer matches the Phase S observation"
        )
    return payload, hashlib.sha256(payload).hexdigest(), len(payload), media, version, latency


def _verify_storage_object(store, execution: ExternalDocumentSourceSuccessorVersionedRestagingExecution):
    if execution.content_sha256 is None or execution.content_byte_count is None:
        raise ExternalDocumentSourceConflictError("Successor versioned restaging storage proof is unavailable")
    try:
        metadata = store.head_object(storage_key=execution.storage_object_key)
        if (
            metadata.file_hash.lower() != execution.content_sha256
            or metadata.file_size_bytes != execution.content_byte_count
        ):
            raise ExternalDocumentSourceConflictError(
                "Successor versioned quarantine object does not match the persisted content proof"
            )
        payload = store.get_bytes(
            storage_key=execution.storage_object_key,
            expected_sha256=execution.content_sha256,
        )
        if len(payload) != execution.content_byte_count:
            raise ExternalDocumentSourceConflictError(
                "Successor versioned quarantine object byte count drifted"
            )
        del payload
        return metadata
    except ExternalDocumentSourceConflictError:
        raise
    except ObjectStorageNotFound:
        raise
    except (ObjectStorageError, ObjectStorageIntegrityError):
        raise ExternalDocumentSourceConflictError(
            "Governed successor versioned quarantine storage verification failed"
        ) from None


def _ensure_integrity(
    db: Session,
    execution: ExternalDocumentSourceSuccessorVersionedRestagingExecution,
    *,
    verify_storage: bool = False,
) -> None:
    change = _get_successor_change(
        db,
        organization_id=execution.organization_id,
        profile_id=execution.profile_id,
        execution_id=execution.successor_change_detection_execution_id,
    )
    if (
        change.result_status != "changed"
        or change.completion_hash is None
        or change.observed_projection_hash is None
        or change.observed_provider_item_id_hash is None
    ):
        raise ExternalDocumentSourceConflictError("Phase S observation is not an eligible changed item")
    listing, item = _listing_and_item(db, change)
    profile = _get_profile(
        db,
        organization_id=execution.organization_id,
        profile_id=execution.profile_id,
    )
    _ensure_profile_integrity(db, profile)
    if profile.status != "active" or profile.profile_hash != change.profile_hash:
        raise ExternalDocumentSourceConflictError("Successor versioned restaging source profile is not active")
    policy = _read_policy(profile.provider_kind, profile.normalized_config, item)
    expected_policy_hash = _endpoint_policy_hash(policy)
    if (
        execution.checkpoint_generation_execution_id != change.checkpoint_generation_execution_id
        or execution.versioned_restaging_execution_id != change.versioned_restaging_execution_id
        or execution.predecessor_sync_checkpoint_execution_id != change.predecessor_sync_checkpoint_execution_id
        or execution.change_detection_execution_id != change.change_detection_execution_id
        or execution.listing_execution_id != change.listing_execution_id
        or execution.metadata_item_id != change.metadata_item_id
        or execution.provider_kind != change.provider_kind
        or execution.profile_hash != change.profile_hash
        or execution.successor_change_scope_hash != change.scope_hash
        or execution.successor_change_request_hash != change.request_hash
        or execution.successor_change_completion_hash != change.completion_hash
        or execution.successor_checkpoint_state_hash != change.successor_checkpoint_state_hash
        or execution.successor_checkpoint_completion_hash != change.successor_checkpoint_completion_hash
        or execution.observed_projection_hash != change.observed_projection_hash
        or execution.observed_provider_item_id_hash != change.observed_provider_item_id_hash
        or execution.observed_version_token_hash != change.observed_version_token_hash
        or execution.observed_byte_size != change.observed_byte_size
        or execution.observed_mime_type_class != change.observed_mime_type_class
        or execution.read_operation_kind != policy.read_operation_kind
        or execution.endpoint_policy_hash != expected_policy_hash
        or execution.candidate_generation != SUCCESSOR_CANDIDATE_GENERATION
        or execution.storage_purpose != SUCCESSOR_VERSIONED_STORAGE_PURPOSE
        or execution.storage_object_key != _storage_key(execution)
        or execution.storage_object_key_hash
        != hashlib.sha256(execution.storage_object_key.encode("utf-8")).hexdigest()
    ):
        raise ExternalDocumentSourceConflictError("Successor versioned restaging lineage/custody drifted")
    if not isinstance(execution.read_adapter_kind, str) or not _SAFE_IDENTIFIER.fullmatch(execution.read_adapter_kind):
        raise ExternalDocumentSourceConflictError("Successor versioned restaging adapter identity drifted")
    expected_scope = _scope_hash(
        change,
        read_operation_kind=execution.read_operation_kind,
        read_adapter_kind=execution.read_adapter_kind,
        endpoint_policy_hash=execution.endpoint_policy_hash,
        storage_backend_kind=execution.storage_backend_kind,
        storage_object_key_hash=execution.storage_object_key_hash,
        request_key=execution.request_key,
    )
    if execution.scope_hash != expected_scope or execution.request_hash != _request_hash(execution):
        raise ExternalDocumentSourceConflictError("Successor versioned restaging request integrity failed")

    rows = _receipts(db, execution)
    expected_events = {
        "requested": ["requested"],
        "content_verified": ["requested", "content_verified"],
        "completed": ["requested", "content_verified", "completed"],
    }
    if execution.status not in expected_events or [row.event_type for row in rows] != expected_events[execution.status]:
        raise ExternalDocumentSourceConflictError("Successor versioned restaging receipt lifecycle drifted")
    prior = None
    for index, receipt in enumerate(rows, start=1):
        decision = (
            execution.request_hash
            if receipt.event_type == "requested"
            else execution.content_proof_hash
            if receipt.event_type == "content_verified"
            else execution.completion_hash
        )
        occurred = (
            execution.requested_at
            if receipt.event_type == "requested"
            else execution.content_verified_at
            if receipt.event_type == "content_verified"
            else execution.completed_at
        )
        if (
            receipt.sequence_number != index
            or receipt.status_after != receipt.event_type
            or receipt.actor_id != execution.requested_by_id
            or occurred is None
            or _aware(receipt.occurred_at) != _aware(occurred)
            or receipt.reason != execution.request_reason
            or receipt.scope_hash != execution.scope_hash
            or receipt.decision_hash != decision
            or receipt.prior_receipt_hash != prior
            or receipt.receipt_hash != _receipt_hash(receipt)
        ):
            raise ExternalDocumentSourceConflictError("Successor versioned restaging receipt integrity failed")
        for field, expected in _base_safety(receipt.event_type).items():
            if bool(getattr(receipt, field)) != expected:
                raise ExternalDocumentSourceConflictError(
                    "Successor versioned restaging receipt safety boundary drifted"
                )
        prior = receipt.receipt_hash

    for field, expected in _base_safety(execution.status).items():
        if bool(getattr(execution, field)) != expected:
            raise ExternalDocumentSourceConflictError("Successor versioned restaging safety boundary drifted")
    if execution.status == "requested":
        if any(
            value is not None
            for value in (
                execution.content_sha256,
                execution.content_byte_count,
                execution.content_proof_hash,
                execution.content_verified_at,
                execution.completed_at,
                execution.completion_hash,
                execution.result_status,
                execution.stored_etag,
            )
        ):
            raise ExternalDocumentSourceConflictError("Successor versioned restaging request anchor drifted")
        return
    if (
        execution.content_sha256 is None
        or not _HEX_64.fullmatch(execution.content_sha256)
        or execution.content_byte_count is None
        or not 0 <= execution.content_byte_count <= MAX_SUCCESSOR_VERSIONED_RESTAGING_BYTES
        or execution.content_proof_hash != _content_proof_hash(execution)
        or execution.content_verified_at is None
        or _aware(execution.content_verified_at) < _aware(execution.requested_at)
    ):
        raise ExternalDocumentSourceConflictError("Successor versioned restaging content proof integrity failed")
    if execution.status == "content_verified":
        if (
            execution.completed_at is not None
            or execution.completion_hash is not None
            or execution.result_status is not None
            or execution.stored_etag is not None
        ):
            raise ExternalDocumentSourceConflictError(
                "Successor versioned restaging content-verified lifecycle drifted"
            )
        return
    if (
        execution.result_status != "staged_candidate_verified"
        or execution.completed_at is None
        or _aware(execution.completed_at) < _aware(execution.content_verified_at)
        or execution.completion_hash != _completion_hash(execution)
    ):
        raise ExternalDocumentSourceConflictError("Successor versioned restaging completion integrity failed")
    if verify_storage:
        _verify_storage_object(_configured_store(), execution)


def _read_changed_payload(
    db: Session,
    execution: ExternalDocumentSourceSuccessorVersionedRestagingExecution,
    change: ExternalDocumentSourceSuccessorChangeDetectionExecution,
    listing,
    item,
    profile,
):
    policy = _read_policy(profile.provider_kind, profile.normalized_config, item)
    if (
        _endpoint_policy_hash(policy) != execution.endpoint_policy_hash
        or policy.read_operation_kind != execution.read_operation_kind
    ):
        raise ExternalDocumentSourceConflictError("Successor versioned restaging read policy drifted")
    adapter = _READ_ADAPTERS.get((profile.provider_kind, policy.read_operation_kind))
    if adapter is None:
        raise ExternalDocumentSourceConflictError(
            "Remote file content read adapter is unavailable for successor versioned restaging"
        )
    if getattr(adapter, "adapter_kind", None) != execution.read_adapter_kind:
        raise ExternalDocumentSourceConflictError(
            "Successor versioned restaging read adapter drifted from the request anchor"
        )
    binding = _active_binding(db, listing)
    locator = CredentialReferenceLocator(
        backend=binding.reference_backend,
        namespace=binding.reference_namespace,
        name=binding.reference_name,
        version=binding.reference_version,
    )
    try:
        result = adapter.read_content(locator, policy)
    except Exception:
        raise ExternalDocumentSourceConflictError(
            "Successor versioned restaging remote content reread failed"
        ) from None
    payload, digest, count, media, version, latency = _validate_content_result(result, policy, change)
    return result, payload, digest, count, media, version, latency


def execute_external_document_source_successor_versioned_restaging(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    successor_change_detection_execution_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)
    store = _configured_store()
    backend = getattr(store.sanitized_health_identity, "backend", None)
    if not isinstance(backend, str) or not _SAFE_IDENTIFIER.fullmatch(backend):
        raise ExternalDocumentSourceConflictError(
            "Governed successor versioned quarantine storage backend identity is invalid"
        )

    existing = db.scalar(
        select(ExternalDocumentSourceSuccessorVersionedRestagingExecution).where(
            ExternalDocumentSourceSuccessorVersionedRestagingExecution.organization_id == organization_id,
            ExternalDocumentSourceSuccessorVersionedRestagingExecution.profile_id == profile_id,
            ExternalDocumentSourceSuccessorVersionedRestagingExecution.successor_change_detection_execution_id
            == successor_change_detection_execution_id,
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing, verify_storage=existing.status == "completed")
        if (
            existing.request_key != normalized_key
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError(
                "Conflicting replay or second consumption for successor versioned restaging"
            )
        if existing.status == "completed":
            return existing, "unchanged"
        execution = existing
        change = _get_successor_change(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            execution_id=successor_change_detection_execution_id,
        )
    else:
        collision = db.scalar(
            select(ExternalDocumentSourceSuccessorVersionedRestagingExecution).where(
                ExternalDocumentSourceSuccessorVersionedRestagingExecution.organization_id == organization_id,
                ExternalDocumentSourceSuccessorVersionedRestagingExecution.profile_id == profile_id,
                ExternalDocumentSourceSuccessorVersionedRestagingExecution.request_key == normalized_key,
            )
        )
        if collision is not None:
            raise ExternalDocumentSourceConflictError(
                "Conflicting replay for successor versioned restaging request_key"
            )
        change = _get_successor_change(
            db,
            organization_id=organization_id,
            profile_id=profile_id,
            execution_id=successor_change_detection_execution_id,
            for_update=True,
        )
        if (
            change.result_status != "changed"
            or change.completion_hash is None
            or change.observed_projection_hash is None
            or change.observed_provider_item_id_hash is None
        ):
            raise ExternalDocumentSourceConflictError(
                "Only a completed Phase S changed observation is eligible for successor versioned restaging"
            )
        listing, item = _listing_and_item(db, change)
        profile = _get_profile(db, organization_id=organization_id, profile_id=profile_id)
        _ensure_profile_integrity(db, profile)
        if profile.status != "active" or profile.profile_hash != change.profile_hash:
            raise ExternalDocumentSourceConflictError("External document source profile is not active")
        policy = _read_policy(profile.provider_kind, profile.normalized_config, item)
        adapter = _READ_ADAPTERS.get((profile.provider_kind, policy.read_operation_kind))
        if adapter is None:
            raise ExternalDocumentSourceConflictError(
                "Remote file content read adapter is unavailable for successor versioned restaging"
            )
        adapter_kind = getattr(adapter, "adapter_kind", None)
        if not isinstance(adapter_kind, str) or not _SAFE_IDENTIFIER.fullmatch(adapter_kind):
            raise ExternalDocumentSourceConflictError(
                "Successor versioned restaging adapter identity is invalid"
            )
        current = _aware(now or _utc_now())
        execution = ExternalDocumentSourceSuccessorVersionedRestagingExecution(
            organization_id=organization_id,
            profile_id=profile_id,
            successor_change_detection_execution_id=change.id,
            checkpoint_generation_execution_id=change.checkpoint_generation_execution_id,
            versioned_restaging_execution_id=change.versioned_restaging_execution_id,
            predecessor_sync_checkpoint_execution_id=change.predecessor_sync_checkpoint_execution_id,
            change_detection_execution_id=change.change_detection_execution_id,
            listing_execution_id=change.listing_execution_id,
            metadata_item_id=change.metadata_item_id,
            provider_kind=change.provider_kind,
            profile_hash=change.profile_hash,
            successor_change_scope_hash=change.scope_hash,
            successor_change_request_hash=change.request_hash,
            successor_change_completion_hash=change.completion_hash,
            successor_checkpoint_state_hash=change.successor_checkpoint_state_hash,
            successor_checkpoint_completion_hash=change.successor_checkpoint_completion_hash,
            observed_projection_hash=change.observed_projection_hash,
            observed_provider_item_id_hash=change.observed_provider_item_id_hash,
            observed_version_token_hash=change.observed_version_token_hash,
            observed_byte_size=change.observed_byte_size,
            observed_mime_type_class=change.observed_mime_type_class,
            read_operation_kind=policy.read_operation_kind,
            read_adapter_kind=adapter_kind,
            endpoint_policy_hash=_endpoint_policy_hash(policy),
            candidate_generation=SUCCESSOR_CANDIDATE_GENERATION,
            storage_backend_kind=backend,
            storage_purpose=SUCCESSOR_VERSIONED_STORAGE_PURPOSE,
            storage_object_key="pending",
            storage_object_key_hash="0" * 64,
            request_key=normalized_key,
            scope_hash="0" * 64,
            request_hash="0" * 64,
            status="requested",
            requested_by_id=requested_by_id,
            request_reason=normalized_reason,
            requested_at=current,
            **_base_safety("requested"),
        )
        db.add(execution)
        db.flush()
        execution.storage_object_key = _storage_key(execution)
        execution.storage_object_key_hash = hashlib.sha256(
            execution.storage_object_key.encode("utf-8")
        ).hexdigest()
        execution.scope_hash = _scope_hash(
            change,
            read_operation_kind=execution.read_operation_kind,
            read_adapter_kind=execution.read_adapter_kind,
            endpoint_policy_hash=execution.endpoint_policy_hash,
            storage_backend_kind=backend,
            storage_object_key_hash=execution.storage_object_key_hash,
            request_key=normalized_key,
        )
        execution.request_hash = _request_hash(execution)
        _append_receipt(
            db,
            execution=execution,
            event_type="requested",
            actor_id=requested_by_id,
            occurred_at=current,
            decision_hash=execution.request_hash,
        )
        _ensure_integrity(db, execution, verify_storage=False)
        db.commit()
        db.refresh(execution)

    listing, item = _listing_and_item(db, change)
    profile = _get_profile(db, organization_id=organization_id, profile_id=profile_id)
    _ensure_profile_integrity(db, profile)
    if profile.status != "active" or profile.profile_hash != change.profile_hash:
        raise ExternalDocumentSourceConflictError("External document source profile is not active")

    if execution.status == "content_verified":
        try:
            metadata = _verify_storage_object(store, execution)
        except ObjectStorageNotFound:
            metadata = None
        if metadata is not None:
            completed_at = max(_aware(execution.content_verified_at), _utc_now())
            execution.status = "completed"
            execution.result_status = "staged_candidate_verified"
            execution.stored_etag = metadata.etag
            execution.completed_at = completed_at
            for field, value in _base_safety("completed").items():
                setattr(execution, field, value)
            execution.completion_hash = _completion_hash(execution)
            _append_receipt(
                db,
                execution=execution,
                event_type="completed",
                actor_id=requested_by_id,
                occurred_at=completed_at,
                decision_hash=execution.completion_hash,
            )
            db.flush()
            _ensure_integrity(db, execution, verify_storage=False)
            return execution, "completed"

    transient_result = None
    payload = None
    try:
        transient_result, payload, digest, count, media, version, latency = _read_changed_payload(
            db,
            execution,
            change,
            listing,
            item,
            profile,
        )
        if execution.status == "requested":
            content_verified_at = max(_aware(execution.requested_at), _utc_now())
            execution.status = "content_verified"
            execution.content_sha256 = digest
            execution.content_byte_count = count
            execution.content_media_type_class = media
            execution.content_version_token_hash = version
            execution.content_latency_class = latency
            execution.content_verified_at = content_verified_at
            for field, value in _base_safety("content_verified").items():
                setattr(execution, field, value)
            execution.content_proof_hash = _content_proof_hash(execution)
            _append_receipt(
                db,
                execution=execution,
                event_type="content_verified",
                actor_id=requested_by_id,
                occurred_at=content_verified_at,
                decision_hash=execution.content_proof_hash,
            )
            db.flush()
            _ensure_integrity(db, execution, verify_storage=False)
            db.commit()
            db.refresh(execution)
        else:
            if (
                digest != execution.content_sha256
                or count != execution.content_byte_count
                or media != execution.content_media_type_class
                or version != execution.content_version_token_hash
            ):
                raise ExternalDocumentSourceConflictError(
                    "Successor versioned restaging recovery reread no longer matches the persisted content proof"
                )
        try:
            store.put_bytes_if_absent(
                payload,
                storage_key=execution.storage_object_key,
                expected_sha256=execution.content_sha256,
            )
        except ObjectStoragePreconditionFailed:
            pass
        except ObjectStorageError:
            raise ExternalDocumentSourceConflictError(
                "Governed successor versioned quarantine storage write failed"
            ) from None
    finally:
        if transient_result is not None:
            del transient_result
        if payload is not None:
            del payload

    metadata = _verify_storage_object(store, execution)
    completed_at = max(_aware(execution.content_verified_at), _utc_now())
    execution.status = "completed"
    execution.result_status = "staged_candidate_verified"
    execution.stored_etag = metadata.etag
    execution.completed_at = completed_at
    for field, value in _base_safety("completed").items():
        setattr(execution, field, value)
    execution.completion_hash = _completion_hash(execution)
    _append_receipt(
        db,
        execution=execution,
        event_type="completed",
        actor_id=requested_by_id,
        occurred_at=completed_at,
        decision_hash=execution.completion_hash,
    )
    db.flush()
    _ensure_integrity(db, execution, verify_storage=False)
    return execution, "completed"


def get_external_document_source_successor_versioned_restaging(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = _get_execution(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    _ensure_integrity(db, execution, verify_storage=execution.status == "completed")
    return execution


def list_external_document_source_successor_versioned_restaging_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = get_external_document_source_successor_versioned_restaging(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _receipts(db, execution)
