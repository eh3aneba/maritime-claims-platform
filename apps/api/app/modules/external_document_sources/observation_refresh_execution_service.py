from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.documents.object_storage import (
    ObjectStorageError,
    ObjectStorageIntegrityError,
    ObjectStorageNotFound,
    ObjectStoragePreconditionFailed,
)
from app.modules.external_document_sources.due_tick_observation_models import (
    ExternalDocumentSourceDueTickObservationExecution,
)
from app.modules.external_document_sources.due_tick_observation_service import (
    _provider_lineage,
    ensure_due_tick_observation_integrity,
)
from app.modules.external_document_sources.family_version_admission_service import (
    _binding_for_update,
    _lock_current_family_document,
)
from app.modules.external_document_sources.generation_3_change_detection_service import (
    _lineage as _generation3_lineage,
)
from app.modules.external_document_sources.observation_refresh_execution_models import (
    ExternalDocumentSourceObservationRefreshExecution,
    ExternalDocumentSourceObservationRefreshReceipt,
)
from app.modules.external_document_sources.observation_review_decision_models import (
    ExternalDocumentSourceObservationRefreshAuthorization,
    ExternalDocumentSourceObservationReviewDecision,
)
from app.modules.external_document_sources.observation_review_decision_service import (
    _require_human_admin,
    ensure_observation_refresh_authorization_integrity,
)
from app.modules.external_document_sources.remote_content_staging_service import (
    _configured_store,
)
from app.modules.external_document_sources.remote_file_content_read_service import (
    _ALLOWED_LATENCY_CLASSES,
    _READ_ADAPTERS,
    _endpoint_policy_hash,
    _normalize_hash,
    _normalize_identifier,
    _normalize_media_type,
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
STORAGE_PURPOSE = "external_observation_refresh_quarantine_v1"
MAX_REFRESH_BYTES = 64 * 1024 * 1024


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _aware(value).isoformat()


def _canonical_hash(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
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


def _safety() -> dict[str, bool]:
    return {
        "authorization_integrity_verified": True,
        "current_authority_verified": True,
        "current_document_verified": True,
        "provider_lineage_verified": True,
        "originating_observation_verified": True,
        "provider_client_constructed": True,
        "exact_item_content_read_performed": True,
        "storage_write_performed": True,
        "storage_read_performed": True,
        "durable_content_staged": True,
        "remote_list_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "storage_delete_performed": False,
        "provider_response_body_stored": False,
        "remote_content_returned": False,
        "content_parsed": False,
        "content_extracted": False,
        "document_mutated": False,
        "evidence_admitted": False,
        "processing_enqueued": False,
        "ai_executed": False,
        "claim_mutated": False,
        "checkpoint_advanced": False,
    }


def _storage_key(authorization_id: UUID, execution_id: UUID) -> str:
    return (
        "external-observation-refresh-quarantine/"
        f"{authorization_id}/{execution_id}"
    )


def _scope_hash(
    authorization: ExternalDocumentSourceObservationRefreshAuthorization,
    *,
    observation: ExternalDocumentSourceDueTickObservationExecution,
    current_document_id: UUID,
    current_version_number: int,
    current_document_file_hash: str,
    read_operation_kind: str,
    read_adapter_kind: str,
    endpoint_policy_hash: str,
    storage_backend_kind: str,
    storage_object_key_hash: str,
    request_key: str,
) -> str:
    return _canonical_hash(
        {
            "authorization_id": str(authorization.id),
            "authorization_hash": authorization.authorization_hash,
            "decision_id": str(authorization.decision_id),
            "handoff_id": str(authorization.handoff_id),
            "binding_id": str(authorization.binding_id),
            "document_family_id": str(authorization.document_family_id),
            "current_document_id": str(current_document_id),
            "current_version_number": current_version_number,
            "current_document_file_hash": current_document_file_hash,
            "provider_kind": authorization.provider_kind,
            "profile_hash": authorization.profile_hash,
            "stable_source_item_hash": authorization.stable_source_item_hash,
            "observed_projection_hash": authorization.observed_projection_hash,
            "observed_version_token_hash": authorization.observed_version_token_hash,
            "observation_execution_id": str(observation.id),
            "observation_completion_hash": observation.completion_hash,
            "read_operation_kind": read_operation_kind,
            "read_adapter_kind": read_adapter_kind,
            "endpoint_policy_hash": endpoint_policy_hash,
            "storage_backend_kind": storage_backend_kind,
            "storage_object_key_hash": storage_object_key_hash,
            "request_key": request_key,
        }
    )


def _request_hash(
    *,
    scope_hash: str,
    requested_by_id: UUID,
    reason: str,
    requested_at: datetime,
) -> str:
    return _canonical_hash(
        {
            "scope_hash": scope_hash,
            "requested_by_id": str(requested_by_id),
            "reason": reason,
            "requested_at": _iso(requested_at),
            **_safety(),
        }
    )


def _content_proof_hash(
    *,
    authorization_hash: str,
    content_sha256: str,
    content_byte_count: int,
    media_type_class: str | None,
    version_token_hash: str | None,
    storage_object_key_hash: str,
) -> str:
    return _canonical_hash(
        {
            "authorization_hash": authorization_hash,
            "content_sha256": content_sha256,
            "content_byte_count": content_byte_count,
            "media_type_class": media_type_class,
            "version_token_hash": version_token_hash,
            "storage_object_key_hash": storage_object_key_hash,
        }
    )


def _completion_hash(execution: ExternalDocumentSourceObservationRefreshExecution) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "request_hash": execution.request_hash,
            "status": execution.status,
            "result_status": execution.result_status,
            "content_proof_hash": execution.content_proof_hash,
            "completed_at": _iso(execution.completed_at),
            **_safety(),
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceObservationRefreshReceipt) -> str:
    return _canonical_hash(
        {
            "receipt_id": str(receipt.id),
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
            **_safety(),
        }
    )


def _authorization_for_update(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
) -> ExternalDocumentSourceObservationRefreshAuthorization:
    authorization = db.scalar(
        select(ExternalDocumentSourceObservationRefreshAuthorization)
        .where(
            ExternalDocumentSourceObservationRefreshAuthorization.id == authorization_id,
            ExternalDocumentSourceObservationRefreshAuthorization.organization_id == organization_id,
            ExternalDocumentSourceObservationRefreshAuthorization.profile_id == profile_id,
        )
        .with_for_update()
    )
    if authorization is None:
        raise ExternalDocumentSourceNotFoundError(
            "Observation refresh authorization not found"
        )
    ensure_observation_refresh_authorization_integrity(db, authorization)
    return authorization


def _originating_observation(
    db: Session,
    authorization: ExternalDocumentSourceObservationRefreshAuthorization,
) -> tuple[ExternalDocumentSourceObservationReviewDecision, ExternalDocumentSourceDueTickObservationExecution]:
    decision = db.get(
        ExternalDocumentSourceObservationReviewDecision,
        authorization.decision_id,
    )
    if decision is None:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh decision lineage is missing"
        )
    observation = db.get(
        ExternalDocumentSourceDueTickObservationExecution,
        decision.observation_execution_id,
    )
    if observation is None:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh due-tick lineage is missing"
        )
    ensure_due_tick_observation_integrity(db, observation)
    if (
        observation.status != "completed"
        or observation.result_status != "changed"
        or observation.organization_id != authorization.organization_id
        or observation.profile_id != authorization.profile_id
        or observation.claim_id != authorization.claim_id
        or observation.binding_id != authorization.binding_id
        or observation.document_family_id != authorization.document_family_id
        or observation.current_document_id != authorization.current_document_id
        or observation.current_version_number != authorization.current_version_number
        or observation.provider_kind != authorization.provider_kind
        or observation.profile_hash != authorization.profile_hash
        or observation.stable_source_item_hash != authorization.stable_source_item_hash
        or observation.observed_projection_hash != authorization.observed_projection_hash
        or observation.observed_version_token_hash != authorization.observed_version_token_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh originating changed observation drifted"
        )
    return decision, observation


