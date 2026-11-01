"""Current claim-wide OCR concern count for *historical* Claim Pack access.

A report is an unverified operator allegation on the exact current source
version/hash, not a finding of error. This is a live advisory count and cannot
change, reapprove or revoke any immutable archived Claim Pack or human decision.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.documents.models import Document
from app.modules.processing.ocr_discrepancy_receipts import (
    current_source_discrepancy_receipts,
)


def current_ocr_source_report_count(
    db: Session, *, organization_id: UUID, claim_id: UUID,
) -> int:
    """Tenant/claim/version/hash-scoped current report count, not source validity."""
    docs = list(db.scalars(
        select(Document).where(
            Document.organization_id == organization_id,
            Document.claim_id == claim_id,
            Document.is_current.is_(True),
            Document.deleted_at.is_(None),
        )
    ))
    return len(current_source_discrepancy_receipts(
        db, organization_id=organization_id, claim_id=claim_id, documents=docs,
    ))
