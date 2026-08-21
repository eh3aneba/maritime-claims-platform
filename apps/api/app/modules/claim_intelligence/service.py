from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.chronology.models import ChronologyEvent, EvidenceConflict, EventEvidence
from app.modules.chronology.service import BUILD_VERSION as CHRONOLOGY_BUILD_VERSION, build_chronology
from app.modules.claim_intelligence.models import (
    ClaimIntelligenceItem,
    ClaimIntelligenceItemDecision,
    ClaimIntelligenceSnapshot,
)
from app.modules.claim_intelligence.schemas import ClaimIntelligenceDecisionWrite
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.financial.models import CostItem, FinancialFlag
from app.modules.policy_intelligence.service import build_policy_intelligence
from app.modules.rules.library import RULESET_VERSION
from app.modules.rules.models import ClaimDocumentRequirement, ClaimIssue
from app.modules.rules.service import evaluate_claim_rules
from app.modules.tasks.models import ClaimTask, TaskPriority, TaskSource, TaskStatus, TaskType
from app.modules.users.models import User

ENGINE_VERSION = "12A.1"
DISCLAIMER = (
    "Claims Intelligence is source-linked decision support only. It does not determine coverage, liability, causation, "
    "recoverability, reserve, settlement, payment, fraud or recovery. Candidate facts and actions remain non-authoritative "
    "until a human handler reviews the underlying evidence and takes an explicit controlled action."
)

