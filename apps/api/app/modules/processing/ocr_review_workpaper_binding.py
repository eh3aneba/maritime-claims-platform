"""Bind an independent OCR reviewer workpaper to managed claim evidence.

Linkage proves only that an authorized stored Document *record* matches the
reviewer's previously asserted workpaper digest. It does NOT independently
verify source text, adjudicate OCR quality or remove any source hold.
"""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.models import AuditLog
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.claims.models import Claim
from app.modules.documents.models import Document, DocumentMalwareScanStatus
from app.modules.documents.security import get_document_for_tenant
from app.modules.processing.ocr_discrepancy import _source_guard
from app.modules.processing.ocr_discrepancy_independent_review import _original_report
from app.modules.processing.service import external_evidence_requires_processing_release
from app.modules.users.models import User, UserRole

router = APIRouter()
_ACTION = "BIND_OCR_INDEPENDENT_REVIEW_WORKPAPER"
_REVIEW = "REVIEW_OCR_SOURCE_DISCREPANCY_INDEPENDENT"
_HASH = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class WorkpaperLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workpaper_document_id: UUID
    workpaper_file_hash: str = _HASH


class WorkpaperLinkReceipt(BaseModel):
    id: UUID
    report_id: UUID
    review_id: UUID
    document_id: UUID
    workpaper_document_id: UUID
    workpaper_document_version: int
    workpaper_file_hash: str
    linked_by_id: UUID
    linked_at: str
    custody_state: Literal["managed_clean_document_record_linked"] = "managed_clean_document_record_linked"
    original_source_hold_cleared: Literal[False] = False
    claim_fact_approved: Literal[False] = False


def _as_receipt(row: AuditLog) -> WorkpaperLinkReceipt:
    v = row.new_values or {}
    return WorkpaperLinkReceipt(
        id=row.id,
        report_id=UUID(v["report_id"]),
        review_id=UUID(v["review_id"]),
        document_id=row.entity_id,
        workpaper_document_id=UUID(v["workpaper_document_id"]),
        workpaper_document_version=v["workpaper_document_version"],
        workpaper_file_hash=v["workpaper_file_hash"],
        linked_by_id=row.user_id,
        linked_at=row.created_at.isoformat(),
    )


def _review_for_current_source(
    db: Session, *, organization_id: UUID, claim_id: UUID, document: Document,
    extraction_text_hash: str, report_id: UUID, review_id: UUID,
) -> AuditLog:
    _original_report(
        db, organization_id=organization_id, claim_id=claim_id,
        document_id=document.id, report_id=report_id,
        current_version=document.version_number,
        current_file_hash=document.file_hash,
        current_text_hash=extraction_text_hash,
    )
    review = db.scalar(select(AuditLog).where(
        AuditLog.id == review_id,
        AuditLog.organization_id == organization_id,
        AuditLog.entity_type == "document",
        AuditLog.entity_id == document.id,
        AuditLog.action == _REVIEW,
    ))
    if review is None:
        raise HTTPException(status_code=404, detail="Independent review not found")
    values = review.new_values
    if (
        type(values) is not dict
        or values.get("claim_id") != str(claim_id)
        or values.get("report_id") != str(report_id)
        or type(values.get("document_version")) is not int
        or values["document_version"] != document.version_number
        or values.get("source_file_hash") != document.file_hash
        or values.get("extraction_text_hash") != extraction_text_hash
        or values.get("review_state") != "independent_observation_no_clearance"
        or values.get("reviewer_compared_original_scan") is not True
        or values.get("source_hold_cleared") is not False
        or values.get("claim_fact_approved") is not False
    ):
        raise HTTPException(status_code=409, detail="Review no longer matches current source")
    return review


def _existing_binding(db: Session, *, organization_id: UUID, claim_id: UUID,
                      source_id: UUID, review_id: UUID) -> AuditLog | None:
    rows = db.scalars(select(AuditLog).where(
        AuditLog.organization_id == organization_id,
        AuditLog.action == _ACTION,
        AuditLog.entity_type == "document",
        AuditLog.entity_id == source_id,
    ).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()))
    for row in rows:
        values = row.new_values
        if (
            type(values) is dict
            and values.get("claim_id") == str(claim_id)
            and values.get("review_id") == str(review_id)
        ):
            return row
    return None


_PATH = "/source-discrepancies/{report_id}/independent-reviews/{review_id}/workpaper-binding"


@router.post(_PATH, response_model=WorkpaperLinkReceipt,
             status_code=status.HTTP_201_CREATED)
