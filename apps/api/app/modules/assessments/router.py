from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.assessments.models import AssessmentSection, InitialAssessment
from app.modules.assessments.schemas import AssessmentApproveRequest, AssessmentGenerateRequest, AssessmentRead, AssessmentSectionRead, AssessmentSectionReview
from app.modules.assessments.service import approve_assessment, generate_assessment, get_assessment, review_section
from app.modules.auth.dependencies import CurrentUser, require_roles
from app.modules.claims.security import get_claim_for_tenant
from app.modules.users.models import UserRole

router=APIRouter(prefix="/claims/{claim_id}/initial-assessment",tags=["initial-assessment"])


def _response(a,sections):
    return AssessmentRead(id=a.id,claim_id=a.claim_id,version=a.version,status=a.status,readiness_score=a.readiness_score,readiness_state=a.readiness_state,blocking_items=a.blocking_items,is_preliminary=a.is_preliminary,generation_override_reason=a.generation_override_reason,generated_by_id=a.generated_by_id,approved_by_id=a.approved_by_id,approved_at=a.approved_at,created_at=a.created_at,updated_at=a.updated_at,sections=[AssessmentSectionRead.model_validate(s) for s in sections])

@router.get("",response_model=AssessmentRead|None)
def latest(claim_id:UUID,current_user:CurrentUser,db:Annotated[Session,Depends(get_db)]):
    claim=get_claim_for_tenant(db,claim_id=claim_id,organization_id=current_user.organization_id)
    if not claim: raise HTTPException(status_code=404,detail="Claim not found")
    a,sections=get_assessment(db,claim=claim)
    return _response(a,sections) if a else None

@router.post("/generate",response_model=AssessmentRead)
def generate(claim_id:UUID,payload:AssessmentGenerateRequest,current_user:CurrentUser,db:Annotated[Session,Depends(get_db)]):
    claim=get_claim_for_tenant(db,claim_id=claim_id,organization_id=current_user.organization_id)
    if not claim: raise HTTPException(status_code=404,detail="Claim not found")
    a=generate_assessment(db,claim=claim,user=current_user,allow_if_not_ready=payload.allow_if_not_ready,override_reason=payload.override_reason)
    a,sections=get_assessment(db,claim=claim,assessment_id=a.id);return _response(a,sections)

@router.post("/sections/{section_id}/review",response_model=AssessmentSectionRead)
def review(claim_id:UUID,section_id:UUID,payload:AssessmentSectionReview,current_user:CurrentUser,db:Annotated[Session,Depends(get_db)]):
    claim=get_claim_for_tenant(db,claim_id=claim_id,organization_id=current_user.organization_id)
    if not claim: raise HTTPException(status_code=404,detail="Claim not found")
    section=db.get(AssessmentSection,section_id)
    if not section: raise HTTPException(status_code=404,detail="Assessment section not found")
    return AssessmentSectionRead.model_validate(review_section(db,claim=claim,section=section,user=current_user,action=payload.action,text=payload.text))

@router.post("/{assessment_id}/approve",response_model=AssessmentRead)
def approve(claim_id:UUID,assessment_id:UUID,payload:AssessmentApproveRequest,current_user:Annotated[object,Depends(require_roles(UserRole.ADMIN,UserRole.CLAIMS_MANAGER))],db:Annotated[Session,Depends(get_db)]):
    claim=get_claim_for_tenant(db,claim_id=claim_id,organization_id=current_user.organization_id)
    if not claim: raise HTTPException(status_code=404,detail="Claim not found")
    a=db.get(InitialAssessment,assessment_id)
    if not a or a.claim_id!=claim.id or a.organization_id!=claim.organization_id: raise HTTPException(status_code=404,detail="Assessment not found")
    approve_assessment(db,claim=claim,assessment=a,user=current_user,note=payload.note)
    a,sections=get_assessment(db,claim=claim,assessment_id=a.id);return _response(a,sections)
