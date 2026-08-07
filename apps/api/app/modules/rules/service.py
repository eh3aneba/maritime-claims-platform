from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.rules.library import (
    DOCUMENT_RULES,
    RULESET_NAME,
    RULESET_VERSION,
    STATUS_RANK,
    TECH_OVERDUE,
    TECH_DEFERRED_MAINTENANCE,
    TECH_RECENT_OVERHAUL,
    TECH_TEMP_REPAIR,
    DocumentRule,
    IssueRuleMetadata,
)
from app.modules.rules.models import (
    ClaimDocumentRequirement,
    ClaimIssue,
    IssueStatus,
    RequirementPriority,
    RequirementStatus,
    RuleEvaluationRun,
)
from app.modules.rules.schemas import DocumentRequirementResponse, ReadinessResponse, RuleSummaryResponse
from app.modules.users.models import User


SATISFIED_STATUSES = {RequirementStatus.RECEIVED, RequirementStatus.UNDER_REVIEW, RequirementStatus.ACCEPTED}
PRIORITY_WEIGHT = {
    RequirementPriority.CRITICAL: 4,
    RequirementPriority.IMPORTANT: 2,
    RequirementPriority.SUPPORTING: 1,
}

EQUIVALENT_EVIDENCE_FACTS: dict[str, tuple[str, ...]] = {
    "maker_recommendation": ("maintenance.recommended_overhaul_interval",),
    "running_hours_record": ("maintenance.running_hours_since_overhaul",),
    "overhaul_report": ("maintenance.last_overhaul_date",),
}


def _current_facts(db: Session, claim: Claim) -> dict[str, Any]:
    facts = list(
        db.scalars(
            select(ClaimFact).where(
                ClaimFact.organization_id == claim.organization_id,
                ClaimFact.claim_id == claim.id,
            )
        )
    )
    return {fact.field_path: fact.value for fact in facts}


def _active_documents(db: Session, claim: Claim) -> list[Document]:
    return list(
        db.scalars(
            select(Document).where(
                Document.organization_id == claim.organization_id,
                Document.claim_id == claim.id,
                Document.deleted_at.is_(None),
            )
        )
    )


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        if "value" in value:
            return str(value.get("value") or "")
        return str(value)
    return str(value)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return bool(value)
    text = _text(value).strip().lower()
    return text in {"true", "yes", "y", "1", "attended", "approved", "required", "temporary"}


def _is_turbocharger(facts: dict[str, Any], claim: Claim) -> bool:
    candidates = [
        facts.get("equipment.type"),
        facts.get("equipment.name"),
        facts.get("engine_log.identification.engine_or_equipment"),
    ]
    if any("turbo" in _text(value).lower() for value in candidates):
        return True
    # Claim description is only a deterministic fallback for scope selection. It does
    # not become an authoritative technical fact.
    return "turbo" in (claim.incident_description or "").lower()


def _condition_applies(condition: str, *, facts: dict[str, Any], claim: Claim) -> bool:
    if condition == "always":
        return True
    if condition == "turbocharger":
        return _is_turbocharger(facts, claim)
    if condition == "towage":
        return _truthy(facts.get("operational_impact.towage"))
    if condition == "class_attended":
        return _truthy(facts.get("class.attended")) or _truthy(facts.get("class.approval_required"))
    if condition == "temporary_repair":
        return _truthy(facts.get("repair.temporary")) or _truthy(facts.get("temporary_repair"))
    return False


def _stage_applies(rule: DocumentRule, claim: Claim) -> bool:
    return STATUS_RANK[claim.status] >= STATUS_RANK[rule.required_from]


def _matched_document(documents: list[Document], document_type: str) -> Document | None:
    matches = [doc for doc in documents if doc.document_type == document_type]
    if not matches:
        return None
    matches.sort(key=lambda doc: doc.created_at, reverse=True)
    return matches[0]


