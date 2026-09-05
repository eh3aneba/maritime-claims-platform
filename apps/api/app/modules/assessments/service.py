from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.assessments.models import AssessmentSection, AssessmentSectionStatus, AssessmentStatus, InitialAssessment
from app.modules.assessments.source_integrity import (
    approved_assessment_content_hash,
    assert_assessment_source_current,
    build_assessment_source_snapshot,
)
from app.modules.audit.service import write_audit_log
from app.modules.chronology.models import ChronologyEvent, ConflictStatus, EvidenceConflict, EventEvidence
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.financial.models import CostItem, CostReviewStatus, FinancialFlag, FinancialFlagStatus, ReserveHistory
from app.modules.rules.models import ClaimDocumentRequirement, ClaimIssue, RequirementPriority, RequirementStatus
from app.modules.rules.service import get_rule_summary
from app.modules.tasks.models import ClaimTask, TaskStatus
from app.modules.technical.service import build_technical_review
from app.modules.users.models import User


SECTION_DEFS = [
    ("incident", "Incident", 10),
    ("vessel_status", "Current Vessel Status", 20),
    ("damage", "Damage & Technical Findings", 30),
    ("documents", "Documents Received", 40),
    ("outstanding", "Outstanding Critical Evidence", 50),
    ("chronology", "Chronology", 60),
    ("conflicts", "Evidence Conflicts", 70),
    ("technical", "Technical Issues", 80),
    ("financial", "Financial Exposure", 90),
    ("reserve", "Reserve", 100),
    ("actions", "Recommended Next Actions", 110),
]


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _current_facts(db: Session, claim: Claim) -> dict[str, Any]:
    rows = db.scalars(
        select(ClaimFact).where(
            ClaimFact.organization_id == claim.organization_id,
            ClaimFact.claim_id == claim.id,
        )
    )
    return {row.field_path: row.value for row in rows}


def _facts_with_prefix(db: Session, claim: Claim, prefix: str) -> list[ClaimFact]:
    return list(
        db.scalars(
            select(ClaimFact).where(
                ClaimFact.organization_id == claim.organization_id,
                ClaimFact.claim_id == claim.id,
                ClaimFact.field_path.like(f"{prefix}%"),
            )
        )
    )


def _docs(db: Session, claim: Claim) -> list[Document]:
    return list(
        db.scalars(
            select(Document)
            .where(
                Document.organization_id == claim.organization_id,
                Document.claim_id == claim.id,
                Document.deleted_at.is_(None),
            )
            .order_by(Document.created_at.asc())
        )
    )


def _line(value: Any) -> str:
    if value is None:
        return "Not established"
    if isinstance(value, dict):
        if "raw" in value:
            return str(value["raw"])
        if "value" in value:
            return str(value["value"])
    return str(value)


def _source(kind: str, identifier: Any, label: str) -> dict[str, str]:
    return {"kind": kind, "id": str(identifier), "label": label}


DOCUMENT_TYPE_LABELS = {
    "claim_notification": "Claim Notification",
    "chief_engineer_report": "Chief Engineer Report",
    "engine_log": "Engine Log",
    "running_hours_record": "Running Hours Record",
    "pms_record": "PMS History",
    "workshop_report": "Workshop Report",
    "quotation": "Quotation",
    "invoice": "Invoice",
    "policy": "H&M Policy / Wording",
    "last_overhaul_report": "Last Overhaul Report",
}


def _document_label(document: Document) -> str:
    return DOCUMENT_TYPE_LABELS.get(
        document.document_type or "",
        (document.document_type or "Unclassified document").replace("_", " ").title(),
    )


def _yes(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "1"}


