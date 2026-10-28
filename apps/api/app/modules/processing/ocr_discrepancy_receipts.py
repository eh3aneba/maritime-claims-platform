"""Read-only detection of operator-reported OCR source discrepancies.

A receipt reports an operator's concern, not a verified error, corrected
transcript, or expert decision. Match the exact current source/version and
original file digest; do not treat OCR reprocessing as resolution.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog
from app.modules.documents.models import Document


def current_source_discrepancy_receipts(
    db: Session, *, organization_id: UUID, claim_id: UUID,
    documents: list[Document],
) -> list[AuditLog]:
    current = {
        document.id: document
        for document in documents
        if (
            document.organization_id == organization_id
            and document.claim_id == claim_id
            and document.deleted_at is None
            and document.is_current
        )
    }
    if not current:
        return []
    receipts = db.scalars(
        select(AuditLog).where(
            AuditLog.organization_id == organization_id,
            AuditLog.entity_type == "document",
            AuditLog.action == "REPORT_OCR_SOURCE_DISCREPANCY",
            AuditLog.entity_id.in_(current),
        )
    )
    matched: list[AuditLog] = []
    for receipt in receipts:
        document = current.get(receipt.entity_id)
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
