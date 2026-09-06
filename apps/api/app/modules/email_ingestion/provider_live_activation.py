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
from app.modules.email_ingestion.provider_credentials import (
    CredentialReferenceError,
    inspect_credential_reference,
    resolve_credential_reference,
)
from app.modules.email_ingestion.schemas import LiveProviderActivationRequest
from app.modules.users.models import User

_PULL_KINDS = {"microsoft_graph", "gmail_api"}
_REQUIRED_PERMISSION = "messages.read.allowed_folder"


def invalidate_live_provider_activation(adapter: EmailProviderAdapter) -> None:
    """Clear live-network authority without touching provider cursor or claim state."""
    if adapter.provider_kind not in _PULL_KINDS:
        return
    adapter.live_execution_enabled = False
    adapter.live_execution_enabled_at = None
    adapter.live_execution_enabled_by_id = None
    adapter.next_sync_at = None


def invalidate_connection_live_provider(
    db: Session,
    *,
    organization_id: UUID,
    connection_id: UUID,
) -> None:
    adapter = db.scalar(
        select(EmailProviderAdapter).where(
            EmailProviderAdapter.connection_id == connection_id,
            EmailProviderAdapter.organization_id == organization_id,
        )
    )
    if adapter is not None:
        invalidate_live_provider_activation(adapter)


def require_live_provider_activation(adapter: EmailProviderAdapter) -> None:
    if adapter.provider_kind in _PULL_KINDS and not adapter.live_execution_enabled:
        raise HTTPException(409, "Live provider activation is required before provider network access")


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


def activate_live_provider(
    db: Session,
    *,
    adapter: EmailProviderAdapter,
    user: User,
    payload: LiveProviderActivationRequest,
) -> dict:
    if not payload.confirm_activation:
        raise HTTPException(422, "Explicit live provider activation confirmation is required")
    reason = payload.reason.strip()
    if len(reason) < 20:
        raise HTTPException(422, "Live provider activation reason must contain at least 20 characters")
    if adapter.organization_id != user.organization_id:
        raise HTTPException(404, "Email provider adapter not found")
    if adapter.provider_kind not in _PULL_KINDS:
        raise HTTPException(409, "This adapter kind has no live pull activation authority")
    if adapter.status != "active":
        raise HTTPException(409, "Provider adapter must be active before live activation")
    connection = _connection_for_adapter(db, adapter)
    if connection is None:
        raise HTTPException(404, "Email ingestion connection not found")
    if connection.status != EmailConnectionStatus.ACTIVE:
        raise HTTPException(409, "Consented connection must be active before live activation")
    if _REQUIRED_PERMISSION not in set(adapter.permission_manifest):
        raise HTTPException(409, "Live provider activation requires selected-folder message read permission")
    if _pending_checkpoint_run(db, adapter.id) is not None:
        raise HTTPException(
            409,
            "Pending checkpoint handoff must be acknowledged or abandoned before live activation",
        )
    if adapter.live_execution_enabled:
        raise HTTPException(409, "Live provider execution is already activated")

    try:
        metadata = inspect_credential_reference(adapter.credential_reference)
    except CredentialReferenceError as exc:
        raise HTTPException(409, "Provider credential reference is invalid") from exc
    if not metadata.resolver_available:
        raise HTTPException(409, "Provider credential resolver is unavailable")
    try:
        resolved = resolve_credential_reference(adapter.credential_reference)
    except CredentialReferenceError as exc:
        if exc.code == "credential_reference_unresolved":
            raise HTTPException(409, "Provider credential reference cannot be resolved") from exc
        if exc.code == "credential_resolver_unavailable":
            raise HTTPException(409, "Provider credential resolver is unavailable") from exc
        raise HTTPException(409, "Provider credential reference is invalid") from exc
    del resolved

    now = datetime.now(UTC)
    adapter.live_execution_enabled = True
    adapter.live_execution_enabled_at = now
    adapter.live_execution_enabled_by_id = user.id
    adapter.next_sync_at = now
    write_audit_log(
        db,
        organization_id=adapter.organization_id,
        user_id=user.id,
        action="ACTIVATE_EMAIL_PROVIDER_LIVE_EXECUTION",
        entity_type="email_provider_adapter",
        entity_id=adapter.id,
        new_values={
            "provider_kind": adapter.provider_kind,
            "live_execution_enabled": True,
            "credential_backend": metadata.backend,
            "credential_reference_version": adapter.credential_reference_version,
            "credential_resolver_available": metadata.resolver_available,
            "checkpoint_present": bool(adapter.checkpoint_hash),
            "operator_reason_supplied": True,
        },
        details=(
            "Local content-free provider readiness preflight completed before live network authority. "
            "No provider call was made; credential locator/value, operator reason, checkpoint values/hashes and provider content are excluded from audit metadata."
        ),
    )
    db.commit()
    db.refresh(adapter)
    return {
        "adapter_id": adapter.id,
        "provider_kind": adapter.provider_kind,
        "live_execution_enabled": adapter.live_execution_enabled,
        "live_execution_enabled_at": adapter.live_execution_enabled_at,
        "credential_backend": metadata.backend,
        "credential_reference_version": adapter.credential_reference_version,
        "checkpoint_present": bool(adapter.checkpoint_hash),
        "next_sync_at": adapter.next_sync_at,
    }
