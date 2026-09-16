from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import quote, urlencode, urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources.change_detection_models import (
    ExternalDocumentSourceChangeDetectionExecution,
    ExternalDocumentSourceChangeDetectionReceipt,
)
from app.modules.external_document_sources.credential_reference_health_service import CredentialReferenceLocator
from app.modules.external_document_sources.remote_metadata_listing_models import (
    ExternalDocumentSourceRemoteMetadataListingExecution,
    ExternalDocumentSourceRemoteMetadataListingItem,
)
from app.modules.external_document_sources.remote_metadata_listing_service import (
    RemoteMetadataItemProjection,
    _active_binding,
    _ensure_integrity as _ensure_remote_metadata_listing_integrity,
    _health_execution,
    _normalize_projection,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
    _ensure_profile_integrity,
    _get_profile,
)
from app.modules.external_document_sources.sync_checkpoint_models import ExternalDocumentSourceSyncCheckpointExecution
from app.modules.external_document_sources.sync_checkpoint_service import (
    _ensure_integrity as _ensure_sync_checkpoint_integrity,
)

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_FAILURE_CODES = {
    "not_found",
    "unauthorized",
    "permission_denied",
    "endpoint_unavailable",
    "timeout",
    "malformed_response",
    "oversized_response",
    "provider_rejected",
}
_PROVIDER_POLICIES = {
    "sharepoint": {
        "client_kind": "microsoft_graph_transient_v1",
        "operation_kind": "graph_drive_item_metadata_read_v1",
        "provider_origin": "https://graph.microsoft.com",
        "field_projection": "id,name,size,lastModifiedDateTime,file,folder,parentReference,eTag",
    },
    "google_drive": {
        "client_kind": "google_drive_transient_v3",
        "operation_kind": "drive_file_metadata_read_v1",
        "provider_origin": "https://www.googleapis.com",
        "field_projection": "id,name,mimeType,size,modifiedTime,parents,md5Checksum",
    },
}


@dataclass(frozen=True)
class ExactItemMetadataPolicy:
    provider_kind: str
    client_kind: str
    observation_operation_kind: str
    provider_origin: str
    metadata_endpoint_url: str
    field_projection: str
    max_response_bytes: int = 65536
    connect_timeout_seconds: float = 3.0
    read_timeout_seconds: float = 7.0
    total_timeout_seconds: float = 10.0
    allow_redirects: bool = False


@dataclass(frozen=True)
class ExactItemMetadataResult:
    found: bool
    item: RemoteMetadataItemProjection | None = None
    failure_code: str | None = None


class ExternalDocumentSourceExactItemMetadataAdapter(Protocol):
    adapter_kind: str
    provider_kind: str
    client_kind: str
    observation_operation_kind: str
    provider_origin: str

    def read_item_metadata(
        self,
        locator: CredentialReferenceLocator,
        policy: ExactItemMetadataPolicy,
    ) -> ExactItemMetadataResult: ...


_OBSERVATION_ADAPTERS: dict[tuple[str, str], ExternalDocumentSourceExactItemMetadataAdapter] = {}


