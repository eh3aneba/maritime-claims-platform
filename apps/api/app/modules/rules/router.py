from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.auth.dependencies import CurrentUser
from app.modules.claims.security import get_claim_for_tenant
from app.modules.claims.facts import ClaimFact
from app.modules.rules.marine_engine_service import latest_marine_rule_summary, record_marine_rule_decision
from app.modules.rules.models import ClaimDocumentRequirement, RuleEvaluationRun
from app.modules.rules.schemas import (
    EquivalentEvidenceRequest,
    EquivalentEvidenceResponse,
    MarineRuleDecisionResponse,
    MarineRuleDecisionWrite,
    MarineRuleEvaluationResponse,
    RequirementDecisionHistoryResponse,
    RequirementDecisionResponse,
    RuleEvaluationResponse,
    RuleSummaryResponse,
)
from app.modules.rules.service import (
    accept_equivalent_evidence,
    enrich_requirement_response,
    evaluate_claim_rules,
    get_requirement_state,
    get_rule_summary,
    list_requirement_decisions,
)

router = APIRouter(prefix="/claims/{claim_id}/rules", tags=["rules"])


def _summary_with_marine(db: Session, *, claim) -> RuleSummaryResponse:
    summary = get_rule_summary(db, claim=claim)
    marine = latest_marine_rule_summary(db, claim=claim)
    evaluations = [
        MarineRuleEvaluationResponse.model_validate(row)
        for row in marine.get("marine_rule_evaluations", [])
    ]
    return summary.model_copy(update={
        "marine_registry_version": marine.get("marine_registry_version"),
        "marine_registry_hash": marine.get("marine_registry_hash"),
        "marine_rule_evaluations": evaluations,
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
    return RuleEvaluationResponse(run_id=run.id, marine_run_id=run.id, summary=_summary_with_marine(db, claim=claim))


@router.post(
    "/runs/{run_id}/evaluations/{rule_id}/decision",
    response_model=MarineRuleDecisionResponse,
)
def decide_marine_rule_evaluation(
    claim_id: UUID,
    run_id: UUID,
    rule_id: str,
    payload: MarineRuleDecisionWrite,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> MarineRuleDecisionResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    run = db.scalar(
        select(RuleEvaluationRun).where(
            RuleEvaluationRun.id == run_id,
            RuleEvaluationRun.organization_id == current_user.organization_id,
            RuleEvaluationRun.claim_id == claim.id,
        )
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule evaluation run not found")
    try:
        decision = record_marine_rule_decision(
            db,
            claim=claim,
            run=run,
            rule_id=rule_id,
            payload=payload,
            user=current_user,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return MarineRuleDecisionResponse.model_validate(decision)


@router.get(
    "/requirements/{requirement_id}/decisions",
    response_model=RequirementDecisionHistoryResponse,
)
def requirement_decision_history(
    claim_id: UUID,
    requirement_id: UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> RequirementDecisionHistoryResponse:
    claim = get_claim_for_tenant(db, claim_id=claim_id, organization_id=current_user.organization_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    requirement = db.scalar(
        select(ClaimDocumentRequirement).where(
            ClaimDocumentRequirement.id == requirement_id,
            ClaimDocumentRequirement.organization_id == current_user.organization_id,
            ClaimDocumentRequirement.claim_id == claim.id,
            ClaimDocumentRequirement.is_active.is_(True),
        )
    )
    if requirement is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document requirement not found")
    state_row = get_requirement_state(db, requirement=requirement)
    if state_row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Requirement evidence state is not initialized. Re-evaluate claim rules and retry.",
        )
    decisions = list_requirement_decisions(db, requirement=requirement)
    return RequirementDecisionHistoryResponse(
        requirement_id=requirement.id,
        state_fingerprint=state_row.state_fingerprint,
        state_version=state_row.state_version,
        items=[RequirementDecisionResponse.model_validate(row) for row in decisions],
    )


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
        requirement, decision = accept_equivalent_evidence(
            db,
            claim=claim,
            requirement=requirement,
            claim_fact=fact,
            user=current_user,
            note=payload.note,
            expected_state_fingerprint=payload.expected_state_fingerprint,
            expected_state_version=payload.expected_state_version,
            expected_claim_fact_version=payload.claim_fact_version,
            re_review=payload.re_review,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return EquivalentEvidenceResponse(
        requirement=enrich_requirement_response(db, claim=claim, requirement=requirement),
        decision=RequirementDecisionResponse.model_validate(decision),
    )
