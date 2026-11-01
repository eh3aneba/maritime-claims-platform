"""Append-only independent HUMAN observation of a reported OCR concern.

An observation is not a claim decision, transcript correction, source clearance,
or independent proof that the operator actually checked the original scan.
The original report remains in the current-source hold predicate until a
separate, expressly authorized disposition lifecycle is implemented.
"""
from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.audit.models import AuditLog
from app.modules.audit.service import write_audit_log
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.claims.models import Claim
from app.modules.documents.models import DocumentMalwareScanStatus, DocumentProcessingStatus
from app.modules.processing.ocr_discrepancy import _source_guard
from app.modules.processing.service import external_evidence_requires_processing_release
from app.modules.users.models import User, UserRole

router = APIRouter()
_ACTION = "REVIEW_OCR_SOURCE_DISCREPANCY_INDEPENDENT"
_REPORT = "REPORT_OCR_SOURCE_DISCREPANCY"
_HASH = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
_OUTCOME = Literal["discrepancy_observed", "not_reproduced", "inconclusive"]


class IndependentOcrObservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_file_hash: str = _HASH
    extraction_text_hash: str = _HASH
    reviewer_compared_original_scan: Literal[True]
    review_method: Literal["visual_original_scan"]
    outcome: _OUTCOME
    # An opaque digest asserted by the reviewer. NOT proof of workpaper custody.
    review_workpaper_sha256: str = _HASH


class IndependentOcrObservationReceipt(BaseModel):
    id: UUID
    report_id: UUID
    document_id: UUID
    reviewed_by_id: UUID
    reviewed_at: str
    source_file_hash: str
    extraction_text_hash: str
    review_method: Literal["visual_original_scan"]
    outcome: _OUTCOME
    review_workpaper_sha256: str
    review_state: Literal["independent_observation_no_clearance"] = "independent_observation_no_clearance"
    source_hold_cleared: Literal[False] = False
    claim_fact_approved: Literal[False] = False


class IndependentOcrObservationList(BaseModel):
    items: list[IndependentOcrObservationReceipt]
    offset: int
    limit: int


def _as_receipt(row: AuditLog) -> IndependentOcrObservationReceipt:
    v = row.new_values or {}
    return IndependentOcrObservationReceipt(
        id=row.id,
        report_id=UUID(v["report_id"]),
        document_id=row.entity_id,
        reviewed_by_id=row.user_id,
        reviewed_at=row.created_at.isoformat(),
        source_file_hash=v["source_file_hash"],
        extraction_text_hash=v["extraction_text_hash"],
        review_method=v["review_method"],
        outcome=v["outcome"],
        review_workpaper_sha256=v["review_workpaper_sha256"],
    )


def _original_report(
    db: Session, *, organization_id: UUID, claim_id: UUID, document_id: UUID,
    report_id: UUID, current_file_hash: str, current_text_hash: str,
    current_version: int,
) -> AuditLog:
    report = db.scalar(select(AuditLog).where(
        AuditLog.id == report_id,
        AuditLog.organization_id == organization_id,
        AuditLog.entity_type == "document",
        AuditLog.entity_id == document_id,
        AuditLog.action == _REPORT,
    ))
    if report is None:
        raise HTTPException(status_code=404, detail="Source discrepancy report not found")
    v = report.new_values
    if (
        type(v) is not dict
        or v.get("claim_id") != str(claim_id)
        or type(v.get("document_version")) is not int
        or v["document_version"] != current_version
        or v.get("source_file_hash") != current_file_hash
        or v.get("extraction_text_hash") != current_text_hash
        or v.get("review_state") != "reported_unverified"
    ):
        raise HTTPException(status_code=409, detail="Report no longer matches current OCR source")
    return report