def link_review_workpaper(
    claim_id: UUID, document_id: UUID, report_id: UUID, review_id: UUID,
    payload: WorkpaperLinkRequest,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.CLAIMS_MANAGER, UserRole.ADMIN))
    ],
    db: Annotated[Session, Depends(get_db)], response: Response,
) -> WorkpaperLinkReceipt:
    response.headers["Cache-Control"] = "no-store"
    document, extraction = _source_guard(
        db, claim_id=claim_id, document_id=document_id, user=current_user,
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        held = db.scalar(select(Claim.id).where(
            Claim.id == claim_id,
            Claim.organization_id == current_user.organization_id,
            Claim.deleted_at.is_(None),
        ).with_for_update())
        if held is None:
            raise HTTPException(status_code=404, detail="Claim not found")
        db.refresh(document)
        db.refresh(extraction)
    if (
        not document.is_current or document.deleted_at is not None
        or document.malware_scan_status != DocumentMalwareScanStatus.CLEAN
        or external_evidence_requires_processing_release(db, document=document)
        or extraction.text_hash is None
        or "tesseract:" not in extraction.extraction_method.lower()
    ):
        raise HTTPException(status_code=409, detail="Current authorized OCR source is required")
    review = _review_for_current_source(
        db, organization_id=current_user.organization_id, claim_id=claim_id,
        document=document, extraction_text_hash=extraction.text_hash,
        report_id=report_id, review_id=review_id,
    )
    if review.user_id is None or review.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the original independent reviewer may bind workpaper")
    workpaper = get_document_for_tenant(
        db, organization_id=current_user.organization_id, claim_id=claim_id,
        document_id=payload.workpaper_document_id,
    )
    if workpaper is None:
        raise HTTPException(status_code=404, detail="Workpaper evidence document not found")
    values = review.new_values
    if (
        workpaper.id == document.id
        or not workpaper.is_current
        or workpaper.document_type != "ocr_review_workpaper"
        or workpaper.uploaded_by_id != current_user.id
        or workpaper.malware_scan_status != DocumentMalwareScanStatus.CLEAN
        or workpaper.malware_scanned_at is None
        or workpaper.file_size_bytes <= 0
        or external_evidence_requires_processing_release(db, document=workpaper)
        or workpaper.file_hash != payload.workpaper_file_hash
        or workpaper.file_hash != values.get("review_workpaper_sha256")
    ):
        raise HTTPException(status_code=409, detail="Managed, clean, reviewer-uploaded workpaper hash required")

    prior = _existing_binding(
        db, organization_id=current_user.organization_id, claim_id=claim_id,
        source_id=document.id, review_id=review_id,
    )
    if prior is not None:
        old = prior.new_values
        if (
            old.get("workpaper_document_id") == str(workpaper.id)
            and old.get("workpaper_document_version") == workpaper.version_number
            and old.get("workpaper_file_hash") == workpaper.file_hash
            and old.get("report_id") == str(report_id)
        ):
            response.status_code = status.HTTP_200_OK
            return _as_receipt(prior)
        raise HTTPException(status_code=409, detail="Review is already bound to another workpaper")

    event = write_audit_log(
        db, organization_id=current_user.organization_id,
        user_id=current_user.id,
        action=_ACTION, entity_type="document", entity_id=document.id,
        new_values={
            "claim_id": str(claim_id),
            "report_id": str(report_id),
            "review_id": str(review_id),
            "source_document_version": document.version_number,
            "source_file_hash": document.file_hash,
            "extraction_text_hash": extraction.text_hash,
            "workpaper_document_id": str(workpaper.id),
            "workpaper_document_version": workpaper.version_number,
            "workpaper_file_hash": workpaper.file_hash,
            "custody_state": "managed_clean_document_record_linked",
            "original_source_hold_cleared": False,
            "claim_fact_approved": False,
        },
    )
    db.commit()
    db.refresh(event)
    return _as_receipt(event)


@router.get(_PATH, response_model=WorkpaperLinkReceipt)
def read_review_workpaper_binding(
    claim_id: UUID, document_id: UUID, report_id: UUID, review_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)], response: Response,
) -> WorkpaperLinkReceipt:
    response.headers["Cache-Control"] = "no-store"
    document, extraction = _source_guard(
        db, claim_id=claim_id, document_id=document_id, user=current_user,
    )
    _review_for_current_source(
        db, organization_id=current_user.organization_id, claim_id=claim_id,
        document=document, extraction_text_hash=extraction.text_hash,
        report_id=report_id, review_id=review_id,
    )
    row = _existing_binding(
        db, organization_id=current_user.organization_id, claim_id=claim_id,
        source_id=document.id, review_id=review_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="No managed workpaper binding recorded")
    return _as_receipt(row)
