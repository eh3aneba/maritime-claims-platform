import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.external_document_sources.models import (
    ExternalDocumentSourceDiscoveryItem,
    ExternalDocumentSourceDiscoveryReceipt,
    ExternalDocumentSourceDiscoveryRun,
    ExternalDocumentSourceProfile,
)
from app.modules.external_document_sources.service import (
    ExternalDocumentSourceConflictError,
    ExternalDocumentSourceNotFoundError,
    ExternalDocumentSourceValidationError,
    get_external_document_source_profile,
)


_DANGEROUS_SAFETY_FIELDS = (
    "credential_stored",
    "oauth_token_exchanged",
    "remote_read_performed",
    "remote_write_performed",
    "remote_delete_performed",
    "subscription_created",
    "sync_executed",
    "evidence_admitted",
    "document_created",
    "claim_mutated",
    "live_connection_authorized",
)


@dataclass(frozen=True)
class ExternalDocumentSourceMetadataItem:
    provider_item_id: str
    display_name: str
    item_kind: str
    parent_item_id: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    modified_at: datetime | None = None
    provider_etag: str | None = None


class ExternalDocumentSourceDiscoveryAdapter(Protocol):
    adapter_kind: str

    def list_metadata(
        self,
        *,
        provider_kind: str,
        normalized_config: dict[str, str],
        max_results: int,
    ) -> list[ExternalDocumentSourceMetadataItem]: ...


_DISCOVERY_ADAPTERS: dict[str, ExternalDocumentSourceDiscoveryAdapter] = {}


def register_external_document_source_discovery_adapter(
    provider_kind: str,
    adapter: ExternalDocumentSourceDiscoveryAdapter,
) -> None:
    if provider_kind not in {"sharepoint", "google_drive"}:
        raise ExternalDocumentSourceValidationError("Unsupported external document source provider")
    kind = str(getattr(adapter, "adapter_kind", "")).strip()
    if not kind or len(kind) > 128:
        raise ExternalDocumentSourceValidationError("Discovery adapter kind is invalid")
    _DISCOVERY_ADAPTERS[provider_kind] = adapter


def unregister_external_document_source_discovery_adapter(provider_kind: str) -> None:
    _DISCOVERY_ADAPTERS.pop(provider_kind, None)


