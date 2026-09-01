from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.financial.models import CostItem
from app.modules.rules.marine_registry import MARINE_REGISTRY_VERSION, MarineRuleStatus, evaluate_marine_rules, registry_hash
from app.modules.rules.models import ClaimIssue, IssueCategory, IssueSeverity, IssueStatus, RuleEvaluationRun
from app.modules.users.models import User


_CORE_TECH_ISSUES = {"TECH-001", "TECH-002", "TECH-003", "TECH-006"}
_FAMILY_CATEGORY = {
    "hm_machinery": IssueCategory.TECHNICAL,
    "hm_repairs": IssueCategory.TECHNICAL,
    "aaa_rules": IssueCategory.FINANCIAL,
    "policy_mia": IssueCategory.INSURANCE,
    "general_average": IssueCategory.INSURANCE,
    "emergency_services": IssueCategory.OPERATIONAL,
    "charterparty": IssueCategory.OPERATIONAL,
}
_HIGH_REVIEW_RULES = {"TECH-002", "MIA-S78", "MARINE-EMERGENCY-001", "GA-YAR-001", "POLICY-TL-001"}


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


def _issue_key(rule_id: str) -> str:
    return f"marine_{rule_id.lower().replace('-', '_')}"


def _issue_title(row: dict[str, Any]) -> str:
    label = row["topic"].replace("_", " ").strip().title()
    prefix = "Evidence gap" if row["status"] == MarineRuleStatus.INSUFFICIENT_EVIDENCE.value else "Marine review"
    return f"{prefix}: {row['source_reference']} — {label}"


def _sync_marine_issues(
    db: Session,
    *,
    claim: Claim,
    evaluations: list[dict[str, Any]],
    now: datetime,
) -> list[ClaimIssue]:
    existing = {
        row.issue_key: row
        for row in db.scalars(
            select(ClaimIssue).where(
                ClaimIssue.organization_id == claim.organization_id,
                ClaimIssue.claim_id == claim.id,
                ClaimIssue.issue_key.like("marine_%"),
            )
        )
    }
    active: list[ClaimIssue] = []
    active_statuses = {MarineRuleStatus.TRIGGERED.value, MarineRuleStatus.INSUFFICIENT_EVIDENCE.value}

    for row in evaluations:
        if row["rule_id"] in _CORE_TECH_ISSUES:
            continue
        key = _issue_key(row["rule_id"])
        issue = existing.get(key)
        should_be_active = row["status"] in active_statuses
        if not should_be_active:
            if issue is not None:
                issue.is_active = False
            continue

        category = IssueCategory.EVIDENCE if row["status"] == MarineRuleStatus.INSUFFICIENT_EVIDENCE.value else _FAMILY_CATEGORY.get(
            row["family"], IssueCategory.INSURANCE
        )
        severity = IssueSeverity.HIGH if row["rule_id"] in _HIGH_REVIEW_RULES and row["status"] == MarineRuleStatus.TRIGGERED.value else IssueSeverity.MEDIUM
        explanation = (
            f"{row['candidate_implication']} Required human action: {row['recommended_action']} "
            "This issue is generated from a versioned marine rule evaluation and is not a coverage, liability, causation or recoverability decision."
        )
        evidence = {
            "marine_rule_status": row["status"],
            "definition_hash": row["definition_hash"],
            "evaluation_hash": row["evaluation_hash"],
            "source_title": row["source_title"],
            "source_reference": row["source_reference"],
            "evidence_used": row["evidence_used"],
            "missing_prerequisites": row["missing_prerequisites"],
        }

        if issue is None:
            issue = ClaimIssue(
                organization_id=claim.organization_id,
                claim_id=claim.id,
                issue_key=key,
                rule_id=row["rule_id"],
                rule_version=row["rule_version"],
                category=category,
                title=_issue_title(row),
                description=row["rationale"],
                severity=severity,
                status=IssueStatus.OPEN,
                evidence=evidence,
                explanation=explanation,
                is_active=True,
                last_triggered_at=now,
            )
            db.add(issue)
            db.flush()
            existing[key] = issue
        else:
            was_active = issue.is_active
            issue.rule_version = row["rule_version"]
            issue.category = category
            issue.title = _issue_title(row)
            issue.description = row["rationale"]
            issue.severity = severity
            issue.evidence = evidence
            issue.explanation = explanation
            issue.is_active = True
            issue.last_triggered_at = now
            if not was_active and issue.status in {IssueStatus.RESOLVED, IssueStatus.DISMISSED}:
                issue.status = IssueStatus.OPEN
        active.append(issue)

    for key, issue in existing.items():
        if issue not in active and key.startswith("marine_"):
            issue.is_active = False
    return active


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
    active_marine_issues = _sync_marine_issues(db, claim=claim, evaluations=rows, now=datetime.now(UTC))
    marine_summary: dict[str, Any] = {
        "marine_registry_version": MARINE_REGISTRY_VERSION,
        "marine_registry_hash": registry_hash(),
        "marine_rule_evaluations": rows,
        "marine_rule_counts": counts,
        "active_marine_issue_count": len(active_marine_issues),
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
            "active_marine_issue_count": len(active_marine_issues),
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
            "active_marine_issue_count": 0,
            "marine_evaluated_at": None,
            "marine_rule_run_id": None,
            "human_authority_boundary": None,
        }
    summary = dict(run.summary or {})
    summary["marine_evaluated_at"] = run.created_at
    summary["marine_rule_run_id"] = run.id
    return summary