def register_external_document_source_change_detection_adapter(
    provider_kind: str,
    observation_operation_kind: str,
    adapter: ExternalDocumentSourceExactItemMetadataAdapter,
) -> None:
    provider = provider_kind.strip().lower()
    operation = observation_operation_kind.strip().lower()
    expected = _PROVIDER_POLICIES.get(provider)
    if expected is None or operation != expected["operation_kind"]:
        raise ValueError("Unsupported provider/change-detection operation combination")
    adapter_kind = getattr(adapter, "adapter_kind", None)
    if not isinstance(adapter_kind, str) or not _SAFE_IDENTIFIER.fullmatch(adapter_kind):
        raise ValueError("Change-detection adapter kind is invalid")
    if getattr(adapter, "provider_kind", None) != provider:
        raise ValueError("Change-detection adapter provider kind does not match")
    if getattr(adapter, "client_kind", None) != expected["client_kind"]:
        raise ValueError("Change-detection adapter client kind is not approved")
    if getattr(adapter, "observation_operation_kind", None) != operation:
        raise ValueError("Change-detection adapter operation kind does not match")
    origin = getattr(adapter, "provider_origin", None)
    if origin != expected["provider_origin"]:
        raise ValueError("Change-detection adapter origin is not approved")
    parsed = urlparse(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise ValueError("Change-detection adapter origin is invalid")
    _OBSERVATION_ADAPTERS[(provider, operation)] = adapter


def clear_external_document_source_change_detection_adapters() -> None:
    _OBSERVATION_ADAPTERS.clear()


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


def _value_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_text(value: str, *, field: str, minimum: int, maximum: int) -> str:
    normalized = " ".join(value.strip().split())
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError(
            f"{field} must contain between {minimum} and {maximum} characters"
        )
    if "\x00" in normalized:
        raise ExternalDocumentSourceValidationError(f"{field} contains an invalid character")
    return normalized


def _normalize_identifier(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not _SAFE_IDENTIFIER.fullmatch(normalized):
        raise ExternalDocumentSourceConflictError(f"{field} is invalid")
    return normalized


def _base_safety(completed: bool) -> dict[str, bool]:
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
        "provider_client_constructed": completed,
        "exact_item_metadata_read_performed": completed,
        "change_detection_completed": completed,
        "remote_content_transiently_observed": False,
        "remote_list_performed": False,
        "remote_read_performed": False,
        "remote_write_performed": False,
        "remote_delete_performed": False,
        "storage_read_performed": False,
        "storage_write_performed": False,
        "storage_delete_performed": False,
        "durable_content_staged": False,
        "checkpoint_advanced": False,
        "sync_executed": False,
        "subscription_created": False,
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
        "evidence_admitted": False,
        "document_created": False,
        "claim_mutated": False,
    }


def _policy(provider_kind: str, normalized_config: dict, provider_item_id: str) -> ExactItemMetadataPolicy:
    provider = provider_kind.strip().lower()
    base = _PROVIDER_POLICIES.get(provider)
    if base is None:
        raise ExternalDocumentSourceConflictError("Unsupported provider for exact-item change detection")
    if not isinstance(normalized_config, dict):
        raise ExternalDocumentSourceConflictError("Governed provider configuration is invalid")
    item_id = _normalize_text(provider_item_id, field="provider_item_id", minimum=1, maximum=512)

    if provider == "sharepoint":
        if set(normalized_config) != {"tenant_domain", "site_id", "library_id"}:
            raise ExternalDocumentSourceConflictError("Governed SharePoint profile configuration drifted")
        site_id = normalized_config.get("site_id")
        library_id = normalized_config.get("library_id")
        if not isinstance(site_id, str) or not site_id.strip() or not isinstance(library_id, str) or not library_id.strip():
            raise ExternalDocumentSourceConflictError("Governed SharePoint source boundary is incomplete")
        path = (
            f"/v1.0/sites/{quote(site_id.strip(), safe='')}/drives/"
            f"{quote(library_id.strip(), safe='')}/items/{quote(item_id, safe='')}"
        )
        query = urlencode({"$select": base["field_projection"]})
        endpoint = f"{base['provider_origin']}{path}?{query}"
    else:
        if not set(normalized_config).issubset({"shared_drive_id", "folder_id"}) or "shared_drive_id" not in normalized_config:
            raise ExternalDocumentSourceConflictError("Governed Google Drive profile configuration drifted")
        shared_drive_id = normalized_config.get("shared_drive_id")
        if not isinstance(shared_drive_id, str) or not shared_drive_id.strip():
            raise ExternalDocumentSourceConflictError("Governed Google Drive source boundary is incomplete")
        query = urlencode({"supportsAllDrives": "true", "fields": base["field_projection"]})
        endpoint = f"{base['provider_origin']}/drive/v3/files/{quote(item_id, safe='')}?{query}"

    parsed_endpoint = urlparse(endpoint)
    parsed_origin = urlparse(base["provider_origin"])
    if (
        parsed_endpoint.scheme != "https"
        or parsed_endpoint.netloc != parsed_origin.netloc
        or parsed_endpoint.username is not None
        or parsed_endpoint.password is not None
        or parsed_endpoint.fragment
    ):
        raise ExternalDocumentSourceConflictError("Derived exact-item metadata endpoint is not approved")
    return ExactItemMetadataPolicy(
        provider_kind=provider,
        client_kind=base["client_kind"],
        observation_operation_kind=base["operation_kind"],
        provider_origin=base["provider_origin"],
        metadata_endpoint_url=endpoint,
        field_projection=base["field_projection"],
    )


def _endpoint_policy_hash(policy: ExactItemMetadataPolicy) -> str:
    return _canonical_hash(
        {
            "provider_kind": policy.provider_kind,
            "client_kind": policy.client_kind,
            "observation_operation_kind": policy.observation_operation_kind,
            "provider_origin": policy.provider_origin,
            "metadata_endpoint_url": policy.metadata_endpoint_url,
            "field_projection": policy.field_projection,
            "max_response_bytes": policy.max_response_bytes,
            "connect_timeout_seconds": policy.connect_timeout_seconds,
            "read_timeout_seconds": policy.read_timeout_seconds,
            "total_timeout_seconds": policy.total_timeout_seconds,
            "allow_redirects": policy.allow_redirects,
        }
    )


def _projection_facts(item: RemoteMetadataItemProjection) -> dict:
    normalized = _normalize_projection(item)
    return {
        "provider_item_id_hash": _value_hash(normalized.provider_item_id),
        "item_kind": normalized.item_kind,
        "display_name_hash": _value_hash(normalized.display_name),
        "parent_item_id_hash": _value_hash(normalized.parent_item_id) if normalized.parent_item_id is not None else None,
        "mime_type_class": normalized.mime_type_class,
        "byte_size": normalized.byte_size,
        "modified_at": normalized.modified_at,
        "version_token_hash": normalized.version_token_hash,
    }


def _projection_hash(facts: dict) -> str:
    return _canonical_hash(
        {
            "provider_item_id_hash": facts["provider_item_id_hash"],
            "item_kind": facts["item_kind"],
            "display_name_hash": facts["display_name_hash"],
            "parent_item_id_hash": facts["parent_item_id_hash"],
            "mime_type_class": facts["mime_type_class"],
            "byte_size": facts["byte_size"],
            "modified_at": _iso(facts["modified_at"]),
            "version_token_hash": facts["version_token_hash"],
        }
    )


def _baseline_projection(item: ExternalDocumentSourceRemoteMetadataListingItem) -> RemoteMetadataItemProjection:
    return RemoteMetadataItemProjection(
        provider_item_id=item.provider_item_id,
        parent_item_id=item.parent_item_id,
        item_kind=item.item_kind,
        display_name=item.display_name,
        mime_type_class=item.mime_type_class,
        byte_size=item.byte_size,
        modified_at=item.modified_at,
        version_token_hash=item.version_token_hash,
    )


def _changed_dimensions(baseline: dict, observed: dict) -> list[str]:
    dimensions = (
        ("item_kind", "item_kind"),
        ("display_name", "display_name_hash"),
        ("parent_item_id", "parent_item_id_hash"),
        ("mime_type_class", "mime_type_class"),
        ("byte_size", "byte_size"),
        ("modified_at", "modified_at"),
        ("version_token_hash", "version_token_hash"),
    )
    changed: list[str] = []
    for label, key in dimensions:
        left = baseline[key]
        right = observed[key]
        if isinstance(left, datetime):
            left = _iso(left)
        if isinstance(right, datetime):
            right = _iso(right)
        if left != right:
            changed.append(label)
    return changed


def _validate_result(result: ExactItemMetadataResult) -> RemoteMetadataItemProjection | None:
    if not isinstance(result, ExactItemMetadataResult):
        raise ExternalDocumentSourceConflictError("Change-detection adapter returned an invalid result")
    if not result.found:
        if result.failure_code not in _ALLOWED_FAILURE_CODES:
            raise ExternalDocumentSourceConflictError("Change-detection adapter returned an unsupported failure code")
        if result.item is not None:
            raise ExternalDocumentSourceConflictError("Failed exact-item observation returned unexpected metadata")
        if result.failure_code == "not_found":
            return None
        raise ExternalDocumentSourceConflictError(f"Exact-item metadata observation failed ({result.failure_code})")
    if result.failure_code is not None or result.item is None:
        raise ExternalDocumentSourceConflictError("Successful exact-item observation returned incomplete facts")
    return _normalize_projection(result.item)


def _scope_hash(
    checkpoint: ExternalDocumentSourceSyncCheckpointExecution,
    *,
    observation_operation_kind: str,
    observation_adapter_kind: str,
    endpoint_policy_hash: str,
    request_key: str,
) -> str:
    if checkpoint.completion_hash is None:
        raise ExternalDocumentSourceConflictError("Phase O checkpoint completion hash is missing")
    return _canonical_hash(
        {
            "organization_id": str(checkpoint.organization_id),
            "profile_id": str(checkpoint.profile_id),
            "sync_checkpoint_execution_id": str(checkpoint.id),
            "checkpoint_state_hash": checkpoint.checkpoint_state_hash,
            "checkpoint_completion_hash": checkpoint.completion_hash,
            "observation_operation_kind": observation_operation_kind,
            "observation_adapter_kind": observation_adapter_kind,
            "endpoint_policy_hash": endpoint_policy_hash,
            "request_key": request_key,
        }
    )


def _request_hash(execution: ExternalDocumentSourceChangeDetectionExecution) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "sync_checkpoint_execution_id": str(execution.sync_checkpoint_execution_id),
            "baseline_projection_hash": execution.baseline_projection_hash,
            "requested_by_id": str(execution.requested_by_id),
            "request_reason": execution.request_reason,
            "requested_at": _iso(execution.requested_at),
            **_base_safety(False),
        }
    )


