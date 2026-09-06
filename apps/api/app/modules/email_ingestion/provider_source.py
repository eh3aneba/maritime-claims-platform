from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from hmac import compare_digest
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.email_ingestion.models import (
    EmailAttachmentManifest,
    EmailConnectionStatus,
    EmailIngestionConnection,
    EmailMessageStatus,
    EmailProviderAdapter,
    IngestedEmailMessage,
)
from app.modules.email_ingestion.schemas import NormalizedEmailInput

CLAIM_REFERENCE = re.compile(r"\bMCRI-HM-\d{4}-\d{4}\b", re.IGNORECASE)


def _canonical(payload: NormalizedEmailInput) -> str:
    return json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def _content_hash(payload: NormalizedEmailInput) -> str:
    return sha256(_canonical(payload).encode()).hexdigest()


def _authorize_connection(
    db: Session,
    connection_id: UUID,
    token: str | None,
) -> EmailIngestionConnection:
    connection = db.get(EmailIngestionConnection, connection_id)
    supplied_hash = sha256((token or "").encode()).hexdigest()
    if connection is None or not token or not compare_digest(supplied_hash, connection.token_hash):
        raise HTTPException(401, "Invalid email ingestion token")
    if connection.status != EmailConnectionStatus.ACTIVE:
        raise HTTPException(409, "Email ingestion connection is not active")
    return connection


def _audit_replay_conflict(
    db: Session,
    *,
    existing: IngestedEmailMessage,
    adapter_id: UUID | None,
    reason: str,
) -> None:
    # Deliberately content-free: do not persist subject/body/sender/recipient data or the
    # incoming payload hash in conflict telemetry/audit metadata.
    write_audit_log(
        db,
        organization_id=existing.organization_id,
        user_id=None,
        action="REJECT_EMAIL_PROVIDER_REPLAY",
        entity_type="ingested_email_message",
        entity_id=existing.id,
        new_values={
            "reason": reason,
            "connection_id": str(existing.connection_id),
            "existing_adapter_id": str(existing.adapter_id) if existing.adapter_id else None,
            "incoming_adapter_id": str(adapter_id) if adapter_id else None,
        },
        details="Provider replay rejected before claim linking or correspondence promotion.",
    )
    db.commit()


def _resolve_existing_replay(
    db: Session,
    *,
    existing: IngestedEmailMessage,
    incoming_hash: str,
    adapter_id: UUID | None,
) -> IngestedEmailMessage:
    if existing.content_hash != incoming_hash:
        _audit_replay_conflict(
            db,
            existing=existing,
            adapter_id=adapter_id,
            reason="content_hash_mismatch",
        )
        raise HTTPException(409, "Provider message replay content mismatch")
    if existing.adapter_id != adapter_id:
        _audit_replay_conflict(
            db,
            existing=existing,
            adapter_id=adapter_id,
            reason="provider_source_mismatch",
        )
        raise HTTPException(409, "Provider message replay source mismatch")
    return existing


def _existing_message(
    db: Session,
    *,
    connection_id: UUID,
    provider_message_id: str,
) -> IngestedEmailMessage | None:
    return db.scalar(
        select(IngestedEmailMessage).where(
            IngestedEmailMessage.connection_id == connection_id,
            IngestedEmailMessage.provider_message_id == provider_message_id,
        )
    )