def _provider_read_context(
    db: Session,
    *,
    authorization: ExternalDocumentSourceObservationRefreshAuthorization,
    observation: ExternalDocumentSourceDueTickObservationExecution,
):
    binding = _binding_for_update(
        db,
        organization_id=authorization.organization_id,
        profile_id=authorization.profile_id,
        binding_id=authorization.binding_id,
    )
    if (
        binding.claim_id != authorization.claim_id
        or binding.document_family_id != authorization.document_family_id
        or binding.provider_kind != authorization.provider_kind
        or binding.profile_hash != authorization.profile_hash
        or binding.stable_source_item_hash != authorization.stable_source_item_hash
        or binding.completion_hash != authorization.binding_completion_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh family binding authority drifted"
        )

    current = _lock_current_family_document(
        db,
        organization_id=authorization.organization_id,
        claim_id=authorization.claim_id,
        document_family_id=authorization.document_family_id,
        expected_current_document_id=authorization.current_document_id,
    )
    if (
        current.version_number != authorization.current_version_number
        or current.file_hash != authorization.current_document_file_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh authorization is stale because canonical Evidence changed"
        )

    lineage_observation, checkpoint, profile, locator, _observation_policy = _provider_lineage(
        db, binding
    )
    if (
        lineage_observation.id != observation.provider_lineage_observation_id
        or checkpoint.id != observation.provider_lineage_checkpoint_id
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh provider lineage no longer matches the changed observation"
        )
    (
        _candidate,
        _phase_s_observation,
        _listing,
        item,
        lineage_profile,
        lineage_locator,
        _policy,
        _baseline,
        _baseline_hash,
    ) = _generation3_lineage(db, checkpoint)
    if lineage_profile.id != profile.id or lineage_locator != locator:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh exact-item provider lineage drifted"
        )
    if (
        hashlib.sha256(item.provider_item_id.encode("utf-8")).hexdigest()
        != authorization.stable_source_item_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh exact provider item drifted"
        )

    profile = _get_profile(
        db,
        organization_id=authorization.organization_id,
        profile_id=authorization.profile_id,
    )
    _ensure_profile_integrity(db, profile)
    if (
        profile.status != "active"
        or profile.provider_kind != authorization.provider_kind
        or profile.profile_hash != authorization.profile_hash
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh source profile is no longer active"
        )

    policy = _read_policy(profile.provider_kind, profile.normalized_config, item)
    adapter = _READ_ADAPTERS.get((profile.provider_kind, policy.read_operation_kind))
    if adapter is None:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh exact-item content adapter is unavailable"
        )
    adapter_kind = _normalize_identifier(
        adapter.adapter_kind,
        field="Observation refresh content adapter kind",
    )
    if (
        adapter.provider_kind != profile.provider_kind
        or adapter.client_kind != policy.client_kind
        or adapter.read_operation_kind != policy.read_operation_kind
        or adapter.provider_origin != policy.provider_origin
        or adapter.redirect_policy_kind != policy.redirect_policy_kind
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh content adapter policy drifted"
        )
    return current, profile, locator, policy, adapter, adapter_kind


