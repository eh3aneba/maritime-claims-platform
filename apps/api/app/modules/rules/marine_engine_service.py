from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.policy_intelligence.service import build_policy_intelligence
from app.modules.rules.marine_engine import MARINE_REGISTRY_VERSION, MarineRuleStatus, evaluate_marine_rules, registry_hash
from app.modules.rules.marine_service import (
    _costs,
    _documents,
    _fact_rows,
    _latest_marine_run,
    _sync_marine_issues,
    _with_latest_decisions,
    record_marine_rule_decision,
)
from app.modules.rules.models import RuleEvaluationRun
from app.modules.users.models import User


def attach_marine_rules_to_run(
    db: Session,
    *,
    claim: Claim,
    user: User,
    run: RuleEvaluationRun,
) -> RuleEvaluationRun:
    if run.organization_id != claim.organization_id or run.claim_id != claim.id:
        raise ValueError("Rule evaluation run does not belong to this claim.")

    policy = build_policy_intelligence(
        db,
        claim_id=claim.id,
        organization_id=claim.organization_id,
    )
    evaluations = evaluate_marine_rules(
        claim=claim,
        fact_rows=_fact_rows(db, claim),
        documents=_documents(db, claim),
        costs=_costs(db, claim),
        policy=policy,
    )
    rows = [evaluation.to_dict() for evaluation in evaluations]
    counts = {
        status: sum(1 for row in rows if row["status"] == status)
        for status in ("triggered", "not_triggered", "insufficient_evidence", "not_applicable")
    }
    triggered = [row["rule_id"] for row in rows if row["status"] == MarineRuleStatus.TRIGGERED.value]
    active_marine_issues = _sync_marine_issues(
        db,
        claim=claim,
        evaluations=rows,
        now=datetime.now(UTC),
    )
    marine_summary: dict[str, Any] = {
        "marine_registry_version": MARINE_REGISTRY_VERSION,
        "marine_registry_hash": registry_hash(),
        "marine_rule_evaluations": rows,
        "marine_rule_counts": counts,
        "active_marine_issue_count": len(active_marine_issues),
        "policy_source_document_version_ids": [str(value) for value in policy.source_document_version_ids],
        "policy_term_count": len(policy.terms),
        "human_authority_boundary": (
            "Marine rule evaluations are explainable review prompts only. They do not determine coverage, liability, "
            "causation, recoverability, General Average contribution, total-loss status, reserve, settlement or payment. "
            "Policy, charterparty and contract prompts use only current human-approved wording; missing terms are not inferred."
        ),
    }
    combined_summary = dict(run.summary or {})
    combined_summary.update(marine_summary)
    run.summary = combined_summary
    run.triggered_rule_ids = list(dict.fromkeys(list(run.triggered_rule_ids or []) + triggered))

    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="EVALUATE_MARINE_RULES",
        entity_type="rule_evaluation_run",
        entity_id=run.id,
        new_values={
            "rule_run_id": str(run.id),
            "marine_registry_version": MARINE_REGISTRY_VERSION,
            "marine_registry_hash": marine_summary["marine_registry_hash"],
            "triggered_rule_ids": triggered,
            "counts": counts,
            "active_marine_issue_count": len(active_marine_issues),
            "policy_term_count": len(policy.terms),
        },
        details=(
            "Evaluated the composed, versioned Marine Rules Engine against controlled claim evidence and current "
            "human-approved policy/contract wording. The output remains non-authoritative decision support."
        ),
    )
    db.commit()
    db.refresh(run)
    return run


def latest_marine_rule_summary(db: Session, *, claim: Claim) -> dict[str, Any]:
    run = _latest_marine_run(db, claim=claim)
    if run is None:
        return {
            "marine_registry_version": MARINE_REGISTRY_VERSION,
            "marine_registry_hash": registry_hash(),
            "marine_rule_evaluations": [],
            "marine_rule_counts": {
                "triggered": 0,
                "not_triggered": 0,
                "insufficient_evidence": 0,
                "not_applicable": 0,
            },
            "active_marine_issue_count": 0,
            "policy_source_document_version_ids": [],
            "policy_term_count": 0,
            "marine_evaluated_at": None,
            "marine_rule_run_id": None,
            "human_authority_boundary": None,
        }
    summary = dict(run.summary or {})
    summary["marine_rule_evaluations"] = _with_latest_decisions(
        db,
        claim=claim,
        rows=list(summary.get("marine_rule_evaluations") or []),
    )
    summary["marine_evaluated_at"] = run.created_at
    summary["marine_rule_run_id"] = run.id
    return summary


__all__ = [
    "attach_marine_rules_to_run",
    "latest_marine_rule_summary",
    "record_marine_rule_decision",
]