def _completion_hash(execution: ExternalDocumentSourceChangeDetectionExecution) -> str:
    if execution.completed_at is None or execution.result_status not in {"unchanged", "changed", "missing"}:
        raise ExternalDocumentSourceConflictError("Change-detection completion facts are incomplete")
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "request_hash": execution.request_hash,
            "result_status": execution.result_status,
            "observed_projection_hash": execution.observed_projection_hash,
            "observed_provider_item_id_hash": execution.observed_provider_item_id_hash,
            "observed_item_kind": execution.observed_item_kind,
            "observed_display_name_hash": execution.observed_display_name_hash,
            "observed_parent_item_id_hash": execution.observed_parent_item_id_hash,
            "observed_mime_type_class": execution.observed_mime_type_class,
            "observed_byte_size": execution.observed_byte_size,
            "observed_modified_at": _iso(execution.observed_modified_at),
            "observed_version_token_hash": execution.observed_version_token_hash,
            "changed_dimensions": execution.changed_dimensions,
            "completed_at": _iso(execution.completed_at),
            **_base_safety(True),
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceChangeDetectionReceipt) -> str:
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
            **_base_safety(receipt.event_type == "completed"),
        }
    )


def _receipts(db: Session, execution: ExternalDocumentSourceChangeDetectionExecution) -> list[ExternalDocumentSourceChangeDetectionReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceChangeDetectionReceipt)
            .where(
                ExternalDocumentSourceChangeDetectionReceipt.organization_id == execution.organization_id,
                ExternalDocumentSourceChangeDetectionReceipt.execution_id == execution.id,
            )
            .order_by(ExternalDocumentSourceChangeDetectionReceipt.sequence_number.asc())
        ).all()
    )