def _build_sections(db: Session, claim: Claim) -> list[tuple[str, str, int, str, list]]:
    facts = _current_facts(db, claim)
    docs = _docs(db, claim)
    rule_summary = get_rule_summary(db, claim=claim)
    events = list(
        db.scalars(
            select(ChronologyEvent)
            .where(
                ChronologyEvent.organization_id == claim.organization_id,
                ChronologyEvent.claim_id == claim.id,
                ChronologyEvent.is_active.is_(True),
            )
            .order_by(
                ChronologyEvent.occurred_on.asc().nullslast(),
                ChronologyEvent.occurred_time.asc().nullslast(),
                ChronologyEvent.created_at.asc(),
            )
        )
    )
    conflicts = list(
        db.scalars(
            select(EvidenceConflict)
            .where(
                EvidenceConflict.organization_id == claim.organization_id,
                EvidenceConflict.claim_id == claim.id,
                EvidenceConflict.is_active.is_(True),
            )
            .order_by(EvidenceConflict.materiality.desc(), EvidenceConflict.created_at.asc())
        )
    )
    issues = list(
        db.scalars(
            select(ClaimIssue)
            .where(
                ClaimIssue.organization_id == claim.organization_id,
                ClaimIssue.claim_id == claim.id,
                ClaimIssue.is_active.is_(True),
            )
            .order_by(ClaimIssue.severity.desc())
        )
    )
    cost_items = list(
        db.scalars(
            select(CostItem)
            .where(CostItem.organization_id == claim.organization_id, CostItem.claim_id == claim.id)
            .order_by(CostItem.created_at.asc())
        )
    )
    fin_flags = list(
        db.scalars(
            select(FinancialFlag)
            .where(FinancialFlag.organization_id == claim.organization_id, FinancialFlag.claim_id == claim.id)
            .order_by(FinancialFlag.created_at.asc())
        )
    )
    reserves = list(
        db.scalars(
            select(ReserveHistory)
            .where(ReserveHistory.organization_id == claim.organization_id, ReserveHistory.claim_id == claim.id)
            .order_by(ReserveHistory.created_at.asc())
        )
    )
    tasks = list(
        db.scalars(
            select(ClaimTask)
            .where(
                ClaimTask.organization_id == claim.organization_id,
                ClaimTask.claim_id == claim.id,
                ClaimTask.status == TaskStatus.OPEN,
            )
            .order_by(ClaimTask.due_date.asc().nullslast(), ClaimTask.created_at.asc())
        )
    )

    sections: dict[str, tuple[str, int, str, list]] = {}
    sections["incident"] = (
        "Incident",
        10,
        f"Claim {claim.claim_reference} concerns {claim.incident_description.strip()} The reported incident date is {claim.incident_date.isoformat()} and notification date is {claim.notification_date.isoformat()}.",
        [_source("claim", claim.id, claim.claim_reference)],
    )

    operational_facts = _facts_with_prefix(db, claim, "operational_impact.")
    operational_sentences: list[str] = []
    if _yes(facts.get("operational_impact.load_reduced")):
        operational_sentences.append("Engine load was reduced in response to the abnormal machinery condition.")
    if _yes(facts.get("operational_impact.speed_reduced")):
        operational_sentences.append("Vessel speed was reduced.")
    if _yes(facts.get("operational_impact.engine_stopped")):
        operational_sentences.append("The main engine was subsequently stopped for inspection.")
    if _yes(facts.get("operational_impact.immobilized")):
        operational_sentences.append("The reviewed evidence records the vessel as immobilized.")
    if _yes(facts.get("operational_impact.towage")):
        operational_sentences.append("Towage is recorded in the reviewed evidence.")
    if _yes(facts.get("operational_impact.deviation")):
        operational_sentences.append("A vessel deviation is recorded in the reviewed evidence.")
    if operational_sentences:
        operational_sentences.append(
            "The vessel's current post-casualty operational and repair status has not been independently established from the reviewed evidence unless updated elsewhere in the claim file."
        )
        vessel_status_text = " ".join(operational_sentences)
    else:
        vessel_status_text = "The vessel's current operational and repair status has not yet been established from human-reviewed evidence."
    sections["vessel_status"] = (
        "Current Vessel Status",
        20,
        vessel_status_text,
        [_source("claim_fact", fact.id, fact.field_path) for fact in operational_facts],
    )

    damage_lines: list[str] = []
    damage_sources: list[dict[str, str]] = []
    equipment_facts = _facts_with_prefix(db, claim, "equipment.")
    maintenance_facts = _facts_with_prefix(db, claim, "maintenance.")
    equipment_bits: list[str] = []
    equipment_name = _line(facts.get("equipment.name")) if facts.get("equipment.name") is not None else None
    equipment_type = _line(facts.get("equipment.type")) if facts.get("equipment.type") is not None else None
    equipment_maker = _line(facts.get("equipment.maker")) if facts.get("equipment.maker") is not None else None
    equipment_model = _line(facts.get("equipment.model")) if facts.get("equipment.model") is not None else None
    if equipment_name:
        equipment_bits.append(equipment_name)
    elif equipment_type:
        equipment_bits.append(equipment_type)
    if equipment_maker:
        equipment_bits.append(f"Maker: {equipment_maker}")
    if equipment_model:
        equipment_bits.append(f"Model: {equipment_model}")
    if equipment_bits:
        damage_lines.append("Equipment:\n- " + "; ".join(equipment_bits))
        damage_sources.extend(_source("claim_fact", fact.id, fact.field_path) for fact in equipment_facts)

    technical_review = build_technical_review(db, claim_id=claim.id, organization_id=claim.organization_id)
    grouped_findings: dict[str, dict[str, Any]] = {}
    grouped_sources: dict[str, list[dict[str, str]]] = {}
    for finding in technical_review.get("workshop_findings", []):
        field_path = str(finding.get("field_path") or "")
        root = field_path.rsplit(".", 1)[0] if "." in field_path else field_path
        leaf = field_path.rsplit(".", 1)[-1]
        grouped_findings.setdefault(root, {})[leaf] = finding.get("value")
        grouped_sources.setdefault(root, []).append(
            _source("document_extraction", finding.get("extraction_id"), field_path)
        )
    physical_lines: list[str] = []
    for root, values in list(grouped_findings.items())[:8]:
        component = _line(values.get("component")) if values.get("component") is not None else None
        description = _line(values.get("damage_description")) if values.get("damage_description") is not None else None
        extent = _line(values.get("extent")) if values.get("extent") is not None else None
        parts = [part for part in (description, extent) if part and part != "Not established"]
        if component and component != "Not established":
            physical_lines.append(f"- Workshop finding — {component}" + (f": {'; '.join(parts)}" if parts else ""))
        elif parts:
            physical_lines.append(f"- {'; '.join(parts)}")
        else:
            continue
        damage_sources.extend(grouped_sources.get(root, []))
    if physical_lines:
        damage_lines.append("Physical findings from reviewed workshop evidence:\n" + "\n".join(physical_lines))

    maintenance_bits: list[str] = []
    if facts.get("maintenance.running_hours_since_overhaul") is not None:
        maintenance_bits.append(f"Running hours since overhaul: {_line(facts['maintenance.running_hours_since_overhaul'])}")
    if facts.get("maintenance.recommended_overhaul_interval") is not None:
        maintenance_bits.append(f"Reviewed recommended overhaul interval: {_line(facts['maintenance.recommended_overhaul_interval'])}")
    if facts.get("maintenance.last_overhaul_date") is not None:
        maintenance_bits.append(f"Last overhaul date recorded: {_line(facts['maintenance.last_overhaul_date'])}")
    if maintenance_bits:
        damage_lines.append("Maintenance context:\n- " + "\n- ".join(maintenance_bits))
        damage_sources.extend(_source("claim_fact", fact.id, fact.field_path) for fact in maintenance_facts)

    if issues:
        issue_lines = [
            f"- {issue.title} — investigation priority {issue.severity.value}; this is not a causation finding."
            for issue in issues[:8]
        ]
        damage_lines.append("Open technical issues:\n" + "\n".join(issue_lines))
        for issue in issues[:8]:
            damage_sources.append(_source("claim_issue", issue.id, issue.rule_id))
    sections["damage"] = (
        "Damage & Technical Findings",
        30,
        "\n\n".join(damage_lines) if damage_lines else "No human-approved technical findings have yet been established.",
        damage_sources,
    )

    doc_lines = [f"{_document_label(document)} ({document.original_filename})" for document in docs]
    sections["documents"] = (
        "Documents Received",
        40,
        "Received documents:\n" + "\n".join(f"- {item}" for item in doc_lines)
        if doc_lines
        else "No active documents are currently recorded.",
        [_source("document", document.id, _document_label(document)) for document in docs],
    )

    missing = [
        requirement
        for requirement in rule_summary.requirements
        if requirement.status not in {RequirementStatus.RECEIVED, RequirementStatus.UNDER_REVIEW, RequirementStatus.ACCEPTED}
    ]
    critical = [requirement for requirement in missing if requirement.priority == RequirementPriority.CRITICAL]
    outstanding_text = (
        "No critical evidence is currently outstanding."
        if not critical
        else "Outstanding critical evidence:\n"
        + "\n".join(f"- {requirement.document_label}: {requirement.reason}" for requirement in critical)
    )
    sections["outstanding"] = (
        "Outstanding Critical Evidence",
        50,
        outstanding_text,
        [_source("document_requirement", requirement.id, requirement.rule_id) for requirement in critical],
    )

    event_document_names: dict[UUID, list[str]] = {}
    for event_evidence, source_document in db.execute(
        select(EventEvidence, Document)
        .join(Document, Document.id == EventEvidence.document_id)
        .where(EventEvidence.organization_id == claim.organization_id, EventEvidence.claim_id == claim.id)
    ).all():
        names = event_document_names.setdefault(event_evidence.event_id, [])
        label = _document_label(source_document)
        if label not in names:
            names.append(label)

    event_lines: list[str] = []
    event_sources: list[dict[str, str]] = []
    for event in events[:25]:
        timezone_suffix = f" {event.timezone_label}" if event.timezone_label else ""
        if event.occurred_on is not None and event.occurred_time is not None:
            when = f"{event.occurred_on.isoformat()} {event.occurred_time.strftime('%H:%M')}{timezone_suffix}"
        elif event.occurred_on is not None:
            when = f"{event.occurred_on.isoformat()} — time not stated"
        else:
            when = "Undated / relative"
        source_suffix = (
            f" — Source: {' / '.join(event_document_names.get(event.id, []))}"
            if event_document_names.get(event.id)
            else ""
        )
        event_lines.append(f"- {when} — {event.title}{source_suffix}")
        event_sources.append(_source("chronology_event", event.id, event.title))
    sections["chronology"] = (
        "Chronology",
        60,
        "Chronology:\n" + "\n".join(event_lines) if event_lines else "No reviewed chronology events are currently available.",
        event_sources,
    )

    open_conflicts = [conflict for conflict in conflicts if conflict.status == ConflictStatus.OPEN]
    conflict_text = (
        "No open evidence conflicts are currently recorded."
        if not open_conflicts
        else "Open evidence conflicts:\n"
        + "\n".join(
            f"- {conflict.topic} ({conflict.materiality.value}): {conflict.description}"
            for conflict in open_conflicts
        )
    )
    sections["conflicts"] = (
        "Evidence Conflicts",
        70,
        conflict_text,
        [_source("evidence_conflict", conflict.id, conflict.topic) for conflict in open_conflicts],
    )

    technical_text = (
        "No active technical issues are currently recorded."
        if not issues
        else "Technical issues requiring review:\n"
        + "\n".join(
            f"- {issue.title} [{issue.severity.value}]: {issue.explanation or issue.description}"
            for issue in issues
        )
    )
    sections["technical"] = (
        "Technical Issues",
        80,
        technical_text,
        [_source("claim_issue", issue.id, issue.rule_id) for issue in issues],
    )

    invoiced_totals: dict[str, Decimal] = {}
    accepted_totals: dict[str, Decimal] = {}
    paid_totals: dict[str, Decimal] = {}
    quote_groups: dict[tuple, Decimal] = {}
    for item in cost_items:
        if item.document_kind == "invoice":
            invoiced_totals[item.currency] = invoiced_totals.get(item.currency, Decimal("0")) + item.amount
            if item.review_status in {CostReviewStatus.ACCEPTED, CostReviewStatus.PAID}:
                accepted_totals[item.currency] = accepted_totals.get(item.currency, Decimal("0")) + item.amount
            if item.review_status == CostReviewStatus.PAID:
                paid_totals[item.currency] = paid_totals.get(item.currency, Decimal("0")) + item.amount
        elif item.document_kind == "quotation":
            key = (item.document_id, item.supplier or "Quotation", item.document_number or "", item.currency)
            quote_groups[key] = quote_groups.get(key, Decimal("0")) + item.amount

    def money_text(values: dict[str, Decimal], empty: str = "None recorded") -> str:
        return ", ".join(f"{currency} {amount:,.2f}" for currency, amount in sorted(values.items())) or empty

    financial_lines = [
        f"Reviewed invoiced/claimed cost: {money_text(invoiced_totals, 'No reviewed invoice cost')}.",
        f"Accepted cost: {money_text(accepted_totals)}.",
        f"Paid cost: {money_text(paid_totals)}.",
    ]
    if quote_groups:
        financial_lines.append("Reviewed quotation alternatives (not cumulative claim exposure):")
        for (_, supplier, number, currency), amount in sorted(quote_groups.items(), key=lambda value: (value[0][1], value[0][2])):
            label = f"{supplier}{f' {number}' if number else ''}"
            financial_lines.append(f"- {label}: {currency} {amount:,.2f}")
    flag_lines = [
        f"- {flag.title} [{flag.severity}] — {flag.status.value}"
        for flag in fin_flags
        if flag.status == FinancialFlagStatus.OPEN
    ]
    if flag_lines:
        financial_lines.append("Open financial review flags:")
        financial_lines.extend(flag_lines)
    financial_text = "\n".join(financial_lines)
    sections["financial"] = (
        "Financial Exposure",
        90,
        financial_text,
        [_source("cost_item", item.id, item.description) for item in cost_items]
        + [_source("financial_flag", flag.id, flag.title) for flag in fin_flags],
    )

    if reserves:
        latest_reserve = reserves[-1]
        reserve_text = (
            f"Current recorded reserve: {latest_reserve.currency} {latest_reserve.amount:,.2f}. "
            f"Latest reserve reason: {latest_reserve.reason}"
        )
        reserve_sources = [_source("reserve_history", latest_reserve.id, "latest reserve")]
    elif claim.current_reserve is not None:
        reserve_text = (
            f"Current recorded reserve: {claim.currency} {claim.current_reserve:,.2f}. "
            "No append-only reserve history entry is available for this amount."
        )
        reserve_sources = [_source("claim", claim.id, "current reserve")]
    else:
        reserve_text = "No reserve is currently recorded."
        reserve_sources = []
    sections["reserve"] = ("Reserve", 100, reserve_text, reserve_sources)

    actions: list[str] = []
    action_sources: list[dict[str, str]] = []
    tasks_by_requirement = {task.requirement_id: task for task in tasks if task.requirement_id is not None}
    included_task_ids: set[UUID] = set()
    today = datetime.now(UTC).date()
    for requirement in critical[:10]:
        task = tasks_by_requirement.get(requirement.id)
        due_text = ""
        if task and task.due_date:
            overdue = " — OVERDUE" if task.due_date < today else ""
            due_text = f" — due {task.due_date.isoformat()}{overdue}"
        actions.append(f"Obtain {requirement.document_label}{due_text}.")
        action_sources.append(_source("document_requirement", requirement.id, requirement.rule_id))
        if task:
            included_task_ids.add(task.id)
            action_sources.append(_source("claim_task", task.id, task.title))
    for task in tasks[:10]:
        if task.id in included_task_ids:
            continue
        overdue = " — OVERDUE" if task.due_date and task.due_date < today else ""
        due = f" — due {task.due_date.isoformat()}{overdue}" if task.due_date else ""
        actions.append(f"Complete task: {task.title}{due}.")
        action_sources.append(_source("claim_task", task.id, task.title))
    for conflict in open_conflicts[:5]:
        actions.append(f"Review evidence conflict: {conflict.topic}.")
        action_sources.append(_source("evidence_conflict", conflict.id, conflict.topic))
    for flag in fin_flags:
        if flag.status == FinancialFlagStatus.OPEN:
            actions.append(f"Review financial flag: {flag.title}.")
            action_sources.append(_source("financial_flag", flag.id, flag.title))
    sections["actions"] = (
        "Recommended Next Actions",
        110,
        "Recommended next actions:\n" + "\n".join(f"- {action}" for action in actions)
        if actions
        else "No open system-generated next actions are currently identified.",
        action_sources,
    )

    return [(key, *sections[key]) for key, _, _ in SECTION_DEFS]