def _upsert_requirement(
    db: Session,
    *,
    claim: Claim,
    rule: DocumentRule,
    matched: Document | None,
    now: datetime,
) -> ClaimDocumentRequirement:
    requirement = db.scalar(
        select(ClaimDocumentRequirement).where(
            ClaimDocumentRequirement.organization_id == claim.organization_id,
            ClaimDocumentRequirement.claim_id == claim.id,
            ClaimDocumentRequirement.rule_id == rule.rule_id,
            ClaimDocumentRequirement.document_type == rule.document_type,
        )
    )
    if requirement is None:
        requirement = ClaimDocumentRequirement(
            organization_id=claim.organization_id,
            claim_id=claim.id,
            rule_id=rule.rule_id,
            rule_version=RULESET_VERSION,
            document_type=rule.document_type,
            document_label=rule.label,
            priority=rule.priority,
            required_from_status=rule.required_from.value,
            reason=rule.reason,
            status=RequirementStatus.RECEIVED if matched else RequirementStatus.MISSING,
            matched_document_id=matched.id if matched else None,
            satisfaction_basis="direct_document" if matched else None,
            is_active=True,
            last_evaluated_at=now,
        )
        db.add(requirement)
        db.flush()
        return requirement

    requirement.rule_version = RULESET_VERSION
    requirement.document_label = rule.label
    requirement.priority = rule.priority
    requirement.required_from_status = rule.required_from.value
    requirement.reason = rule.reason
    requirement.is_active = True
    requirement.last_evaluated_at = now
    if matched is not None:
        requirement.matched_document_id = matched.id
        requirement.satisfaction_basis = "direct_document"
        requirement.equivalent_claim_fact_id = None
        requirement.satisfaction_note = None
        requirement.satisfied_by_id = None
        requirement.satisfied_at = None
        if requirement.status not in {RequirementStatus.UNDER_REVIEW}:
            requirement.status = RequirementStatus.RECEIVED
    else:
        requirement.matched_document_id = None
        if requirement.satisfaction_basis == "equivalent_evidence" and requirement.equivalent_claim_fact_id is not None:
            requirement.status = RequirementStatus.ACCEPTED
        elif requirement.status not in {RequirementStatus.REQUESTED, RequirementStatus.REJECTED}:
            requirement.status = RequirementStatus.MISSING
    return requirement


def _sync_document_requirements(
    db: Session,
    *,
    claim: Claim,
    facts: dict[str, Any],
    documents: list[Document],
    now: datetime,
) -> tuple[list[ClaimDocumentRequirement], list[str]]:
    existing = list(
        db.scalars(
            select(ClaimDocumentRequirement).where(
                ClaimDocumentRequirement.organization_id == claim.organization_id,
                ClaimDocumentRequirement.claim_id == claim.id,
            )
        )
    )
    for requirement in existing:
        requirement.is_active = False
        requirement.last_evaluated_at = now

    active: list[ClaimDocumentRequirement] = []
    triggered: list[str] = []
    for rule in DOCUMENT_RULES:
        if not _stage_applies(rule, claim):
            continue
        if not _condition_applies(rule.condition, facts=facts, claim=claim):
            continue
        matched = _matched_document(documents, rule.document_type)
        requirement = _upsert_requirement(db, claim=claim, rule=rule, matched=matched, now=now)
        active.append(requirement)
        triggered.append(rule.rule_id)
    return active, triggered


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, str):
        stripped = value.strip().lower().replace(",", "")
        for suffix in ("hours", "hour", "hrs", "hr", "h"):
            if stripped.endswith(suffix):
                stripped = stripped[: -len(suffix)].strip()
                break
        value = stripped
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _date_value(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, dict):
        value = value.get("value")
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _issue_key(rule: IssueRuleMetadata) -> str:
    return rule.rule_id.lower().replace("-", "_")