def _append_receipt(
    db: Session,
    *,
    execution: ExternalDocumentSourceChangeDetectionExecution,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    decision_hash: str,
) -> None:
    rows = _receipts(db, execution)
    receipt = ExternalDocumentSourceChangeDetectionReceipt(
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
        **_base_safety(event_type == "completed"),
    )
    receipt.receipt_hash = _receipt_hash(receipt)
    db.add(receipt)
    db.flush()


def _checkpoint(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    checkpoint_id: UUID,
    for_update: bool = False,
) -> ExternalDocumentSourceSyncCheckpointExecution:
    statement = select(ExternalDocumentSourceSyncCheckpointExecution).where(
        ExternalDocumentSourceSyncCheckpointExecution.id == checkpoint_id,
        ExternalDocumentSourceSyncCheckpointExecution.organization_id == organization_id,
        ExternalDocumentSourceSyncCheckpointExecution.profile_id == profile_id,
    )
    if for_update:
        statement = statement.with_for_update()
    row = db.scalar(statement)
    if row is None:
        raise ExternalDocumentSourceNotFoundError("Phase O synchronization checkpoint not found")
    _ensure_sync_checkpoint_integrity(db, row)
    return row


def _listing_and_item(
    db: Session,
    checkpoint: ExternalDocumentSourceSyncCheckpointExecution,
) -> tuple[ExternalDocumentSourceRemoteMetadataListingExecution, ExternalDocumentSourceRemoteMetadataListingItem]:
    listing = db.scalar(
        select(ExternalDocumentSourceRemoteMetadataListingExecution).where(
            ExternalDocumentSourceRemoteMetadataListingExecution.id == checkpoint.listing_execution_id,
            ExternalDocumentSourceRemoteMetadataListingExecution.organization_id == checkpoint.organization_id,
            ExternalDocumentSourceRemoteMetadataListingExecution.profile_id == checkpoint.profile_id,
        )
    )
    if listing is None:
        raise ExternalDocumentSourceConflictError("Phase L metadata listing lineage is missing")
    _ensure_remote_metadata_listing_integrity(db, listing)
    item = db.scalar(
        select(ExternalDocumentSourceRemoteMetadataListingItem).where(
            ExternalDocumentSourceRemoteMetadataListingItem.id == checkpoint.metadata_item_id,
            ExternalDocumentSourceRemoteMetadataListingItem.organization_id == checkpoint.organization_id,
            ExternalDocumentSourceRemoteMetadataListingItem.execution_id == listing.id,
        )
    )
    if item is None:
        raise ExternalDocumentSourceConflictError("Checkpointed Phase L metadata item is missing")
    if item.item_hash != checkpoint.metadata_item_hash:
        raise ExternalDocumentSourceConflictError("Checkpointed metadata-item lineage drifted")
    return listing, item