@router.post(
    "/source-discrepancies/{report_id}/independent-reviews",
    response_model=IndependentOcrObservationReceipt,
    status_code=status.HTTP_201_CREATED,
)
def record_independent_observation(
    claim_id: UUID,
    document_id: UUID,
    report_id: UUID,
    payload: IndependentOcrObservationRequest,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.CLAIMS_MANAGER, UserRole.ADMIN))
    ],
    db: Annotated[Session, Depends(get_db)],
    response: Response,
) -> IndependentOcrObservationReceipt:
    response.headers["Cache-Control"] = "no-store"
    document, extraction = _source_guard(
        db, claim_id=claim_id, document_id=document_id, user=current_user,
    )
    # Serialize alongside report, source replacement, and AI ClaimFact
    # admission on real PostgreSQL. Recheck all source bindings under lock.
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
        document.deleted_at is not None
        or not document.is_current
        or document.malware_scan_status != DocumentMalwareScanStatus.CLEAN
        or document.processing_status != DocumentProcessingStatus.PROCESSED
        or external_evidence_requires_processing_release(db, document=document)
        or "tesseract:" not in extraction.extraction_method.lower()
        or extraction.text_hash is None
        or document.file_hash != payload.source_file_hash
        or extraction.text_hash != payload.extraction_text_hash
    ):
        raise HTTPException(status_code=409, detail="Source changed; reload original scan")
    # Do not consider a reviewer independent of their own initial allegation.
    original = _original_report(
        db, organization_id=current_user.organization_id, claim_id=claim_id,
        document_id=document.id, report_id=report_id,
        current_version=document.version_number,
        current_file_hash=document.file_hash,
        current_text_hash=extraction.text_hash,
    )
    if original.user_id is None or original.user_id == current_user.id:
        raise HTTPException(status_code=403, detail="A different human reviewer is required")

    prior = db.scalars(select(AuditLog).where(
        AuditLog.organization_id == current_user.organization_id,
        AuditLog.user_id == current_user.id,
        AuditLog.entity_type == "document",
        AuditLog.entity_id == document.id,
        AuditLog.action == _ACTION,
    ))
    for row in prior:
        v = row.new_values
        if (
            type(v) is dict
            and v.get("report_id") == str(report_id)
            and v.get("source_file_hash") == document.file_hash
            and v.get("extraction_text_hash") == extraction.text_hash
            and v.get("review_method") == payload.review_method
            and v.get("outcome") == payload.outcome
            and v.get("review_workpaper_sha256") == payload.review_workpaper_sha256
            and v.get("review_state") == "independent_observation_no_clearance"
        ):
            response.status_code = status.HTTP_200_OK
            return _as_receipt(row)

    record = write_audit_log(
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        action=_ACTION,
        entity_type="document",
        entity_id=document.id,
        new_values={
            "claim_id": str(claim_id),
            "report_id": str(report_id),
            "document_version": document.version_number,
            "source_file_hash": document.file_hash,
            "extraction_text_hash": extraction.text_hash,
            "review_method": payload.review_method,
            "reviewer_compared_original_scan": True,
            "outcome": payload.outcome,
            "review_workpaper_sha256": payload.review_workpaper_sha256,
            "review_state": "independent_observation_no_clearance",
            "source_hold_cleared": False,
            "claim_fact_approved": False,
        },
    )
    db.commit()
    db.refresh(record)
    return _as_receipt(record)


@router.get(
    "/source-discrepancies/{report_id}/independent-reviews",
    response_model=IndependentOcrObservationList,
)
def list_independent_observations(
    claim_id: UUID,
    document_id: UUID,
    report_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    response: Response,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
    limit: Annotated[int, Query(ge=1, le=25)] = 25,
) -> IndependentOcrObservationList:
    response.headers["Cache-Control"] = "no-store"
    document, extraction = _source_guard(
        db, claim_id=claim_id, document_id=document_id, user=current_user,
    )
    _original_report(
        db, organization_id=current_user.organization_id, claim_id=claim_id,
        document_id=document.id, report_id=report_id,
        current_version=document.version_number,
        current_file_hash=document.file_hash, current_text_hash=extraction.text_hash,
    )
    rows = db.scalars(select(AuditLog).where(
        AuditLog.organization_id == current_user.organization_id,
        AuditLog.entity_type == "document",
        AuditLog.entity_id == document.id,
        AuditLog.action == _ACTION,
    ).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()))
    matched = [
        r for r in rows if type(r.new_values) is dict
        and r.new_values.get("report_id") == str(report_id)
    ]
    return IndependentOcrObservationList(
        items=[_as_receipt(r) for r in matched[offset:offset+limit]],
        offset=offset, limit=limit,
    )
