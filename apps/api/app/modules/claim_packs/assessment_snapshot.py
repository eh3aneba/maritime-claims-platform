from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.assessments.models import AssessmentSection, AssessmentStatus, InitialAssessment
from app.modules.assessments.source_integrity import assessment_source_state
from app.modules.claims.models import Claim


ASSESSMENT_HANDOFF_DISCLAIMER = (
    "This is an immutable downstream reporting copy of an explicitly human-approved Initial Assessment. "
    "The approved-content digest verifies the persisted assessment content and its bound source identity. "
    "Current source-state reporting does not rewrite, invalidate or re-approve the historical human record. "
    "This handoff does not determine coverage, causation, liability, recoverability, governing law, time-bar legal effect, "
    "reserve adequacy, settlement, payment or claim closure."
)


def build_approved_assessment_handoff(db: Session, *, claim: Claim) -> dict[str, Any] | None:
    """Return the latest digest-bound approved Initial Assessment for downstream reporting only.

    Approved legacy rows without an approved-content digest are deliberately excluded rather than assigned fabricated
    integrity metadata. Draft and under-review rows are never eligible.
    """

    assessment = db.scalar(
        select(InitialAssessment)
        .where(
            InitialAssessment.organization_id == claim.organization_id,
            InitialAssessment.claim_id == claim.id,
            InitialAssessment.status == AssessmentStatus.APPROVED,
            InitialAssessment.approved_content_hash.is_not(None),
        )
        .order_by(InitialAssessment.version.desc(), InitialAssessment.created_at.desc())
        .limit(1)
    )
    if assessment is None:
        return None

    sections = list(
        db.scalars(
            select(AssessmentSection)
            .where(
                AssessmentSection.organization_id == claim.organization_id,
                AssessmentSection.claim_id == claim.id,
                AssessmentSection.assessment_id == assessment.id,
            )
            .order_by(AssessmentSection.sort_order.asc(), AssessmentSection.section_key.asc())
        )
    )
    source_state, current_source_fingerprint = assessment_source_state(
        db,
        claim=claim,
        assessment=assessment,
    )
    return {
        "authority": "downstream_approved_assessment_context_only",
        "disclaimer": ASSESSMENT_HANDOFF_DISCLAIMER,
        "id": str(assessment.id),
        "version": assessment.version,
        "status": assessment.status.value,
        "classification": "preliminary" if assessment.is_preliminary else "final",
        "is_preliminary": assessment.is_preliminary,
        "readiness_score": assessment.readiness_score,
        "readiness_state": assessment.readiness_state,
        "blocking_items": list(assessment.blocking_items or []),
        "source_fingerprint": assessment.source_fingerprint,
        "source_state_at_export": source_state,
        "current_source_fingerprint_at_export": current_source_fingerprint,
        "approved_content_hash": assessment.approved_content_hash,
        "approved_by_id": str(assessment.approved_by_id) if assessment.approved_by_id else None,
        "approved_at": assessment.approved_at.isoformat() if assessment.approved_at else None,
        "sections": [
            {
                "section_key": section.section_key,
                "title": section.title,
                "sort_order": section.sort_order,
                "text": section.approved_text if section.approved_text is not None else section.draft_text,
                "sources": list(section.source_manifest or []),
                "review_status": section.status.value,
                "reviewed_by_id": str(section.reviewed_by_id) if section.reviewed_by_id else None,
                "reviewed_at": section.reviewed_at.isoformat() if section.reviewed_at else None,
            }
            for section in sections
        ],
    }