def _persisted_baseline_facts(execution: ExternalDocumentSourceChangeDetectionExecution) -> dict:
    return {
        "provider_item_id_hash": execution.baseline_provider_item_id_hash,
        "item_kind": execution.baseline_item_kind,
        "display_name_hash": execution.baseline_display_name_hash,
        "parent_item_id_hash": execution.baseline_parent_item_id_hash,
        "mime_type_class": execution.baseline_mime_type_class,
        "byte_size": execution.baseline_byte_size,
        "modified_at": execution.baseline_modified_at,
        "version_token_hash": execution.baseline_version_token_hash,
    }


def _persisted_observed_facts(execution: ExternalDocumentSourceChangeDetectionExecution) -> dict:
    return {
        "provider_item_id_hash": execution.observed_provider_item_id_hash,
        "item_kind": execution.observed_item_kind,
        "display_name_hash": execution.observed_display_name_hash,
        "parent_item_id_hash": execution.observed_parent_item_id_hash,
        "mime_type_class": execution.observed_mime_type_class,
        "byte_size": execution.observed_byte_size,
        "modified_at": execution.observed_modified_at,
        "version_token_hash": execution.observed_version_token_hash,
    }


def _ensure_integrity(db: Session, execution: ExternalDocumentSourceChangeDetectionExecution) -> None:
    checkpoint = _checkpoint(
        db,
        organization_id=execution.organization_id,
        profile_id=execution.profile_id,
        checkpoint_id=execution.sync_checkpoint_execution_id,
    )
    listing, item = _listing_and_item(db, checkpoint)
    baseline = _projection_facts(_baseline_projection(item))
    baseline_hash = _projection_hash(baseline)
    profile = _get_profile(db, organization_id=execution.organization_id, profile_id=execution.profile_id)
    _ensure_profile_integrity(db, profile)
    if profile.status != "active" or profile.profile_hash != checkpoint.profile_hash:
        raise ExternalDocumentSourceConflictError("Change-detection source profile is not active")
    policy = _policy(profile.provider_kind, profile.normalized_config, item.provider_item_id)
    expected_policy_hash = _endpoint_policy_hash(policy)

    if (
        execution.remote_content_staging_execution_id != checkpoint.remote_content_staging_execution_id
        or execution.listing_execution_id != checkpoint.listing_execution_id
        or execution.metadata_item_id != checkpoint.metadata_item_id
        or execution.provider_kind != checkpoint.provider_kind
        or execution.profile_hash != checkpoint.profile_hash
        or execution.checkpoint_state_hash != checkpoint.checkpoint_state_hash
        or execution.checkpoint_completion_hash != checkpoint.completion_hash
        or execution.baseline_metadata_item_hash != item.item_hash
        or execution.baseline_projection_hash != baseline_hash
        or execution.baseline_provider_item_id_hash != baseline["provider_item_id_hash"]
        or execution.baseline_item_kind != baseline["item_kind"]
        or execution.baseline_display_name_hash != baseline["display_name_hash"]
        or execution.baseline_parent_item_id_hash != baseline["parent_item_id_hash"]
        or execution.baseline_version_token_hash != baseline["version_token_hash"]
        or execution.baseline_byte_size != baseline["byte_size"]
        or execution.baseline_mime_type_class != baseline["mime_type_class"]
        or (_iso(execution.baseline_modified_at) != _iso(baseline["modified_at"]))
        or execution.observation_operation_kind != policy.observation_operation_kind
        or execution.endpoint_policy_hash != expected_policy_hash
    ):
        raise ExternalDocumentSourceConflictError("Change-detection baseline lineage drifted")

    adapter_kind = _normalize_identifier(execution.observation_adapter_kind, field="Change-detection adapter kind")
    expected_scope = _scope_hash(
        checkpoint,
        observation_operation_kind=policy.observation_operation_kind,
        observation_adapter_kind=adapter_kind,
        endpoint_policy_hash=expected_policy_hash,
        request_key=execution.request_key,
    )
    if execution.scope_hash != expected_scope or execution.request_hash != _request_hash(execution):
        raise ExternalDocumentSourceConflictError("Change-detection request integrity failed")

    if execution.status != "completed" or execution.result_status not in {"unchanged", "changed", "missing"}:
        raise ExternalDocumentSourceConflictError("Change-detection lifecycle is incomplete")
    if execution.completed_at is None or _aware(execution.completed_at) < _aware(execution.requested_at):
        raise ExternalDocumentSourceConflictError("Change-detection timestamps drifted")
    for field, expected in _base_safety(True).items():
        if bool(getattr(execution, field)) != expected:
            raise ExternalDocumentSourceConflictError("Change-detection safety boundary drifted")

    if execution.result_status == "missing":
        observed_fields = (
            execution.observed_projection_hash,
            execution.observed_provider_item_id_hash,
            execution.observed_item_kind,
            execution.observed_display_name_hash,
            execution.observed_parent_item_id_hash,
            execution.observed_version_token_hash,
            execution.observed_byte_size,
            execution.observed_modified_at,
            execution.observed_mime_type_class,
        )
        if any(value is not None for value in observed_fields) or execution.changed_dimensions != "missing":
            raise ExternalDocumentSourceConflictError("Missing-item observation facts drifted")
    else:
        observed = _persisted_observed_facts(execution)
        if (
            execution.observed_provider_item_id_hash is None
            or execution.observed_item_kind is None
            or execution.observed_display_name_hash is None
            or execution.observed_provider_item_id_hash != execution.baseline_provider_item_id_hash
        ):
            raise ExternalDocumentSourceConflictError("Observed exact-item identity drifted")
        expected_observed_hash = _projection_hash(observed)
        if execution.observed_projection_hash != expected_observed_hash:
            raise ExternalDocumentSourceConflictError("Observed metadata projection integrity failed")
        expected_dimensions = _changed_dimensions(_persisted_baseline_facts(execution), observed)
        expected_result = "unchanged" if not expected_dimensions else "changed"
        expected_dimension_text = ",".join(expected_dimensions)
        if execution.result_status != expected_result or execution.changed_dimensions != expected_dimension_text:
            raise ExternalDocumentSourceConflictError("Change-detection comparison facts drifted")

    if execution.completion_hash != _completion_hash(execution):
        raise ExternalDocumentSourceConflictError("Change-detection completion integrity failed")

    rows = _receipts(db, execution)
    if len(rows) != 2 or [row.event_type for row in rows] != ["requested", "completed"]:
        raise ExternalDocumentSourceConflictError("Change-detection receipt lifecycle is incomplete")
    expected_rows = (
        (1, "requested", execution.requested_at, execution.request_hash, False),
        (2, "completed", execution.completed_at, execution.completion_hash, True),
    )
    prior: str | None = None
    for receipt, facts in zip(rows, expected_rows, strict=True):
        sequence, status_after, occurred_at, decision_hash, completed = facts
        if (
            receipt.sequence_number != sequence
            or receipt.event_type != status_after
            or receipt.status_after != status_after
            or receipt.actor_id != execution.requested_by_id
            or _aware(receipt.occurred_at) != _aware(occurred_at)
            or receipt.reason != execution.request_reason
            or receipt.scope_hash != execution.scope_hash
            or receipt.decision_hash != decision_hash
            or receipt.prior_receipt_hash != prior
        ):
            raise ExternalDocumentSourceConflictError("Change-detection receipt facts drifted")
        for field, expected in _base_safety(completed).items():
            if bool(getattr(receipt, field)) != expected:
                raise ExternalDocumentSourceConflictError("Change-detection receipt safety boundary drifted")
        if receipt.receipt_hash != _receipt_hash(receipt):
            raise ExternalDocumentSourceConflictError("Change-detection receipt integrity failed")
        prior = receipt.receipt_hash


