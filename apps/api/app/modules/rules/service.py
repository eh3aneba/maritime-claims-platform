from __future__ import annotations

from sqlalchemy import select

from app.modules.rules import service_core as _core
from app.modules.rules.models import ClaimDocumentRequirement, RuleEvaluationRun
from app.modules.rules.requirement_lineage import (
    accept_equivalent_evidence_with_lineage,
    get_requirement_state,
    latest_requirement_decision,
    list_requirement_decisions,
    sync_claim_requirement_states,
)
from app.modules.rules.schemas import DocumentRequirementResponse, RequirementDecisionResponse

# Preserve the established rules-service surface while replacing only the small
# set of Phase 13.4B functions that must add evidence-state lineage.
_OVERRIDDEN = {
    "evaluate_claim_rules",
    "accept_equivalent_evidence",
    "equivalent_evidence_candidates",
    "get_rule_summary",
}
for _name in dir(_core):
    if not _name.startswith("__") and _name not in _OVERRIDDEN:
        globals()[_name] = getattr(_core, _name)


def _active_requirements(db, *, claim) -> list[ClaimDocumentRequirement]:
    return list(
        db.scalars(
            select(ClaimDocumentRequirement).where(
                ClaimDocumentRequirement.organization_id == claim.organization_id,
                ClaimDocumentRequirement.claim_id == claim.id,
                ClaimDocumentRequirement.is_active.is_(True),
            )
        )
    )


def _update_run_readiness(db, *, claim, run: RuleEvaluationRun) -> None:
    requirements = _active_requirements(db, claim=claim)
    readiness = _core.calculate_readiness(requirements)
    summary = dict(run.summary or {})
    summary.update(
        {
            "readiness_score": readiness.score,
            "readiness_state": readiness.state,
            "critical_missing_count": readiness.critical_missing_count,
            "important_missing_count": readiness.important_missing_count,
            "active_requirement_count": len(requirements),
        }
    )
    run.summary = summary


def evaluate_claim_rules(db, *, claim, user, trigger: str = "manual"):
    """Evaluate core rules, reconcile requirement lineage, then attach marine rules.

    The core evaluator remains the deterministic source of requirement activation
    and current operational state. Phase 13.4B adds an evidence-state identity and
    append-only human decision history after that evaluation, without introducing
    a second rules engine or changing the claims-authority boundary.
    """

    run = _core.evaluate_claim_rules(db, claim=claim, user=user, trigger=trigger)
    lineage_changed = sync_claim_requirement_states(db, claim=claim, user=user)
    if lineage_changed:
        from app.modules.tasks.service import sync_requirement_tasks

        sync_requirement_tasks(db, claim=claim, user=user)
    _update_run_readiness(db, claim=claim, run=run)
    db.commit()
    db.refresh(run)

    from app.modules.rules.marine_engine_service import attach_marine_rules_to_run

    return attach_marine_rules_to_run(db, claim=claim, user=user, run=run)


def equivalent_evidence_candidates(db, *, claim, requirement: ClaimDocumentRequirement) -> list[dict]:
    candidates = _core.equivalent_evidence_candidates(db, claim=claim, requirement=requirement)
    if not candidates:
        return []
    fact_ids = [row["claim_fact_id"] for row in candidates]
    from app.modules.claims.facts import ClaimFact

    facts = {
        str(row.id): row
        for row in db.scalars(
            select(ClaimFact).where(
                ClaimFact.organization_id == claim.organization_id,
                ClaimFact.claim_id == claim.id,
                ClaimFact.id.in_(fact_ids),
            )
        )
    }
    return [
        {
            **row,
            "claim_fact_version": facts[str(row["claim_fact_id"])].version
            if str(row["claim_fact_id"]) in facts
            else None,
        }
        for row in candidates
    ]


def enrich_requirement_response(db, *, claim, requirement: ClaimDocumentRequirement) -> DocumentRequirementResponse:
    state = get_requirement_state(db, requirement=requirement)
    decision = latest_requirement_decision(db, requirement=requirement)
    return DocumentRequirementResponse.model_validate(requirement).model_copy(
        update={
            "equivalent_evidence_candidates": equivalent_evidence_candidates(
                db, claim=claim, requirement=requirement
            ),
            "state_fingerprint": state.state_fingerprint if state else None,
            "state_version": state.state_version if state else None,
            "latest_decision": RequirementDecisionResponse.model_validate(decision) if decision else None,
        }
    )


def get_rule_summary(db, *, claim):
    summary = _core.get_rule_summary(db, claim=claim)
    requirements = _active_requirements(db, claim=claim)
    return summary.model_copy(
        update={
            "requirements": [
                enrich_requirement_response(db, claim=claim, requirement=requirement)
                for requirement in requirements
            ],
            "readiness": _core.calculate_readiness(requirements),
        }
    )


def accept_equivalent_evidence(
    db,
    *,
    claim,
    requirement,
    claim_fact,
    user,
    note: str,
    expected_state_fingerprint: str,
    expected_state_version: int,
    expected_claim_fact_version: int,
    re_review: bool = False,
):
    return accept_equivalent_evidence_with_lineage(
        db,
        claim=claim,
        requirement=requirement,
        claim_fact=claim_fact,
        user=user,
        note=note,
        expected_state_fingerprint=expected_state_fingerprint,
        expected_state_version=expected_state_version,
        expected_claim_fact_version=expected_claim_fact_version,
        re_review=re_review,
    )