def _upsert_issue(
    db: Session,
    *,
    claim: Claim,
    rule: IssueRuleMetadata,
    description: str,
    evidence: dict[str, Any],
    now: datetime,
) -> ClaimIssue:
    key = _issue_key(rule)
    issue = db.scalar(
        select(ClaimIssue).where(
            ClaimIssue.organization_id == claim.organization_id,
            ClaimIssue.claim_id == claim.id,
            ClaimIssue.issue_key == key,
        )
    )
    if issue is None:
        issue = ClaimIssue(
            organization_id=claim.organization_id,
            claim_id=claim.id,
            issue_key=key,
            rule_id=rule.rule_id,
            rule_version=RULESET_VERSION,
            category=rule.category,
            title=rule.title,
            description=description,
            severity=rule.severity,
            status=IssueStatus.OPEN,
            evidence=evidence,
            explanation=rule.explanation,
            is_active=True,
            last_triggered_at=now,
        )
        db.add(issue)
        db.flush()
        return issue

    was_active = issue.is_active
    issue.rule_version = RULESET_VERSION
    issue.title = rule.title
    issue.description = description
    issue.severity = rule.severity
    issue.evidence = evidence
    issue.explanation = rule.explanation
    issue.is_active = True
    issue.last_triggered_at = now
    if not was_active and issue.status in {IssueStatus.RESOLVED, IssueStatus.DISMISSED}:
        issue.status = IssueStatus.OPEN
    return issue


def _sync_issues(
    db: Session,
    *,
    claim: Claim,
    facts: dict[str, Any],
    now: datetime,
) -> tuple[list[ClaimIssue], list[str]]:
    existing = list(
        db.scalars(
            select(ClaimIssue).where(
                ClaimIssue.organization_id == claim.organization_id,
                ClaimIssue.claim_id == claim.id,
            )
        )
    )
    for issue in existing:
        issue.is_active = False

    active: list[ClaimIssue] = []
    triggered: list[str] = []

    running_hours = _decimal(facts.get("maintenance.running_hours_since_overhaul"))
    interval = _decimal(facts.get("maintenance.recommended_overhaul_interval"))
    if running_hours is not None and interval is not None and interval > 0 and running_hours > interval:
        variance = running_hours - interval
        issue = _upsert_issue(
            db,
            claim=claim,
            rule=TECH_OVERDUE,
            description=f"Reviewed running hours since overhaul ({running_hours} h) exceed the reviewed recommended interval ({interval} h) by {variance} h.",
            evidence={
                "running_hours_since_overhaul": str(running_hours),
                "recommended_overhaul_interval": str(interval),
                "variance_hours": str(variance),
            },
            now=now,
        )
        active.append(issue)
        triggered.append(TECH_OVERDUE.rule_id)

    overhaul_date = _date_value(facts.get("maintenance.last_overhaul_date"))
    if overhaul_date is not None and overhaul_date <= claim.incident_date:
        days = (claim.incident_date - overhaul_date).days
        if days <= 90:
            issue = _upsert_issue(
                db,
                claim=claim,
                rule=TECH_RECENT_OVERHAUL,
                description=f"The casualty occurred {days} days after the reviewed last overhaul date ({overhaul_date.isoformat()}).",
                evidence={"last_overhaul_date": overhaul_date.isoformat(), "incident_date": claim.incident_date.isoformat(), "days_between": days},
                now=now,
            )
            active.append(issue)
            triggered.append(TECH_RECENT_OVERHAUL.rule_id)

    if facts.get("maintenance.overhaul_deferred") is True or "defer" in str(facts.get("maintenance.pms_status") or "").lower():
        issue = _upsert_issue(
            db, claim=claim, rule=TECH_DEFERRED_MAINTENANCE,
            description="Human-reviewed PMS evidence indicates that relevant maintenance was deferred.",
            evidence={"overhaul_deferred": facts.get("maintenance.overhaul_deferred"), "pms_status": facts.get("maintenance.pms_status")},
            now=now,
        )
        active.append(issue); triggered.append(TECH_DEFERRED_MAINTENANCE.rule_id)

    if _condition_applies("temporary_repair", facts=facts, claim=claim):
        issue = _upsert_issue(
            db,
            claim=claim,
            rule=TECH_TEMP_REPAIR,
            description="Reviewed claim facts indicate that a temporary repair has been performed or remains in place.",
            evidence={"temporary_repair": True},
            now=now,
        )
        active.append(issue)
        triggered.append(TECH_TEMP_REPAIR.rule_id)

    return active, triggered


