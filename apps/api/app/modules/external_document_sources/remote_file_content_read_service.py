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

from app.modules.external_document_sources.credential_reference_health_service import CredentialReferenceLocator
from app.modules.external_document_sources.credential_reference_service import get_external_document_source_credential_reference
from app.modules.external_document_sources.remote_file_content_read_models import (
    MAX_REMOTE_CONTENT_BYTES,
    ExternalDocumentSourceRemoteFileContentReadExecution,
    ExternalDocumentSourceRemoteFileContentReadReceipt,
)
from app.modules.external_document_sources.remote_metadata_listing_models import (
    ExternalDocumentSourceRemoteMetadataListingExecution,
    ExternalDocumentSourceRemoteMetadataListingItem,
)
from app.modules.external_document_sources.remote_metadata_listing_service import (
    _ensure_integrity as _ensure_remote_metadata_listing_integrity,
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
_ALLOWED_LATENCY_CLASSES = {"fast", "normal", "slow", "unknown"}
_ALLOWED_FAILURE_CODES = {
    "unauthorized",
    "permission_denied",
    "not_found",
    "endpoint_unavailable",
    "timeout",
    "malformed_response",
    "oversized_response",
    "version_mismatch",
    "provider_rejected",
}
_FALSE_SAFETY_FIELDS = (
    "credential_stored",
    "oauth_authorization_code_stored",
    "access_token_stored",
    "refresh_token_stored",
    "id_token_stored",
    "client_secret_stored",
    "private_key_stored",
    "provider_client_stored",
    "provider_response_body_stored",
    "remote_content_stored",
    "remote_content_returned",
    "remote_content_logged",
    "content_parsed",
    "content_extracted",
    "remote_list_performed",
    "remote_write_performed",
    "remote_delete_performed",
    "subscription_created",
    "checkpoint_created",
    "sync_executed",
    "evidence_admitted",
    "document_created",
    "claim_mutated",
)
_PROVIDER_READ_POLICIES = {
    "sharepoint": {
        "client_kind": "microsoft_graph_transient_v1",
        "read_operation_kind": "graph_drive_item_content_read_v1",
        "provider_origin": "https://graph.microsoft.com",
        "redirect_policy_kind": "provider_internal_https_one_hop_v1",
        "max_redirects": 1,
    },
    "google_drive": {
        "client_kind": "google_drive_transient_v3",
        "read_operation_kind": "drive_file_media_read_v1",
        "provider_origin": "https://www.googleapis.com",
        "redirect_policy_kind": "no_redirects_v1",
        "max_redirects": 0,
    },
}


@dataclass(frozen=True)
class RemoteFileContentReadPolicy:
    provider_kind: str
    client_kind: str
    read_operation_kind: str
    provider_origin: str
    content_endpoint_url: str
    redirect_policy_kind: str
    max_redirects: int
    max_content_bytes: int = MAX_REMOTE_CONTENT_BYTES
    max_chunk_bytes: int = 65536
    connect_timeout_seconds: float = 3.0
    read_timeout_seconds: float = 12.0
    total_timeout_seconds: float = 15.0


@dataclass(frozen=True)
class RemoteFileContentReadResult:
    """Transient adapter result. `content` must never be persisted, returned by the API, logged or cached."""

    read: bool
    content: bytes | None = None
    media_type_class: str | None = None
    observed_version_token_hash: str | None = None
    latency_class: str | None = None
    failure_code: str | None = None


@dataclass(frozen=True)
class _RemoteContentProof:
    content_sha256: str
    content_byte_count: int
    media_type_class: str | None
    observed_version_token_hash: str | None
    latency_class: str


class ExternalDocumentSourceRemoteFileContentReadAdapter(Protocol):
    adapter_kind: str
    provider_kind: str
    client_kind: str
    read_operation_kind: str
    provider_origin: str
    redirect_policy_kind: str

    def read_content(
        self,
        locator: CredentialReferenceLocator,
        policy: RemoteFileContentReadPolicy,
    ) -> RemoteFileContentReadResult: ...


_READ_ADAPTERS: dict[tuple[str, str], ExternalDocumentSourceRemoteFileContentReadAdapter] = {}


def register_external_document_source_remote_file_content_read_adapter(
    provider_kind: str,
    read_operation_kind: str,
    adapter: ExternalDocumentSourceRemoteFileContentReadAdapter,
) -> None:
    provider = provider_kind.strip().lower()
    operation = read_operation_kind.strip().lower()
    expected = _PROVIDER_READ_POLICIES.get(provider)
    if expected is None or operation != expected["read_operation_kind"]:
        raise ValueError("Unsupported provider/content-read-operation combination")
    adapter_kind = getattr(adapter, "adapter_kind", None)
    if not isinstance(adapter_kind, str) or not _SAFE_IDENTIFIER.fullmatch(adapter_kind):
        raise ValueError("Remote file content read adapter kind is invalid")
    if getattr(adapter, "provider_kind", None) != provider:
        raise ValueError("Remote file content read adapter provider kind does not match the governed provider")
    if getattr(adapter, "client_kind", None) != expected["client_kind"]:
        raise ValueError("Remote file content read adapter client kind is not approved")
    if getattr(adapter, "read_operation_kind", None) != operation:
        raise ValueError("Remote file content read adapter operation does not match the governed operation")
    origin = getattr(adapter, "provider_origin", None)
    if origin != expected["provider_origin"]:
        raise ValueError("Remote file content read adapter origin is not approved")
    if getattr(adapter, "redirect_policy_kind", None) != expected["redirect_policy_kind"]:
        raise ValueError("Remote file content read adapter redirect policy is not approved")
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
        raise ValueError("Remote file content read adapter origin is invalid")
    _READ_ADAPTERS[(provider, operation)] = adapter


def clear_external_document_source_remote_file_content_read_adapters() -> None:
    _READ_ADAPTERS.clear()


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


def _normalize_identifier(value: str, *, field: str) -> str:
    normalized = value.strip()
    if not _SAFE_IDENTIFIER.fullmatch(normalized):
        raise ExternalDocumentSourceConflictError(f"{field} is invalid")
    return normalized


def _normalize_media_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized or len(normalized) > 128 or "\x00" in normalized:
        raise ExternalDocumentSourceConflictError("Remote file content read returned an invalid media type class")
    return normalized


def _normalize_hash(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not _HEX_64.fullmatch(normalized):
        raise ExternalDocumentSourceConflictError(f"{field} is invalid")
    return normalized


def _read_policy(
    provider_kind: str,
    normalized_config: dict,
    item: ExternalDocumentSourceRemoteMetadataListingItem,
) -> RemoteFileContentReadPolicy:
    provider = provider_kind.strip().lower()
    base = _PROVIDER_READ_POLICIES.get(provider)
    if base is None:
        raise ExternalDocumentSourceConflictError("Unsupported external document source provider for remote file content read")
    if item.item_kind != "file":
        raise ExternalDocumentSourceConflictError("Only Phase L file metadata items are eligible for remote content read")
    provider_item_id = item.provider_item_id.strip()
    if not provider_item_id:
        raise ExternalDocumentSourceConflictError("Phase L metadata item provider identifier is missing")
    if not isinstance(normalized_config, dict):
        raise ExternalDocumentSourceConflictError("Governed provider configuration is invalid")

    if provider == "sharepoint":
        if set(normalized_config) != {"tenant_domain", "site_id", "library_id"}:
            raise ExternalDocumentSourceConflictError("Governed SharePoint profile configuration drifted")
        site_id = normalized_config.get("site_id")
        library_id = normalized_config.get("library_id")
        if not isinstance(site_id, str) or not site_id.strip() or not isinstance(library_id, str) or not library_id.strip():
            raise ExternalDocumentSourceConflictError("Governed SharePoint source boundary is incomplete")
        endpoint = (
            f"{base['provider_origin']}/v1.0/sites/{quote(site_id.strip(), safe='')}"
            f"/drives/{quote(library_id.strip(), safe='')}/items/{quote(provider_item_id, safe='')}/content"
        )
    else:
        if not set(normalized_config).issubset({"shared_drive_id", "folder_id"}) or "shared_drive_id" not in normalized_config:
            raise ExternalDocumentSourceConflictError("Governed Google Drive profile configuration drifted")
        shared_drive_id = normalized_config.get("shared_drive_id")
        if not isinstance(shared_drive_id, str) or not shared_drive_id.strip():
            raise ExternalDocumentSourceConflictError("Governed Google Drive source boundary is incomplete")
        if item.mime_type_class and item.mime_type_class.strip().lower().startswith("application/vnd.google-apps."):
            raise ExternalDocumentSourceConflictError("Google-native file export is not authorized in Phase 17.5-M")
        query = urlencode({"alt": "media", "supportsAllDrives": "true"})
        endpoint = f"{base['provider_origin']}/drive/v3/files/{quote(provider_item_id, safe='')}?{query}"

    parsed_endpoint = urlparse(endpoint)
    parsed_origin = urlparse(base["provider_origin"])
    if (
        parsed_endpoint.scheme != "https"
        or parsed_endpoint.netloc != parsed_origin.netloc
        or parsed_endpoint.username is not None
        or parsed_endpoint.password is not None
        or parsed_endpoint.fragment
    ):
        raise ExternalDocumentSourceConflictError("Derived remote file content endpoint is not approved")
    return RemoteFileContentReadPolicy(
        provider_kind=provider,
        client_kind=base["client_kind"],
        read_operation_kind=base["read_operation_kind"],
        provider_origin=base["provider_origin"],
        content_endpoint_url=endpoint,
        redirect_policy_kind=base["redirect_policy_kind"],
        max_redirects=base["max_redirects"],
    )


def _endpoint_policy_hash(policy: RemoteFileContentReadPolicy) -> str:
    return _canonical_hash(
        {
            "provider_kind": policy.provider_kind,
            "client_kind": policy.client_kind,
            "read_operation_kind": policy.read_operation_kind,
            "provider_origin": policy.provider_origin,
            "content_endpoint_url": policy.content_endpoint_url,
            "redirect_policy_kind": policy.redirect_policy_kind,
            "max_redirects": policy.max_redirects,
            "max_content_bytes": policy.max_content_bytes,
            "max_chunk_bytes": policy.max_chunk_bytes,
            "connect_timeout_seconds": policy.connect_timeout_seconds,
            "read_timeout_seconds": policy.read_timeout_seconds,
            "total_timeout_seconds": policy.total_timeout_seconds,
        }
    )


def _consume_result(
    result: RemoteFileContentReadResult,
    policy: RemoteFileContentReadPolicy,
    item: ExternalDocumentSourceRemoteMetadataListingItem,
) -> _RemoteContentProof:
    if not isinstance(result, RemoteFileContentReadResult):
        raise ExternalDocumentSourceConflictError("Remote file content read adapter returned an invalid result")
    if not result.read:
        if result.failure_code not in _ALLOWED_FAILURE_CODES:
            raise ExternalDocumentSourceConflictError("Remote file content read adapter returned an unsupported failure code")
        if (
            result.content is not None
            or result.media_type_class is not None
            or result.observed_version_token_hash is not None
            or result.latency_class is not None
        ):
            raise ExternalDocumentSourceConflictError("Failed remote file content read returned unexpected result data")
        raise ExternalDocumentSourceConflictError(f"Remote file content read failed ({result.failure_code})")
    if result.failure_code is not None:
        raise ExternalDocumentSourceConflictError("Successful remote file content read cannot include a failure code")
    if type(result.content) is not bytes:
        raise ExternalDocumentSourceConflictError("Remote file content read adapter returned an invalid content body")
    content = result.content
    byte_count = len(content)
    if byte_count > policy.max_content_bytes:
        raise ExternalDocumentSourceConflictError("Remote file content exceeded the Phase M byte bound")
    if item.byte_size is not None and byte_count != item.byte_size:
        raise ExternalDocumentSourceConflictError("Remote file content size no longer matches Phase L metadata")
    if result.latency_class not in _ALLOWED_LATENCY_CLASSES:
        raise ExternalDocumentSourceConflictError("Remote file content read adapter returned an invalid latency class")

    media_type = _normalize_media_type(result.media_type_class)
    expected_media_type = _normalize_media_type(item.mime_type_class)
    if media_type is not None and expected_media_type is not None and media_type != expected_media_type:
        raise ExternalDocumentSourceConflictError("Remote file content media type no longer matches Phase L metadata")
    media_type = media_type or expected_media_type

    observed_version = _normalize_hash(result.observed_version_token_hash, field="Observed version-token hash")
    expected_version = _normalize_hash(item.version_token_hash, field="Phase L version-token hash")
    if expected_version is not None and observed_version != expected_version:
        raise ExternalDocumentSourceConflictError("Remote file content version no longer matches Phase L metadata")

    digest = hashlib.sha256(content).hexdigest()
    del content
    return _RemoteContentProof(
        content_sha256=digest,
        content_byte_count=byte_count,
        media_type_class=media_type,
        observed_version_token_hash=observed_version,
        latency_class=result.latency_class,
    )


def _base_safety(executed: bool) -> dict[str, bool]:
    return {
        "credential_reference_stored": True,
        "credential_reference_resolution_performed": True,
        "activation_authorization_consumed": True,
        "upstream_token_acquisition_completed": True,
        "upstream_provider_client_health_completed": True,
        "upstream_remote_metadata_listing_completed": True,
        "provider_client_constructed": executed,
        "remote_content_transiently_observed": executed,
        "remote_read_performed": executed,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    }


def _scope_hash(
    *,
    listing: ExternalDocumentSourceRemoteMetadataListingExecution,
    item: ExternalDocumentSourceRemoteMetadataListingItem,
    read_operation_kind: str,
    read_adapter_kind: str,
    endpoint_policy_hash: str,
    request_key: str,
) -> str:
    if listing.completion_hash is None or listing.items_hash is None:
        raise ExternalDocumentSourceConflictError("Phase L remote metadata listing completion facts are incomplete")
    return _canonical_hash(
        {
            "organization_id": str(listing.organization_id),
            "profile_id": str(listing.profile_id),
            "listing_execution_id": str(listing.id),
            "metadata_item_id": str(item.id),
            "provider_client_health_execution_id": str(listing.provider_client_health_execution_id),
            "token_acquisition_execution_id": str(listing.token_acquisition_execution_id),
            "credential_resolution_execution_id": str(listing.credential_resolution_execution_id),
            "credential_reference_binding_id": str(listing.credential_reference_binding_id),
            "provider_kind": listing.provider_kind,
            "profile_hash": listing.profile_hash,
            "locator_hash": listing.locator_hash,
            "reference_backend": listing.reference_backend,
            "client_kind": listing.client_kind,
            "listing_operation_kind": listing.listing_operation_kind,
            "list_adapter_kind": listing.list_adapter_kind,
            "listing_scope_hash": listing.scope_hash,
            "listing_request_hash": listing.request_hash,
            "listing_completion_hash": listing.completion_hash,
            "listing_items_hash": listing.items_hash,
            "metadata_item_hash": item.item_hash,
            "metadata_item_version_token_hash": item.version_token_hash,
            "declared_byte_size": item.byte_size,
            "metadata_mime_type_class": item.mime_type_class,
            "read_operation_kind": read_operation_kind,
            "read_adapter_kind": read_adapter_kind,
            "endpoint_policy_hash": endpoint_policy_hash,
            "request_key": request_key,
        }
    )


def _request_hash(execution: ExternalDocumentSourceRemoteFileContentReadExecution) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "requested_by_id": str(execution.requested_by_id),
            "request_reason": execution.request_reason,
            "requested_at": _iso(execution.requested_at),
            **_base_safety(False),
        }
    )