def _read_exact_changed_content(adapter, locator, policy, observation):
    try:
        result = adapter.read_content(locator, policy)
    except Exception:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh exact-item content read failed"
        ) from None

    if getattr(result, "read", None) is not True:
        failure_code = getattr(result, "failure_code", None)
        raise ExternalDocumentSourceConflictError(
            f"Observation refresh content read failed ({failure_code or 'invalid_result'})"
        )
    payload = getattr(result, "content", None)
    if getattr(result, "failure_code", None) is not None or type(payload) is not bytes:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh adapter returned an invalid successful result"
        )
    if len(payload) > policy.max_content_bytes or len(payload) > MAX_REFRESH_BYTES:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh content exceeded the byte bound"
        )
    if observation.observed_byte_size is not None and len(payload) != observation.observed_byte_size:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh byte count no longer matches the changed observation"
        )
    latency = getattr(result, "latency_class", None)
    if latency not in _ALLOWED_LATENCY_CLASSES:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh adapter returned an invalid latency class"
        )
    media = _normalize_media_type(getattr(result, "media_type_class", None))
    expected_media = _normalize_media_type(observation.observed_mime_type_class)
    if media is not None and expected_media is not None and media != expected_media:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh media type no longer matches the changed observation"
        )
    media = media or expected_media
    version = _normalize_hash(
        getattr(result, "observed_version_token_hash", None),
        field="Observed version-token hash",
    )
    expected_version = _normalize_hash(
        observation.observed_version_token_hash,
        field="Changed observation version-token hash",
    )
    if expected_version is not None and version != expected_version:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh version no longer matches the changed observation"
        )
    return payload, hashlib.sha256(payload).hexdigest(), len(payload), media, version


