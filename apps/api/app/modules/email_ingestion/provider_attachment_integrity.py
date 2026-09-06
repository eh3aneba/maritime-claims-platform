from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.documents.service import _storage
from app.modules.email_ingestion.models import EmailAttachmentManifest, IngestedEmailMessage
from app.modules.email_ingestion.provider_attachment_acquisition import acquire_provider_attachment
from app.modules.users.models import User

_TERMINAL_QUARANTINE_STATES = {
    "clean_pending_human_admission",
    "infected_quarantined",
    "scan_error_quarantined",
}


def acquire_provider_attachment_with_integrity(
    db: Session,
    *,
    message: IngestedEmailMessage,
    manifest: EmailAttachmentManifest,
    user: User,
) -> dict:
    if manifest.admission_status in _TERMINAL_QUARANTINE_STATES and manifest.quarantine_key:
        try:
            _storage().path_for(manifest.quarantine_key)
        except FileNotFoundError as exc:
            manifest.admission_status = "acquisition_failed"
            manifest.acquisition_failure_code = "provider_attachment_quarantine_missing"
            manifest.quarantine_key = None
            write_audit_log(
                db,
                organization_id=manifest.organization_id,
                user_id=user.id,
                action="REJECT_EMAIL_PROVIDER_ATTACHMENT_REPLAY",
                entity_type="email_attachment_manifest",
                entity_id=manifest.id,
                new_values={
                    "failure_code": "provider_attachment_quarantine_missing",
                    "message_id": str(message.id),
                },
                details=(
                    "Terminal provider attachment state could not be replayed because quarantine bytes "
                    "were unavailable. No provider locator, filename, hash, credential or message content logged."
                ),
            )
            db.commit()
            raise HTTPException(409, "Provider attachment quarantine state requires reconciliation") from exc
    return acquire_provider_attachment(
        db,
        message=message,
        manifest=manifest,
        user=user,
    )
