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
from app.modules.external_document_sources.provider_client_health_models import ExternalDocumentSourceProviderClientHealthExecution
from app.modules.external_document_sources.provider_client_health_service import _ensure_integrity as _ensure_provider_client_health_integrity
from app.modules.external_document_sources.remote_metadata_listing_models import (
    ExternalDocumentSourceRemoteMetadataListingExecution,
    ExternalDocumentSourceRemoteMetadataListingItem,
    ExternalDocumentSourceRemoteMetadataListingReceipt,
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
_ALLOWED_FAILURE_CODES = {
    "unauthorized",
    "permission_denied",
    "endpoint_unavailable",
    "timeout",
    "malformed_response",
    "oversized_response",
    "too_many_items",
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
    "remote_read_performed",
    "remote_write_performed",
    "remote_delete_performed",
    "subscription_created",
    "checkpoint_created",
    "sync_executed",
    "evidence_admitted",
    "document_created",
    "claim_mutated",
)
_PROVIDER_LIST_POLICIES = {
    "sharepoint": {
        "client_kind": "microsoft_graph_transient_v1",
        "listing_operation_kind": "graph_drive_children_metadata_v1",
        "provider_origin": "https://graph.microsoft.com",
        "field_projection": "id,name,size,lastModifiedDateTime,file,folder,parentReference,eTag",
    },
    "google_drive": {
        "client_kind": "google_drive_transient_v3",
        "listing_operation_kind": "drive_files_list_metadata_v1",
        "provider_origin": "https://www.googleapis.com",
        "field_projection": "files(id,name,mimeType,size,modifiedTime,parents,md5Checksum,version),nextPageToken",
    },
}


@dataclass(frozen=True)
class RemoteMetadataListingPolicy:
    provider_kind: str
    client_kind: str
    listing_operation_kind: str
    provider_origin: str
    listing_endpoint_url: str
    field_projection: str
    max_items: int = 100
    max_pages: int = 1
    max_response_bytes: int = 131072
    connect_timeout_seconds: float = 3.0
    read_timeout_seconds: float = 7.0
    total_timeout_seconds: float = 10.0
    allow_redirects: bool = False


@dataclass(frozen=True)
class RemoteMetadataItemProjection:
    provider_item_id: str
    item_kind: str
    display_name: str
    parent_item_id: str | None = None
    mime_type_class: str | None = None
    byte_size: int | None = None
    modified_at: datetime | None = None
    version_token_hash: str | None = None


@dataclass(frozen=True)
class RemoteMetadataListResult:
    """Bounded metadata-only result. Tokens, raw provider payloads and file bodies must never cross this interface."""

    listed: bool
    items: tuple[RemoteMetadataItemProjection, ...] = ()
    truncated: bool = False
    page_count: int = 0
    failure_code: str | None = None


class ExternalDocumentSourceRemoteMetadataListAdapter(Protocol):
    adapter_kind: str
    provider_kind: str
    client_kind: str
    listing_operation_kind: str
    provider_origin: str

    def list_metadata(
        self,
        locator: CredentialReferenceLocator,
        policy: RemoteMetadataListingPolicy,
    ) -> RemoteMetadataListResult: ...


_LIST_ADAPTERS: dict[tuple[str, str], ExternalDocumentSourceRemoteMetadataListAdapter] = {}


def register_external_document_source_remote_metadata_list_adapter(
    provider_kind: str,
    listing_operation_kind: str,
    adapter: ExternalDocumentSourceRemoteMetadataListAdapter,
) -> None:
    provider = provider_kind.strip().lower()
    operation = listing_operation_kind.strip().lower()
    expected = _PROVIDER_LIST_POLICIES.get(provider)
    if expected is None or operation != expected["listing_operation_kind"]:
        raise ValueError("Unsupported provider/list-operation combination")
    adapter_kind = getattr(adapter, "adapter_kind", None)
    if not isinstance(adapter_kind, str) or not _SAFE_IDENTIFIER.fullmatch(adapter_kind):
        raise ValueError("Remote metadata list adapter kind is invalid")
    if getattr(adapter, "provider_kind", None) != provider:
        raise ValueError("Remote metadata list adapter provider kind does not match the governed provider")
    if getattr(adapter, "client_kind", None) != expected["client_kind"]:
        raise ValueError("Remote metadata list adapter client kind is not approved")
    if getattr(adapter, "listing_operation_kind", None) != operation:
        raise ValueError("Remote metadata list adapter operation does not match the governed operation")
    origin = getattr(adapter, "provider_origin", None)
    if origin != expected["provider_origin"]:
        raise ValueError("Remote metadata list adapter origin is not approved")
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
        raise ValueError("Remote metadata list adapter origin is invalid")
    _LIST_ADAPTERS[(provider, operation)] = adapter


def clear_external_document_source_remote_metadata_list_adapters() -> None:
    _LIST_ADAPTERS.clear()


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


def _listing_policy(provider_kind: str, normalized_config: dict) -> RemoteMetadataListingPolicy:
    provider = provider_kind.strip().lower()
    base = _PROVIDER_LIST_POLICIES.get(provider)
    if base is None:
        raise ExternalDocumentSourceConflictError("Unsupported external document source provider for remote metadata listing")
    if not isinstance(normalized_config, dict):
        raise ExternalDocumentSourceConflictError("Governed provider configuration is invalid")

    if provider == "sharepoint":
        if set(normalized_config) != {"tenant_domain", "site_id", "library_id"}:
            raise ExternalDocumentSourceConflictError("Governed SharePoint profile configuration drifted")
        site_id = normalized_config.get("site_id")
        library_id = normalized_config.get("library_id")
        if not isinstance(site_id, str) or not site_id.strip() or not isinstance(library_id, str) or not library_id.strip():
            raise ExternalDocumentSourceConflictError("Governed SharePoint source boundary is incomplete")
        path = f"/v1.0/sites/{quote(site_id.strip(), safe='')}/drives/{quote(library_id.strip(), safe='')}/root/children"
        query = urlencode({"$select": base["field_projection"], "$top": "100"})
        endpoint = f"{base['provider_origin']}{path}?{query}"
    else:
        if not set(normalized_config).issubset({"shared_drive_id", "folder_id"}) or "shared_drive_id" not in normalized_config:
            raise ExternalDocumentSourceConflictError("Governed Google Drive profile configuration drifted")
        shared_drive_id = normalized_config.get("shared_drive_id")
        folder_id = normalized_config.get("folder_id") or shared_drive_id
        if not isinstance(shared_drive_id, str) or not shared_drive_id.strip() or not isinstance(folder_id, str) or not folder_id.strip():
            raise ExternalDocumentSourceConflictError("Governed Google Drive source boundary is incomplete")
        query = urlencode(
            {
                "q": f"'{folder_id.strip()}' in parents and trashed=false",
                "corpora": "drive",
                "driveId": shared_drive_id.strip(),
                "includeItemsFromAllDrives": "true",
                "supportsAllDrives": "true",
                "pageSize": "100",
                "fields": base["field_projection"],
            }
        )
        endpoint = f"{base['provider_origin']}/drive/v3/files?{query}"

    parsed_endpoint = urlparse(endpoint)
    parsed_origin = urlparse(base["provider_origin"])
    if (
        parsed_endpoint.scheme != "https"
        or parsed_endpoint.netloc != parsed_origin.netloc
        or parsed_endpoint.username is not None
        or parsed_endpoint.password is not None
        or parsed_endpoint.fragment
    ):
        raise ExternalDocumentSourceConflictError("Derived remote metadata listing endpoint is not approved")
    return RemoteMetadataListingPolicy(
        provider_kind=provider,
        client_kind=base["client_kind"],
        listing_operation_kind=base["listing_operation_kind"],
        provider_origin=base["provider_origin"],
        listing_endpoint_url=endpoint,
        field_projection=base["field_projection"],
    )


def _endpoint_policy_hash(policy: RemoteMetadataListingPolicy) -> str:
    return _canonical_hash(
        {
            "provider_kind": policy.provider_kind,
            "client_kind": policy.client_kind,
            "listing_operation_kind": policy.listing_operation_kind,
            "provider_origin": policy.provider_origin,
            "listing_endpoint_url": policy.listing_endpoint_url,
            "field_projection": policy.field_projection,
            "max_items": policy.max_items,
            "max_pages": policy.max_pages,
            "max_response_bytes": policy.max_response_bytes,
            "connect_timeout_seconds": policy.connect_timeout_seconds,
            "read_timeout_seconds": policy.read_timeout_seconds,
            "total_timeout_seconds": policy.total_timeout_seconds,
            "allow_redirects": policy.allow_redirects,
        }
    )


def _normalize_projection(item: RemoteMetadataItemProjection) -> RemoteMetadataItemProjection:
    if not isinstance(item, RemoteMetadataItemProjection):
        raise ExternalDocumentSourceConflictError("Remote metadata list adapter returned an invalid item projection")
    provider_item_id = _normalize_text(item.provider_item_id, field="provider_item_id", minimum=1, maximum=512)
    parent_item_id = None
    if item.parent_item_id is not None:
        parent_item_id = _normalize_text(item.parent_item_id, field="parent_item_id", minimum=1, maximum=512)
    item_kind = item.item_kind.strip().lower()
    if item_kind not in {"file", "folder"}:
        raise ExternalDocumentSourceConflictError("Remote metadata list adapter returned an invalid item kind")
    display_name = _normalize_text(item.display_name, field="display_name", minimum=1, maximum=512)
    mime_type_class = None
    if item.mime_type_class is not None:
        mime_type_class = _normalize_text(item.mime_type_class, field="mime_type_class", minimum=1, maximum=128)
    byte_size = item.byte_size
    if byte_size is not None and (not isinstance(byte_size, int) or isinstance(byte_size, bool) or byte_size < 0 or byte_size > 10**15):
        raise ExternalDocumentSourceConflictError("Remote metadata list adapter returned an invalid byte size")
    modified_at = item.modified_at
    if modified_at is not None:
        if not isinstance(modified_at, datetime):
            raise ExternalDocumentSourceConflictError("Remote metadata list adapter returned an invalid modified timestamp")
        modified_at = _aware(modified_at)
    version_token_hash = item.version_token_hash
    if version_token_hash is not None:
        version_token_hash = version_token_hash.strip().lower()
        if not _HEX_64.fullmatch(version_token_hash):
            raise ExternalDocumentSourceConflictError("Remote metadata list adapter returned an invalid version-token hash")
    return RemoteMetadataItemProjection(
        provider_item_id=provider_item_id,
        parent_item_id=parent_item_id,
        item_kind=item_kind,
        display_name=display_name,
        mime_type_class=mime_type_class,
        byte_size=byte_size,
        modified_at=modified_at,
        version_token_hash=version_token_hash,
    )


def _validate_result(result: RemoteMetadataListResult, policy: RemoteMetadataListingPolicy) -> tuple[RemoteMetadataItemProjection, ...]:
    if not isinstance(result, RemoteMetadataListResult):
        raise ExternalDocumentSourceConflictError("Remote metadata list adapter returned an invalid result")
    if not result.listed:
        if result.failure_code not in _ALLOWED_FAILURE_CODES:
            raise ExternalDocumentSourceConflictError("Remote metadata list adapter returned an unsupported failure code")
        if result.items or result.page_count != 0 or result.truncated:
            raise ExternalDocumentSourceConflictError("Failed remote metadata listing returned unexpected result data")
        raise ExternalDocumentSourceConflictError(f"Remote metadata listing failed ({result.failure_code})")
    if result.failure_code is not None:
        raise ExternalDocumentSourceConflictError("Successful remote metadata listing cannot include a failure code")
    if result.page_count != 1 or result.page_count > policy.max_pages:
        raise ExternalDocumentSourceConflictError("Remote metadata listing exceeded the page bound")
    if not isinstance(result.items, tuple):
        raise ExternalDocumentSourceConflictError("Remote metadata list adapter must return an immutable item tuple")
    if len(result.items) > policy.max_items:
        raise ExternalDocumentSourceConflictError("Remote metadata listing exceeded the item bound")
    normalized: list[RemoteMetadataItemProjection] = []
    seen_ids: set[str] = set()
    for item in result.items:
        projected = _normalize_projection(item)
        if projected.provider_item_id in seen_ids:
            raise ExternalDocumentSourceConflictError("Remote metadata listing returned duplicate provider item identifiers")
        seen_ids.add(projected.provider_item_id)
        normalized.append(projected)
    if not isinstance(result.truncated, bool):
        raise ExternalDocumentSourceConflictError("Remote metadata listing returned an invalid truncation flag")
    return tuple(normalized)


def _base_safety(executed: bool) -> dict[str, bool]:
    return {
        "credential_reference_stored": True,
        "credential_reference_resolution_performed": True,
        "activation_authorization_consumed": True,
        "upstream_token_acquisition_completed": True,
        "upstream_provider_client_health_completed": True,
        "provider_client_constructed": executed,
        "remote_list_performed": executed,
        **{field: False for field in _FALSE_SAFETY_FIELDS},
    }


def _scope_hash(
    *,
    health_execution: ExternalDocumentSourceProviderClientHealthExecution,
    listing_operation_kind: str,
    list_adapter_kind: str,
    endpoint_policy_hash: str,
    request_key: str,
) -> str:
    if health_execution.completion_hash is None:
        raise ExternalDocumentSourceConflictError("Phase K provider client health completion facts are incomplete")
    return _canonical_hash(
        {
            "organization_id": str(health_execution.organization_id),
            "profile_id": str(health_execution.profile_id),
            "provider_client_health_execution_id": str(health_execution.id),
            "token_acquisition_execution_id": str(health_execution.token_acquisition_execution_id),
            "credential_resolution_execution_id": str(health_execution.credential_resolution_execution_id),
            "credential_reference_binding_id": str(health_execution.credential_reference_binding_id),
            "provider_kind": health_execution.provider_kind,
            "profile_hash": health_execution.profile_hash,
            "locator_hash": health_execution.locator_hash,
            "reference_backend": health_execution.reference_backend,
            "resolution_resolver_kind": health_execution.resolution_resolver_kind,
            "token_flow_kind": health_execution.token_flow_kind,
            "client_kind": health_execution.client_kind,
            "health_operation_kind": health_execution.health_operation_kind,
            "health_adapter_kind": health_execution.health_adapter_kind,
            "provider_client_health_scope_hash": health_execution.scope_hash,
            "provider_client_health_request_hash": health_execution.request_hash,
            "provider_client_health_completion_hash": health_execution.completion_hash,
            "listing_operation_kind": listing_operation_kind,
            "list_adapter_kind": list_adapter_kind,
            "endpoint_policy_hash": endpoint_policy_hash,
            "request_key": request_key,
        }
    )


def _request_hash(execution: ExternalDocumentSourceRemoteMetadataListingExecution) -> str:
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


def _projection_from_row(row: ExternalDocumentSourceRemoteMetadataListingItem) -> RemoteMetadataItemProjection:
    return RemoteMetadataItemProjection(
        provider_item_id=row.provider_item_id,
        parent_item_id=row.parent_item_id,
        item_kind=row.item_kind,
        display_name=row.display_name,
        mime_type_class=row.mime_type_class,
        byte_size=row.byte_size,
        modified_at=row.modified_at,
        version_token_hash=row.version_token_hash,
    )


def _item_hash(execution_id: UUID, item_index: int, item: RemoteMetadataItemProjection) -> str:
    return _canonical_hash(
        {
            "execution_id": str(execution_id),
            "item_index": item_index,
            "provider_item_id": item.provider_item_id,
            "parent_item_id": item.parent_item_id,
            "item_kind": item.item_kind,
            "display_name": item.display_name,
            "mime_type_class": item.mime_type_class,
            "byte_size": item.byte_size,
            "modified_at": _iso(item.modified_at),
            "version_token_hash": item.version_token_hash,
        }
    )


def _completion_hash(execution: ExternalDocumentSourceRemoteMetadataListingExecution) -> str:
    if (
        execution.completed_at is None
        or execution.result_status != "listed"
        or execution.items_hash is None
        or execution.page_count != 1
    ):
        raise ExternalDocumentSourceConflictError("Remote metadata listing completion facts are incomplete")
    return _canonical_hash(
        {
            "execution_id": str(execution.id),
            "scope_hash": execution.scope_hash,
            "request_hash": execution.request_hash,
            "result_status": execution.result_status,
            "item_count": execution.item_count,
            "page_count": execution.page_count,
            "truncated": execution.truncated,
            "items_hash": execution.items_hash,
            "completed_at": _iso(execution.completed_at),
            **_base_safety(True),
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceRemoteMetadataListingReceipt) -> str:
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


def _receipts(db: Session, execution: ExternalDocumentSourceRemoteMetadataListingExecution) -> list[ExternalDocumentSourceRemoteMetadataListingReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceRemoteMetadataListingReceipt)
            .where(
                ExternalDocumentSourceRemoteMetadataListingReceipt.organization_id == execution.organization_id,
                ExternalDocumentSourceRemoteMetadataListingReceipt.execution_id == execution.id,
            )
            .order_by(ExternalDocumentSourceRemoteMetadataListingReceipt.sequence_number.asc())
        ).all()
    )


