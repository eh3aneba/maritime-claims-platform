from __future__ import annotations

import json
import re
import secrets
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
from app.modules.correspondence.models import (
    ClaimCorrespondence, CorrespondenceChannel, CorrespondenceDirection, CorrespondenceKind,
    CorrespondenceStatus,
)
from app.modules.correspondence.state_identity import bind_initial_correspondence_state
from app.modules.email_ingestion.models import (
    EmailAdapterRun, EmailAttachmentManifest, EmailConnectionStatus, EmailIngestionConnection,
    EmailMessageStatus, EmailProviderAdapter, EmailRetentionRun, IngestedEmailMessage,
)
from app.modules.email_ingestion.schemas import (
    EmailAdapterCreate, EmailAdapterRunCreate, EmailConnectionCreate, EmailReview,
    NormalizedEmailInput,
)
from app.modules.users.models import User

CLAIM_REFERENCE = re.compile(r"\bMCRI-HM-\d{4}-\d{4}\b", re.IGNORECASE)
ADAPTER_PERMISSIONS = {"messages.read.allowed_folder", "attachments.metadata.read"}


def _audit(db: Session, *, organization_id: UUID, user_id: UUID | None, action: str,
           entity_type: str, entity_id: UUID, values: dict, details: str | None = None) -> None:
    write_audit_log(db, organization_id=organization_id, user_id=user_id, action=action,
                    entity_type=entity_type, entity_id=entity_id, new_values=values, details=details)


def _attachments(db: Session, message_id: UUID) -> list[EmailAttachmentManifest]:
    return list(db.scalars(select(EmailAttachmentManifest).where(
        EmailAttachmentManifest.message_id == message_id,
    ).order_by(EmailAttachmentManifest.created_at.asc())))


def message_response(db: Session, item: IngestedEmailMessage) -> dict:
    return {**{column.name: getattr(item, column.name) for column in item.__table__.columns
               if column.name not in {"organization_id", "linked_by_id", "updated_at"}},
            "attachments": _attachments(db, item.id)}


def list_inbox(db: Session, organization_id: UUID) -> tuple[list[EmailIngestionConnection], list[dict]]:
    connections = list(db.scalars(select(EmailIngestionConnection).where(
        EmailIngestionConnection.organization_id == organization_id,
    ).order_by(EmailIngestionConnection.created_at.desc())))
    messages = list(db.scalars(select(IngestedEmailMessage).where(
        IngestedEmailMessage.organization_id == organization_id,
    ).order_by(IngestedEmailMessage.received_at.desc())))
    return connections, [message_response(db, item) for item in messages]


