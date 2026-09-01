from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.financial.models import CostItem
from app.modules.rules.marine_registry import MARINE_REGISTRY_VERSION, evaluate_marine_rules, registry_hash
from app.modules.rules.models import RuleEvaluationRun
from app.modules.users.models import User


def _fact_rows(db: Session, claim: Claim) -> list[ClaimFact]:
    return list(
        db.scalars(
            select(ClaimFact).where(
                ClaimFact.organization_id == claim.organization_id,
                ClaimFact.claim_id == claim.id,
            ).order_by(ClaimFact.field_path.asc())
        )
    )


def _documents(db: Session, claim: Claim) -> list[Document]:
    return list(
        db.scalars(
            select(Document).where(
                Document.organization_id == claim.organization_id,
                Document.claim_id == claim.id,
                Document.deleted_at.is_(None),
                Document.is_current.is_(True),
            ).order_by(Document.created_at.asc())
        )
    )


def _costs(db: Session, claim: Claim) -> list[CostItem]:
    return list(
        db.scalars(
            select(CostItem).where(
                CostItem.organization_id == claim.organization_id,
                CostItem.claim_id == claim.id,
            ).order_by(CostItem.created_at.asc(), CostItem.line_index.asc())
        )
    )


def attach_marine_rules_to_run(
    db: Session,
    *,
    claim: Claim,
    user: User,
    run: RuleEvaluationRun,
) -> RuleEvaluationRun:
    if run.organization_id != claim.organization_id or run.claim_id != claim.id:
        raise ValueError("Rule evaluation run does not belong to this claim.")

    evaluations = evaluate_marine_rules(
        claim=claim,
        fact_rows=_fact_rows(db, claim),
        documents=_documents(db, claim),
        costs=_costs(db, claim),
    )
    rows = [evaluation.to_dict() for evaluation in evaluations]
    counts = {status: sum(1 for row in rows if row["status"] == status) for status in (
        "triggered", "not_triggered", "insufficient_evidence", "not_applicable"
    )}
    triggered = [row["rule_id"] for row in rows if row["status"] == "triggered"]
    marine_summary: dict[str, Any] = {
        "marine_registry_version": MARINE_REGISTRY_VERSION,
        "marine_registry_hash": registry_hash(),
        "marine_rule_evaluations": rows,
        "marine_rule_counts": counts,
        "human_authority_boundary": (
            "Marine rule evaluations are explainable review prompts only. They do not determine coverage, liability, "
            "causation, recoverability, General Average contribution, total-loss status, reserve, settlement or payment."
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
        },
    )
    db.commit()
    db.refresh(run)
    return run


def latest_marine_rule_summary(db: Session, *, claim: Claim) -> dict[str, Any]:
    runs = list(
        db.scalars(
            select(RuleEvaluationRun).where(
                RuleEvaluationRun.organization_id == claim.organization_id,
                RuleEvaluationRun.claim_id == claim.id,
            ).order_by(RuleEvaluationRun.created_at.desc())
        )
    )
    run = next((row for row in runs if (row.summary or {}).get("marine_registry_version")), None)
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
            "marine_evaluated_at": None,
            "marine_rule_run_id": None,
            "human_authority_boundary": None,
        }
    summary = dict(run.summary or {})
    summary["marine_evaluated_at"] = run.created_at
    summary["marine_rule_run_id"] = run.id
    return summary
