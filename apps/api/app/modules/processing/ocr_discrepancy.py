"""Append-only, content-free *reported* OCR discrepancies.

Observations are user reports, NOT independent source-text verification,
corrected transcripts, authority to extract claim facts, or claim approval.
Reuse the immutable audit ledger without creating a parallel source of truth.
"""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.models import AuditLog
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.models import Claim
from app.modules.claims.security import get_claim_for_tenant
from app.modules.documents.models import Document, DocumentMalwareScanStatus, DocumentProcessingStatus
from app.modules.documents.security import get_document_for_tenant
from app.modules.processing.models import DocumentTextExtraction, DocumentTextSegment
from app.modules.processing.service import external_evidence_requires_processing_release

router = APIRouter()
_ACTION = "REPORT_OCR_SOURCE_DISCREPANCY"
_KINDS = Literal[
    "negation_missing",
    "negation_scope_changed",
    "date_time_changed",
    "technical_term_changed",
    "other_transcription_discrepancy",
]
_HASH = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class OcrDiscrepancyReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_version: int = Field(ge=1)
    source_file_hash: str = _HASH
    extraction_text_hash: str = _HASH
    segment_index: int = Field(ge=0, le=100000)
    issue_kind: _KINDS
    # An operator confirms viewing the unchanged source, not correctness.
    source_compared_by_operator: Literal[True]


class OcrDiscrepancyReceipt(BaseModel):
    id: UUID
    document_id: UUID
    document_version: int
    source_file_hash: str
    extraction_text_hash: str
    segment_index: int
    locator_type: str
    locator_value: str
    issue_kind: _KINDS
    reported_by_id: UUID
    reported_at: str
    review_state: Literal["reported_unverified"] = "reported_unverified"
    claim_fact_approved: Literal[False] = False


class OcrDiscrepancyList(BaseModel):
    items: list[OcrDiscrepancyReceipt]
    offset: int
    limit: int


def _source_guard(
    db: Session, *, claim_id: UUID, document_id: UUID, user: CurrentUser
) -> tuple[Document, DocumentTextExtraction]:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=user.organization_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    doc = get_document_for_tenant(
        db, claim_id=claim.id, document_id=document_id,
        organization_id=user.organization_id,
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if (
        doc.malware_scan_status != DocumentMalwareScanStatus.CLEAN
        or doc.processing_status != DocumentProcessingStatus.PROCESSED
        or external_evidence_requires_processing_release(db, document=doc)
    ):
        raise HTTPException(status_code=409, detail="Clean, processed, authorized OCR evidence required")

    extraction = db.scalar(
        select(DocumentTextExtraction).where(
            DocumentTextExtraction.document_id == doc.id,
            DocumentTextExtraction.organization_id == user.organization_id,
        )
    )
    if (
        extraction is None
        or "tesseract:" not in extraction.extraction_method.lower()
        or extraction.text_hash is None
    ):
        raise HTTPException(status_code=409, detail="Persisted OCR text is unavailable")
    return doc, extraction


def _as_receipt(audit: AuditLog) -> OcrDiscrepancyReceipt:
    values = audit.new_values or {}
    return OcrDiscrepancyReceipt(
        id=audit.id,
        document_id=audit.entity_id,
        document_version=values["document_version"],
        source_file_hash=values["source_file_hash"],
        extraction_text_hash=values["extraction_text_hash"],
        segment_index=values["segment_index"],
        locator_type=values["locator_type"],
        locator_value=values["locator_value"],
        issue_kind=values["issue_kind"],
        reported_by_id=audit.user_id,
        reported_at=audit.created_at.isoformat(),
    )


@router.post(
    "/source-discrepancies",
    response_model=OcrDiscrepancyReceipt,
    status_code=status.HTTP_201_CREATED,
)
def report_unverified_ocr_discrepancy(
    claim_id: UUID,
    document_id: UUID,
    payload: OcrDiscrepancyReport,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    response: Response,
) -> OcrDiscrepancyReceipt:
    response.headers["Cache-Control"] = "no-store"
    doc, extraction = _source_guard(
        db, claim_id=claim_id, document_id=document_id, user=current_user
    )
    # Serialize a newly reported source hold with AI fact approval and
    # document replacement on PostgreSQL. Otherwise an approval can race
    # between the preliminary source read and the append-only receipt.
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        locked_claim = db.scalar(
            select(Claim.id).where(
                Claim.id == claim_id,
                Claim.organization_id == current_user.organization_id,
                Claim.deleted_at.is_(None),
            ).with_for_update()
        )
        if locked_claim is None:
            raise HTTPException(status_code=404, detail="Claim not found")
        db.refresh(doc)
        db.refresh(extraction)
    if (
        doc.deleted_at is not None
        or doc.malware_scan_status != DocumentMalwareScanStatus.CLEAN
        or doc.processing_status != DocumentProcessingStatus.PROCESSED
        or external_evidence_requires_processing_release(db, document=doc)
        or "tesseract:" not in extraction.extraction_method.lower()
        or extraction.text_hash is None
    ):
        raise HTTPException(status_code=409, detail="Current authorized OCR source required")
    if (
        not doc.is_current
        or doc.version_number != payload.document_version
        or doc.file_hash != payload.source_file_hash
        or extraction.text_hash != payload.extraction_text_hash
    ):
        raise HTTPException(status_code=409, detail="Source or OCR extraction has changed; reload first")
    segment = db.scalar(
        select(DocumentTextSegment).where(
            DocumentTextSegment.organization_id == current_user.organization_id,
            DocumentTextSegment.document_id == doc.id,
            DocumentTextSegment.extraction_id == extraction.id,
            DocumentTextSegment.segment_index == payload.segment_index,
        )
    )
    if segment is None:
        raise HTTPException(status_code=409, detail="Selected OCR source segment is unavailable")

    entry = write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action=_ACTION,
        entity_type="document",
        entity_id=doc.id,
        new_values={
            "claim_id": str(claim_id),
            "document_version": doc.version_number,
            "source_file_hash": doc.file_hash,
            "extraction_text_hash": extraction.text_hash,
            "segment_index": segment.segment_index,
            "locator_type": segment.locator_type,
            "locator_value": segment.locator_value,
            "issue_kind": payload.issue_kind,
            "review_state": "reported_unverified",
            "source_compared_by_operator": True,
            "claim_fact_approved": False,
        },
    )
    db.commit()
    db.refresh(entry)
    return _as_receipt(entry)


@router.get("/source-discrepancies", response_model=OcrDiscrepancyList)
def list_ocr_discrepancies(
    claim_id: UUID,
    document_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    response: Response,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
    limit: Annotated[int, Query(ge=1, le=25)] = 25,
) -> OcrDiscrepancyList:
    response.headers["Cache-Control"] = "no-store"
    # Strict source authorization also gates readback. Older source versions
    # remain individually addressable but cannot accept new reports.
    _source_guard(db, claim_id=claim_id, document_id=document_id, user=current_user)
    items = db.scalars(
        select(AuditLog).where(
            AuditLog.organization_id == current_user.organization_id,
            AuditLog.entity_type == "document",
            AuditLog.entity_id == document_id,
            AuditLog.action == _ACTION,
        )
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return OcrDiscrepancyList(
        items=[_as_receipt(row) for row in items], offset=offset, limit=limit
    )