def clear_external_document_source_discovery_adapters() -> None:
    _DISCOVERY_ADAPTERS.clear()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _canonical_hash(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_request_key(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 128:
        raise ExternalDocumentSourceValidationError("request_key must contain between 1 and 128 characters")
    return normalized


def _validate_limit(value: int) -> int:
    if value < 1 or value > 500:
        raise ExternalDocumentSourceValidationError("max_results must be between 1 and 500")
    return value


def _normalize_optional_text(value: str | None, *, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError(f"Discovery item field {field} is too long")
    return normalized


def _normalize_required_text(value: str, *, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise ExternalDocumentSourceValidationError(f"Discovery item field {field} is invalid")
    return normalized


def _normalized_item(item: ExternalDocumentSourceMetadataItem) -> dict:
    if not isinstance(item, ExternalDocumentSourceMetadataItem):
        raise ExternalDocumentSourceValidationError("Discovery adapter returned an unsupported metadata item")
    provider_item_id = _normalize_required_text(item.provider_item_id, field="provider_item_id", maximum=512)
    display_name = _normalize_required_text(item.display_name, field="display_name", maximum=512)
    if item.item_kind not in {"file", "folder"}:
        raise ExternalDocumentSourceValidationError("Discovery item kind must be file or folder")
    if item.size_bytes is not None and item.size_bytes < 0:
        raise ExternalDocumentSourceValidationError("Discovery item size_bytes must not be negative")
    return {
        "provider_item_id": provider_item_id,
        "parent_item_id": _normalize_optional_text(item.parent_item_id, field="parent_item_id", maximum=512),
        "display_name": display_name,
        "item_kind": item.item_kind,
        "mime_type": _normalize_optional_text(item.mime_type, field="mime_type", maximum=255),
        "size_bytes": item.size_bytes,
        "modified_at": item.modified_at,
        "provider_etag": _normalize_optional_text(item.provider_etag, field="provider_etag", maximum=512),
    }


def _item_hash(*, run_id: UUID, ordinal: int, value: dict) -> str:
    return _canonical_hash(
        {
            "run_id": str(run_id),
            "ordinal": ordinal,
            "provider_item_id": value["provider_item_id"],
            "parent_item_id": value["parent_item_id"],
            "display_name": value["display_name"],
            "item_kind": value["item_kind"],
            "mime_type": value["mime_type"],
            "size_bytes": value["size_bytes"],
            "modified_at": _iso(value["modified_at"]),
            "provider_etag": value["provider_etag"],
        }
    )


def _scope_hash(
    *,
    profile: ExternalDocumentSourceProfile,
    request_key: str,
    max_results: int,
) -> str:
    return _canonical_hash(
        {
            "organization_id": str(profile.organization_id),
            "profile_id": str(profile.id),
            "provider_kind": profile.provider_kind,
            "profile_hash": profile.profile_hash,
            "request_key": request_key,
            "max_results": max_results,
        }
    )


def _run_hash(run: ExternalDocumentSourceDiscoveryRun) -> str:
    return _canonical_hash(
        {
            "organization_id": str(run.organization_id),
            "profile_id": str(run.profile_id),
            "provider_kind": run.provider_kind,
            "profile_hash": run.profile_hash,
            "request_key": run.request_key,
            "max_results": run.max_results,
            "adapter_kind": run.adapter_kind,
            "scope_hash": run.scope_hash,
            "status": run.status,
            "result_count": run.result_count,
            "manifest_hash": run.manifest_hash,
            "requested_by_id": str(run.requested_by_id),
            "requested_at": _iso(run.requested_at),
            "completed_at": _iso(run.completed_at),
            "remote_list_performed": True,
            **{field: False for field in _DANGEROUS_SAFETY_FIELDS},
        }
    )


def _receipt_hash(receipt: ExternalDocumentSourceDiscoveryReceipt) -> str:
    return _canonical_hash(
        {
            "organization_id": str(receipt.organization_id),
            "run_id": str(receipt.run_id),
            "sequence_number": receipt.sequence_number,
            "event_type": receipt.event_type,
            "status_after": receipt.status_after,
            "actor_id": str(receipt.actor_id),
            "occurred_at": _iso(receipt.occurred_at),
            "scope_hash": receipt.scope_hash,
            "manifest_hash": receipt.manifest_hash,
            "run_hash": receipt.run_hash,
            "prior_receipt_hash": receipt.prior_receipt_hash,
            "remote_list_performed": receipt.remote_list_performed,
            **{field: False for field in _DANGEROUS_SAFETY_FIELDS},
        }
    )


def _get_run(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    run_id: UUID,
) -> ExternalDocumentSourceDiscoveryRun:
    run = db.scalar(
        select(ExternalDocumentSourceDiscoveryRun).where(
            ExternalDocumentSourceDiscoveryRun.id == run_id,
            ExternalDocumentSourceDiscoveryRun.organization_id == organization_id,
            ExternalDocumentSourceDiscoveryRun.profile_id == profile_id,
        )
    )
    if run is None:
        raise ExternalDocumentSourceNotFoundError("External document source discovery run not found")
    return run


def _run_items(db: Session, run: ExternalDocumentSourceDiscoveryRun) -> list[ExternalDocumentSourceDiscoveryItem]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceDiscoveryItem)
            .where(
                ExternalDocumentSourceDiscoveryItem.organization_id == run.organization_id,
                ExternalDocumentSourceDiscoveryItem.run_id == run.id,
            )
            .order_by(ExternalDocumentSourceDiscoveryItem.ordinal.asc())
        ).all()
    )


def _run_receipts(db: Session, run: ExternalDocumentSourceDiscoveryRun) -> list[ExternalDocumentSourceDiscoveryReceipt]:
    return list(
        db.scalars(
            select(ExternalDocumentSourceDiscoveryReceipt)
            .where(
                ExternalDocumentSourceDiscoveryReceipt.organization_id == run.organization_id,
                ExternalDocumentSourceDiscoveryReceipt.run_id == run.id,
            )
            .order_by(ExternalDocumentSourceDiscoveryReceipt.sequence_number.asc())
        ).all()
    )


def _ensure_discovery_integrity(
    db: Session,
    *,
    profile: ExternalDocumentSourceProfile,
    run: ExternalDocumentSourceDiscoveryRun,
) -> None:
    if run.profile_hash != profile.profile_hash or run.provider_kind != profile.provider_kind:
        raise ExternalDocumentSourceConflictError("External document source discovery profile lineage drifted")
    if run.status != "completed" or not run.remote_list_performed:
        raise ExternalDocumentSourceConflictError("External document source discovery execution state drifted")
    if any(bool(getattr(run, field)) for field in _DANGEROUS_SAFETY_FIELDS):
        raise ExternalDocumentSourceConflictError("External document source discovery safety boundary drifted")
    expected_scope = _scope_hash(profile=profile, request_key=run.request_key, max_results=run.max_results)
    if run.scope_hash != expected_scope:
        raise ExternalDocumentSourceConflictError("External document source discovery scope integrity failed")

    items = _run_items(db, run)
    if len(items) != run.result_count:
        raise ExternalDocumentSourceConflictError("External document source discovery result count drifted")
    item_hashes: list[str] = []
    provider_ids: set[str] = set()
    for expected_ordinal, item in enumerate(items, start=1):
        if item.ordinal != expected_ordinal or item.provider_item_id in provider_ids:
            raise ExternalDocumentSourceConflictError("External document source discovery item ordering drifted")
        provider_ids.add(item.provider_item_id)
        value = {
            "provider_item_id": item.provider_item_id,
            "parent_item_id": item.parent_item_id,
            "display_name": item.display_name,
            "item_kind": item.item_kind,
            "mime_type": item.mime_type,
            "size_bytes": item.size_bytes,
            "modified_at": item.modified_at,
            "provider_etag": item.provider_etag,
        }
        expected_item_hash = _item_hash(run_id=run.id, ordinal=item.ordinal, value=value)
        if item.item_hash != expected_item_hash:
            raise ExternalDocumentSourceConflictError("External document source discovery item integrity failed")
        item_hashes.append(item.item_hash)
    if run.manifest_hash != _canonical_hash(item_hashes) or run.run_hash != _run_hash(run):
        raise ExternalDocumentSourceConflictError("External document source discovery manifest integrity failed")

    receipts = _run_receipts(db, run)
    if len(receipts) != 2 or [row.event_type for row in receipts] != ["requested", "completed"]:
        raise ExternalDocumentSourceConflictError("External document source discovery receipt lifecycle is incomplete")
    prior: str | None = None
    for expected_sequence, receipt in enumerate(receipts, start=1):
        if receipt.sequence_number != expected_sequence or receipt.prior_receipt_hash != prior:
            raise ExternalDocumentSourceConflictError("External document source discovery receipt chain linkage failed")
        if receipt.scope_hash != run.scope_hash:
            raise ExternalDocumentSourceConflictError("External document source discovery receipt scope drifted")
        if any(bool(getattr(receipt, field)) for field in _DANGEROUS_SAFETY_FIELDS):
            raise ExternalDocumentSourceConflictError("External document source discovery receipt safety boundary drifted")
        if receipt.event_type == "requested":
            if receipt.remote_list_performed or receipt.manifest_hash is not None or receipt.run_hash is not None:
                raise ExternalDocumentSourceConflictError("External document source discovery request receipt drifted")
        else:
            if not receipt.remote_list_performed or receipt.manifest_hash != run.manifest_hash or receipt.run_hash != run.run_hash:
                raise ExternalDocumentSourceConflictError("External document source discovery completion receipt drifted")
        if receipt.receipt_hash != _receipt_hash(receipt):
            raise ExternalDocumentSourceConflictError("External document source discovery receipt integrity failed")
        prior = receipt.receipt_hash


def execute_external_document_source_discovery(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    requested_by_id: UUID,
    request_key: str,
    max_results: int,
    now: datetime | None = None,
):
    profile = get_external_document_source_profile(db, organization_id=organization_id, profile_id=profile_id)
    normalized_key = _normalize_request_key(request_key)
    limit = _validate_limit(max_results)
    scope_hash = _scope_hash(profile=profile, request_key=normalized_key, max_results=limit)

    existing = db.scalar(
        select(ExternalDocumentSourceDiscoveryRun).where(
            ExternalDocumentSourceDiscoveryRun.organization_id == organization_id,
            ExternalDocumentSourceDiscoveryRun.profile_id == profile_id,
            ExternalDocumentSourceDiscoveryRun.request_key == normalized_key,
        )
    )
    if existing is not None:
        _ensure_discovery_integrity(db, profile=profile, run=existing)
        if existing.scope_hash != scope_hash:
            raise ExternalDocumentSourceConflictError("Conflicting replay for external document source discovery request_key")
        return existing, "unchanged"

    if profile.status != "active":
        raise ExternalDocumentSourceConflictError("External document source profile must be active before discovery")
    adapter = _DISCOVERY_ADAPTERS.get(profile.provider_kind)
    if adapter is None:
        raise ExternalDocumentSourceConflictError(
            f"Read-only discovery adapter is not enabled for provider:{profile.provider_kind}"
        )
    adapter_kind = str(getattr(adapter, "adapter_kind", "")).strip()
    if not adapter_kind or len(adapter_kind) > 128:
        raise ExternalDocumentSourceConflictError("External document source discovery adapter identity is invalid")

    raw_items = adapter.list_metadata(
        provider_kind=profile.provider_kind,
        normalized_config=dict(profile.normalized_config),
        max_results=limit,
    )
    if not isinstance(raw_items, list):
        raise ExternalDocumentSourceValidationError("Discovery adapter must return a list of metadata items")
    if len(raw_items) > limit:
        raise ExternalDocumentSourceConflictError("Discovery adapter exceeded the governed max_results boundary")

    normalized = [_normalized_item(item) for item in raw_items]
    normalized.sort(key=lambda value: value["provider_item_id"])
    provider_ids = [value["provider_item_id"] for value in normalized]
    if len(provider_ids) != len(set(provider_ids)):
        raise ExternalDocumentSourceConflictError("Discovery adapter returned duplicate provider item identifiers")

    requested_at = now or _utc_now()
    completed_at = requested_at
    run = ExternalDocumentSourceDiscoveryRun(
        organization_id=organization_id,
        profile_id=profile.id,
        provider_kind=profile.provider_kind,
        profile_hash=profile.profile_hash,
        request_key=normalized_key,
        max_results=limit,
        adapter_kind=adapter_kind,
        scope_hash=scope_hash,
        status="completed",
        result_count=len(normalized),
        manifest_hash="0" * 64,
        run_hash="0" * 64,
        requested_by_id=requested_by_id,
        requested_at=requested_at,
        completed_at=completed_at,
        remote_list_performed=True,
        **{field: False for field in _DANGEROUS_SAFETY_FIELDS},
    )
    db.add(run)
    db.flush()

    item_hashes: list[str] = []
    for ordinal, value in enumerate(normalized, start=1):
        item_hash = _item_hash(run_id=run.id, ordinal=ordinal, value=value)
        item_hashes.append(item_hash)
        db.add(
            ExternalDocumentSourceDiscoveryItem(
                organization_id=organization_id,
                run_id=run.id,
                ordinal=ordinal,
                item_hash=item_hash,
                **value,
            )
        )
    run.manifest_hash = _canonical_hash(item_hashes)
    run.run_hash = _run_hash(run)

    requested_receipt = ExternalDocumentSourceDiscoveryReceipt(
        organization_id=organization_id,
        run_id=run.id,
        sequence_number=1,
        event_type="requested",
        status_after="requested",
        actor_id=requested_by_id,
        occurred_at=requested_at,
        scope_hash=scope_hash,
        manifest_hash=None,
        run_hash=None,
        prior_receipt_hash=None,
        remote_list_performed=False,
        **{field: False for field in _DANGEROUS_SAFETY_FIELDS},
    )
    requested_receipt.receipt_hash = _receipt_hash(requested_receipt)
    db.add(requested_receipt)
    db.flush()

    completed_receipt = ExternalDocumentSourceDiscoveryReceipt(
        organization_id=organization_id,
        run_id=run.id,
        sequence_number=2,
        event_type="completed",
        status_after="completed",
        actor_id=requested_by_id,
        occurred_at=completed_at,
        scope_hash=scope_hash,
        manifest_hash=run.manifest_hash,
        run_hash=run.run_hash,
        prior_receipt_hash=requested_receipt.receipt_hash,
        remote_list_performed=True,
        **{field: False for field in _DANGEROUS_SAFETY_FIELDS},
    )
    completed_receipt.receipt_hash = _receipt_hash(completed_receipt)
    db.add(completed_receipt)
    db.flush()
    _ensure_discovery_integrity(db, profile=profile, run=run)
    return run, "completed"


def get_external_document_source_discovery(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    run_id: UUID,
) -> ExternalDocumentSourceDiscoveryRun:
    profile = get_external_document_source_profile(db, organization_id=organization_id, profile_id=profile_id)
    run = _get_run(db, organization_id=organization_id, profile_id=profile_id, run_id=run_id)
    _ensure_discovery_integrity(db, profile=profile, run=run)
    return run


def list_external_document_source_discovery_items(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    run_id: UUID,
) -> list[ExternalDocumentSourceDiscoveryItem]:
    run = get_external_document_source_discovery(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        run_id=run_id,
    )
    return _run_items(db, run)


def list_external_document_source_discovery_receipts(
    db: Session,
    *,
    organization_id: UUID,
    profile_id: UUID,
    run_id: UUID,
) -> list[ExternalDocumentSourceDiscoveryReceipt]:
    run = get_external_document_source_discovery(
        db,
        organization_id=organization_id,
        profile_id=profile_id,
        run_id=run_id,
    )
    return _run_receipts(db, run)
