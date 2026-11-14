"""Read-only detection of operator-reported OCR source discrepancies.

A receipt reports an operator's concern, not a verified error, corrected
transcript, or expert decision. Claim-wide freshness uses only the exact
current document. An assessment bound to an approved AI fact must also retain
the allegation if that *same original document* is later superseded; replacing
a document is not independent OCR source adjudication.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog
from app.modules.documents.models import Document


def _matching_source_discrepancy_receipts(
    db: Session, *, organization_id: UUID, claim_id: UUID,
    documents: list[Document], require_current: bool,
) -> list[AuditLog]:
    eligible = {
        document.id: document
        for document in documents
        if (
            document.organization_id == organization_id
            and document.claim_id == claim_id
            and (
                not require_current
                or (document.deleted_at is None and document.is_current)
            )
        )
    }
    if not eligible:
        return []
    receipts = db.scalars(
        select(AuditLog).where(
            AuditLog.organization_id == organization_id,
            AuditLog.entity_type == "document",
            AuditLog.action == "REPORT_OCR_SOURCE_DISCREPANCY",
            AuditLog.entity_id.in_(list(eligible)),
        )
    )
    matched: list[AuditLog] = []
    for receipt in receipts:
        document = eligible.get(receipt.entity_id)
        values = receipt.new_values
        if (
            document is not None
            and type(values) is dict
            and values.get("claim_id") == str(claim_id)
            and type(values.get("document_version")) is int
            and values["document_version"] == document.version_number
            and values.get("source_file_hash") == document.file_hash
            and values.get("review_state") == "reported_unverified"
        ):
            matched.append(receipt)
    return matched


def current_source_discrepancy_receipts(
    db: Session, *, organization_id: UUID, claim_id: UUID,
    documents: list[Document],
) -> list[AuditLog]:
    """Only the current document contributes to claim-wide source freshness."""
    return _matching_source_discrepancy_receipts(
        db, organization_id=organization_id, claim_id=claim_id,
        documents=documents, require_current=True,
    )


def bound_fact_source_discrepancy_receipts(
    db: Session, *, organization_id: UUID, claim_id: UUID,
    documents: list[Document],
) -> list[AuditLog]:
    """For an exact-bound AI fact, supersession/deletion cannot clear a report.

    Only call with documents already selected through tenant/claim-bound fact
    provenance. Exact original document ID, version and file hash are required.
    This never makes a report an independently verified finding.
    """
    return _matching_source_discrepancy_receipts(
        db, organization_id=organization_id, claim_id=claim_id,
        documents=documents, require_current=False,
    )