def _completion_hash(execution: ExternalDocumentSourceRemoteFileContentReadExecution) -> str:
    if (
        execution.completed_at is None
        or execution.result_status != "read_verified"
        or execution.content_sha256 is None
        or execution.content_byte_count is None
        or execution.latency_class not in _ALLOWED_LATENCY_CLASSES
    ):
        raise ExternalDocumentSourceConflictError("Remote file content read completion facts are incomplete")
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "request_hash": execution.request_hash,
            "result_status": execution.result_status,
            "content_sha256": execution.content_sha256,
            "content_byte_count": execution.content_byte_count,
            "media_type_class": execution.media_type_class,
            "latency_class": execution.latency_class,
            "observed_version_token_hash": execution.observed_version_token_hash,
            "completed_at": _iso(execution.completed_at),
            **_base_safety(True),
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceRemoteFileContentReadReceipt) -> str:
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


def _receipts(
    db: Session,
    execution: ExternalDocumentSourceRemoteFileContentReadExecution,
) -> list[ExternalDocumentSourceRemoteFileContentReadReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceRemoteFileContentReadReceipt)
            .where(
                ExternalDocumentSourceRemoteFileContentReadReceipt.organization_id == execution.organization_id,
                ExternalDocumentSourceRemoteFileContentReadReceipt.execution_id == execution.id,
            )
            .order_by(ExternalDocumentSourceRemoteFileContentReadReceipt.sequence_number.asc())
        ).all()
    )