def _verify_storage(store, *, storage_key: str, digest: str, byte_count: int) -> None:
    try:
        metadata = store.head_object(storage_key=storage_key)
        if (
            metadata.file_hash.lower() != digest
            or metadata.file_size_bytes != byte_count
        ):
            raise ExternalDocumentSourceConflictError(
                "Observation refresh quarantine object does not match the content proof"
            )
        payload = store.get_bytes(storage_key=storage_key, expected_sha256=digest)
        if len(payload) != byte_count:
            raise ExternalDocumentSourceConflictError(
                "Observation refresh quarantine object byte count drifted"
            )
        del payload
    except ExternalDocumentSourceConflictError:
        raise
    except (ObjectStorageNotFound, ObjectStorageError, ObjectStorageIntegrityError):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh quarantine storage verification failed"
        ) from None


def _receipts(
    db: Session,
    execution: ExternalDocumentSourceObservationRefreshExecution,
) -> list[ExternalDocumentSourceObservationRefreshReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceObservationRefreshReceipt).where(
                ExternalDocumentSourceObservationRefreshReceipt.organization_id
                == execution.organization_id,
                ExternalDocumentSourceObservationRefreshReceipt.execution_id
                == execution.id,
            )
        ).all()
    )


def ensure_observation_refresh_execution_integrity(
    db: Session,
    execution: ExternalDocumentSourceObservationRefreshExecution,
    *,
    verify_storage: bool = False,
) -> None:
    authorization = db.get(
        ExternalDocumentSourceObservationRefreshAuthorization,
        execution.authorization_id,
    )
    if authorization is None:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh execution authorization is missing"
        )
    ensure_observation_refresh_authorization_integrity(db, authorization)
    decision, observation = _originating_observation(db, authorization)
    expected = {
        "organization_id": authorization.organization_id,
        "claim_id": authorization.claim_id,
        "profile_id": authorization.profile_id,
        "decision_id": authorization.decision_id,
        "handoff_id": authorization.handoff_id,
        "observation_execution_id": observation.id,
        "binding_id": authorization.binding_id,
        "document_family_id": authorization.document_family_id,
        "current_document_id": authorization.current_document_id,
        "current_version_number": authorization.current_version_number,
        "current_document_file_hash": authorization.current_document_file_hash,
        "provider_kind": authorization.provider_kind,
        "profile_hash": authorization.profile_hash,
        "stable_source_item_hash": authorization.stable_source_item_hash,
        "authorization_hash": authorization.authorization_hash,
        "decision_completion_hash": decision.completion_hash,
        "handoff_completion_hash": authorization.handoff_completion_hash,
        "binding_completion_hash": authorization.binding_completion_hash,
        "observed_projection_hash": authorization.observed_projection_hash,
        "observed_version_token_hash": authorization.observed_version_token_hash,
    }
    for field, value in expected.items():
        if getattr(execution, field) != value:
            raise ExternalDocumentSourceConflictError(
                f"Observation refresh execution snapshot drifted at {field}"
            )
    expected_execution_id = uuid5(
        NAMESPACE_URL,
        f"mcri:observation-refresh:{authorization.id}",
    )
    expected_storage_key = _storage_key(authorization.id, expected_execution_id)
    expected_storage_key_hash = hashlib.sha256(
        expected_storage_key.encode("utf-8")
    ).hexdigest()
    expected_scope_hash = _scope_hash(
        authorization,
        observation=observation,
        current_document_id=execution.current_document_id,
        current_version_number=execution.current_version_number,
        current_document_file_hash=execution.current_document_file_hash,
        read_operation_kind=execution.read_operation_kind,
        read_adapter_kind=execution.read_adapter_kind,
        endpoint_policy_hash=execution.endpoint_policy_hash,
        storage_backend_kind=execution.storage_backend_kind,
        storage_object_key_hash=execution.storage_object_key_hash,
        request_key=execution.request_key,
    )
    expected_request_hash = _request_hash(
        scope_hash=expected_scope_hash,
        requested_by_id=execution.requested_by_id,
        reason=execution.request_reason,
        requested_at=execution.requested_at,
    )
    if (
        execution.id != expected_execution_id
        or execution.storage_object_key != expected_storage_key
        or execution.storage_object_key_hash != expected_storage_key_hash
        or execution.scope_hash != expected_scope_hash
        or execution.request_hash != expected_request_hash
        or execution.status != "completed"
        or execution.result_status != "staged_refresh_verified"
        or execution.content_byte_count < 0
        or _aware(execution.completed_at) < _aware(execution.requested_at)
        or execution.content_proof_hash
        != _content_proof_hash(
            authorization_hash=execution.authorization_hash,
            content_sha256=execution.content_sha256,
            content_byte_count=execution.content_byte_count,
            media_type_class=execution.content_media_type_class,
            version_token_hash=execution.content_version_token_hash,
            storage_object_key_hash=execution.storage_object_key_hash,
        )
        or execution.completion_hash != _completion_hash(execution)
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh execution cryptographic integrity failed"
        )
    for field, value in _safety().items():
        if bool(getattr(execution, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Observation refresh execution safety boundary drifted"
            )
    receipts = _receipts(db, execution)
    if len(receipts) != 1:
        raise ExternalDocumentSourceConflictError(
            "Observation refresh execution receipt lifecycle drifted"
        )
    receipt = receipts[0]
    if (
        receipt.sequence_number != 1
        or receipt.event_type != "completed"
        or receipt.status_after != "completed"
        or receipt.actor_id != execution.requested_by_id
        or _aware(receipt.occurred_at) != _aware(execution.completed_at)
        or receipt.reason != execution.request_reason
        or receipt.scope_hash != execution.scope_hash
        or receipt.decision_hash != execution.completion_hash
        or receipt.prior_receipt_hash is not None
        or receipt.receipt_hash != _receipt_hash(receipt)
    ):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh execution receipt integrity drifted"
        )
    for field, value in _safety().items():
        if bool(getattr(receipt, field)) != value:
            raise ExternalDocumentSourceConflictError(
                "Observation refresh receipt safety boundary drifted"
            )
    if verify_storage:
        _verify_storage(
            _configured_store(),
            storage_key=execution.storage_object_key,
            digest=execution.content_sha256,
            byte_count=execution.content_byte_count,
        )


