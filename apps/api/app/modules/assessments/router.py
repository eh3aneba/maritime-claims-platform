from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.assessments.models import AssessmentSection, InitialAssessment
from app.modules.assessments.schemas import (
    AssessmentApproveRequest,
    AssessmentGenerateRequest,
    AssessmentRead,
    AssessmentSectionRead,
    AssessmentSectionReview,
)
from app.modules.assessments.service import approve_assessment, generate_assessment, get_assessment, review_section
from app.modules.assessments.source_integrity import assessment_source_state
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.claims.security import get_claim_for_tenant
from app.modules.pilot.service import record_active_event
from app.modules.users.models import UserRole

router = APIRouter(prefix="/claims/{claim_id}/initial-assessment", tags=["initial-assessment"])


def _response(db: Session, claim, assessment, sections):
    source_state, current_source_fingerprint = assessment_source_state(
        db,
        claim=claim,
        assessment=assessment,
    )
    return AssessmentRead(
        id=assessment.id,
        claim_id=assessment.claim_id,
        version=assessment.version,
        status=assessment.status,
        readiness_score=assessment.readiness_score,
        readiness_state=assessment.readiness_state,
        blocking_items=assessment.blocking_items,
        is_preliminary=assessment.is_preliminary,
        generation_override_reason=assessment.generation_override_reason,
        generated_by_id=assessment.generated_by_id,
        approved_by_id=assessment.approved_by_id,
        approved_at=assessment.approved_at,
        source_fingerprint=assessment.source_fingerprint,
        current_source_fingerprint=current_source_fingerprint,
        source_state=source_state,
        approved_content_hash=assessment.approved_content_hash,
        created_at=assessment.created_at,
        updated_at=assessment.updated_at,
        sections=[AssessmentSectionRead.model_validate(section) for section in sections],
    )


@router.get("", response_model=AssessmentRead | None)
def latest(claim_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]):
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    assessment, sections = get_assessment(db, claim=claim)
    return _response(db, claim, assessment, sections) if assessment else None


@router.post("/generate", response_model=AssessmentRead)
def generate(
    claim_id: UUID,
    payload: AssessmentGenerateRequest,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    assessment = generate_assessment(
        db,
        claim=claim,
        user=current_user,
        allow_if_not_ready=payload.allow_if_not_ready,
        override_reason=payload.override_reason,
    )
    record_active_event(
        db,
        organization_id=current_user.organization_id,
        claim_id=claim.id,
        user_id=current_user.id,
        event_type="initial_assessment_generated",
        entity_type="initial_assessment",
        entity_id=assessment.id,
        event_data={
            "version": assessment.version,
            "preliminary": assessment.is_preliminary,
            "source_fingerprint": assessment.source_fingerprint,
        },
    )
    db.commit()
    assessment, sections = get_assessment(db, claim=claim, assessment_id=assessment.id)
    return _response(db, claim, assessment, sections)


@router.post("/sections/{section_id}/review", response_model=AssessmentSectionRead)
def review(
    claim_id: UUID,
    section_id: UUID,
    payload: AssessmentSectionReview,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
):
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    section = db.get(AssessmentSection, section_id)
    if not section:
        raise HTTPException(status_code=404, detail="Assessment section not found")
    reviewed = review_section(
        db,
        claim=claim,
        section=section,
        user=current_user,
        action=payload.action,
        text=payload.text,
        expected_source_fingerprint=payload.expected_source_fingerprint,
    )
    record_active_event(
        db,
        organization_id=current_user.organization_id,
        claim_id=claim.id,
        user_id=current_user.id,
        event_type="assessment_section_reviewed",
        entity_type="assessment_section",
        entity_id=section.id,
        event_data={"action": payload.action, "section_key": section.section_key},
    )
    db.commit()
    return AssessmentSectionRead.model_validate(reviewed)


@router.post("/{assessment_id}/approve", response_model=AssessmentRead)
def approve(
    claim_id: UUID,
    assessment_id: UUID,
    payload: AssessmentApproveRequest,
    current_user: Annotated[object, Depends(require_roles(UserRole.ADMIN, UserRole.CLAIMS_MANAGER))],
    db: Annotated[Session, Depends(get_db)],
):
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    assessment = db.get(InitialAssessment, assessment_id)
    if not assessment or assessment.claim_id != claim.id or assessment.organization_id != claim.organization_id:
        raise HTTPException(status_code=404, detail="Assessment not found")
    approve_assessment(
        db,
        claim=claim,
        assessment=assessment,
        user=current_user,
        note=payload.note,
        expected_source_fingerprint=payload.expected_source_fingerprint,
    )
    record_active_event(
        db,
        organization_id=current_user.organization_id,
        claim_id=claim.id,
        user_id=current_user.id,
        event_type="initial_assessment_approved",
        entity_type="initial_assessment",
        entity_id=assessment.id,
        event_data={
            "version": assessment.version,
            "preliminary": assessment.is_preliminary,
            "approved_content_hash": assessment.approved_content_hash,
        },
    )
    db.commit()
    assessment, sections = get_assessment(db, claim=claim, assessment_id=assessment.id)
    return _response(db, claim, assessment, sections)
