from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.email_ingestion.models import (
    EmailAttachmentManifest,
    EmailMessageStatus,
    EmailRetentionRun,
    IngestedEmailMessage,
)
from app.modules.email_ingestion.provider_attachment_acquisition import (
    purge_provider_attachment_for_retention,
)
from app.modules.email_ingestion.service import expire_due, run_retention
from app.modules.users.models import User


def _purge_expired_provider_attachment_state(db: Session, user: User) -> None:
    manifests = list(
        db.scalars(
            select(EmailAttachmentManifest)
            .join(IngestedEmailMessage, IngestedEmailMessage.id == EmailAttachmentManifest.message_id)
            .where(
                EmailAttachmentManifest.organization_id == user.organization_id,
                IngestedEmailMessage.organization_id == user.organization_id,
                IngestedEmailMessage.status == EmailMessageStatus.EXPIRED,
                IngestedEmailMessage.adapter_id.is_not(None),
            )
        )
    )
    for manifest in manifests:
        purge_provider_attachment_for_retention(manifest)
        manifest.evidence_admission_failure_code = None
        manifest.evidence_admission_attempted_at = None
        manifest.filename = "[expired]"
        manifest.mime_type = "application/octet-stream"
        manifest.file_size_bytes = 0
        manifest.provider_sha256 = None
    if manifests:
        db.commit()


def expire_due_with_provider_attachment_purge(db: Session, user: User) -> int:
    expired_count = expire_due(db, user)
    _purge_expired_provider_attachment_state(db, user)
    return expired_count


def run_retention_with_provider_attachment_purge(
    db: Session,
    user: User,
    idempotency_key: str,
) -> EmailRetentionRun:
    result = run_retention(db, user, idempotency_key)
    # Always reconcile physical quarantine cleanup, including idempotent replay of a
    # retention run created before provider-attachment quarantine cleanup existed.
    _purge_expired_provider_attachment_state(db, user)
    return result