_SEVERITY_SCORE = {"info": 20, "low": 35, "medium": 55, "high": 80, "critical": 100}
_MATERIALITY_TO_SEVERITY = {"low": "low", "medium": "medium", "high": "high", "critical": "critical"}
_TASK_PRIORITY = {
    "info": TaskPriority.LOW,
    "low": TaskPriority.LOW,
    "medium": TaskPriority.MEDIUM,
    "high": TaskPriority.HIGH,
    "critical": TaskPriority.CRITICAL,
}
_ISSUE_FACT_PATHS = {
    "TECH-001": ("maintenance.running_hours_since_overhaul", "maintenance.recommended_overhaul_interval"),
    "TECH-002": ("maintenance.last_overhaul_date",),
    "TECH-003": ("maintenance.overhaul_deferred", "maintenance.pms_status"),
    "TECH-006": ("repair.temporary", "temporary_repair"),
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "value") and not isinstance(value, (str, bytes, dict, list, tuple)):
        return value.value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(_jsonable(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _rank(urgency: int, evidence: int) -> int:
    return max(0, min(100, round((urgency * 0.55) + (evidence * 0.45))))


def _source(kind: str, identifier: Any, **extra: Any) -> dict:
    payload = {"kind": kind, "id": str(identifier)}
    payload.update({key: _jsonable(value) for key, value in extra.items() if value is not None})
    return payload


def _item(
    *, key: str, category: str, title: str, description: str, severity: str,
    urgency: int, evidence: int, rationale: str, sources: list[dict],
    action_type: str | None = None, suggested_action: str | None = None,
    related_entity_type: str | None = None, related_entity_id: UUID | None = None,
) -> dict:
    payload = {
        "item_key": key,
        "category": category,
        "title": title.strip(),
        "description": description.strip(),
        "severity": severity,
        "urgency_score": urgency,
        "evidential_value_score": evidence,
        "rank_score": _rank(urgency, evidence),
        "rationale": rationale.strip(),
        "source_refs": sources,
        "action_type": action_type,
        "suggested_action": suggested_action.strip() if suggested_action else None,
        "related_entity_type": related_entity_type,
        "related_entity_id": related_entity_id,
    }
    payload["item_hash"] = _hash(payload)
    return payload


def _fact_source(fact: ClaimFact) -> dict:
    return _source(
        "claim_fact", fact.id, field_path=fact.field_path, document_id=fact.source_document_id,
        extraction_id=fact.source_extraction_id, segment_id=fact.source_segment_id, version=fact.version,
    )


def _load_sources(db: Session, claim: Claim) -> dict[str, Any]:
    facts = list(db.scalars(select(ClaimFact).where(
        ClaimFact.organization_id == claim.organization_id, ClaimFact.claim_id == claim.id,
    ).order_by(ClaimFact.field_path.asc())))
    documents = list(db.scalars(select(Document).where(
        Document.organization_id == claim.organization_id, Document.claim_id == claim.id,
        Document.deleted_at.is_(None), Document.is_current.is_(True),
    ).order_by(Document.document_type.asc().nulls_last(), Document.created_at.asc())))
    requirements = list(db.scalars(select(ClaimDocumentRequirement).where(
        ClaimDocumentRequirement.organization_id == claim.organization_id,
        ClaimDocumentRequirement.claim_id == claim.id,
        ClaimDocumentRequirement.is_active.is_(True),
    ).order_by(ClaimDocumentRequirement.priority.asc(), ClaimDocumentRequirement.document_label.asc())))
    issues = list(db.scalars(select(ClaimIssue).where(
        ClaimIssue.organization_id == claim.organization_id, ClaimIssue.claim_id == claim.id,
        ClaimIssue.is_active.is_(True),
    ).order_by(ClaimIssue.severity.desc(), ClaimIssue.created_at.asc())))
    events = list(db.scalars(select(ChronologyEvent).where(
        ChronologyEvent.organization_id == claim.organization_id, ChronologyEvent.claim_id == claim.id,
        ChronologyEvent.is_active.is_(True),
    ).order_by(ChronologyEvent.occurred_on.asc().nulls_last(), ChronologyEvent.occurred_time.asc().nulls_last(), ChronologyEvent.created_at.asc())))
    event_evidence = list(db.scalars(select(EventEvidence).where(
        EventEvidence.organization_id == claim.organization_id, EventEvidence.claim_id == claim.id,
    )))
    conflicts = list(db.scalars(select(EvidenceConflict).where(
        EvidenceConflict.organization_id == claim.organization_id, EvidenceConflict.claim_id == claim.id,
        EvidenceConflict.is_active.is_(True),
    ).order_by(EvidenceConflict.materiality.desc(), EvidenceConflict.created_at.asc())))
    costs = list(db.scalars(select(CostItem).where(
        CostItem.organization_id == claim.organization_id, CostItem.claim_id == claim.id,
    ).order_by(CostItem.created_at.asc())))
    flags = list(db.scalars(select(FinancialFlag).where(
        FinancialFlag.organization_id == claim.organization_id, FinancialFlag.claim_id == claim.id,
        FinancialFlag.status == "open",
    ).order_by(FinancialFlag.created_at.asc())))
    return {
        "facts": facts, "documents": documents, "requirements": requirements, "issues": issues,
        "events": events, "event_evidence": event_evidence, "conflicts": conflicts, "costs": costs, "flags": flags,
    }


def _source_state(claim: Claim, data: dict[str, Any], policy: Any) -> dict:
    return {
        "claim": {
            "id": str(claim.id), "status": claim.status.value, "incident_date": claim.incident_date.isoformat(),
            "notification_date": claim.notification_date.isoformat(), "incident_description": claim.incident_description,
            "estimated_loss": str(claim.estimated_loss) if claim.estimated_loss is not None else None,
            "current_reserve": str(claim.current_reserve) if claim.current_reserve is not None else None,
            "currency": claim.currency,
        },
        "facts": [{
            "id": str(x.id), "field": x.field_path, "value": x.value, "version": x.version,
            "document": str(x.source_document_id), "extraction": str(x.source_extraction_id),
            "segment": str(x.source_segment_id) if x.source_segment_id else None,
        } for x in data["facts"]],
        "documents": [{
            "id": str(x.id), "type": x.document_type, "hash": x.file_hash, "version": x.version_number,
            "processing": x.processing_status.value, "confidentiality": x.confidentiality_level.value,
        } for x in data["documents"]],
        "requirements": [{
            "id": str(x.id), "rule": x.rule_id, "type": x.document_type, "priority": x.priority.value,
            "status": x.status.value, "matched_document": str(x.matched_document_id) if x.matched_document_id else None,
            "equivalent_fact": str(x.equivalent_claim_fact_id) if x.equivalent_claim_fact_id else None,
        } for x in data["requirements"]],
        "issues": [{
            "id": str(x.id), "rule": x.rule_id, "severity": x.severity.value, "status": x.status.value,
            "description": x.description, "evidence": x.evidence,
        } for x in data["issues"]],
        "events": [{
            "id": str(x.id), "type": x.event_type, "date": x.occurred_on.isoformat() if x.occurred_on else None,
            "time": x.occurred_time.isoformat() if x.occurred_time else None, "description": x.description,
            "materiality": x.materiality.value, "signature": x.source_signature,
        } for x in data["events"]],
        "conflicts": [{
            "id": str(x.id), "key": x.conflict_key, "type": x.conflict_type, "topic": x.topic,
            "status": x.status.value, "a": x.value_a, "b": x.value_b, "materiality": x.materiality.value,
        } for x in data["conflicts"]],
        "costs": [{
            "id": str(x.id), "document": str(x.document_id), "description": x.description,
            "amount": str(x.amount), "currency": x.currency, "category": x.category, "status": x.review_status.value,
        } for x in data["costs"]],
        "financial_flags": [{
            "id": str(x.id), "type": x.flag_type.value, "severity": x.severity, "status": x.status.value,
            "explanation": x.explanation, "evidence": x.evidence,
        } for x in data["flags"]],
        "policy_terms": [{
            "id": str(x.extraction_id), "category": x.category, "value": x.value,
            "document": str(x.source.document_id), "document_version": x.source.document_version,
        } for x in policy.terms],
        "policy_issues": [{
            "code": x.code, "severity": x.severity, "trigger": x.trigger,
            "related": [str(v) for v in x.related_extraction_ids],
        } for x in policy.issue_spots],
        "engine": {"claims_intelligence": ENGINE_VERSION, "chronology": CHRONOLOGY_BUILD_VERSION, "rules": RULESET_VERSION},
    }


def _build_items(claim: Claim, data: dict[str, Any], policy: Any) -> list[dict]:
    facts: list[ClaimFact] = data["facts"]
    fact_by_path = {fact.field_path: fact for fact in facts}
    items: dict[str, dict] = {}

    def add(row: dict) -> None:
        items[row["item_key"]] = row

    add(_item(
        key="incident-summary", category="incident_summary", title=f"{claim.claim_reference} incident snapshot",
        description=claim.incident_description, severity="info", urgency=45, evidence=100,
        rationale="Core incident narrative entered in the controlled claim record; it is context, not an AI causation finding.",
        sources=[_source("claim", claim.id, field="incident_description")],
    ))

    evidence_by_event: dict[UUID, list[EventEvidence]] = {}
    for row in data["event_evidence"]:
        evidence_by_event.setdefault(row.event_id, []).append(row)
    for event in data["events"]:
        refs = [_source("chronology_event", event.id, source_signature=event.source_signature)]
        refs.extend(_source("document_extraction", e.extraction_id, document_id=e.document_id, segment_id=e.source_segment_id) for e in evidence_by_event.get(event.id, []))
        stamp = ""
        if event.occurred_on:
            stamp = event.occurred_on.isoformat()
            if event.occurred_time:
                stamp += f" {event.occurred_time.isoformat(timespec='minutes')}"
        add(_item(
            key=f"chronology-{event.id}", category="chronology", title=event.title,
            description=f"{stamp + ' — ' if stamp else ''}{event.description or 'Reviewed chronology event.'}",
            severity=_MATERIALITY_TO_SEVERITY[event.materiality.value], urgency=_SEVERITY_SCORE[_MATERIALITY_TO_SEVERITY[event.materiality.value]], evidence=95,
            rationale="Chronology event generated only from human-reviewed document extractions; source truth is not adjudicated by the engine.", sources=refs,
        ))

    machinery_prefixes = ("equipment.", "maintenance.", "repair.", "operational_impact.")
    for fact in facts:
        if not fact.field_path.startswith(machinery_prefixes):
            continue
        label = fact.field_path.replace("_", " ").replace(".", " › ")
        add(_item(
            key=f"context-{fact.id}", category="machinery_context", title=label.title(),
            description=f"Human-approved fact: {json.dumps(_jsonable(fact.value), ensure_ascii=False, default=str)}",
            severity="info", urgency=30, evidence=100,
            rationale="This context is copied from the current human-approved ClaimFact record and remains traceable to its source extraction.",
            sources=[_fact_source(fact)],
        ))

    satisfied = {"received", "under_review", "accepted"}
    missing_rows: list[ClaimDocumentRequirement] = []
    for requirement in data["requirements"]:
        if requirement.status.value in satisfied:
            refs = [_source("document_requirement", requirement.id, rule_id=requirement.rule_id, status=requirement.status.value)]
            if requirement.matched_document_id:
                refs.append(_source("document", requirement.matched_document_id, document_type=requirement.document_type))
            if requirement.equivalent_claim_fact_id:
                refs.append(_source("claim_fact", requirement.equivalent_claim_fact_id))
            add(_item(
                key=f"evidence-{requirement.id}", category="evidence_available", title=requirement.document_label,
                description=f"Requirement is {requirement.status.value.replace('_', ' ')}.", severity="info", urgency=20, evidence=95,
                rationale=requirement.reason, sources=refs,
            ))
            continue
        missing_rows.append(requirement)
        severity = "critical" if requirement.priority.value == "critical" else "high" if requirement.priority.value == "important" else "medium"
        urgency = 95 if severity == "critical" else 78 if severity == "high" else 58
        refs = [_source("document_requirement", requirement.id, rule_id=requirement.rule_id, document_type=requirement.document_type, status=requirement.status.value)]
        add(_item(
            key=f"missing-{requirement.id}", category="missing_evidence", title=f"Missing / unresolved: {requirement.document_label}",
            description=requirement.reason, severity=severity, urgency=urgency, evidence=100,
            rationale=f"Triggered by deterministic H&M machinery rule {requirement.rule_id} at the current claim stage.", sources=refs,
            action_type="document_request", suggested_action=f"Obtain and review {requirement.document_label}; if unavailable, record the reason and assess acceptable equivalent evidence.",
            related_entity_type="document_requirement", related_entity_id=requirement.id,
        ))
        add(_item(
            key=f"next-missing-{requirement.id}", category="next_action", title=f"Request {requirement.document_label}",
            description=f"Close the evidence gap before relying on conclusions affected by {requirement.document_label.lower()}.",
            severity=severity, urgency=urgency, evidence=100,
            rationale=requirement.reason, sources=refs,
            action_type="document_request", suggested_action=f"Send a controlled request for {requirement.document_label} and track receipt/review in the evidence workflow.",
            related_entity_type="document_requirement", related_entity_id=requirement.id,
        ))

    open_conflicts = [x for x in data["conflicts"] if x.status.value == "open"]
    for conflict in open_conflicts:
        severity = _MATERIALITY_TO_SEVERITY[conflict.materiality.value]
        refs = [_source("evidence_conflict", conflict.id, conflict_key=conflict.conflict_key)]
        if conflict.evidence_a_extraction_id:
            refs.append(_source("document_extraction", conflict.evidence_a_extraction_id))
        if conflict.evidence_b_extraction_id:
            refs.append(_source("document_extraction", conflict.evidence_b_extraction_id))
        add(_item(
            key=f"conflict-{conflict.id}", category="conflict", title=f"Unresolved conflict: {conflict.topic}",
            description=conflict.description, severity=severity, urgency=_SEVERITY_SCORE[severity], evidence=100,
            rationale="The chronology engine detected materially different human-reviewed evidence. It does not choose which source is true.",
            sources=refs, action_type="conflict_review", suggested_action="Review the cited sources, obtain clarification if required, and explicitly resolve or accept the difference in the conflict workflow.",
            related_entity_type="evidence_conflict", related_entity_id=conflict.id,
        ))
        add(_item(
            key=f"next-conflict-{conflict.id}", category="next_action", title=f"Reconcile {conflict.topic}",
            description="A defensible assessment should identify how this material discrepancy is treated rather than silently selecting one source.",
            severity=severity, urgency=min(100, _SEVERITY_SCORE[severity] + 5), evidence=100,
            rationale=conflict.description, sources=refs, action_type="conflict_review",
            suggested_action="Compare the underlying reviewed sources and record a reasoned conflict disposition.",
            related_entity_type="evidence_conflict", related_entity_id=conflict.id,
        ))

    for issue in data["issues"]:
        severity = issue.severity.value
        refs = [_source("claim_issue", issue.id, rule_id=issue.rule_id, issue_key=issue.issue_key), _source("rule", issue.rule_id, version=issue.rule_version)]
        for path in _ISSUE_FACT_PATHS.get(issue.rule_id, ()):
            fact = fact_by_path.get(path)
            if fact:
                refs.append(_fact_source(fact))
        category = "hypothesis" if issue.category.value == "technical" else "issue_flag"
        title = f"Hypothesis for review: {issue.title}" if category == "hypothesis" else issue.title
        add(_item(
            key=f"issue-{issue.id}", category=category, title=title, description=issue.description,
            severity=severity, urgency=_SEVERITY_SCORE[severity], evidence=92,
            rationale=(issue.explanation or "Deterministic claim issue generated from reviewed evidence; it is a review flag, not a finding."),
            sources=refs, action_type="technical_review", suggested_action="Review the cited facts and technical evidence; obtain surveyor, maker or workshop clarification where necessary before forming any causation view.",
            related_entity_type="claim_issue", related_entity_id=issue.id,
        ))
        add(_item(
            key=f"next-issue-{issue.id}", category="next_action", title=f"Review: {issue.title}",
            description="Resolve this investigation flag using the underlying evidence before relying on a technical or coverage assessment.",
            severity=severity, urgency=_SEVERITY_SCORE[severity], evidence=90,
            rationale=issue.explanation or issue.description, sources=refs, action_type="technical_review",
            suggested_action="Complete a documented human technical review of the cited issue and preserve the source rationale.",
            related_entity_type="claim_issue", related_entity_id=issue.id,
        ))

    term_by_extraction = {str(term.extraction_id): term for term in policy.terms}
    for policy_issue in policy.issue_spots:
        related = [term_by_extraction.get(str(x)) for x in policy_issue.related_extraction_ids]
        refs = [_source("policy_issue", policy_issue.code)]
        for term in related:
            if term is not None:
                refs.append(_source("policy_term", term.extraction_id, category=term.category, document_id=term.source.document_id, document_version=term.source.document_version))
        deadline = "time" in policy_issue.code or "notice" in policy_issue.code or "diaris" in policy_issue.required_human_action.lower()
        category = "deadline_lead" if deadline else "issue_flag"
        severity = policy_issue.severity if policy_issue.severity in _SEVERITY_SCORE else "medium"
        add(_item(
            key=f"policy-{policy_issue.code}", category=category, title=policy_issue.title,
            description=policy_issue.description, severity=severity, urgency=_SEVERITY_SCORE[severity], evidence=90 if related else 75,
            rationale="Generated by the policy/contract issue-spotting workspace from reviewed wording. It is not a coverage, breach or deadline conclusion.",
            sources=refs, action_type="deadline_review" if deadline else "policy_review",
            suggested_action=policy_issue.required_human_action,
        ))
        if severity in {"critical", "high", "medium"}:
            add(_item(
                key=f"next-policy-{policy_issue.code}", category="next_action", title=f"Policy follow-up: {policy_issue.title}",
                description=policy_issue.required_human_action, severity=severity,
                urgency=min(100, _SEVERITY_SCORE[severity] + (10 if deadline else 0)), evidence=90 if related else 75,
                rationale=policy_issue.description, sources=refs, action_type="deadline_review" if deadline else "policy_review",
                suggested_action=policy_issue.required_human_action,
            ))

    for flag in data["flags"]:
        severity = flag.severity if flag.severity in _SEVERITY_SCORE else "medium"
        refs = [_source("financial_flag", flag.id, flag_type=flag.flag_type.value)]
        add(_item(
            key=f"financial-flag-{flag.id}", category="financial_lead", title=flag.title,
            description=flag.explanation, severity=severity, urgency=_SEVERITY_SCORE[severity], evidence=85,
            rationale="Existing financial-control flag. It requires human investigation and does not decide recoverability.",
            sources=refs, action_type="financial_review", suggested_action="Review the cited cost evidence and record a financial disposition with supporting documents.",
            related_entity_type="financial_flag", related_entity_id=flag.id,
        ))

    cost_patterns = (
        ("AAA-D1", ("tow", "pilot", "deviation", "port charge", "bunker"), "Potential D1 removal / movement cost review", "Review whether the expense arose from necessary removal or movement to a repair location and verify the exact policy/adjusting basis."),
        ("AAA-D2", ("fuel", "bunker", "stores"), "Potential D2 fuel / stores cost review", "Review whether fuel or stores were consumed in qualifying repair activity rather than ordinary operation or commercial readiness."),
        ("AAA-D6", ("winch", "machinery", "generator", "engine", "crane", "power"), "Potential D6 machinery-assisting-repairs review", "Review whether machinery was specifically used to assist insured repairs and whether the claimed consumption/cost is evidenced."),
    )
    for cost in data["costs"]:
        text = f"{cost.description} {cost.category or ''}".lower()
        for rule_id, needles, title, action in cost_patterns:
            if not any(needle in text for needle in needles):
                continue
            refs = [_source("cost_item", cost.id, document_id=cost.document_id, amount=str(cost.amount), currency=cost.currency), _source("reference_rule", rule_id)]
            add(_item(
                key=f"cost-{rule_id.lower()}-{cost.id}", category="financial_lead", title=title,
                description=f"Cost line: {cost.description} — {cost.amount} {cost.currency}.", severity="medium", urgency=55, evidence=85,
                rationale=f"Keyword-based marine adjustment issue spotting only. The engine has not decided that {rule_id} applies or that the expense is recoverable.",
                sources=refs, action_type="financial_review", suggested_action=action,
                related_entity_type="cost_item", related_entity_id=cost.id,
            ))

    recent_overhaul = next((x for x in data["issues"] if x.rule_id == "TECH-002"), None)
    recovery_facts = [f for f in facts if any(token in f.field_path.lower() for token in ("third_party", "repairer", "workshop", "maker", "supplier"))]
    if recent_overhaul is not None or recovery_facts:
        refs = []
        if recent_overhaul is not None:
            refs.extend([_source("claim_issue", recent_overhaul.id, rule_id=recent_overhaul.rule_id), _source("rule", recent_overhaul.rule_id)])
        refs.extend(_fact_source(f) for f in recovery_facts[:6])
        add(_item(
            key="recovery-preservation-lead", category="recovery_lead", title="Potential third-party / workmanship recovery lead",
            description="Reviewed evidence may justify preserving a recovery investigation against a maker, workshop, repairer, supplier or other responsible party. No responsibility finding has been made.",
            severity="high" if recent_overhaul else "medium", urgency=82 if recent_overhaul else 62, evidence=80,
            rationale="Recovery rights can be time-sensitive; recent overhaul/workmanship relevance or approved counterparty facts warrant a human preservation review.",
            sources=refs or [_source("claim", claim.id)], action_type="recovery_review",
            suggested_action="Preserve relevant evidence and contractual notices, identify potentially responsible parties, and check contractual/statutory time bars before responsibility evidence is lost.",
        ))
        add(_item(
            key="next-recovery-preservation", category="next_action", title="Preserve potential recovery rights",
            description="Open a human recovery review without alleging liability.", severity="high" if recent_overhaul else "medium",
            urgency=86 if recent_overhaul else 66, evidence=80,
            rationale="The current evidence creates a non-authoritative recovery lead that may become time-sensitive.",
            sources=refs or [_source("claim", claim.id)], action_type="recovery_review",
            suggested_action="Identify possible responsible parties, preserve evidence and diary any notice or limitation requirements.",
        ))

    description_lower = (claim.incident_description or "").lower()
    if any(token in description_lower for token in ("tow", "deviat", "salvage", "general average", "sue and labour")):
        add(_item(
            key="emergency-expense-classification", category="issue_flag", title="Emergency expense classification requires review",
            description="The recorded incident narrative contains emergency movement / salvage / deviation indicators. Review whether any expense belongs to PA repair costs, Sue & Labour, salvage or General Average; no classification is made here.",
            severity="medium", urgency=60, evidence=70,
            rationale="Marine claims treatment depends on the actual service, purpose, policy wording and contribution framework, not keyword presence alone.",
            sources=[_source("claim", claim.id, field="incident_description")], action_type="financial_review",
            suggested_action="Review the underlying contracts, invoices, service reports and policy wording before classifying emergency expenditure.",
        ))

    ordered = sorted(items.values(), key=lambda row: (-row["rank_score"], row["category"], row["item_key"]))
    return ordered


def latest_snapshot(db: Session, *, claim: Claim) -> ClaimIntelligenceSnapshot | None:
    return db.scalar(select(ClaimIntelligenceSnapshot).where(
        ClaimIntelligenceSnapshot.organization_id == claim.organization_id,
        ClaimIntelligenceSnapshot.claim_id == claim.id,
    ).order_by(ClaimIntelligenceSnapshot.snapshot_version.desc()).limit(1))


def _items(db: Session, snapshot_id: UUID) -> list[ClaimIntelligenceItem]:
    return list(db.scalars(select(ClaimIntelligenceItem).where(
        ClaimIntelligenceItem.snapshot_id == snapshot_id,
    ).order_by(ClaimIntelligenceItem.rank_score.desc(), ClaimIntelligenceItem.category.asc(), ClaimIntelligenceItem.item_key.asc())))


def _latest_decision(db: Session, item_id: UUID) -> ClaimIntelligenceItemDecision | None:
    return db.scalar(select(ClaimIntelligenceItemDecision).where(
        ClaimIntelligenceItemDecision.item_id == item_id,
    ).order_by(ClaimIntelligenceItemDecision.decision_number.desc()).limit(1))


def snapshot_response(db: Session, snapshot: ClaimIntelligenceSnapshot) -> dict:
    rows = _items(db, snapshot.id)
    rendered = []
    for row in rows:
        decision = _latest_decision(db, row.id)
        rendered.append({
            "id": row.id, "snapshot_id": row.snapshot_id, "item_key": row.item_key, "category": row.category,
            "title": row.title, "description": row.description, "severity": row.severity,
            "urgency_score": row.urgency_score, "evidential_value_score": row.evidential_value_score,
            "rank_score": row.rank_score, "rationale": row.rationale, "source_refs": list(row.source_refs or []),
            "action_type": row.action_type, "suggested_action": row.suggested_action,
            "related_entity_type": row.related_entity_type, "related_entity_id": row.related_entity_id,
            "item_hash": row.item_hash, "latest_decision": decision,
        })
    return {
        "id": snapshot.id, "claim_id": snapshot.claim_id, "generated_by_id": snapshot.generated_by_id,
        "snapshot_version": snapshot.snapshot_version, "engine_version": snapshot.engine_version,
        "source_state_hash": snapshot.source_state_hash, "snapshot_hash": snapshot.snapshot_hash,
        "summary": dict(snapshot.summary or {}), "generated_at": snapshot.generated_at, "items": rendered,
    }


def dashboard_response(db: Session, *, claim: Claim) -> dict:
    snapshot = latest_snapshot(db, claim=claim)
    return {"claim_id": claim.id, "snapshot": snapshot_response(db, snapshot) if snapshot else None, "disclaimer": DISCLAIMER}


def build_claim_intelligence(db: Session, *, claim: Claim, user: User) -> ClaimIntelligenceSnapshot:
    # Keep prerequisite deterministic layers current. These functions only consume human-reviewed evidence.
    evaluate_claim_rules(db, claim=claim, user=user, trigger="claims_intelligence")
    build_chronology(db, claim=claim, user=user)
    policy = build_policy_intelligence(db, claim_id=claim.id, organization_id=claim.organization_id)
    data = _load_sources(db, claim)
    state = _source_state(claim, data, policy)
    state_hash = _hash(state)

    existing = db.scalar(select(ClaimIntelligenceSnapshot).where(
        ClaimIntelligenceSnapshot.organization_id == claim.organization_id,
        ClaimIntelligenceSnapshot.claim_id == claim.id,
        ClaimIntelligenceSnapshot.source_state_hash == state_hash,
    ))
    if existing is not None:
        return existing

    item_payloads = _build_items(claim, data, policy)
    counts: dict[str, int] = {}
    for row in item_payloads:
        counts[row["category"]] = counts.get(row["category"], 0) + 1
    summary = {
        "source_linked": True,
        "non_authoritative": True,
        "human_review_required": True,
        "external_provider_scope_expanded": False,
        "ruleset_version": RULESET_VERSION,
        "chronology_build_version": CHRONOLOGY_BUILD_VERSION,
        "item_count": len(item_payloads),
        "category_counts": counts,
        "missing_evidence_count": counts.get("missing_evidence", 0),
        "open_conflict_count": counts.get("conflict", 0),
        "hypothesis_count": counts.get("hypothesis", 0),
        "financial_recovery_lead_count": counts.get("financial_lead", 0) + counts.get("recovery_lead", 0),
        "deadline_lead_count": counts.get("deadline_lead", 0),
        "next_action_count": counts.get("next_action", 0),
        "authoritative_claim_facts_updated": False,
        "coverage_decision_made": False,
        "causation_decision_made": False,
        "liability_decision_made": False,
        "reserve_or_settlement_decision_made": False,
    }
    item_hashes = [row["item_hash"] for row in item_payloads]
    snapshot_hash = _hash({"engine": ENGINE_VERSION, "source_state_hash": state_hash, "summary": summary, "item_hashes": item_hashes})
    current_max = db.scalar(select(func.max(ClaimIntelligenceSnapshot.snapshot_version)).where(
        ClaimIntelligenceSnapshot.organization_id == claim.organization_id,
        ClaimIntelligenceSnapshot.claim_id == claim.id,
    )) or 0
    now = datetime.now(UTC)
    snapshot = ClaimIntelligenceSnapshot(
        organization_id=claim.organization_id, claim_id=claim.id, generated_by_id=user.id,
        snapshot_version=current_max + 1, engine_version=ENGINE_VERSION, source_state_hash=state_hash,
        snapshot_hash=snapshot_hash, summary=summary, generated_at=now,
    )
    db.add(snapshot)
    db.flush()
    for payload in item_payloads:
        db.add(ClaimIntelligenceItem(
            organization_id=claim.organization_id, claim_id=claim.id, snapshot_id=snapshot.id,
            **payload,
        ))
    write_audit_log(
        db, organization_id=claim.organization_id, user_id=user.id,
        action="BUILD_CLAIM_INTELLIGENCE", entity_type="claim", entity_id=claim.id,
        new_values={
            "snapshot_id": str(snapshot.id), "snapshot_version": snapshot.snapshot_version,
            "source_state_hash": state_hash, "snapshot_hash": snapshot_hash, **summary,
        },
        details="Built a source-linked, non-authoritative claims intelligence snapshot from controlled claim evidence and rules.",
    )
    db.commit()
    db.refresh(snapshot)
    return snapshot


def record_item_decision(
    db: Session, *, claim: Claim, item: ClaimIntelligenceItem, user: User,
    payload: ClaimIntelligenceDecisionWrite,
) -> ClaimIntelligenceItemDecision:
    if item.organization_id != claim.organization_id or item.claim_id != claim.id:
        raise ValueError("Intelligence item does not belong to this claim")
    previous = _latest_decision(db, item.id)
    number = (previous.decision_number + 1) if previous else 1
    task: ClaimTask | None = None
    if payload.convert_to_task:
        if not item.suggested_action and not payload.edited_suggested_action:
            raise ValueError("Only intelligence with a suggested action can be converted to a task")
        task_type = TaskType.DOCUMENT_REQUEST if item.action_type == "document_request" else (
            TaskType.FOLLOW_UP if item.action_type in {"recovery_review", "deadline_review"} else TaskType.REVIEW
        )
        requirement_id = item.related_entity_id if item.related_entity_type == "document_requirement" else None
        title = payload.edited_title or item.title
        description = payload.edited_suggested_action or item.suggested_action or payload.edited_description or item.description
        task = ClaimTask(
            organization_id=claim.organization_id, claim_id=claim.id,
            requirement_id=requirement_id, request_batch_id=None,
            assignee_id=claim.handler_id or user.id, title=title[:220], description=description,
            task_type=task_type, status=TaskStatus.OPEN, priority=_TASK_PRIORITY.get(item.severity, TaskPriority.MEDIUM),
            source=TaskSource.AI_SUGGESTION, due_date=None,
        )
        db.add(task)
        db.flush()
    now = datetime.now(UTC)
    decision_payload = {
        "item_hash": item.item_hash, "decision_number": number, "action": payload.action,
        "edited_title": payload.edited_title, "edited_description": payload.edited_description,
        "edited_suggested_action": payload.edited_suggested_action, "note": payload.note.strip(),
        "converted_task_id": str(task.id) if task else None,
        "previous_decision_hash": previous.decision_hash if previous else None,
        "decided_by_id": str(user.id), "decided_at": now.isoformat(),
    }
    decision = ClaimIntelligenceItemDecision(
        organization_id=claim.organization_id, claim_id=claim.id, item_id=item.id, decided_by_id=user.id,
        converted_task_id=task.id if task else None, decision_number=number, action=payload.action,
        edited_title=payload.edited_title, edited_description=payload.edited_description,
        edited_suggested_action=payload.edited_suggested_action, note=payload.note.strip(),
        previous_decision_hash=previous.decision_hash if previous else None,
        decision_hash=_hash(decision_payload), decided_at=now,
    )
    db.add(decision)
    db.flush()
    write_audit_log(
        db, organization_id=claim.organization_id, user_id=user.id,
        action="REVIEW_CLAIM_INTELLIGENCE_ITEM", entity_type="claim_intelligence_item", entity_id=item.id,
        new_values={
            "decision_id": str(decision.id), "decision_number": number, "action": payload.action,
            "decision_hash": decision.decision_hash, "converted_task_id": str(task.id) if task else None,
        },
        details="Human review recorded separately from the immutable intelligence snapshot/item.",
    )
    db.commit()
    db.refresh(decision)
    return decision