def _items(db: Session, execution: ExternalDocumentSourceRemoteMetadataListingExecution) -> list[ExternalDocumentSourceRemoteMetadataListingItem]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceRemoteMetadataListingItem)
            .where(
                ExternalDocumentSourceRemoteMetadataListingItem.organization_id == execution.organization_id,
                ExternalDocumentSourceRemoteMetadataListingItem.execution_id == execution.id,
            )
            .order_by(ExternalDocumentSourceRemoteMetadataListingItem.item_index.asc())
        ).all()
    )


def _append_receipt(
    db: Session,
    *,
    execution: ExternalDocumentSourceRemoteMetadataListingExecution,
    event_type: str,
    actor_id: UUID,
    occurred_at: datetime,
    decision_hash: str,
) -> None:
    rows = _receipts(db, execution)
    receipt = ExternalDocumentSourceRemoteMetadataListingReceipt(
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
) -> ExternalDocumentSourceRemoteMetadataListingExecution:
    row = db.scalar(
        select(ExternalDocumentSourceRemoteMetadataListingExecution).where(
            ExternalDocumentSourceRemoteMetadataListingExecution.id == execution_id,
            ExternalDocumentSourceRemoteMetadataListingExecution.organization_id == organization_id,
            ExternalDocumentSourceRemoteMetadataListingExecution.profile_id == profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceNotFoundError("Remote metadata listing execution not found")
    return row


def _health_execution(
    db: Session,
    execution: ExternalDocumentSourceRemoteMetadataListingExecution,
) -> ExternalDocumentSourceProviderClientHealthExecution:
    row = db.scalar(
        select(ExternalDocumentSourceProviderClientHealthExecution).where(
            ExternalDocumentSourceProviderClientHealthExecution.id == execution.provider_client_health_execution_id,
            ExternalDocumentSourceProviderClientHealthExecution.organization_id == execution.organization_id,
            ExternalDocumentSourceProviderClientHealthExecution.profile_id == execution.profile_id,
        )
    )
    if row is None:
        raise ExternalDocumentSourceConflictError("Phase K provider client health lineage is missing")
    return row


def _active_binding(db: Session, health_execution: ExternalDocumentSourceProviderClientHealthExecution):
    binding = get_external_document_source_credential_reference(
        db,
        organization_id=health_execution.organization_id,
        profile_id=health_execution.profile_id,
        binding_id=health_execution.credential_reference_binding_id,
    )
    if binding.status != "active" or binding.approval_hash is None:
        raise ExternalDocumentSourceConflictError("Bound credential reference is not active")
    if (
        binding.provider_kind != health_execution.provider_kind
        or binding.profile_hash != health_execution.profile_hash
        or binding.locator_hash != health_execution.locator_hash
        or binding.reference_backend != health_execution.reference_backend
    ):
        raise ExternalDocumentSourceConflictError("Remote metadata listing credential-reference lineage drifted")
    return binding


def _ensure_integrity(db: Session, execution: ExternalDocumentSourceRemoteMetadataListingExecution) -> None:
    if (
        execution.status != "completed"
        or execution.result_status != "listed"
        or execution.page_count != 1
        or execution.item_count < 0
        or execution.item_count > 100
        or execution.items_hash is None
    ):
        raise ExternalDocumentSourceConflictError("Remote metadata listing execution lifecycle is incomplete")
    for field, expected in _base_safety(True).items():
        if bool(getattr(execution, field)) != expected:
            raise ExternalDocumentSourceConflictError("Remote metadata listing execution safety boundary drifted")

    health_execution = _health_execution(db, execution)
    _ensure_provider_client_health_integrity(db, health_execution)
    if health_execution.status != "completed" or health_execution.completion_hash is None:
        raise ExternalDocumentSourceConflictError("Phase K provider client health is not complete")
    _active_binding(db, health_execution)

    profile = _get_profile(db, organization_id=execution.organization_id, profile_id=execution.profile_id)
    _ensure_profile_integrity(db, profile)
    if profile.status != "active" or profile.profile_hash != execution.profile_hash:
        raise ExternalDocumentSourceConflictError("Remote metadata listing source profile is not active")
    policy = _listing_policy(profile.provider_kind, profile.normalized_config)
    expected_policy_hash = _endpoint_policy_hash(policy)
    if (
        execution.token_acquisition_execution_id != health_execution.token_acquisition_execution_id
        or execution.credential_resolution_execution_id != health_execution.credential_resolution_execution_id
        or execution.credential_reference_binding_id != health_execution.credential_reference_binding_id
        or execution.provider_kind != health_execution.provider_kind
        or execution.profile_hash != health_execution.profile_hash
        or execution.locator_hash != health_execution.locator_hash
        or execution.reference_backend != health_execution.reference_backend
        or execution.resolution_resolver_kind != health_execution.resolution_resolver_kind
        or execution.token_flow_kind != health_execution.token_flow_kind
        or execution.client_kind != health_execution.client_kind
        or execution.health_operation_kind != health_execution.health_operation_kind
        or execution.health_adapter_kind != health_execution.health_adapter_kind
        or execution.provider_client_health_scope_hash != health_execution.scope_hash
        or execution.provider_client_health_request_hash != health_execution.request_hash
        or execution.provider_client_health_completion_hash != health_execution.completion_hash
        or execution.client_kind != policy.client_kind
        or execution.listing_operation_kind != policy.listing_operation_kind
        or execution.endpoint_policy_hash != expected_policy_hash
    ):
        raise ExternalDocumentSourceConflictError("Remote metadata listing execution lineage drifted")
    adapter_kind = _normalize_identifier(execution.list_adapter_kind, field="Remote metadata list adapter kind")
    expected_scope = _scope_hash(
        health_execution=health_execution,
        listing_operation_kind=policy.listing_operation_kind,
        list_adapter_kind=adapter_kind,
        endpoint_policy_hash=expected_policy_hash,
        request_key=execution.request_key,
    )
    if execution.scope_hash != expected_scope or execution.request_hash != _request_hash(execution):
        raise ExternalDocumentSourceConflictError("Remote metadata listing request integrity failed")

    item_rows = _items(db, execution)
    if len(item_rows) != execution.item_count:
        raise ExternalDocumentSourceConflictError("Remote metadata listing item count drifted")
    item_hashes: list[str] = []
    for expected_index, row in enumerate(item_rows):
        if row.item_index != expected_index or row.organization_id != execution.organization_id:
            raise ExternalDocumentSourceConflictError("Remote metadata listing item ordering drifted")
        normalized = _normalize_projection(_projection_from_row(row))
        expected_item_hash = _item_hash(execution.id, expected_index, normalized)
        if row.item_hash != expected_item_hash:
            raise ExternalDocumentSourceConflictError("Remote metadata listing item integrity failed")
        item_hashes.append(row.item_hash)
    if execution.items_hash != _canonical_hash(item_hashes):
        raise ExternalDocumentSourceConflictError("Remote metadata listing item-set integrity failed")
    if execution.completion_hash != _completion_hash(execution):
        raise ExternalDocumentSourceConflictError("Remote metadata listing completion integrity failed")
    if execution.completed_at is None or _aware(execution.completed_at) < _aware(execution.requested_at):
        raise ExternalDocumentSourceConflictError("Remote metadata listing timestamps drifted")

    rows = _receipts(db, execution)
    if len(rows) != 2 or [row.event_type for row in rows] != ["requested", "completed"]:
        raise ExternalDocumentSourceConflictError("Remote metadata listing receipt lifecycle is incomplete")
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
            raise ExternalDocumentSourceConflictError("Remote metadata listing receipt facts drifted")
        for field, expected in _base_safety(performed).items():
            if bool(getattr(receipt, field)) != expected:
                raise ExternalDocumentSourceConflictError("Remote metadata listing receipt safety boundary drifted")
        if receipt.receipt_hash != _receipt_hash(receipt):
            raise ExternalDocumentSourceConflictError("Remote metadata listing receipt integrity failed")
        prior = receipt.receipt_hash


def execute_external_document_source_remote_metadata_listing(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    provider_client_health_execution_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    request_reason: str,
    now: datetime | None = None,
):
    normalized_key = _normalize_text(request_key, field="request_key", minimum=1, maximum=128)
    normalized_reason = _normalize_text(request_reason, field="reason", minimum=8, maximum=2000)
    existing = db.scalar(
        select(ExternalDocumentSourceRemoteMetadataListingExecution).where(
            ExternalDocumentSourceRemoteMetadataListingExecution.organization_id == organization_id,
            ExternalDocumentSourceRemoteMetadataListingExecution.profile_id == profile_id,
            ExternalDocumentSourceRemoteMetadataListingExecution.provider_client_health_execution_id == provider_client_health_execution_id,
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if existing.request_key != normalized_key or existing.request_reason != normalized_reason or existing.requested_by_id != requested_by_id:
            raise ExternalDocumentSourceConflictError("Conflicting replay for remote metadata listing execution")
        return existing, "unchanged"

    key_collision = db.scalar(
        select(ExternalDocumentSourceRemoteMetadataListingExecution).where(
            ExternalDocumentSourceRemoteMetadataListingExecution.organization_id == organization_id,
            ExternalDocumentSourceRemoteMetadataListingExecution.profile_id == profile_id,
            ExternalDocumentSourceRemoteMetadataListingExecution.request_key == normalized_key,
        )
    )
    if key_collision is not None:
        raise ExternalDocumentSourceConflictError("Conflicting replay for remote metadata listing request_key")

    health_execution = db.scalar(
        select(ExternalDocumentSourceProviderClientHealthExecution)
        .where(
            ExternalDocumentSourceProviderClientHealthExecution.id == provider_client_health_execution_id,
            ExternalDocumentSourceProviderClientHealthExecution.organization_id == organization_id,
            ExternalDocumentSourceProviderClientHealthExecution.profile_id == profile_id,
        )
        .with_for_update()
    )
    if health_execution is None:
        raise ExternalDocumentSourceNotFoundError("Phase K provider client health execution not found")

    existing = db.scalar(
        select(ExternalDocumentSourceRemoteMetadataListingExecution).where(
            ExternalDocumentSourceRemoteMetadataListingExecution.provider_client_health_execution_id == provider_client_health_execution_id
        )
    )
    if existing is not None:
        _ensure_integrity(db, existing)
        if existing.request_key != normalized_key or existing.request_reason != normalized_reason or existing.requested_by_id != requested_by_id:
            raise ExternalDocumentSourceConflictError("Conflicting replay for remote metadata listing execution")
        return existing, "unchanged"

    _ensure_provider_client_health_integrity(db, health_execution)
    if health_execution.status != "completed" or health_execution.completion_hash is None:
        raise ExternalDocumentSourceConflictError("Phase K provider client health is not eligible for remote metadata listing")
    binding = _active_binding(db, health_execution)
    profile = _get_profile(db, organization_id=organization_id, profile_id=profile_id)
    _ensure_profile_integrity(db, profile)
    if profile.status != "active" or profile.profile_hash != health_execution.profile_hash:
        raise ExternalDocumentSourceConflictError("External document source profile is not active")

    policy = _listing_policy(profile.provider_kind, profile.normalized_config)
    if health_execution.client_kind != policy.client_kind:
        raise ExternalDocumentSourceConflictError("Remote metadata listing client lineage drifted")
    adapter = _LIST_ADAPTERS.get((profile.provider_kind, policy.listing_operation_kind))
    if adapter is None:
        raise ExternalDocumentSourceConflictError("Remote metadata list adapter is unavailable")
    adapter_kind = _normalize_identifier(adapter.adapter_kind, field="Remote metadata list adapter kind")
    if (
        adapter.provider_kind != profile.provider_kind
        or adapter.client_kind != policy.client_kind
        or adapter.listing_operation_kind != policy.listing_operation_kind
        or adapter.provider_origin != policy.provider_origin
    ):
        raise ExternalDocumentSourceConflictError("Remote metadata list adapter policy drifted")

    endpoint_policy_hash = _endpoint_policy_hash(policy)
    current = _aware(now or _utc_now())
    scope_hash = _scope_hash(
        health_execution=health_execution,
        listing_operation_kind=policy.listing_operation_kind,
        list_adapter_kind=adapter_kind,
        endpoint_policy_hash=endpoint_policy_hash,
        request_key=normalized_key,
    )
    execution = ExternalDocumentSourceRemoteMetadataListingExecution(
        organization_id=organization_id,
        profile_id=profile_id,
        provider_client_health_execution_id=health_execution.id,
        token_acquisition_execution_id=health_execution.token_acquisition_execution_id,
        credential_resolution_execution_id=health_execution.credential_resolution_execution_id,
        credential_reference_binding_id=health_execution.credential_reference_binding_id,
        provider_kind=health_execution.provider_kind,
        profile_hash=health_execution.profile_hash,
        locator_hash=health_execution.locator_hash,
        reference_backend=health_execution.reference_backend,
        resolution_resolver_kind=health_execution.resolution_resolver_kind,
        token_flow_kind=health_execution.token_flow_kind,
        client_kind=health_execution.client_kind,
        health_operation_kind=health_execution.health_operation_kind,
        health_adapter_kind=health_execution.health_adapter_kind,
        provider_client_health_scope_hash=health_execution.scope_hash,
        provider_client_health_request_hash=health_execution.request_hash,
        provider_client_health_completion_hash=health_execution.completion_hash,
        listing_operation_kind=policy.listing_operation_kind,
        list_adapter_kind=adapter_kind,
        endpoint_policy_hash=endpoint_policy_hash,
        request_key=normalized_key,
        scope_hash=scope_hash,
        request_hash="0" * 64,
        status="requested",
        item_count=0,
        page_count=0,
        truncated=False,
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
        result = adapter.list_metadata(locator, policy)
    except Exception:
        raise ExternalDocumentSourceConflictError("Remote metadata listing failed") from None
    normalized_items = _validate_result(result, policy)

    item_hashes: list[str] = []
    for item_index, item in enumerate(normalized_items):
        item_hash = _item_hash(execution.id, item_index, item)
        row = ExternalDocumentSourceRemoteMetadataListingItem(
            organization_id=organization_id,
            execution_id=execution.id,
            item_index=item_index,
            provider_item_id=item.provider_item_id,
            parent_item_id=item.parent_item_id,
            item_kind=item.item_kind,
            display_name=item.display_name,
            mime_type_class=item.mime_type_class,
            byte_size=item.byte_size,
            modified_at=item.modified_at,
            version_token_hash=item.version_token_hash,
            item_hash=item_hash,
        )
        db.add(row)
        item_hashes.append(item_hash)
    db.flush()

    completed_at = max(current, _utc_now())
    execution.status = "completed"
    execution.result_status = "listed"
    execution.item_count = len(normalized_items)
    execution.page_count = result.page_count
    execution.truncated = result.truncated
    execution.items_hash = _canonical_hash(item_hashes)
    execution.completed_at = completed_at
    execution.provider_client_constructed = True
    execution.remote_list_performed = True
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


def get_external_document_source_remote_metadata_listing(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = _get_execution(db, organization_id=organization_id, profile_id=profile_id, execution_id=execution_id)
    _ensure_integrity(db, execution)
    return execution


def list_external_document_source_remote_metadata_listing_items(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = get_external_document_source_remote_metadata_listing(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _items(db, execution)


def list_external_document_source_remote_metadata_listing_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    execution_id: UUID,
):
    execution = get_external_document_source_remote_metadata_listing(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        execution_id=execution_id,
    )
    return _receipts(db, execution)
