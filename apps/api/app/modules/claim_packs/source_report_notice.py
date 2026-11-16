"""Current claim-wide OCR concern count for *historical* Claim Pack access.

A report is an unverified operator allegation on the exact current source
version/hash, not a finding of error. This is a live advisory count and cannot
change, reapprove or revoke any immutable archived Claim Pack or human decision.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.claims.service import (
    approved_ai_fact_source_revalidation_reasons,
    list_claim_facts,
)
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


def approved_ai_fact_unverified_ocr_discrepancy_count(
    db: Session, *, organization_id: UUID, claim_id: UUID,
) -> int:
    """Count canonical human-approved AI facts still tied to an exact OCR report.

    Unlike the current-document report count, this is a **fact** count, not a
    count of allegations. It retains exact-bound reports when their original
    evidence is superseded or soft-deleted; the shared fact helper validates
    tenant/claim/document ID/version/original SHA and never resolves a report.
    Use only for live, non-authoritative notices on immutable archive access.
    """
    facts = list_claim_facts(
        db, claim_id=claim_id, organization_id=organization_id,
    )
    reasons = approved_ai_fact_source_revalidation_reasons(
        db, facts=facts, claim_id=claim_id,
        organization_id=organization_id,
    )
    return sum(
        reason == "source_ocr_discrepancy_reported_unverified"
        for reason in reasons.values()
    )