def generate_assessment(
    db: Session,
    *,
    claim: Claim,
    user: User,
    allow_if_not_ready: bool,
    override_reason: str | None,
) -> InitialAssessment:
    summary = get_rule_summary(db, claim=claim)
    not_ready = summary.readiness.state != "ready"
    if not_ready and not allow_if_not_ready:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Initial assessment is not ready",
                "blocking_items": summary.readiness.blocking_items,
                "score": summary.readiness.score,
            },
        )

    source_snapshot, source_fingerprint = build_assessment_source_snapshot(db, claim=claim)
    latest = db.scalar(
        select(func.max(InitialAssessment.version)).where(
            InitialAssessment.organization_id == claim.organization_id,
            InitialAssessment.claim_id == claim.id,
        )
    ) or 0
    assessment = InitialAssessment(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        version=latest + 1,
        status=AssessmentStatus.DRAFT,
        readiness_score=summary.readiness.score,
        readiness_state=summary.readiness.state,
        blocking_items=summary.readiness.blocking_items,
        is_preliminary=not_ready,
        generation_override_reason=(override_reason or None),
        generated_by_id=user.id,
        source_snapshot=source_snapshot,
        source_fingerprint=source_fingerprint,
    )
    db.add(assessment)
    db.flush()
    for key, title, order, text, sources in _build_sections(db, claim):
        db.add(
            AssessmentSection(
                organization_id=claim.organization_id,
                claim_id=claim.id,
                assessment_id=assessment.id,
                section_key=key,
                title=title,
                sort_order=order,
                draft_text=text,
                source_manifest=sources,
            )
        )

    _, final_source_fingerprint = build_assessment_source_snapshot(db, claim=claim)
    if final_source_fingerprint != source_fingerprint:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "Claim evidence changed while the assessment version was being generated. "
                "No assessment version was committed; generate again from the current claim state."
            ),
        )

    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="GENERATE_INITIAL_ASSESSMENT",
        entity_type="initial_assessment",
        entity_id=assessment.id,
        new_values={
            "version": assessment.version,
            "readiness_score": assessment.readiness_score,
            "preliminary": assessment.is_preliminary,
            "blocking_items": assessment.blocking_items,
            "source_fingerprint": source_fingerprint,
        },
    )
    db.commit()
    db.refresh(assessment)
    return assessment