def execute_observation_refresh_authorization(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    authorization_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
) -> tuple[ExternalDocumentSourceObservationRefreshExecution, str]:
    _require_human_admin(
        db,
        organization_id=organization_id,
        user_id=requested_by_id,
    )
    normalized_key = _normalize_text(
        request_key, field="request_key", minimum=1, maximum=128
    )
    normalized_reason = _normalize_text(
        request_reason, field="reason", minimum=20, maximum=2000
    )

    existing_request = db.scalar(
        select(ExternalDocumentSourceObservationRefreshExecution).where(
            ExternalDocumentSourceObservationRefreshExecution.organization_id
            == organization_id,
            ExternalDocumentSourceObservationRefreshExecution.profile_id
            == profile_id,
            ExternalDocumentSourceObservationRefreshExecution.request_key
            == normalized_key,
        )
    )
    if existing_request is not None:
        ensure_observation_refresh_execution_integrity(
            db, existing_request, verify_storage=True
        )
        if (
            existing_request.authorization_id != authorization_id
            or existing_request.requested_by_id != requested_by_id
            or existing_request.request_reason != normalized_reason
        ):
            raise ExternalDocumentSourceConflictError(
                "Observation refresh request_key is already bound to another execution"
            )
        return existing_request, "replayed"

    authorization = _authorization_for_update(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        authorization_id=authorization_id,
    )
    existing = db.scalar(
        select(ExternalDocumentSourceObservationRefreshExecution).where(
            ExternalDocumentSourceObservationRefreshExecution.authorization_id
            == authorization.id
        )
    )
    if existing is not None:
        ensure_observation_refresh_execution_integrity(
            db, existing, verify_storage=True
        )
        if (
            existing.request_key != normalized_key
            or existing.requested_by_id != requested_by_id
            or existing.request_reason != normalized_reason
        ):
            raise ExternalDocumentSourceConflictError(
                "Observation refresh authorization was already consumed by another request"
            )
        return existing, "replayed"

    decision, observation = _originating_observation(db, authorization)
    current, _profile, locator, policy, adapter, adapter_kind = _provider_read_context(
        db,
        authorization=authorization,
        observation=observation,
    )

    store = _configured_store()
    backend = getattr(store.sanitized_health_identity, "backend", None)
    if not isinstance(backend, str) or not _SAFE_IDENTIFIER.fullmatch(backend):
        raise ExternalDocumentSourceConflictError(
            "Observation refresh quarantine storage backend identity is invalid"
        )

    execution_id = uuid5(
        NAMESPACE_URL,
        f"mcri:observation-refresh:{authorization.id}",
    )
    storage_key = _storage_key(authorization.id, execution_id)
    storage_key_hash = hashlib.sha256(storage_key.encode("utf-8")).hexdigest()
    endpoint_policy_hash = _endpoint_policy_hash(policy)
    requested_at = _aware(now or _utc_now())
    scope_hash = _scope_hash(
        authorization,
        observation=observation,
        current_document_id=current.id,
        current_version_number=current.version_number,
        current_document_file_hash=current.file_hash,
        read_operation_kind=policy.read_operation_kind,
        read_adapter_kind=adapter_kind,
        endpoint_policy_hash=endpoint_policy_hash,
        storage_backend_kind=backend,
        storage_object_key_hash=storage_key_hash,
        request_key=normalized_key,
    )
    request_hash = _request_hash(
        scope_hash=scope_hash,
        requested_by_id=requested_by_id,
        reason=normalized_reason,
        requested_at=requested_at,
    )

    payload, digest, count, media, version = _read_exact_changed_content(
        adapter, locator, policy, observation
    )
    try:
        try:
            store.put_bytes_if_absent(
                payload,
                storage_key=storage_key,
                expected_sha256=digest,
            )
        except ObjectStoragePreconditionFailed:
            pass
        except ObjectStorageError:
            raise ExternalDocumentSourceConflictError(
                "Observation refresh quarantine storage write failed"
            ) from None
    finally:
        del payload

    _verify_storage(
        store,
        storage_key=storage_key,
        digest=digest,
        byte_count=count,
    )
    completed_at = max(requested_at, _utc_now())
    content_proof_hash = _content_proof_hash(
        authorization_hash=authorization.authorization_hash,
        content_sha256=digest,
        content_byte_count=count,
        media_type_class=media,
        version_token_hash=version,
        storage_object_key_hash=storage_key_hash,
    )
    execution = ExternalDocumentSourceObservationRefreshExecution(
        id=execution_id,
        organization_id=organization_id,
        claim_id=authorization.claim_id,
        profile_id=profile_id,
        authorization_id=authorization.id,
        decision_id=authorization.decision_id,
        handoff_id=authorization.handoff_id,
        observation_execution_id=observation.id,
        binding_id=authorization.binding_id,
        document_family_id=authorization.document_family_id,
        current_document_id=current.id,
        current_version_number=current.version_number,
        current_document_file_hash=current.file_hash,
        provider_kind=authorization.provider_kind,
        profile_hash=authorization.profile_hash,
        stable_source_item_hash=authorization.stable_source_item_hash,
        authorization_hash=authorization.authorization_hash,
        decision_completion_hash=decision.completion_hash,
        handoff_completion_hash=authorization.handoff_completion_hash,
        binding_completion_hash=authorization.binding_completion_hash,
        observed_projection_hash=authorization.observed_projection_hash,
        observed_version_token_hash=authorization.observed_version_token_hash,
        read_operation_kind=policy.read_operation_kind,
        read_adapter_kind=adapter_kind,
        endpoint_policy_hash=endpoint_policy_hash,
        storage_backend_kind=backend,
        storage_purpose=STORAGE_PURPOSE,
        storage_object_key=storage_key,
        storage_object_key_hash=storage_key_hash,
        content_sha256=digest,
        content_byte_count=count,
        content_media_type_class=media,
        content_version_token_hash=version,
        content_proof_hash=content_proof_hash,
        request_key=normalized_key,
        request_hash=request_hash,
        scope_hash=scope_hash,
        status="completed",
        result_status="staged_refresh_verified",
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=requested_at,
        completed_at=completed_at,
        completion_hash="",
        **_safety(),
    )
    execution.completion_hash = _completion_hash(execution)
    db.add(execution)
    db.flush()

    receipt = ExternalDocumentSourceObservationRefreshReceipt(
        id=uuid4(),
        organization_id=organization_id,
        execution_id=execution.id,
        sequence_number=1,
        event_type="completed",
        status_after="completed",
        actor_id=requested_by_id,
        occurred_at=completed_at,
        reason=normalized_reason,
        scope_hash=scope_hash,
        decision_hash=execution.completion_hash,
        prior_receipt_hash=None,
        receipt_hash="",
        **_safety(),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()
    ensure_observation_refresh_execution_integrity(
        db, execution, verify_storage=True
    )
    write_audit_log(
        db,
        organization_id=organization_id,
        user_id=requested_by_id,
        action="CONSUME_EXTERNAL_EVIDENCE_OBSERVATION_REFRESH_AUTHORIZATION",
        entity_type="external_document_source_observation_refresh_execution",
        entity_id=execution.id,
        new_values={
            "authorization_id": str(authorization.id),
            "handoff_id": str(authorization.handoff_id),
            "observation_execution_id": str(observation.id),
            "current_document_id": str(current.id),
            "current_version_number": current.version_number,
            "result_status": execution.result_status,
            "content_sha256": digest,
            "content_byte_count": count,
            "remote_list_performed": False,
            "exact_item_content_read_performed": True,
            "document_mutated": False,
            "evidence_admitted": False,
            "processing_enqueued": False,
            "ai_executed": False,
        },
    )
    db.commit()
    db.refresh(execution)
    return execution, "completed"


def get_observation_refresh_execution(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
) -> ExternalDocumentSourceObservationRefreshExecution:
    execution = db.scalar(
        select(ExternalDocumentSourceObservationRefreshExecution).where(
            ExternalDocumentSourceObservationRefreshExecution.id == execution_id,
            ExternalDocumentSourceObservationRefreshExecution.organization_id
            == organization_id,
            ExternalDocumentSourceObservationRefreshExecution.profile_id
            == profile_id,
        )
    )
    if execution is None:
        raise ExternalDocumentSourceNotFoundError(
            "Observation refresh execution not found"
        )
    ensure_observation_refresh_execution_integrity(
        db, execution, verify_storage=True
    )
    return execution


def list_observation_refresh_execution_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
) -> list[ExternalDocumentSourceObservationRefreshReceipt]:
    execution = get_observation_refresh_execution(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _receipts(db, execution)
