from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
import hashlib
import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.chronology.models import ChronologyEvent, EvidenceConflict, EventEvidence
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.financial.models import CostItem, FinancialFlag, ReserveHistory
from app.modules.intelligence.models import AIReviewStatus, DocumentExtraction
from app.modules.rules.models import ClaimDocumentRequirement, ClaimIssue
from app.modules.tasks.models import ClaimTask, TaskStatus


SOURCE_SNAPSHOT_SCHEMA = "assessment-source-v1"
REVIEWED_EXTRACTION_STATES = {AIReviewStatus.APPROVED, AIReviewStatus.EDITED}


def _jsonable(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, (str, int, float, bool)):
        return enum_value
    return value


def canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _jsonable(payload),
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _row_state(row: Any) -> dict[str, str]:
    payload = {
        column.name: _jsonable(getattr(row, column.name))
        for column in row.__table__.columns
    }
    identifier = getattr(row, "id", None)
    return {
        "id": str(identifier) if identifier is not None else canonical_hash(payload)[:32],
        "row_hash": canonical_hash(payload),
    }


def _compact(rows: list[Any]) -> list[dict[str, str]]:
    states = [_row_state(row) for row in rows]
    return sorted(states, key=lambda item: (item["id"], item["row_hash"]))


def _claim_rows(db: Session, model: Any, claim: Claim, *extra_conditions: Any) -> list[Any]:
    conditions = [
        model.organization_id == claim.organization_id,
        model.claim_id == claim.id,
        *extra_conditions,
    ]
    return list(db.scalars(select(model).where(*conditions)))


def build_assessment_source_snapshot(db: Session, *, claim: Claim) -> tuple[dict[str, Any], str]:
    """Build a compact deterministic identity of the state that can drive Initial Assessment text.

    The snapshot deliberately stores row hashes rather than duplicating evidence, legal conclusions,
    technical findings, reserve authority, or other upstream content. Historical assessments retain
    their exact bound fingerprint while current state is recomputed from the canonical modules.
    """

    claim_facts = _claim_rows(db, ClaimFact, claim)
    documents = _claim_rows(db, Document, claim, Document.deleted_at.is_(None))
    reviewed_extractions = _claim_rows(
        db,
        DocumentExtraction,
        claim,
        DocumentExtraction.human_status.in_(REVIEWED_EXTRACTION_STATES),
    )
    chronology_events = _claim_rows(db, ChronologyEvent, claim, ChronologyEvent.is_active.is_(True))
    event_evidence = _claim_rows(db, EventEvidence, claim)
    conflicts = _claim_rows(db, EvidenceConflict, claim, EvidenceConflict.is_active.is_(True))
    requirements = _claim_rows(db, ClaimDocumentRequirement, claim)
    issues = _claim_rows(db, ClaimIssue, claim, ClaimIssue.is_active.is_(True))
    cost_items = _claim_rows(db, CostItem, claim)
    financial_flags = _claim_rows(db, FinancialFlag, claim)
    reserves = _claim_rows(db, ReserveHistory, claim)
    open_tasks = _claim_rows(db, ClaimTask, claim, ClaimTask.status == TaskStatus.OPEN)

    snapshot: dict[str, Any] = {
        "schema": SOURCE_SNAPSHOT_SCHEMA,
        "claim_id": str(claim.id),
        "sources": {
            "claim": [_row_state(claim)],
            "claim_facts": _compact(claim_facts),
            "documents": _compact(documents),
            "reviewed_document_extractions": _compact(reviewed_extractions),
            "chronology_events": _compact(chronology_events),
            "event_evidence": _compact(event_evidence),
            "evidence_conflicts": _compact(conflicts),
            "document_requirements": _compact(requirements),
            "claim_issues": _compact(issues),
            "cost_items": _compact(cost_items),
            "financial_flags": _compact(financial_flags),
            "reserve_history": _compact(reserves),
            "open_tasks": _compact(open_tasks),
        },
    }
    return snapshot, canonical_hash(snapshot)


def assessment_source_state(
    db: Session,
    *,
    claim: Claim,
    assessment: Any,
) -> tuple[str, str | None]:
    if not assessment.source_fingerprint:
        return "legacy_unbound", None
    _, current_fingerprint = build_assessment_source_snapshot(db, claim=claim)
    return (
        "current" if current_fingerprint == assessment.source_fingerprint else "stale",
        current_fingerprint,
    )


def assert_assessment_source_current(
    db: Session,
    *,
    claim: Claim,
    assessment: Any,
    expected_source_fingerprint: str | None,
) -> str:
    stored = assessment.source_fingerprint
    if not stored:
        raise HTTPException(
            status_code=409,
            detail=(
                "This historical assessment predates source-state binding and cannot accept new review "
                "or approval writes. Generate a new assessment version."
            ),
        )
    if expected_source_fingerprint is not None and expected_source_fingerprint != stored:
        raise HTTPException(
            status_code=409,
            detail=(
                "The assessment source context shown in this session is no longer the bound version. "
                "Reload the assessment before continuing."
            ),
        )
    _, current = build_assessment_source_snapshot(db, claim=claim)
    if current != stored:
        raise HTTPException(
            status_code=409,
            detail=(
                "The claim evidence or human-reviewed upstream state changed after this assessment was "
                "generated. This assessment is now stale; generate a new version before reviewing or approving it."
            ),
        )
    return current


def approved_assessment_content_hash(assessment: Any, sections: list[Any]) -> str:
    """Digest only persisted approved assessment content and its bound source identity."""

    payload = {
        "assessment_id": assessment.id,
        "claim_id": assessment.claim_id,
        "version": assessment.version,
        "status": assessment.status,
        "readiness_score": assessment.readiness_score,
        "readiness_state": assessment.readiness_state,
        "blocking_items": assessment.blocking_items,
        "is_preliminary": assessment.is_preliminary,
        "generation_override_reason": assessment.generation_override_reason,
        "source_fingerprint": assessment.source_fingerprint,
        "approved_by_id": assessment.approved_by_id,
        "approved_at": assessment.approved_at,
        "sections": [
            {
                "id": section.id,
                "section_key": section.section_key,
                "title": section.title,
                "sort_order": section.sort_order,
                "draft_text": section.draft_text,
                "approved_text": section.approved_text,
                "status": section.status,
                "source_manifest": section.source_manifest,
                "reviewed_by_id": section.reviewed_by_id,
                "reviewed_at": section.reviewed_at,
            }
            for section in sorted(sections, key=lambda row: (row.sort_order, row.section_key))
        ],
    }
    return canonical_hash(payload)