def calculate_readiness(requirements: list[ClaimDocumentRequirement]) -> ReadinessResponse:
    active = [requirement for requirement in requirements if requirement.is_active]
    total_weight = sum(PRIORITY_WEIGHT[requirement.priority] for requirement in active)
    satisfied_weight = sum(
        PRIORITY_WEIGHT[requirement.priority]
        for requirement in active
        if requirement.status in SATISFIED_STATUSES
    )
    doc_score = round((satisfied_weight / total_weight) * 90) if total_weight else 90
    score = min(100, 10 + doc_score)  # Core claim intake fields account for 10 points and are mandatory at claim creation.
    critical_missing = [
        requirement for requirement in active
        if requirement.priority == RequirementPriority.CRITICAL and requirement.status not in SATISFIED_STATUSES
    ]
    important_missing = [
        requirement for requirement in active
        if requirement.priority == RequirementPriority.IMPORTANT and requirement.status not in SATISFIED_STATUSES
    ]
    if critical_missing:
        state = "not_ready"
    elif important_missing:
        state = "limited"
    else:
        state = "ready"
    return ReadinessResponse(
        score=score,
        state=state,
        critical_missing_count=len(critical_missing),
        important_missing_count=len(important_missing),
        blocking_items=[requirement.document_label for requirement in critical_missing],
        satisfied_weight=satisfied_weight,
        total_weight=total_weight,
    )


def evaluate_claim_rules(db: Session, *, claim: Claim, user: User, trigger: str = "manual") -> RuleEvaluationRun:
    now = datetime.now(UTC)
    facts = _current_facts(db, claim)
    documents = _active_documents(db, claim)
    requirements, document_rule_ids = _sync_document_requirements(db, claim=claim, facts=facts, documents=documents, now=now)
    issues, issue_rule_ids = _sync_issues(db, claim=claim, facts=facts, now=now)
    # Keep rule-driven document-request tasks synchronized with evidence receipt.
    from app.modules.tasks.service import sync_requirement_tasks
    sync_requirement_tasks(db, claim=claim, user=user)
    readiness = calculate_readiness(requirements)
    triggered = list(dict.fromkeys(document_rule_ids + issue_rule_ids))
    summary = {
        "readiness_score": readiness.score,
        "readiness_state": readiness.state,
        "critical_missing_count": readiness.critical_missing_count,
        "important_missing_count": readiness.important_missing_count,
        "active_requirement_count": len(requirements),
        "active_issue_count": len(issues),
    }
    run = RuleEvaluationRun(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        evaluated_by_id=user.id,
        ruleset_name=RULESET_NAME,
        ruleset_version=RULESET_VERSION,
        trigger=trigger,
        triggered_rule_ids=triggered,
        summary=summary,
        created_at=now,
    )
    db.add(run)
    db.flush()
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="EVALUATE_CLAIM_RULES",
        entity_type="claim",
        entity_id=claim.id,
        new_values={"rule_run_id": str(run.id), "ruleset_version": RULESET_VERSION, **summary},
    )
    db.commit()
    db.refresh(run)
    return run