def execute_external_document_source_change_detection(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    sync_checkpoint_execution_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)

    existing = db.scalar(
        select(ExternalDocumentSourceChangeDetectionExecution).where(
            ExternalDocumentSourceChangeDetectionExecution.organization_id == organization_id,
            ExternalDocumentSourceChangeDetectionExecution.profile_id == profile_id,
            ExternalDocumentSourceChangeDetectionExecution.request_key == normalized_key,
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if (
            existing.sync_checkpoint_execution_id != sync_checkpoint_execution_id
            or existing.request_reason != normalized_reason
            or existing.requested_by_id != requested_by_id
        ):
            raise ExternalDocumentSourceConflictError("Conflicting replay for change-detection request_key")
        return existing, "unchanged"

    checkpoint = _checkpoint(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        checkpoint_id=sync_checkpoint_execution_id,
        for_update=True,
    )
    listing, item = _listing_and_item(db, checkpoint)
    baseline = _projection_facts(_baseline_projection(item))
    baseline_hash = _projection_hash(baseline)

    profile = _get_profile(db, organization_id=organization_id, profile_id=profile_id)
    _ensure_profile_integrity(db, profile)
    if profile.status != "active" or profile.profile_hash != checkpoint.profile_hash:
        raise ExternalDocumentSourceConflictError("External document source profile is not active")
    policy = _policy(profile.provider_kind, profile.normalized_config, item.provider_item_id)

    health_execution = _health_execution(db, listing)
    binding = _active_binding(db, health_execution)
    adapter = _OBSERVATION_ADAPTERS.get((profile.provider_kind, policy.observation_operation_kind))
    if adapter is None:
        raise ExternalDocumentSourceConflictError("Exact-item change-detection adapter is unavailable")
    adapter_kind = _normalize_identifier(adapter.adapter_kind, field="Change-detection adapter kind")
    if (
        adapter.provider_kind != profile.provider_kind
        or adapter.client_kind != policy.client_kind
        or adapter.observation_operation_kind != policy.observation_operation_kind
        or adapter.provider_origin != policy.provider_origin
    ):
        raise ExternalDocumentSourceConflictError("Change-detection adapter policy drifted")

    current = _aware(now or _utc_now())
    endpoint_policy_hash = _endpoint_policy_hash(policy)
    scope_hash = _scope_hash(
        checkpoint,
        observation_operation_kind=policy.observation_operation_kind,
        observation_adapter_kind=adapter_kind,
        endpoint_policy_hash=endpoint_policy_hash,
        request_key=normalized_key,
    )
    execution = ExternalDocumentSourceChangeDetectionExecution(
        organization_id=organization_id,
        profile_id=profile_id,
        sync_checkpoint_execution_id=checkpoint.id,
        remote_content_staging_execution_id=checkpoint.remote_content_staging_execution_id,
        listing_execution_id=checkpoint.listing_execution_id,
        metadata_item_id=checkpoint.metadata_item_id,
        provider_kind=checkpoint.provider_kind,
        profile_hash=checkpoint.profile_hash,
        checkpoint_state_hash=checkpoint.checkpoint_state_hash,
        checkpoint_completion_hash=checkpoint.completion_hash,
        baseline_metadata_item_hash=item.item_hash,
        baseline_projection_hash=baseline_hash,
        baseline_provider_item_id_hash=baseline["provider_item_id_hash"],
        baseline_item_kind=baseline["item_kind"],
        baseline_display_name_hash=baseline["display_name_hash"],
        baseline_parent_item_id_hash=baseline["parent_item_id_hash"],
        baseline_version_token_hash=baseline["version_token_hash"],
        baseline_byte_size=baseline["byte_size"],
        baseline_modified_at=baseline["modified_at"],
        baseline_mime_type_class=baseline["mime_type_class"],
        observation_operation_kind=policy.observation_operation_kind,
        observation_adapter_kind=adapter_kind,
        endpoint_policy_hash=endpoint_policy_hash,
        request_key=normalized_key,
        scope_hash=scope_hash,
        request_hash="0" * 64,
        status="requested",
        requested_by_id=requested_by_id,
        request_reason=normalized_reason,
        requested_at=current,
        **_base_safety(False),
    )
    db.add(execution)
    db.flush()
    execution.request_hash = _request_hash(execution)
    _append_receipt(
        db,
        execution=execution,
        event_type="requested",
        actor_id=requested_by_id,
        occurred_at=current,
        decision_hash=execution.request_hash,
    )

    locator = CredentialReferenceLocator(
        backend=binding.reference_backend,
        namespace=binding.reference_namespace,
        name=binding.reference_name,
        version=binding.reference_version,
    )
    try:
        result = adapter.read_item_metadata(locator, policy)
    except Exception:
        raise ExternalDocumentSourceConflictError("Exact-item metadata observation failed") from None
    observed_projection = _validate_result(result)

    if observed_projection is None:
        execution.result_status = "missing"
        execution.changed_dimensions = "missing"
    else:
        observed = _projection_facts(observed_projection)
        if observed["provider_item_id_hash"] != baseline["provider_item_id_hash"]:
            raise ExternalDocumentSourceConflictError("Exact-item endpoint returned an unexpected provider item identity")
        changed = _changed_dimensions(baseline, observed)
        execution.result_status = "unchanged" if not changed else "changed"
        execution.observed_projection_hash = _projection_hash(observed)
        execution.observed_provider_item_id_hash = observed["provider_item_id_hash"]
        execution.observed_item_kind = observed["item_kind"]
        execution.observed_display_name_hash = observed["display_name_hash"]
        execution.observed_parent_item_id_hash = observed["parent_item_id_hash"]
        execution.observed_version_token_hash = observed["version_token_hash"]
        execution.observed_byte_size = observed["byte_size"]
        execution.observed_modified_at = observed["modified_at"]
        execution.observed_mime_type_class = observed["mime_type_class"]
        execution.changed_dimensions = ",".join(changed)

    completed_at = max(current, _utc_now())
    execution.status = "completed"
    execution.completed_at = completed_at
    execution.provider_client_constructed = True
    execution.exact_item_metadata_read_performed = True
    execution.change_detection_completed = True
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
    _ensure_integrity(db, execution)
    return execution, "completed"


def get_external_document_source_change_detection(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = db.scalar(
        select(ExternalDocumentSourceChangeDetectionExecution).where(
            ExternalDocumentSourceChangeDetectionExecution.id == execution_id,
            ExternalDocumentSourceChangeDetectionExecution.organization_id == organization_id,
            ExternalDocumentSourceChangeDetectionExecution.profile_id == profile_id,
        )
    )
    if execution is None:
        raise ExternalDocumentSourceNotFoundError("Change-detection execution not found")
    _ensure_integrity(db, execution)
    return execution


def list_external_document_source_change_detection_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = get_external_document_source_change_detection(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _receipts(db, execution)
