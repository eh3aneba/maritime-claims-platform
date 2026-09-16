from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.documents.object_storage import (
    ObjectStorageError,
    ObjectStorageIntegrityError,
    ObjectStorageNotFound,
    ObjectStoragePreconditionFailed,
    S3CompatibleEvidenceStore,
    S3ObjectStoreConfig,
)
from app.modules.external_document_sources.credential_reference_health_service import CredentialReferenceLocator
from app.modules.external_document_sources.remote_content_staging_models import (
    MAX_STAGED_CONTENT_BYTES,
    STORAGE_PURPOSE,
    ExternalDocumentSourceRemoteContentStagingExecution,
    ExternalDocumentSourceRemoteContentStagingReceipt,
)
from app.modules.external_document_sources.remote_file_content_read_models import ExternalDocumentSourceRemoteFileContentReadExecution
from app.modules.external_document_sources.remote_file_content_read_service import (
    _READ_ADAPTERS,
    _active_binding,
    _consume_result,
    _endpoint_policy_hash,
    _ensure_integrity as _ensure_remote_content_read_integrity,
    _listing_execution,
    _metadata_item,
    _read_policy,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
    _ensure_profile_integrity,
    _get_profile,
)

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_FALSE_SAFETY_FIELDS = (
    "credential_stored", "oauth_authorization_code_stored", "access_token_stored", "refresh_token_stored",
    "id_token_stored", "client_secret_stored", "private_key_stored", "provider_client_stored",
    "provider_response_body_stored", "remote_content_returned", "remote_content_logged", "content_parsed",
    "content_extracted", "remote_list_performed", "remote_write_performed", "remote_delete_performed",
    "storage_delete_performed", "subscription_created", "checkpoint_created", "sync_executed",
    "evidence_admitted", "document_created", "claim_mutated",
)


class RemoteContentQuarantineStore(Protocol):
    @property
    def sanitized_health_identity(self): ...
    def put_bytes_if_absent(self, payload: bytes, *, storage_key: str, expected_sha256: str | None = None): ...
    def head_object(self, *, storage_key: str): ...
    def get_bytes(self, *, storage_key: str, expected_sha256: str | None = None) -> bytes: ...


_STAGING_STORE_OVERRIDE: RemoteContentQuarantineStore | None = None


def register_external_document_source_remote_content_staging_store(store: RemoteContentQuarantineStore) -> None:
    for name in ("put_bytes_if_absent", "head_object", "get_bytes"):
        if not callable(getattr(store, name, None)):
            raise ValueError("Remote content staging store does not implement the governed object-storage contract")
    identity = getattr(store, "sanitized_health_identity", None)
    backend = getattr(identity, "backend", None)
    if not isinstance(backend, str) or not _SAFE_IDENTIFIER.fullmatch(backend):
        raise ValueError("Remote content staging store backend identity is invalid")
    global _STAGING_STORE_OVERRIDE
    _STAGING_STORE_OVERRIDE = store


def clear_external_document_source_remote_content_staging_store() -> None:
    global _STAGING_STORE_OVERRIDE
    _STAGING_STORE_OVERRIDE = None


def _configured_store() -> RemoteContentQuarantineStore:
    if _STAGING_STORE_OVERRIDE is not None:
        return _STAGING_STORE_OVERRIDE
    settings = get_settings()
    if not settings.s3_foundation_enabled:
        raise ExternalDocumentSourceConflictError("Governed S3 foundation is not enabled for remote content staging")
    config = S3ObjectStoreConfig(
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        bucket=settings.s3_bucket,
        access_key_id=settings.s3_access_key_id,
        secret_access_key=settings.s3_secret_access_key.get_secret_value(),
        session_token=settings.s3_session_token.get_secret_value(),
        request_timeout_seconds=settings.s3_request_timeout_seconds,
        max_attempts=settings.s3_max_attempts,
        tls_verify=settings.s3_tls_verify,
    )
    try:
        config.validate(require_https=settings.app_env.strip().lower() in {"staging", "production"})
        return S3CompatibleEvidenceStore(config)
    except ObjectStorageError:
        raise ExternalDocumentSourceConflictError("Governed S3 foundation configuration is invalid") from None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return None if value is None else _aware(value).isoformat()


