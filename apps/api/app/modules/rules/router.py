from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.security import get_claim_for_tenant
from app.modules.claims.facts import ClaimFact
from app.modules.rules.marine_service import attach_marine_rules_to_run, latest_marine_rule_summary
from app.modules.rules.models import ClaimDocumentRequirement
from app.modules.rules.schemas import DocumentRequirementResponse, EquivalentEvidenceRequest, EquivalentEvidenceResponse, RuleEvaluationResponse, RuleSummaryResponse
from app.modules.rules.service import accept_equivalent_evidence, equivalent_evidence_candidates, evaluate_claim_rules, get_rule_summary

router = APIRouter(prefix="/claims/{claim_id}/rules", tags=["rules"])


def _summary_with_marine(db: Session, *, claim) -> RuleSummaryResponse:
    summary = get_rule_summary(db, claim=claim)
    marine = latest_marine_rule_summary(db, claim=claim)
    return summary.model_copy(update={
        "marine_registry_version": marine.get("marine_registry_version"),
        "marine_registry_hash": marine.get("marine_registry_hash"),
        "marine_rule_evaluations": marine.get("marine_rule_evaluations", []),
        "marine_rule_counts": marine.get("marine_rule_counts", {}),
        "marine_evaluated_at": marine.get("marine_evaluated_at"),
        "marine_rule_run_id": marine.get("marine_rule_run_id"),
        "human_authority_boundary": marine.get("human_authority_boundary"),
    })


@router.get("", response_model=RuleSummaryResponse)
def rule_summary(claim_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> RuleSummaryResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    return _summary_with_marine(db, claim=claim)


@router.post("/evaluate", response_model=RuleEvaluationResponse)
def evaluate_rules(claim_id: UUID, current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> RuleEvaluationResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    run = evaluate_claim_rules(db, claim=claim, user=current_user)
    run = attach_marine_rules_to_run(db, claim=claim, user=current_user, run=run)
    return RuleEvaluationResponse(run_id=run.id, marine_run_id=run.id, summary=_summary_with_marine(db, claim=claim))


@router.post("/requirements/{requirement_id}/accept-equivalent", response_model=EquivalentEvidenceResponse)
def accept_equivalent_requirement(
    claim_id: UUID,
    requirement_id: UUID,
    payload: EquivalentEvidenceRequest,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> EquivalentEvidenceResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    requirement = db.scalar(select(ClaimDocumentRequirement).where(
        ClaimDocumentRequirement.id == requirement_id,
        ClaimDocumentRequirement.organization_id == current_user.organization_id,
        ClaimDocumentRequirement.claim_id == claim.id,
        ClaimDocumentRequirement.is_active.is_(True),
    ))
    if requirement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document requirement not found")
    fact = db.scalar(select(ClaimFact).where(
        ClaimFact.id == payload.claim_fact_id,
        ClaimFact.organization_id == current_user.organization_id,
        ClaimFact.claim_id == claim.id,
    ))
    if fact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approved claim fact not found")
    try:
        requirement = accept_equivalent_evidence(
            db, claim=claim, requirement=requirement, claim_fact=fact, user=current_user, note=payload.note
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    response = DocumentRequirementResponse.model_validate(requirement).model_copy(
        update={"equivalent_evidence_candidates": equivalent_evidence_candidates(db, claim=claim, requirement=requirement)}
    )
    return EquivalentEvidenceResponse(requirement=response)