def get_assessment(
    db: Session,
    *,
    claim: Claim,
    assessment_id: UUID | None = None,
) -> tuple[InitialAssessment | None, list[AssessmentSection]]:
    query = select(InitialAssessment).where(
        InitialAssessment.organization_id == claim.organization_id,
        InitialAssessment.claim_id == claim.id,
    )
    query = (
        query.where(InitialAssessment.id == assessment_id)
        if assessment_id
        else query.order_by(InitialAssessment.version.desc()).limit(1)
    )
    assessment = db.scalar(query)
    if not assessment:
        return None, []
    sections = list(
        db.scalars(
            select(AssessmentSection)
            .where(AssessmentSection.assessment_id == assessment.id)
            .order_by(AssessmentSection.sort_order.asc())
        )
    )
    return assessment, sections


def review_section(
    db: Session,
    *,
    claim: Claim,
    section: AssessmentSection,
    user: User,
    action: str,
    text: str | None,
    expected_source_fingerprint: str | None = None,
) -> AssessmentSection:
    if section.claim_id != claim.id or section.organization_id != claim.organization_id:
        raise HTTPException(status_code=404, detail="Assessment section not found")
    assessment = db.get(InitialAssessment, section.assessment_id)
    if not assessment:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if assessment.status == AssessmentStatus.APPROVED:
        raise HTTPException(
            status_code=409,
            detail="Approved assessment versions are immutable. Generate a new assessment version before making changes.",
        )
    assert_assessment_source_current(
        db,
        claim=claim,
        assessment=assessment,
        expected_source_fingerprint=expected_source_fingerprint,
    )

    section.status = AssessmentSectionStatus.EDITED if action == "edit" else AssessmentSectionStatus.APPROVED
    section.approved_text = text.strip() if action == "edit" and text else section.draft_text
    section.reviewed_by_id = user.id
    section.reviewed_at = datetime.now(UTC)
    if assessment.status == AssessmentStatus.DRAFT:
        assessment.status = AssessmentStatus.UNDER_REVIEW
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="REVIEW_ASSESSMENT_SECTION",
        entity_type="assessment_section",
        entity_id=section.id,
        new_values={
            "action": action,
            "section_key": section.section_key,
            "source_fingerprint": assessment.source_fingerprint,
        },
    )
    db.commit()
    db.refresh(section)
    return section