def _canonical_hash(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_text(value: str, *, field: str, minimum: int, maximum: int) -> str:
    normalized = " ".join(value.strip().split())
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError(f"{field} must contain between {minimum} and {maximum} characters")
    if "\x00" in normalized:
        raise ExternalDocumentSourceValidationError(f"{field} contains an invalid character")
    return normalized


def _base_safety(executed: bool) -> dict[str, bool]:
    return {
        "credential_reference_stored": True,
        "credential_reference_resolution_performed": True,
        "activation_authorization_consumed": True,
        "upstream_token_acquisition_completed": True,
        "upstream_provider_client_health_completed": True,
        "upstream_remote_metadata_listing_completed": True,
        "upstream_remote_file_content_read_completed": True,
        "provider_client_constructed": executed,
        "remote_content_transiently_observed": executed,
        "remote_read_performed": executed,
        "durable_content_staged": executed,
        "remote_content_stored": executed,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    }


def _storage_key(execution_id: UUID, organization_id: UUID, digest: str) -> str:
    return f"external-remote-content-quarantine/{organization_id}/{execution_id}/{digest}"


def _scope_hash(upstream: ExternalDocumentSourceRemoteFileContentReadExecution, *, storage_backend_kind: str, storage_object_key_hash: str, request_key: str) -> str:
    if upstream.completion_hash is None or upstream.content_sha256 is None or upstream.content_byte_count is None:
        raise ExternalDocumentSourceConflictError("Phase M remote content read completion facts are incomplete")
    return _canonical_hash({
        "organization_id": str(upstream.organization_id), "profile_id": str(upstream.profile_id),
        "remote_content_read_execution_id": str(upstream.id), "listing_execution_id": str(upstream.listing_execution_id),
        "metadata_item_id": str(upstream.metadata_item_id), "provider_kind": upstream.provider_kind,
        "profile_hash": upstream.profile_hash, "metadata_item_hash": upstream.metadata_item_hash,
        "upstream_scope_hash": upstream.scope_hash, "upstream_request_hash": upstream.request_hash,
        "upstream_completion_hash": upstream.completion_hash, "read_operation_kind": upstream.read_operation_kind,
        "read_adapter_kind": upstream.read_adapter_kind, "endpoint_policy_hash": upstream.endpoint_policy_hash,
        "expected_content_sha256": upstream.content_sha256, "expected_content_byte_count": upstream.content_byte_count,
        "expected_media_type_class": upstream.media_type_class,
        "expected_version_token_hash": upstream.observed_version_token_hash,
        "storage_backend_kind": storage_backend_kind, "storage_purpose": STORAGE_PURPOSE,
        "storage_object_key_hash": storage_object_key_hash, "request_key": request_key,
    })


def _request_hash(execution: ExternalDocumentSourceRemoteContentStagingExecution) -> str:
    return _canonical_hash({
        "execution_id": str(execution.id), "scope_hash": execution.scope_hash,
        "storage_object_key": execution.storage_object_key,
        "requested_by_id": str(execution.requested_by_id), "request_reason": execution.request_reason,
        "requested_at": _iso(execution.requested_at), **_base_safety(False),
    })


def _completion_hash(execution: ExternalDocumentSourceRemoteContentStagingExecution) -> str:
    if execution.completed_at is None or execution.result_status != "staged_verified":
        raise ExternalDocumentSourceConflictError("Remote content staging completion facts are incomplete")
    return _canonical_hash({
        "execution_id": str(execution.id), "scope_hash": execution.scope_hash, "request_hash": execution.request_hash,
        "result_status": execution.result_status, "expected_content_sha256": execution.expected_content_sha256,
        "expected_content_byte_count": execution.expected_content_byte_count,
        "storage_backend_kind": execution.storage_backend_kind, "storage_purpose": execution.storage_purpose,
        "storage_object_key_hash": execution.storage_object_key_hash, "stored_etag": execution.stored_etag,
        "completed_at": _iso(execution.completed_at), **_base_safety(True),
    })


def _receipt_hash(receipt: ExternalDocumentSourceRemoteContentStagingReceipt) -> str:
    return _canonical_hash({
        "organization_id": str(receipt.organization_id), "execution_id": str(receipt.execution_id),
        "sequence_number": receipt.sequence_number, "event_type": receipt.event_type,
        "status_after": receipt.status_after, "actor_id": str(receipt.actor_id),
        "occurred_at": _iso(receipt.occurred_at), "reason": receipt.reason, "scope_hash": receipt.scope_hash,
        "decision_hash": receipt.decision_hash, "prior_receipt_hash": receipt.prior_receipt_hash,
        **_base_safety(receipt.event_type == "completed"),
    })


def _receipts(db: Session, execution: ExternalDocumentSourceRemoteContentStagingExecution):
    return list(db.scalars(select(ExternalDocumentSourceRemoteContentStagingReceipt).where(
        ExternalDocumentSourceRemoteContentStagingReceipt.organization_id == execution.organization_id,
        ExternalDocumentSourceRemoteContentStagingReceipt.execution_id == execution.id,
    ).order_by(ExternalDocumentSourceRemoteContentStagingReceipt.sequence_number.asc())).all())


def _append_receipt(db: Session, *, execution, event_type: str, actor_id: UUID, occurred_at: datetime, decision_hash: str) -> None:
    rows = _receipts(db, execution)
    receipt = ExternalDocumentSourceRemoteContentStagingReceipt(
        organization_id=execution.organization_id, execution_id=execution.id, sequence_number=len(rows) + 1,
        event_type=event_type, status_after=execution.status, actor_id=actor_id, occurred_at=occurred_at,
        reason=execution.request_reason, scope_hash=execution.scope_hash, decision_hash=decision_hash,
        prior_receipt_hash=rows[-1].receipt_hash if rows else None, **_base_safety(event_type == "completed"),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()


def _get_upstream(db: Session, execution: ExternalDocumentSourceRemoteContentStagingExecution) -> ExternalDocumentSourceRemoteFileContentReadExecution:
    row = db.scalar(select(ExternalDocumentSourceRemoteFileContentReadExecution).where(
        ExternalDocumentSourceRemoteFileContentReadExecution.id == execution.remote_content_read_execution_id,
        ExternalDocumentSourceRemoteFileContentReadExecution.organization_id == execution.organization_id,
        ExternalDocumentSourceRemoteFileContentReadExecution.profile_id == execution.profile_id,
    ))
    if row is None:
        raise ExternalDocumentSourceConflictError("Phase M remote content read lineage is missing")
    return row


def _verify_storage_object(store: RemoteContentQuarantineStore, execution: ExternalDocumentSourceRemoteContentStagingExecution):
    try:
        metadata = store.head_object(storage_key=execution.storage_object_key)
        if metadata.file_hash.lower() != execution.expected_content_sha256 or metadata.file_size_bytes != execution.expected_content_byte_count:
            raise ExternalDocumentSourceConflictError("Quarantine object no longer matches the Phase M content proof")
        payload = store.get_bytes(storage_key=execution.storage_object_key, expected_sha256=execution.expected_content_sha256)
        if len(payload) != execution.expected_content_byte_count:
            raise ExternalDocumentSourceConflictError("Quarantine object byte count no longer matches the Phase M content proof")
        del payload
        return metadata
    except ExternalDocumentSourceConflictError:
        raise
    except ObjectStorageNotFound:
        raise
    except (ObjectStorageError, ObjectStorageIntegrityError):
        raise ExternalDocumentSourceConflictError("Governed quarantine storage verification failed") from None


def _ensure_anchor_integrity(db: Session, execution: ExternalDocumentSourceRemoteContentStagingExecution, *, verify_storage: bool) -> None:
    upstream = _get_upstream(db, execution)
    _ensure_remote_content_read_integrity(db, upstream)
    if upstream.status != "completed" or upstream.completion_hash is None or upstream.content_sha256 is None or upstream.content_byte_count is None:
        raise ExternalDocumentSourceConflictError("Phase M remote content read is not complete")
    if (
        execution.listing_execution_id != upstream.listing_execution_id
        or execution.metadata_item_id != upstream.metadata_item_id
        or execution.provider_kind != upstream.provider_kind
        or execution.profile_hash != upstream.profile_hash
        or execution.metadata_item_hash != upstream.metadata_item_hash
        or execution.upstream_scope_hash != upstream.scope_hash
        or execution.upstream_request_hash != upstream.request_hash
        or execution.upstream_completion_hash != upstream.completion_hash
        or execution.read_operation_kind != upstream.read_operation_kind
        or execution.read_adapter_kind != upstream.read_adapter_kind
        or execution.endpoint_policy_hash != upstream.endpoint_policy_hash
        or execution.expected_content_sha256 != upstream.content_sha256
        or execution.expected_content_byte_count != upstream.content_byte_count
        or execution.expected_media_type_class != upstream.media_type_class
        or execution.expected_version_token_hash != upstream.observed_version_token_hash
        or execution.storage_purpose != STORAGE_PURPOSE
        or execution.storage_object_key != _storage_key(execution.id, execution.organization_id, execution.expected_content_sha256)
        or execution.storage_object_key_hash != hashlib.sha256(execution.storage_object_key.encode("utf-8")).hexdigest()
    ):
        raise ExternalDocumentSourceConflictError("Remote content staging upstream/custody lineage drifted")
    if not _HEX_64.fullmatch(execution.expected_content_sha256) or not 0 <= execution.expected_content_byte_count <= MAX_STAGED_CONTENT_BYTES:
        raise ExternalDocumentSourceConflictError("Remote content staging proof boundary drifted")
    expected_scope = _scope_hash(
        upstream, storage_backend_kind=execution.storage_backend_kind,
        storage_object_key_hash=execution.storage_object_key_hash, request_key=execution.request_key,
    )
    if execution.scope_hash != expected_scope or execution.request_hash != _request_hash(execution):
        raise ExternalDocumentSourceConflictError("Remote content staging request integrity failed")
    rows = _receipts(db, execution)
    if not rows or rows[0].event_type != "requested" or rows[0].sequence_number != 1:
        raise ExternalDocumentSourceConflictError("Remote content staging requested receipt is missing")
    requested = rows[0]
    if (
        requested.status_after != "requested" or requested.actor_id != execution.requested_by_id
        or _aware(requested.occurred_at) != _aware(execution.requested_at) or requested.reason != execution.request_reason
        or requested.scope_hash != execution.scope_hash or requested.decision_hash != execution.request_hash
        or requested.prior_receipt_hash is not None or requested.receipt_hash != _receipt_hash(requested)
    ):
        raise ExternalDocumentSourceConflictError("Remote content staging requested receipt integrity failed")
    for field, expected in _base_safety(False).items():
        if bool(getattr(requested, field)) != expected:
            raise ExternalDocumentSourceConflictError("Remote content staging requested receipt safety boundary drifted")

    if execution.status == "requested":
        if len(rows) != 1 or execution.result_status is not None or execution.completed_at is not None or execution.completion_hash is not None:
            raise ExternalDocumentSourceConflictError("Remote content staging recovery-anchor lifecycle drifted")
        for field, expected in _base_safety(False).items():
            if bool(getattr(execution, field)) != expected:
                raise ExternalDocumentSourceConflictError("Remote content staging recovery-anchor safety boundary drifted")
        return

    if execution.status != "completed" or execution.result_status != "staged_verified" or execution.completed_at is None or execution.completion_hash != _completion_hash(execution):
        raise ExternalDocumentSourceConflictError("Remote content staging completion integrity failed")
    for field, expected in _base_safety(True).items():
        if bool(getattr(execution, field)) != expected:
            raise ExternalDocumentSourceConflictError("Remote content staging completion safety boundary drifted")
    if len(rows) != 2 or rows[1].event_type != "completed":
        raise ExternalDocumentSourceConflictError("Remote content staging receipt lifecycle is incomplete")
    completed = rows[1]
    if (
        completed.sequence_number != 2 or completed.status_after != "completed" or completed.actor_id != execution.requested_by_id
        or _aware(completed.occurred_at) != _aware(execution.completed_at) or completed.reason != execution.request_reason
        or completed.scope_hash != execution.scope_hash or completed.decision_hash != execution.completion_hash
        or completed.prior_receipt_hash != requested.receipt_hash or completed.receipt_hash != _receipt_hash(completed)
    ):
        raise ExternalDocumentSourceConflictError("Remote content staging completed receipt integrity failed")
    for field, expected in _base_safety(True).items():
        if bool(getattr(completed, field)) != expected:
            raise ExternalDocumentSourceConflictError("Remote content staging completed receipt safety boundary drifted")
    if _aware(execution.completed_at) < _aware(execution.requested_at):
        raise ExternalDocumentSourceConflictError("Remote content staging timestamps drifted")
    if verify_storage:
        _verify_storage_object(_configured_store(), execution)


def _complete_from_storage(db: Session, execution: ExternalDocumentSourceRemoteContentStagingExecution, *, store, metadata, completed_at: datetime) -> None:
    execution.status = "completed"
    execution.result_status = "staged_verified"
    execution.stored_etag = metadata.etag
    execution.completed_at = completed_at
    execution.provider_client_constructed = True
    execution.remote_content_transiently_observed = True
    execution.remote_read_performed = True
    execution.durable_content_staged = True
    execution.remote_content_stored = True
    execution.completion_hash = _completion_hash(execution)
    _append_receipt(db, execution=execution, event_type="completed", actor_id=execution.requested_by_id, occurred_at=completed_at, decision_hash=execution.completion_hash)
    db.flush()
    _ensure_anchor_integrity(db, execution, verify_storage=False)


def execute_external_document_source_remote_content_staging(
    db: Session, *, organization_id: UUID, profile_id: UUID, remote_content_read_execution_id: UUID,
    requested_by_id: UUID, request_key: str, request_reason: str, now: datetime | None = None,
):
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)
    store = _configured_store()
    backend = getattr(store.sanitized_health_identity, "backend", None)
    if not isinstance(backend, str) or not _SAFE_IDENTIFIER.fullmatch(backend):
        raise ExternalDocumentSourceConflictError("Governed quarantine storage backend identity is invalid")

    existing = db.scalar(select(ExternalDocumentSourceRemoteContentStagingExecution).where(
        ExternalDocumentSourceRemoteContentStagingExecution.organization_id == organization_id,
        ExternalDocumentSourceRemoteContentStagingExecution.profile_id == profile_id,
        ExternalDocumentSourceRemoteContentStagingExecution.remote_content_read_execution_id == remote_content_read_execution_id,
    ))
    new_anchor = existing is None
    if existing is not None:
        _ensure_anchor_integrity(db, existing, verify_storage=existing.status == "completed")
        if existing.request_key != normalized_key or existing.request_reason != normalized_reason or existing.requested_by_id != requested_by_id:
            raise ExternalDocumentSourceConflictError("Conflicting replay for remote content staging execution")
        if existing.status == "completed":
            return existing, "unchanged"
        execution = existing
        upstream = _get_upstream(db, execution)
    else:
        collision = db.scalar(select(ExternalDocumentSourceRemoteContentStagingExecution).where(
            ExternalDocumentSourceRemoteContentStagingExecution.organization_id == organization_id,
            ExternalDocumentSourceRemoteContentStagingExecution.profile_id == profile_id,
            ExternalDocumentSourceRemoteContentStagingExecution.request_key == normalized_key,
        ))
        if collision is not None:
            raise ExternalDocumentSourceConflictError("Conflicting replay for remote content staging request_key")
        upstream = db.scalar(select(ExternalDocumentSourceRemoteFileContentReadExecution).where(
            ExternalDocumentSourceRemoteFileContentReadExecution.id == remote_content_read_execution_id,
            ExternalDocumentSourceRemoteFileContentReadExecution.organization_id == organization_id,
            ExternalDocumentSourceRemoteFileContentReadExecution.profile_id == profile_id,
        ).with_for_update())
        if upstream is None:
            raise ExternalDocumentSourceNotFoundError("Phase M remote content read execution not found")
        _ensure_remote_content_read_integrity(db, upstream)
        if upstream.status != "completed" or upstream.completion_hash is None or upstream.content_sha256 is None or upstream.content_byte_count is None:
            raise ExternalDocumentSourceConflictError("Phase M remote content read is not eligible for durable staging")
        if upstream.content_byte_count > MAX_STAGED_CONTENT_BYTES:
            raise ExternalDocumentSourceConflictError("Phase M content proof exceeds the Phase N byte bound")
        current = _aware(now or _utc_now())
        execution = ExternalDocumentSourceRemoteContentStagingExecution(
            organization_id=organization_id, profile_id=profile_id, remote_content_read_execution_id=upstream.id,
            listing_execution_id=upstream.listing_execution_id, metadata_item_id=upstream.metadata_item_id,
            provider_kind=upstream.provider_kind, profile_hash=upstream.profile_hash, metadata_item_hash=upstream.metadata_item_hash,
            upstream_scope_hash=upstream.scope_hash, upstream_request_hash=upstream.request_hash,
            upstream_completion_hash=upstream.completion_hash, read_operation_kind=upstream.read_operation_kind,
            read_adapter_kind=upstream.read_adapter_kind, endpoint_policy_hash=upstream.endpoint_policy_hash,
            expected_content_sha256=upstream.content_sha256, expected_content_byte_count=upstream.content_byte_count,
            expected_media_type_class=upstream.media_type_class, expected_version_token_hash=upstream.observed_version_token_hash,
            storage_backend_kind=backend, storage_purpose=STORAGE_PURPOSE, storage_object_key="pending",
            storage_object_key_hash="0" * 64, request_key=normalized_key, scope_hash="0" * 64, request_hash="0" * 64,
            status="requested", requested_by_id=requested_by_id, request_reason=normalized_reason, requested_at=current,
            **_base_safety(False),
        )
        db.add(execution)
        db.flush()
        execution.storage_object_key = _storage_key(execution.id, organization_id, upstream.content_sha256)
        execution.storage_object_key_hash = hashlib.sha256(execution.storage_object_key.encode("utf-8")).hexdigest()
        execution.scope_hash = _scope_hash(upstream, storage_backend_kind=backend, storage_object_key_hash=execution.storage_object_key_hash, request_key=normalized_key)
        execution.request_hash = _request_hash(execution)
        _append_receipt(db, execution=execution, event_type="requested", actor_id=requested_by_id, occurred_at=current, decision_hash=execution.request_hash)
        _ensure_anchor_integrity(db, execution, verify_storage=False)
        db.commit()
        db.refresh(execution)

    # Recovery path: an earlier attempt may have written the deterministic object before DB completion.
    if not new_anchor:
        try:
            metadata = _verify_storage_object(store, execution)
        except ObjectStorageNotFound:
            metadata = None
        if metadata is not None:
            completed_at = max(_aware(execution.requested_at), _utc_now())
            _complete_from_storage(db, execution, store=store, metadata=metadata, completed_at=completed_at)
            return execution, "completed"

    listing = _listing_execution(db, upstream)
    item = _metadata_item(db, upstream)
    binding = _active_binding(db, listing)
    profile = _get_profile(db, organization_id=organization_id, profile_id=profile_id)
    _ensure_profile_integrity(db, profile)
    if profile.status != "active" or profile.profile_hash != upstream.profile_hash:
        raise ExternalDocumentSourceConflictError("External document source profile is not active")
    policy = _read_policy(profile.provider_kind, profile.normalized_config, item)
    if _endpoint_policy_hash(policy) != upstream.endpoint_policy_hash or policy.read_operation_kind != upstream.read_operation_kind:
        raise ExternalDocumentSourceConflictError("Phase N remote reread policy drifted from Phase M")
    adapter = _READ_ADAPTERS.get((profile.provider_kind, policy.read_operation_kind))
    if adapter is None:
        raise ExternalDocumentSourceConflictError("Remote file content read adapter is unavailable for Phase N staging")
    if getattr(adapter, "adapter_kind", None) != upstream.read_adapter_kind:
        raise ExternalDocumentSourceConflictError("Phase N remote reread adapter drifted from Phase M")
    locator = CredentialReferenceLocator(
        backend=binding.reference_backend, namespace=binding.reference_namespace,
        name=binding.reference_name, version=binding.reference_version,
    )
    try:
        transient_result = adapter.read_content(locator, policy)
    except Exception:
        raise ExternalDocumentSourceConflictError("Remote content staging reread failed") from None
    try:
        proof = _consume_result(transient_result, policy, item)
        payload = transient_result.content
        if type(payload) is not bytes:
            raise ExternalDocumentSourceConflictError("Remote content staging reread returned an invalid body")
        if proof.content_sha256 != upstream.content_sha256 or proof.content_byte_count != upstream.content_byte_count:
            raise ExternalDocumentSourceConflictError("Phase N reread does not match the Phase M content proof")
        if proof.media_type_class != upstream.media_type_class or proof.observed_version_token_hash != upstream.observed_version_token_hash:
            raise ExternalDocumentSourceConflictError("Phase N reread metadata does not match the Phase M proof")
        try:
            store.put_bytes_if_absent(payload, storage_key=execution.storage_object_key, expected_sha256=upstream.content_sha256)
        except ObjectStoragePreconditionFailed:
            pass
        except ObjectStorageError:
            raise ExternalDocumentSourceConflictError("Governed quarantine storage write failed") from None
    finally:
        del transient_result

    metadata = _verify_storage_object(store, execution)
    completed_at = max(_aware(execution.requested_at), _utc_now())
    _complete_from_storage(db, execution, store=store, metadata=metadata, completed_at=completed_at)
    return execution, "completed"


def get_external_document_source_remote_content_staging(db: Session, *, organization_id: UUID, profile_id: UUID, execution_id: UUID):
    execution = db.scalar(select(ExternalDocumentSourceRemoteContentStagingExecution).where(
        ExternalDocumentSourceRemoteContentStagingExecution.id == execution_id,
        ExternalDocumentSourceRemoteContentStagingExecution.organization_id == organization_id,
        ExternalDocumentSourceRemoteContentStagingExecution.profile_id == profile_id,
    ))
    if execution is None:
        raise ExternalDocumentSourceNotFoundError("Remote content staging execution not found")
    _ensure_anchor_integrity(db, execution, verify_storage=execution.status == "completed")
    return execution


def list_external_document_source_remote_content_staging_receipts(db: Session, *, organization_id: UUID, profile_id: UUID, execution_id: UUID):
    execution = get_external_document_source_remote_content_staging(
        db, organization_id=organization_id, profile_id=profile_id, execution_id=execution_id,
    )
    return _receipts(db, execution)