def create_connection(db: Session, user: User, payload: EmailConnectionCreate) -> tuple[EmailIngestionConnection, str]:
    if not payload.consent_confirmed:
        raise HTTPException(422, "Explicit mailbox-owner/organization consent is required")
    token = secrets.token_urlsafe(32)
    item = EmailIngestionConnection(
        organization_id=user.organization_id, created_by_id=user.id,
        provider_label=payload.provider_label.strip(), mailbox_address=str(payload.mailbox_address).lower(),
        status=EmailConnectionStatus.ACTIVE, consent_basis=payload.consent_basis.strip(),
        consent_confirmed_at=datetime.now(UTC), retention_days=payload.retention_days,
        token_hash=sha256(token.encode()).hexdigest(),
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This mailbox already has an ingestion connection") from exc
    _audit(db, organization_id=item.organization_id, user_id=user.id, action="CREATE_EMAIL_INGESTION_CONNECTION",
           entity_type="email_ingestion_connection", entity_id=item.id,
           values={"provider_label": item.provider_label, "mailbox_address": item.mailbox_address,
                   "retention_days": item.retention_days, "status": item.status.value},
           details="Consent recorded. Ingestion token is displayed once and only its SHA-256 hash is stored.")
    db.commit(); db.refresh(item)
    return item, token


def get_connection(db: Session, organization_id: UUID, connection_id: UUID) -> EmailIngestionConnection:
    item = db.scalar(select(EmailIngestionConnection).where(
        EmailIngestionConnection.id == connection_id,
        EmailIngestionConnection.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Email ingestion connection not found")
    return item


def transition_connection(db: Session, item: EmailIngestionConnection, user: User, action: str, note: str) -> EmailIngestionConnection:
    allowed = {"suspend": EmailConnectionStatus.SUSPENDED, "reactivate": EmailConnectionStatus.ACTIVE, "revoke": EmailConnectionStatus.REVOKED}
    if action not in allowed:
        raise HTTPException(422, "Action must be suspend, reactivate or revoke")
    if item.status == EmailConnectionStatus.REVOKED:
        raise HTTPException(409, "A revoked connection cannot be changed or reactivated")
    item.status = allowed[action]
    if item.status == EmailConnectionStatus.REVOKED:
        item.revoked_at = datetime.now(UTC)
    _audit(db, organization_id=item.organization_id, user_id=user.id,
           action=f"{action.upper()}_EMAIL_INGESTION_CONNECTION", entity_type="email_ingestion_connection",
           entity_id=item.id, values={"status": item.status.value}, details=note.strip())
    db.commit(); db.refresh(item)
    return item


def _canonical(payload: NormalizedEmailInput) -> str:
    value = payload.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def ingest_email(db: Session, connection_id: UUID, token: str | None, payload: NormalizedEmailInput) -> IngestedEmailMessage:
    connection = db.get(EmailIngestionConnection, connection_id)
    supplied_hash = sha256((token or "").encode()).hexdigest()
    if connection is None or not token or not compare_digest(supplied_hash, connection.token_hash):
        raise HTTPException(401, "Invalid email ingestion token")
    if connection.status != EmailConnectionStatus.ACTIVE:
        raise HTTPException(409, "Email ingestion connection is not active")
    existing = db.scalar(select(IngestedEmailMessage).where(
        IngestedEmailMessage.connection_id == connection.id,
        IngestedEmailMessage.provider_message_id == payload.provider_message_id,
    ))
    if existing is not None:
        return existing
    received_at = payload.received_at if payload.received_at.tzinfo else payload.received_at.replace(tzinfo=UTC)
    text = f"{payload.subject}\n{payload.body_text}"
    match = CLAIM_REFERENCE.search(text)
    suggested = db.scalar(select(Claim).where(
        Claim.organization_id == connection.organization_id,
        Claim.claim_reference == match.group(0).upper(),
    )) if match else None
    now = datetime.now(UTC)
    item = IngestedEmailMessage(
        organization_id=connection.organization_id, connection_id=connection.id,
        provider_message_id=payload.provider_message_id, internet_message_id=payload.internet_message_id,
        sender=payload.sender.strip(), recipients=[value.strip() for value in payload.recipients],
        cc=[value.strip() for value in payload.cc], subject=payload.subject.strip(),
        body_text=payload.body_text, status=EmailMessageStatus.PENDING_REVIEW,
        content_hash=sha256(_canonical(payload).encode()).hexdigest(), received_at=received_at,
        retain_until=now + timedelta(days=connection.retention_days),
        suggested_claim_id=suggested.id if suggested else None,
    )
    db.add(item); db.flush()
    for attachment in payload.attachments:
        db.add(EmailAttachmentManifest(
            organization_id=connection.organization_id, message_id=item.id,
            filename=attachment.filename, mime_type=attachment.mime_type,
            file_size_bytes=attachment.file_size_bytes,
            provider_sha256=attachment.sha256.lower() if attachment.sha256 else None,
            admission_status="blocked_pending_quarantine",
        ))
    connection.last_ingested_at = now
    _audit(db, organization_id=item.organization_id, user_id=None, action="INGEST_EMAIL_PENDING_REVIEW",
           entity_type="ingested_email_message", entity_id=item.id,
           values={"provider_message_id": item.provider_message_id,
                   "suggested_claim_id": str(item.suggested_claim_id) if item.suggested_claim_id else None,
                   "attachment_count": len(payload.attachments), "retain_until": item.retain_until.isoformat()},
           details="Normalized inbound message only. Claim linking requires human confirmation; attachment bytes were not accepted.")
    db.commit(); db.refresh(item)
    return item


def get_message(db: Session, organization_id: UUID, message_id: UUID) -> IngestedEmailMessage:
    item = db.scalar(select(IngestedEmailMessage).where(
        IngestedEmailMessage.id == message_id,
        IngestedEmailMessage.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Ingested email not found")
    return item


def review_email(db: Session, item: IngestedEmailMessage, user: User, payload: EmailReview) -> IngestedEmailMessage:
    if item.status != EmailMessageStatus.PENDING_REVIEW:
        raise HTTPException(409, "Only pending email can be reviewed")
    item.review_note = payload.note.strip(); item.reviewed_at = datetime.now(UTC); item.linked_by_id = user.id
    if payload.action == "reject":
        item.status = EmailMessageStatus.REJECTED
        _audit(db, organization_id=item.organization_id, user_id=user.id, action="REJECT_INGESTED_EMAIL",
               entity_type="ingested_email_message", entity_id=item.id, values={"status": item.status.value}, details=item.review_note)
    else:
        claim = db.scalar(select(Claim).where(
            Claim.id == payload.claim_id, Claim.organization_id == item.organization_id,
        ))
        if claim is None:
            raise HTTPException(404, "Claim not found")
        correspondence = ClaimCorrespondence(
            organization_id=item.organization_id, claim_id=claim.id, created_by_id=user.id,
            direction=CorrespondenceDirection.INBOUND, kind=CorrespondenceKind.GENERAL,
            status=CorrespondenceStatus.RECEIVED_EXTERNAL, sensitivity=payload.sensitivity,
            channel=CorrespondenceChannel.EMAIL, sender_label=item.sender[:180],
            recipient_label=", ".join(item.recipients)[:180] or None, subject=item.subject[:240],
            body=item.body_text or "(No plain-text body supplied)", requirement_ids=[],
            external_reference=(item.internet_message_id or item.provider_message_id)[:240], occurred_at=item.received_at,
            state_fingerprint="0" * 64, state_version=1,
        )
        bind_initial_correspondence_state(correspondence)
        db.add(correspondence); db.flush()
        item.status = EmailMessageStatus.LINKED; item.linked_claim_id = claim.id
        item.correspondence_id = correspondence.id
        item.body_text = f"[Promoted to correspondence {correspondence.id}; staging body redacted]"
        _audit(db, organization_id=item.organization_id, user_id=user.id, action="LINK_INGESTED_EMAIL_TO_CLAIM",
               entity_type="ingested_email_message", entity_id=item.id,
               values={"status": item.status.value, "claim_id": str(claim.id), "correspondence_id": str(correspondence.id),
                       "correspondence_state_fingerprint": correspondence.state_fingerprint,
                       "correspondence_state_version": correspondence.state_version},
               details="Human-confirmed claim link. Attachment manifests remain blocked pending quarantine admission.")
    db.commit(); db.refresh(item)
    return item


def expire_due(db: Session, user: User) -> int:
    now = datetime.now(UTC)
    items = list(db.scalars(select(IngestedEmailMessage).where(
        IngestedEmailMessage.organization_id == user.organization_id,
        IngestedEmailMessage.retain_until <= now,
        IngestedEmailMessage.status != EmailMessageStatus.EXPIRED,
    )))
    for item in items:
        item.status = EmailMessageStatus.EXPIRED; item.sender = "[expired]"; item.recipients = []
        item.cc = []; item.subject = "[expired by retention policy]"; item.body_text = "[expired]"
        for attachment in _attachments(db, item.id):
            attachment.filename = "[expired]"; attachment.admission_status = "expired_manifest"
        _audit(db, organization_id=item.organization_id, user_id=user.id, action="EXPIRE_INGESTED_EMAIL",
               entity_type="ingested_email_message", entity_id=item.id,
               values={"status": item.status.value, "retain_until": item.retain_until.isoformat()},
               details="Staging content redacted under the configured retention policy; any separately filed claim correspondence remains.")
    db.commit()
    return len(items)


def list_adapter_operations(db: Session, organization_id: UUID):
    adapters = list(db.scalars(select(EmailProviderAdapter).where(
        EmailProviderAdapter.organization_id == organization_id,
    ).order_by(EmailProviderAdapter.created_at.desc())))
    runs = list(db.scalars(select(EmailAdapterRun).where(
        EmailAdapterRun.organization_id == organization_id,
    ).order_by(EmailAdapterRun.started_at.desc()).limit(50)))
    retention_runs = list(db.scalars(select(EmailRetentionRun).where(
        EmailRetentionRun.organization_id == organization_id,
    ).order_by(EmailRetentionRun.started_at.desc()).limit(25)))
    return adapters, runs, retention_runs


def create_adapter(db: Session, user: User, payload: EmailAdapterCreate) -> EmailProviderAdapter:
    connection = get_connection(db, user.organization_id, payload.connection_id)
    if connection.status != EmailConnectionStatus.ACTIVE:
        raise HTTPException(409, "Adapter requires an active consented connection")
    permissions = set(payload.permission_manifest)
    if not permissions or not permissions.issubset(ADAPTER_PERMISSIONS):
        raise HTTPException(422, "Only selected-folder read and attachment-metadata permissions are allowed")
    item = EmailProviderAdapter(
        organization_id=user.organization_id, connection_id=connection.id, created_by_id=user.id,
        provider_kind=payload.provider_kind, display_name=payload.display_name.strip(),
        credential_reference=payload.credential_reference, allowed_folder=payload.allowed_folder.strip(),
        permission_manifest=sorted(permissions), status="active", batch_limit=payload.batch_limit,
        retention_schedule_enabled=payload.retention_schedule_enabled,
        next_sync_at=datetime.now(UTC),
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This connection already has a provider adapter") from exc
    _audit(db, organization_id=item.organization_id, user_id=user.id, action="CREATE_EMAIL_PROVIDER_ADAPTER",
           entity_type="email_provider_adapter", entity_id=item.id,
           values={"provider_kind": item.provider_kind, "allowed_folder": item.allowed_folder,
                   "permission_manifest": item.permission_manifest, "credential_reference": item.credential_reference},
           details="Credential reference only; no OAuth access or refresh token stored.")
    db.commit(); db.refresh(item)
    return item


def get_adapter(db: Session, organization_id: UUID, adapter_id: UUID) -> EmailProviderAdapter:
    item = db.scalar(select(EmailProviderAdapter).where(
        EmailProviderAdapter.id == adapter_id, EmailProviderAdapter.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Email provider adapter not found")
    return item


def transition_adapter(db: Session, item: EmailProviderAdapter, user: User, action: str, note: str) -> EmailProviderAdapter:
    if action not in {"suspend", "reactivate", "revoke"}:
        raise HTTPException(422, "Action must be suspend, reactivate or revoke")
    if item.status == "revoked":
        raise HTTPException(409, "A revoked adapter cannot be changed")
    connection = get_connection(db, user.organization_id, item.connection_id)
    if action == "reactivate" and connection.status != EmailConnectionStatus.ACTIVE:
        raise HTTPException(409, "The consented connection must be active before reactivation")
    item.status = {"suspend": "suspended", "reactivate": "active", "revoke": "revoked"}[action]
    if item.status == "revoked":
        item.revoked_at = datetime.now(UTC); item.next_sync_at = None
    _audit(db, organization_id=item.organization_id, user_id=user.id,
           action=f"{action.upper()}_EMAIL_PROVIDER_ADAPTER", entity_type="email_provider_adapter",
           entity_id=item.id, values={"status": item.status}, details=note.strip())
    db.commit(); db.refresh(item)
    return item


def record_adapter_run(db: Session, item: EmailProviderAdapter, user: User,
                       payload: EmailAdapterRunCreate) -> EmailAdapterRun:
    connection = get_connection(db, user.organization_id, item.connection_id)
    if item.status != "active" or connection.status != EmailConnectionStatus.ACTIVE:
        raise HTTPException(409, "Adapter and consented connection must both be active")
    if payload.messages_seen > item.batch_limit or payload.messages_ingested > payload.messages_seen:
        raise HTTPException(422, "Run counts exceed the bounded adapter batch")
    existing = db.scalar(select(EmailAdapterRun).where(
        EmailAdapterRun.adapter_id == item.id,
        EmailAdapterRun.idempotency_key == payload.idempotency_key,
    ))
    if existing is not None:
        return existing
    now = datetime.now(UTC)
    checkpoint_hash = sha256(payload.provider_checkpoint.encode()).hexdigest() if payload.provider_checkpoint else None
    run = EmailAdapterRun(
        organization_id=item.organization_id, adapter_id=item.id, initiated_by_id=user.id,
        idempotency_key=payload.idempotency_key, trigger=payload.trigger,
        status="failed" if payload.failure_summary else "succeeded",
        messages_seen=payload.messages_seen, messages_ingested=payload.messages_ingested,
        checkpoint_hash=checkpoint_hash, failure_summary=payload.failure_summary,
        started_at=now, finished_at=now,
    )
    db.add(run); db.flush()
    item.last_sync_at = now; item.next_sync_at = now + timedelta(minutes=15)
    if checkpoint_hash:
        item.checkpoint_hash = checkpoint_hash
    _audit(db, organization_id=item.organization_id, user_id=user.id, action="RECORD_EMAIL_ADAPTER_RUN",
           entity_type="email_adapter_run", entity_id=run.id,
           values={"status": run.status, "messages_seen": run.messages_seen,
                   "messages_ingested": run.messages_ingested, "trigger": run.trigger},
           details="Provider cursor stored as a one-way hash; message ingestion remains on the normalized gateway.")
    db.commit(); db.refresh(run)
    return run


def run_retention(db: Session, user: User, idempotency_key: str) -> EmailRetentionRun:
    existing = db.scalar(select(EmailRetentionRun).where(
        EmailRetentionRun.organization_id == user.organization_id,
        EmailRetentionRun.idempotency_key == idempotency_key,
    ))
    if existing is not None:
        return existing
    started = datetime.now(UTC)
    count = expire_due(db, user)
    item = EmailRetentionRun(
        organization_id=user.organization_id, initiated_by_id=user.id,
        idempotency_key=idempotency_key, expired_count=count,
        started_at=started, finished_at=datetime.now(UTC),
    )
    db.add(item); db.flush()
    _audit(db, organization_id=user.organization_id, user_id=user.id,
           action="RUN_EMAIL_RETENTION_SCHEDULE", entity_type="email_retention_run",
           entity_id=item.id, values={"expired_count": count, "idempotency_key": idempotency_key},
           details="Idempotent tenant-scoped retention execution.")
    db.commit(); db.refresh(item)
    return item