def equivalent_evidence_candidates(db: Session, *, claim: Claim, requirement: ClaimDocumentRequirement) -> list[dict[str, Any]]:
    allowed = EQUIVALENT_EVIDENCE_FACTS.get(requirement.document_type, ())
    if not allowed:
        return []
    rows = list(db.scalars(select(ClaimFact).where(
        ClaimFact.organization_id == claim.organization_id,
        ClaimFact.claim_id == claim.id,
        ClaimFact.field_path.in_(allowed),
    )))
    return [
        {
            "claim_fact_id": str(row.id),
            "field_path": row.field_path,
            "value": row.value,
            "source_document_id": str(row.source_document_id),
            "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        }
        for row in rows
    ]


def accept_equivalent_evidence(
    db: Session,
    *,
    claim: Claim,
    requirement: ClaimDocumentRequirement,
    claim_fact: ClaimFact,
    user: User,
    note: str,
) -> ClaimDocumentRequirement:
    if requirement.organization_id != claim.organization_id or requirement.claim_id != claim.id or not requirement.is_active:
        raise ValueError("Document requirement not found for this claim.")
    if claim_fact.organization_id != claim.organization_id or claim_fact.claim_id != claim.id:
        raise ValueError("Equivalent evidence must belong to the same claim and organization.")
    allowed = EQUIVALENT_EVIDENCE_FACTS.get(requirement.document_type, ())
    if claim_fact.field_path not in allowed:
        raise ValueError("The selected approved claim fact is not an accepted equivalent for this requirement.")
    if len((note or "").strip()) < 5:
        raise ValueError("A short justification is required when accepting equivalent evidence.")
    old = {
        "status": requirement.status.value,
        "satisfaction_basis": requirement.satisfaction_basis,
        "equivalent_claim_fact_id": str(requirement.equivalent_claim_fact_id) if requirement.equivalent_claim_fact_id else None,
    }
    requirement.status = RequirementStatus.ACCEPTED
    requirement.satisfaction_basis = "equivalent_evidence"
    requirement.satisfaction_note = note.strip()
    requirement.equivalent_claim_fact_id = claim_fact.id
    requirement.matched_document_id = None
    requirement.satisfied_by_id = user.id
    requirement.satisfied_at = datetime.now(UTC)
    from app.modules.tasks.service import sync_requirement_tasks
    sync_requirement_tasks(db, claim=claim, user=user)
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="ACCEPT_EQUIVALENT_EVIDENCE",
        entity_type="claim_document_requirement",
        entity_id=requirement.id,
        old_values=old,
        new_values={
            "status": requirement.status.value,
            "satisfaction_basis": requirement.satisfaction_basis,
            "claim_fact_id": str(claim_fact.id),
            "field_path": claim_fact.field_path,
            "note": requirement.satisfaction_note,
        },
    )
    db.commit()
    db.refresh(requirement)
    return requirement

def get_rule_summary(db: Session, *, claim: Claim) -> RuleSummaryResponse:
    requirements = list(
        db.scalars(
            select(ClaimDocumentRequirement).where(
                ClaimDocumentRequirement.organization_id == claim.organization_id,
                ClaimDocumentRequirement.claim_id == claim.id,
                ClaimDocumentRequirement.is_active.is_(True),
            ).order_by(ClaimDocumentRequirement.priority.asc(), ClaimDocumentRequirement.document_label.asc())
        )
    )
    issues = list(
        db.scalars(
            select(ClaimIssue).where(
                ClaimIssue.organization_id == claim.organization_id,
                ClaimIssue.claim_id == claim.id,
                ClaimIssue.is_active.is_(True),
            ).order_by(ClaimIssue.severity.desc(), ClaimIssue.created_at.asc())
        )
    )
    latest_run = db.scalar(
        select(RuleEvaluationRun).where(
            RuleEvaluationRun.organization_id == claim.organization_id,
            RuleEvaluationRun.claim_id == claim.id,
        ).order_by(RuleEvaluationRun.created_at.desc()).limit(1)
    )
    return RuleSummaryResponse(
        ruleset_name=RULESET_NAME,
        ruleset_version=RULESET_VERSION,
        claim_id=claim.id,
        evaluated_at=latest_run.created_at if latest_run else None,
        requirements=[
            DocumentRequirementResponse.model_validate(row).model_copy(
                update={"equivalent_evidence_candidates": equivalent_evidence_candidates(db, claim=claim, requirement=row)}
            )
            for row in requirements
        ],
        issues=issues,
        readiness=calculate_readiness(requirements),
        triggered_rule_ids=list(latest_run.triggered_rule_ids or []) if latest_run else [],
    )