def approve_assessment(
    db: Session,
    *,
    claim: Claim,
    assessment: InitialAssessment,
    user: User,
    note: str | None,
    expected_source_fingerprint: str | None = None,
) -> InitialAssessment:
    if assessment.claim_id != claim.id or assessment.organization_id != claim.organization_id:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if assessment.status == AssessmentStatus.APPROVED:
        raise HTTPException(
            status_code=409,
            detail="Approved assessment versions are immutable. Generate a new assessment version before making changes.",
        )
    assert_assessment_source_current(
        db,
        claim=claim,
        assessment=assessment,
        expected_source_fingerprint=expected_source_fingerprint,
    )
    sections = list(
        db.scalars(
            select(AssessmentSection)
            .where(AssessmentSection.assessment_id == assessment.id)
            .order_by(AssessmentSection.sort_order.asc())
        )
    )
    pending = [section.title for section in sections if section.status == AssessmentSectionStatus.PENDING]
    if pending:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "All assessment sections must be reviewed before approval",
                "pending_sections": pending,
            },
        )

    assessment.status = AssessmentStatus.APPROVED
    assessment.approved_by_id = user.id
    assessment.approved_at = datetime.now(UTC)
    assessment.approved_content_hash = approved_assessment_content_hash(assessment, sections)
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="APPROVE_INITIAL_ASSESSMENT",
        entity_type="initial_assessment",
        entity_id=assessment.id,
        new_values={
            "version": assessment.version,
            "preliminary": assessment.is_preliminary,
            "note": note,
            "source_fingerprint": assessment.source_fingerprint,
            "approved_content_hash": assessment.approved_content_hash,
        },
    )
    db.commit()
    db.refresh(assessment)
    return assessment