def _stage_email(
    db: Session,
    *,
    connection: EmailIngestionConnection,
    adapter: EmailProviderAdapter | None,
    payload: NormalizedEmailInput,
) -> IngestedEmailMessage:
    incoming_hash = _content_hash(payload)
    existing = _existing_message(
        db,
        connection_id=connection.id,
        provider_message_id=payload.provider_message_id,
    )
    if existing is not None:
        return _resolve_existing_replay(
            db,
            existing=existing,
            incoming_hash=incoming_hash,
            adapter_id=adapter.id if adapter else None,
        )

    received_at = payload.received_at if payload.received_at.tzinfo else payload.received_at.replace(tzinfo=UTC)
    text = f"{payload.subject}\n{payload.body_text}"
    match = CLAIM_REFERENCE.search(text)
    suggested = (
        db.scalar(
            select(Claim).where(
                Claim.organization_id == connection.organization_id,
                Claim.claim_reference == match.group(0).upper(),
            )
        )
        if match
        else None
    )
    now = datetime.now(UTC)
    item = IngestedEmailMessage(
        organization_id=connection.organization_id,
        connection_id=connection.id,
        adapter_id=adapter.id if adapter else None,
        provider_message_id=payload.provider_message_id,
        internet_message_id=payload.internet_message_id,
        sender=payload.sender.strip(),
        recipients=[value.strip() for value in payload.recipients],
        cc=[value.strip() for value in payload.cc],
        subject=payload.subject.strip(),
        body_text=payload.body_text,
        status=EmailMessageStatus.PENDING_REVIEW,
        content_hash=incoming_hash,
        received_at=received_at,
        retain_until=now + timedelta(days=connection.retention_days),
        suggested_claim_id=suggested.id if suggested else None,
    )

    savepoint = db.begin_nested()
    try:
        db.add(item)
        db.flush()
        savepoint.commit()
    except IntegrityError:
        savepoint.rollback()
        db.expire_all()
        concurrent = _existing_message(
            db,
            connection_id=connection.id,
            provider_message_id=payload.provider_message_id,
        )
        if concurrent is None:
            raise
        return _resolve_existing_replay(
            db,
            existing=concurrent,
            incoming_hash=incoming_hash,
            adapter_id=adapter.id if adapter else None,
        )

    for attachment in payload.attachments:
        db.add(
            EmailAttachmentManifest(
                organization_id=connection.organization_id,
                message_id=item.id,
                filename=attachment.filename,
                mime_type=attachment.mime_type,
                file_size_bytes=attachment.file_size_bytes,
                provider_sha256=attachment.sha256.lower() if attachment.sha256 else None,
                admission_status="blocked_pending_quarantine",
            )
        )
    connection.last_ingested_at = now
    write_audit_log(
        db,
        organization_id=item.organization_id,
        user_id=None,
        action="INGEST_EMAIL_PENDING_REVIEW",
        entity_type="ingested_email_message",
        entity_id=item.id,
        new_values={
            "source_mode": "provider_adapter" if adapter else "legacy_connection",
            "adapter_id": str(adapter.id) if adapter else None,
            "attachment_count": len(payload.attachments),
            "retain_until": item.retain_until.isoformat(),
        },
        details="Normalized inbound message staged only. Human confirmation is required for claim linking and Correspondence promotion; attachment bytes were not accepted.",
    )
    db.commit()
    db.refresh(item)
    return item


def ingest_legacy_webhook(
    db: Session,
    connection_id: UUID,
    token: str | None,
    payload: NormalizedEmailInput,
) -> IngestedEmailMessage:
    connection = _authorize_connection(db, connection_id, token)
    configured_adapter = db.scalar(
        select(EmailProviderAdapter).where(EmailProviderAdapter.connection_id == connection.id)
    )
    if configured_adapter is not None:
        raise HTTPException(
            409,
            "This connection is provider-bound; use its adapter-specific intake path",
        )
    return _stage_email(db, connection=connection, adapter=None, payload=payload)


def ingest_provider_webhook(
    db: Session,
    adapter_id: UUID,
    token: str | None,
    payload: NormalizedEmailInput,
) -> IngestedEmailMessage:
    adapter = db.get(EmailProviderAdapter, adapter_id)
    if adapter is None:
        raise HTTPException(401, "Invalid email provider source")
    connection = _authorize_connection(db, adapter.connection_id, token)
    if adapter.organization_id != connection.organization_id:
        raise HTTPException(409, "Email provider source is not bound to this connection")
    if adapter.status != "active":
        raise HTTPException(409, "Email provider adapter is not active")
    if adapter.provider_kind != "provider_webhook":
        raise HTTPException(
            409,
            "This adapter kind has no normalized webhook execution authority",
        )
    return _stage_email(db, connection=connection, adapter=adapter, payload=payload)
