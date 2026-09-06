from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.email_ingestion.models import (
    EmailAdapterRun,
    EmailConnectionStatus,
    EmailIngestionConnection,
    EmailProviderAdapter,
)
from app.modules.email_ingestion.provider_checkpoint_handoff import (
    list_provider_reconciliation_with_handoff,
)
from app.modules.email_ingestion.provider_credentials import (
    CredentialReferenceError,
    ProviderCredentialMetadata,
    inspect_credential_reference,
)
from app.modules.email_ingestion.provider_live_activation import invalidate_live_provider_activation
from app.modules.email_ingestion.schemas import CredentialReferenceRotationRequest
from app.modules.users.models import User

_PULL_KINDS = {"microsoft_graph", "gmail_api"}


def _pending_checkpoint_run(db: Session, adapter_id: UUID) -> EmailAdapterRun | None:
    return db.scalar(
        select(EmailAdapterRun)
        .where(
            EmailAdapterRun.adapter_id == adapter_id,
            EmailAdapterRun.checkpoint_handoff_status == "pending",
        )
        .order_by(EmailAdapterRun.started_at.desc())
        .limit(1)
    )


def _connection_for_adapter(
    db: Session,
    adapter: EmailProviderAdapter,
) -> EmailIngestionConnection | None:
    return db.scalar(
        select(EmailIngestionConnection).where(
            EmailIngestionConnection.id == adapter.connection_id,
            EmailIngestionConnection.organization_id == adapter.organization_id,
        )
    )


def _safe_metadata(reference: str) -> ProviderCredentialMetadata:
    try:
        return inspect_credential_reference(reference)
    except CredentialReferenceError:
        return ProviderCredentialMetadata(
            backend="invalid",
            reference_configured=bool(reference),
            resolver_available=False,
        )


def _metadata_dict(adapter: EmailProviderAdapter) -> dict:
    metadata = _safe_metadata(adapter.credential_reference)
    return {
        "credential_backend": metadata.backend,
        "credential_reference_configured": metadata.reference_configured,
        "credential_resolver_available": metadata.resolver_available,
    }


def rotate_provider_credential_reference(
    db: Session,
    *,
    adapter: EmailProviderAdapter,
    user: User,
    payload: CredentialReferenceRotationRequest,
) -> dict:
    if not payload.confirm_rotation:
        raise HTTPException(422, "Explicit credential reference rotation confirmation is required")
    reason = payload.reason.strip()
    if len(reason) < 20:
        raise HTTPException(422, "Credential rotation reason must contain at least 20 characters")
    if adapter.organization_id != user.organization_id:
        raise HTTPException(404, "Email provider adapter not found")
    if adapter.status == "revoked":
        raise HTTPException(409, "A revoked provider adapter cannot rotate credentials")
    if _pending_checkpoint_run(db, adapter.id) is not None:
        raise HTTPException(
            409,
            "Pending checkpoint handoff must be acknowledged or abandoned before credential rotation",
        )

    try:
        new_metadata = inspect_credential_reference(payload.credential_reference)
    except CredentialReferenceError as exc:
        raise HTTPException(422, "Credential reference is invalid") from exc
    old_metadata = _safe_metadata(adapter.credential_reference)

    if payload.credential_reference == adapter.credential_reference:
        raise HTTPException(409, "Credential reference is unchanged")

    previous_checkpoint_hash = adapter.checkpoint_hash
    was_live = bool(adapter.live_execution_enabled)
    now = datetime.now(UTC)
    invalidate_live_provider_activation(adapter)
    adapter.credential_reference = payload.credential_reference
    adapter.credential_reference_version = max(adapter.credential_reference_version or 1, 1) + 1
    adapter.credential_reference_changed_at = now

    write_audit_log(
        db,
        organization_id=adapter.organization_id,
        user_id=user.id,
        action="ROTATE_EMAIL_PROVIDER_CREDENTIAL_REFERENCE",
        entity_type="email_provider_adapter",
        entity_id=adapter.id,
        new_values={
            "credential_backend_before": old_metadata.backend,
            "credential_backend_after": new_metadata.backend,
            "credential_reference_version": adapter.credential_reference_version,
            "credential_reference_changed": True,
            "operator_reason_supplied": True,
            "checkpoint_preserved": adapter.checkpoint_hash == previous_checkpoint_hash,
            "resolver_available": new_metadata.resolver_available,
            "live_execution_invalidated": was_live,
        },
        details=(
            "External credential reference rotated by explicit operator action and live provider authority cleared. "
            "Credential locators, resolved credential values, checkpoint values/hashes and operator reason text are excluded from audit metadata."
        ),
    )
    db.commit()
    db.refresh(adapter)
    return {
        "adapter_id": adapter.id,
        "credential_backend": new_metadata.backend,
        "credential_reference_version": adapter.credential_reference_version,
        "credential_reference_changed_at": adapter.credential_reference_changed_at,
        "credential_resolver_available": new_metadata.resolver_available,
        "checkpoint_preserved": adapter.checkpoint_hash == previous_checkpoint_hash,
        "next_sync_at": adapter.next_sync_at,
        "live_execution_enabled": adapter.live_execution_enabled,
    }


def list_provider_reconciliation_with_credentials(db: Session, user: User) -> dict:
    result = list_provider_reconciliation_with_handoff(db, user)
    for item in result["items"]:
        adapter = db.get(EmailProviderAdapter, UUID(item["adapter_id"]))
        if adapter is None or adapter.organization_id != user.organization_id:
            continue
        item.update(_metadata_dict(adapter))
        item["credential_reference_version"] = adapter.credential_reference_version
        item["credential_reference_changed_at"] = adapter.credential_reference_changed_at
        item["live_execution_enabled"] = adapter.live_execution_enabled
        item["live_execution_enabled_at"] = adapter.live_execution_enabled_at
        if adapter.provider_kind in _PULL_KINDS and adapter.status == "active":
            connection = _connection_for_adapter(db, adapter)
            if connection is not None and connection.status == EmailConnectionStatus.ACTIVE and not adapter.live_execution_enabled:
                metadata = _safe_metadata(adapter.credential_reference)
                if metadata.backend == "invalid":
                    blocker = "credential_reference_invalid"
                elif not metadata.resolver_available:
                    blocker = "credential_resolver_unavailable"
                else:
                    blocker = "operator_activation_required"
                item["operational_state"] = "activation_required"
                item["activation_blocker"] = blocker
                item["next_sync_at"] = None
            else:
                item["activation_blocker"] = None
        else:
            item["activation_blocker"] = None
    return result