def _append_receipt(
    db: Session,
    *,
    execution: ExternalDocumentSourceRemoteFileContentReadExecution,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    decision_hash: str,
) -> None:
    rows = _receipts(db, execution)
    receipt = ExternalDocumentSourceRemoteFileContentReadReceipt(
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


def _get_execution(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
) -> ExternalDocumentSourceRemoteFileContentReadExecution:
    row = db.scalar(
        select(ExternalDocumentSourceRemoteFileContentReadExecution).where(
            ExternalDocumentSourceRemoteFileContentReadExecution.id == execution_id,
            ExternalDocumentSourceRemoteFileContentReadExecution.organization_id == organization_id,
            ExternalDocumentSourceRemoteFileContentReadExecution.profile_id == profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceNotFoundError("Remote file content read execution not found")
    return row


def _listing_execution(
    db: Session,
    execution: ExternalDocumentSourceRemoteFileContentReadExecution,
) -> ExternalDocumentSourceRemoteMetadataListingExecution:
    row = db.scalar(
        select(ExternalDocumentSourceRemoteMetadataListingExecution).where(
            ExternalDocumentSourceRemoteMetadataListingExecution.id == execution.listing_execution_id,
            ExternalDocumentSourceRemoteMetadataListingExecution.organization_id == execution.organization_id,
            ExternalDocumentSourceRemoteMetadataListingExecution.profile_id == execution.profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceConflictError("Phase L remote metadata listing lineage is missing")
    return row


def _metadata_item(
    db: Session,
    execution: ExternalDocumentSourceRemoteFileContentReadExecution,
) -> ExternalDocumentSourceRemoteMetadataListingItem:
    row = db.scalar(
        select(ExternalDocumentSourceRemoteMetadataListingItem).where(
            ExternalDocumentSourceRemoteMetadataListingItem.id == execution.metadata_item_id,
            ExternalDocumentSourceRemoteMetadataListingItem.organization_id == execution.organization_id,
            ExternalDocumentSourceRemoteMetadataListingItem.execution_id == execution.listing_execution_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceConflictError("Phase L metadata-item lineage is missing")
    return row


def _active_binding(db: Session, listing: ExternalDocumentSourceRemoteMetadataListingExecution):
    binding = get_external_document_source_credential_reference(
        db,
        organization_id=listing.organization_id,
        profile_id=listing.profile_id,
        binding_id=listing.credential_reference_binding_id,
    )
    if binding.status != "active" or binding.approval_hash is None:
        raise ExternalDocumentSourceConflictError("Bound credential reference is not active")
    if (
        binding.provider_kind != listing.provider_kind
        or binding.profile_hash != listing.profile_hash
        or binding.locator_hash != listing.locator_hash
        or binding.reference_backend != listing.reference_backend
    ):
        raise ExternalDocumentSourceConflictError("Remote file content read credential-reference lineage drifted")
    return binding


def _ensure_integrity(db: Session, execution: ExternalDocumentSourceRemoteFileContentReadExecution) -> None:
    if (
        execution.status != "completed"
        or execution.result_status != "read_verified"
        or execution.content_sha256 is None
        or not _HEX_64.fullmatch(execution.content_sha256)
        or execution.content_byte_count is None
        or execution.content_byte_count < 0
        or execution.content_byte_count > MAX_REMOTE_CONTENT_BYTES
        or execution.latency_class not in _ALLOWED_LATENCY_CLASSES
    ):
        raise ExternalDocumentSourceConflictError("Remote file content read execution lifecycle is incomplete")
    for field, expected in _base_safety(True).items():
        if bool(getattr(execution, field)) != expected:
            raise ExternalDocumentSourceConflictError("Remote file content read execution safety boundary drifted")

    listing = _listing_execution(db, execution)
    _ensure_remote_metadata_listing_integrity(db, listing)
    if listing.status != "completed" or listing.completion_hash is None or listing.items_hash is None:
        raise ExternalDocumentSourceConflictError("Phase L remote metadata listing is not complete")
    item = _metadata_item(db, execution)
    if item.item_kind != "file":
        raise ExternalDocumentSourceConflictError("Phase M metadata item is no longer a file")
    if (
        execution.provider_client_health_execution_id != listing.provider_client_health_execution_id
        or execution.token_acquisition_execution_id != listing.token_acquisition_execution_id
        or execution.credential_resolution_execution_id != listing.credential_resolution_execution_id
        or execution.credential_reference_binding_id != listing.credential_reference_binding_id
        or execution.provider_kind != listing.provider_kind
        or execution.profile_hash != listing.profile_hash
        or execution.locator_hash != listing.locator_hash
        or execution.reference_backend != listing.reference_backend
        or execution.client_kind != listing.client_kind
        or execution.listing_operation_kind != listing.listing_operation_kind
        or execution.list_adapter_kind != listing.list_adapter_kind
        or execution.listing_scope_hash != listing.scope_hash
        or execution.listing_request_hash != listing.request_hash
        or execution.listing_completion_hash != listing.completion_hash
        or execution.listing_items_hash != listing.items_hash
        or execution.metadata_item_hash != item.item_hash
        or execution.metadata_item_version_token_hash != item.version_token_hash
        or execution.declared_byte_size != item.byte_size
        or execution.metadata_mime_type_class != item.mime_type_class
    ):
        raise ExternalDocumentSourceConflictError("Remote file content read upstream lineage drifted")
    if execution.declared_byte_size is not None and execution.content_byte_count != execution.declared_byte_size:
        raise ExternalDocumentSourceConflictError("Remote file content read byte-count proof drifted")
    expected_media = _normalize_media_type(execution.metadata_mime_type_class)
    observed_media = _normalize_media_type(execution.media_type_class)
    if expected_media is not None and observed_media != expected_media:
        raise ExternalDocumentSourceConflictError("Remote file content read media-type proof drifted")
    expected_version = _normalize_hash(execution.metadata_item_version_token_hash, field="Phase L version-token hash")
    observed_version = _normalize_hash(execution.observed_version_token_hash, field="Observed version-token hash")
    if expected_version is not None and observed_version != expected_version:
        raise ExternalDocumentSourceConflictError("Remote file content read version proof drifted")

    _active_binding(db, listing)
    profile = _get_profile(db, organization_id=execution.organization_id, profile_id=execution.profile_id)
    _ensure_profile_integrity(db, profile)
    if profile.status != "active" or profile.profile_hash != execution.profile_hash:
        raise ExternalDocumentSourceConflictError("Remote file content read source profile is not active")
    policy = _read_policy(profile.provider_kind, profile.normalized_config, item)
    expected_policy_hash = _endpoint_policy_hash(policy)
    if (
        execution.client_kind != policy.client_kind
        or execution.read_operation_kind != policy.read_operation_kind
        or execution.endpoint_policy_hash != expected_policy_hash
    ):
        raise ExternalDocumentSourceConflictError("Remote file content read policy lineage drifted")
    adapter_kind = _normalize_identifier(execution.read_adapter_kind, field="Remote file content read adapter kind")
    expected_scope = _scope_hash(
        listing=listing,
        item=item,
        read_operation_kind=policy.read_operation_kind,
        read_adapter_kind=adapter_kind,
        endpoint_policy_hash=expected_policy_hash,
        request_key=execution.request_key,
    )
    if execution.scope_hash != expected_scope or execution.request_hash != _request_hash(execution):
        raise ExternalDocumentSourceConflictError("Remote file content read request integrity failed")
    if execution.completion_hash != _completion_hash(execution):
        raise ExternalDocumentSourceConflictError("Remote file content read completion integrity failed")
    if execution.completed_at is None or _aware(execution.completed_at) < _aware(execution.requested_at):
        raise ExternalDocumentSourceConflictError("Remote file content read timestamps drifted")

    rows = _receipts(db, execution)
    if len(rows) != 2 or [row.event_type for row in rows] != ["requested", "completed"]:
        raise ExternalDocumentSourceConflictError("Remote file content read receipt lifecycle is incomplete")
    expected_rows = (
        (1, "requested", execution.requested_at, execution.request_hash, False),
        (2, "completed", execution.completed_at, execution.completion_hash, True),
    )
    prior: str | None = None
    for receipt, facts in zip(rows, expected_rows, strict=True):
        sequence, status_after, occurred_at, decision_hash, performed = facts
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
            raise ExternalDocumentSourceConflictError("Remote file content read receipt facts drifted")
        for field, expected in _base_safety(performed).items():
            if bool(getattr(receipt, field)) != expected:
                raise ExternalDocumentSourceConflictError("Remote file content read receipt safety boundary drifted")
        if receipt.receipt_hash != _receipt_hash(receipt):
            raise ExternalDocumentSourceConflictError("Remote file content read receipt integrity failed")
        prior = receipt.receipt_hash


def execute_external_document_source_remote_file_content_read(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    listing_execution_id: UUID,
    metadata_item_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)
    existing = db.scalar(
        select(ExternalDocumentSourceRemoteFileContentReadExecution).where(
            ExternalDocumentSourceRemoteFileContentReadExecution.organization_id == organization_id,
            ExternalDocumentSourceRemoteFileContentReadExecution.profile_id == profile_id,
            ExternalDocumentSourceRemoteFileContentReadExecution.listing_execution_id == listing_execution_id,
            ExternalDocumentSourceRemoteFileContentReadExecution.metadata_item_id == metadata_item_id,
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if existing.request_key != normalized_key or existing.request_reason != normalized_reason or existing.requested_by_id != requested_by_id:
            raise ExternalDocumentSourceConflictError("Conflicting replay for remote file content read execution")
        return existing, "unchanged"

    key_collision = db.scalar(
        select(ExternalDocumentSourceRemoteFileContentReadExecution).where(
            ExternalDocumentSourceRemoteFileContentReadExecution.organization_id == organization_id,
            ExternalDocumentSourceRemoteFileContentReadExecution.profile_id == profile_id,
            ExternalDocumentSourceRemoteFileContentReadExecution.request_key == normalized_key,
        )
    )
    if key_collision is not None:
        raise ExternalDocumentSourceConflictError("Conflicting replay for remote file content read request_key")

    listing = db.scalar(
        select(ExternalDocumentSourceRemoteMetadataListingExecution)
        .where(
            ExternalDocumentSourceRemoteMetadataListingExecution.id == listing_execution_id,
            ExternalDocumentSourceRemoteMetadataListingExecution.organization_id == organization_id,
            ExternalDocumentSourceRemoteMetadataListingExecution.profile_id == profile_id,
        )
        .with_for_update()
    )
    if listing is None:
        raise ExternalDocumentSourceNotFoundError("Phase L remote metadata listing execution not found")
    _ensure_remote_metadata_listing_integrity(db, listing)
    if listing.status != "completed" or listing.completion_hash is None or listing.items_hash is None:
        raise ExternalDocumentSourceConflictError("Phase L remote metadata listing is not eligible for remote content read")

    item = db.scalar(
        select(ExternalDocumentSourceRemoteMetadataListingItem)
        .where(
            ExternalDocumentSourceRemoteMetadataListingItem.id == metadata_item_id,
            ExternalDocumentSourceRemoteMetadataListingItem.organization_id == organization_id,
            ExternalDocumentSourceRemoteMetadataListingItem.execution_id == listing_execution_id,
        )
        .with_for_update()
    )
    if item is None:
        raise ExternalDocumentSourceNotFoundError("Phase L metadata item not found")
    if item.item_kind != "file":
        raise ExternalDocumentSourceConflictError("Only Phase L file metadata items are eligible for remote content read")

    existing = db.scalar(
        select(ExternalDocumentSourceRemoteFileContentReadExecution).where(
            ExternalDocumentSourceRemoteFileContentReadExecution.metadata_item_id == metadata_item_id
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if existing.request_key != normalized_key or existing.request_reason != normalized_reason or existing.requested_by_id != requested_by_id:
            raise ExternalDocumentSourceConflictError("Conflicting replay for remote file content read execution")
        return existing, "unchanged"

    binding = _active_binding(db, listing)
    profile = _get_profile(db, organization_id=organization_id, profile_id=profile_id)
    _ensure_profile_integrity(db, profile)
    if profile.status != "active" or profile.profile_hash != listing.profile_hash:
        raise ExternalDocumentSourceConflictError("External document source profile is not active")

    policy = _read_policy(profile.provider_kind, profile.normalized_config, item)
    if item.byte_size is not None and item.byte_size > policy.max_content_bytes:
        raise ExternalDocumentSourceConflictError("Phase L file exceeds the Phase M declared-size byte bound")
    if listing.client_kind != policy.client_kind:
        raise ExternalDocumentSourceConflictError("Remote file content read client lineage drifted")
    adapter = _READ_ADAPTERS.get((profile.provider_kind, policy.read_operation_kind))
    if adapter is None:
        raise ExternalDocumentSourceConflictError("Remote file content read adapter is unavailable")
    adapter_kind = _normalize_identifier(adapter.adapter_kind, field="Remote file content read adapter kind")
    if (
        adapter.provider_kind != profile.provider_kind
        or adapter.client_kind != policy.client_kind
        or adapter.read_operation_kind != policy.read_operation_kind
        or adapter.provider_origin != policy.provider_origin
        or adapter.redirect_policy_kind != policy.redirect_policy_kind
    ):
        raise ExternalDocumentSourceConflictError("Remote file content read adapter policy drifted")

    endpoint_policy_hash = _endpoint_policy_hash(policy)
    current = _aware(now or _utc_now())
    scope_hash = _scope_hash(
        listing=listing,
        item=item,
        read_operation_kind=policy.read_operation_kind,
        read_adapter_kind=adapter_kind,
        endpoint_policy_hash=endpoint_policy_hash,
        request_key=normalized_key,
    )
    execution = ExternalDocumentSourceRemoteFileContentReadExecution(
        organization_id=organization_id,
        profile_id=profile_id,
        listing_execution_id=listing.id,
        metadata_item_id=item.id,
        provider_client_health_execution_id=listing.provider_client_health_execution_id,
        token_acquisition_execution_id=listing.token_acquisition_execution_id,
        credential_resolution_execution_id=listing.credential_resolution_execution_id,
        credential_reference_binding_id=listing.credential_reference_binding_id,
        provider_kind=listing.provider_kind,
        profile_hash=listing.profile_hash,
        locator_hash=listing.locator_hash,
        reference_backend=listing.reference_backend,
        client_kind=listing.client_kind,
        listing_operation_kind=listing.listing_operation_kind,
        list_adapter_kind=listing.list_adapter_kind,
        listing_scope_hash=listing.scope_hash,
        listing_request_hash=listing.request_hash,
        listing_completion_hash=listing.completion_hash,
        listing_items_hash=listing.items_hash,
        metadata_item_hash=item.item_hash,
        metadata_item_version_token_hash=item.version_token_hash,
        declared_byte_size=item.byte_size,
        metadata_mime_type_class=item.mime_type_class,
        read_operation_kind=policy.read_operation_kind,
        read_adapter_kind=adapter_kind,
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
        transient_result = adapter.read_content(locator, policy)
    except Exception:
        raise ExternalDocumentSourceConflictError("Remote file content read failed") from None
    try:
        proof = _consume_result(transient_result, policy, item)
    finally:
        del transient_result

    completed_at = max(current, _utc_now())
    execution.status = "completed"
    execution.result_status = "read_verified"
    execution.content_sha256 = proof.content_sha256
    execution.content_byte_count = proof.content_byte_count
    execution.media_type_class = proof.media_type_class
    execution.latency_class = proof.latency_class
    execution.observed_version_token_hash = proof.observed_version_token_hash
    execution.completed_at = completed_at
    execution.provider_client_constructed = True
    execution.remote_content_transiently_observed = True
    execution.remote_read_performed = True
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


def get_external_document_source_remote_file_content_read(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = _get_execution(db, organization_id=organization_id, profile_id=profile_id, execution_id=execution_id)
    _ensure_integrity(db, execution)
    return execution


def list_external_document_source_remote_file_content_read_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = get_external_document_source_remote_file_content_read(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _receipts(db, execution)