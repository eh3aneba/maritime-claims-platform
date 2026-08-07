from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.assessments.models import AssessmentSection, AssessmentSectionStatus, AssessmentStatus, InitialAssessment
from app.modules.audit.service import write_audit_log
from app.modules.chronology.models import ChronologyEvent, ConflictStatus, EvidenceConflict, EventEvidence
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.financial.models import CostItem, CostReviewStatus, FinancialFlag, FinancialFlagStatus, ReserveHistory
from app.modules.rules.models import ClaimDocumentRequirement, ClaimIssue, RequirementPriority, RequirementStatus
from app.modules.rules.service import get_rule_summary
from app.modules.tasks.models import ClaimTask, TaskStatus
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
    if isinstance(value, Decimal): return str(value)
    if hasattr(value, "value"): return value.value
    if isinstance(value, (datetime,)): return value.isoformat()
    return value


def _current_facts(db: Session, claim: Claim) -> dict[str, Any]:
    rows = db.scalars(select(ClaimFact).where(ClaimFact.organization_id == claim.organization_id, ClaimFact.claim_id == claim.id))
    return {row.field_path: row.value for row in rows}


def _docs(db: Session, claim: Claim) -> list[Document]:
    return list(db.scalars(select(Document).where(Document.organization_id == claim.organization_id, Document.claim_id == claim.id, Document.deleted_at.is_(None)).order_by(Document.created_at.asc())))


def _line(value: Any) -> str:
    if value is None: return "Not established"
    if isinstance(value, dict):
        if "raw" in value: return str(value["raw"])
        if "value" in value: return str(value["value"])
    return str(value)


def _source(kind: str, identifier: Any, label: str) -> dict[str, str]:
    return {"kind": kind, "id": str(identifier), "label": label}


def _build_sections(db: Session, claim: Claim) -> list[tuple[str, str, int, str, list]]:
    facts = _current_facts(db, claim)
    docs = _docs(db, claim)
    rule_summary = get_rule_summary(db, claim=claim)
    events = list(db.scalars(select(ChronologyEvent).where(ChronologyEvent.organization_id == claim.organization_id, ChronologyEvent.claim_id == claim.id, ChronologyEvent.is_active.is_(True)).order_by(ChronologyEvent.occurred_on, ChronologyEvent.occurred_time)))
    conflicts = list(db.scalars(select(EvidenceConflict).where(EvidenceConflict.organization_id == claim.organization_id, EvidenceConflict.claim_id == claim.id, EvidenceConflict.is_active.is_(True)).order_by(EvidenceConflict.materiality.desc(), EvidenceConflict.created_at.asc())))
    issues = list(db.scalars(select(ClaimIssue).where(ClaimIssue.organization_id == claim.organization_id, ClaimIssue.claim_id == claim.id, ClaimIssue.is_active.is_(True)).order_by(ClaimIssue.severity.desc())))
    cost_items = list(db.scalars(select(CostItem).where(CostItem.organization_id == claim.organization_id, CostItem.claim_id == claim.id).order_by(CostItem.created_at.asc())))
    fin_flags = list(db.scalars(select(FinancialFlag).where(FinancialFlag.organization_id == claim.organization_id, FinancialFlag.claim_id == claim.id).order_by(FinancialFlag.created_at.asc())))
    reserves = list(db.scalars(select(ReserveHistory).where(ReserveHistory.organization_id == claim.organization_id, ReserveHistory.claim_id == claim.id).order_by(ReserveHistory.created_at.asc())))
    tasks = list(db.scalars(select(ClaimTask).where(ClaimTask.organization_id == claim.organization_id, ClaimTask.claim_id == claim.id, ClaimTask.status == TaskStatus.OPEN).order_by(ClaimTask.due_date.asc().nullslast(), ClaimTask.created_at.asc())))

    sections: dict[str, tuple[str, int, str, list]] = {}
    sections["incident"] = ("Incident", 10, f"Claim {claim.claim_reference} concerns {claim.incident_description.strip()} The reported incident date is {claim.incident_date.isoformat()} and notification date is {claim.notification_date.isoformat()}.", [_source("claim", claim.id, claim.claim_reference)])

    status_bits = [f"Claim status: {claim.status.value.replace('_', ' ')}."]
    for key, label in [("operational_impact.engine_stopped","Engine stopped"),("operational_impact.load_reduced","Load reduced"),("operational_impact.speed_reduced","Speed reduced"),("operational_impact.immobilized","Vessel immobilized"),("operational_impact.towage","Towage"),("operational_impact.deviation","Deviation")]:
        if key in facts: status_bits.append(f"{label}: {_line(facts[key])}.")
    sections["vessel_status"] = ("Current Vessel Status", 20, " ".join(status_bits), [_source("claim_fact", fact.id, fact.field_path) for fact in db.scalars(select(ClaimFact).where(ClaimFact.claim_id==claim.id, ClaimFact.organization_id==claim.organization_id, ClaimFact.field_path.like("operational_impact.%")))])

    damage_lines=[]; damage_sources=[]
    for fp in ("equipment.type","equipment.name","equipment.maker","equipment.model","maintenance.running_hours_since_overhaul","maintenance.last_overhaul_date"):
        if fp in facts: damage_lines.append(f"{fp.replace('.', ' / ').replace('_',' ')}: {_line(facts[fp])}.")
    for issue in issues[:8]:
        damage_lines.append(f"Review issue: {issue.title} ({issue.severity.value}).")
        damage_sources.append(_source("claim_issue", issue.id, issue.rule_id))
    sections["damage"]=("Damage & Technical Findings",30," ".join(damage_lines) if damage_lines else "No human-approved technical findings have yet been established.",damage_sources)

    doc_lines=[f"{d.original_filename} — {d.document_type or 'unclassified'}" for d in docs]
    sections["documents"]=("Documents Received",40,"Received documents:\n"+"\n".join(f"- {x}" for x in doc_lines) if doc_lines else "No active documents are currently recorded.",[_source("document",d.id,d.original_filename) for d in docs])

    missing=[r for r in rule_summary.requirements if r.status not in {RequirementStatus.RECEIVED,RequirementStatus.UNDER_REVIEW,RequirementStatus.ACCEPTED}]
    critical=[r for r in missing if r.priority==RequirementPriority.CRITICAL]
    outstanding_text="No critical evidence is currently outstanding." if not critical else "Outstanding critical evidence:\n"+"\n".join(f"- {r.document_label}: {r.reason}" for r in critical)
    sections["outstanding"]=("Outstanding Critical Evidence",50,outstanding_text,[_source("document_requirement",r.id,r.rule_id) for r in critical])

    event_lines=[]; event_sources=[]
    for e in events[:25]:
        tz=f" {e.timezone_label}" if e.timezone_label else ""
        event_lines.append(f"- {e.occurred_on.isoformat()} {e.occurred_time.strftime('%H:%M')}{tz} — {e.title}")
        event_sources.append(_source("chronology_event",e.id,e.title))
    sections["chronology"]=("Chronology",60,"Chronology:\n"+"\n".join(event_lines) if event_lines else "No reviewed chronology events are currently available.",event_sources)

    open_conflicts=[c for c in conflicts if c.status==ConflictStatus.OPEN]
    ctext="No open evidence conflicts are currently recorded." if not open_conflicts else "Open evidence conflicts:\n"+"\n".join(f"- {c.topic} ({c.materiality.value}): {c.description}" for c in open_conflicts)
    sections["conflicts"]=("Evidence Conflicts",70,ctext,[_source("evidence_conflict",c.id,c.topic) for c in open_conflicts])

    technical_text="No active technical issues are currently recorded." if not issues else "Technical issues requiring review:\n"+"\n".join(f"- {i.title} [{i.severity.value}]: {i.explanation or i.description}" for i in issues)
    sections["technical"]=("Technical Issues",80,technical_text,[_source("claim_issue",i.id,i.rule_id) for i in issues])

    totals:dict[str,Decimal]={}
    for item in cost_items:
        totals[item.currency]=totals.get(item.currency,Decimal("0"))+item.amount
    total_text=", ".join(f"{ccy} {amount:,.2f}" for ccy,amount in sorted(totals.items())) or "No reviewed cost items"
    flag_lines=[f"- {f.title} [{f.severity}] — {f.status.value}" for f in fin_flags if f.status==FinancialFlagStatus.OPEN]
    financial_text=f"Reviewed cost schedule total(s): {total_text}."
    if flag_lines: financial_text += "\nOpen financial review flags:\n"+"\n".join(flag_lines)
    sections["financial"]=("Financial Exposure",90,financial_text,[_source("cost_item",i.id,i.description) for i in cost_items]+[_source("financial_flag",f.id,f.title) for f in fin_flags])

    if reserves:
        latest=reserves[-1]; reserve_text=f"Current recorded reserve: {latest.currency} {latest.amount:,.2f}. Latest reserve reason: {latest.reason}"
        reserve_sources=[_source("reserve_history",latest.id,"latest reserve")]
    elif claim.current_reserve is not None:
        reserve_text=f"Current recorded reserve: {claim.currency} {claim.current_reserve:,.2f}. No append-only reserve history entry is available for this amount."
        reserve_sources=[_source("claim",claim.id,"current reserve")]
    else:
        reserve_text="No reserve is currently recorded."
        reserve_sources=[]
    sections["reserve"]=("Reserve",100,reserve_text,reserve_sources)

    actions=[]; action_sources=[]
    for r in critical[:10]: actions.append(f"Obtain {r.document_label}."); action_sources.append(_source("document_requirement",r.id,r.rule_id))
    for t in tasks[:10]: actions.append(f"Complete task: {t.title}" + (f" by {t.due_date.isoformat()}" if t.due_date else "") + "."); action_sources.append(_source("claim_task",t.id,t.title))
    for c in open_conflicts[:5]: actions.append(f"Review evidence conflict: {c.topic}."); action_sources.append(_source("evidence_conflict",c.id,c.topic))
    for f in fin_flags:
        if f.status==FinancialFlagStatus.OPEN: actions.append(f"Review financial flag: {f.title}."); action_sources.append(_source("financial_flag",f.id,f.title))
    sections["actions"]=("Recommended Next Actions",110,"Recommended next actions:\n"+"\n".join(f"- {x}" for x in actions) if actions else "No open system-generated next actions are currently identified.",action_sources)

    return [(key,*sections[key]) for key,_,_ in SECTION_DEFS]


def generate_assessment(db: Session, *, claim: Claim, user: User, allow_if_not_ready: bool, override_reason: str | None) -> InitialAssessment:
    summary=get_rule_summary(db,claim=claim)
    not_ready=summary.readiness.state!="ready"
    if not_ready and not allow_if_not_ready:
        raise HTTPException(status_code=409,detail={"message":"Initial assessment is not ready","blocking_items":summary.readiness.blocking_items,"score":summary.readiness.score})
    latest=db.scalar(select(func.max(InitialAssessment.version)).where(InitialAssessment.organization_id==claim.organization_id,InitialAssessment.claim_id==claim.id)) or 0
    assessment=InitialAssessment(organization_id=claim.organization_id,claim_id=claim.id,version=latest+1,status=AssessmentStatus.DRAFT,readiness_score=summary.readiness.score,readiness_state=summary.readiness.state,blocking_items=summary.readiness.blocking_items,is_preliminary=not_ready,generation_override_reason=(override_reason or None),generated_by_id=user.id)
    db.add(assessment);db.flush()
    for key,title,order,text,sources in _build_sections(db,claim):
        db.add(AssessmentSection(organization_id=claim.organization_id,claim_id=claim.id,assessment_id=assessment.id,section_key=key,title=title,sort_order=order,draft_text=text,source_manifest=sources))
    write_audit_log(db,organization_id=claim.organization_id,user_id=user.id,action="GENERATE_INITIAL_ASSESSMENT",entity_type="initial_assessment",entity_id=assessment.id,new_values={"version":assessment.version,"readiness_score":assessment.readiness_score,"preliminary":assessment.is_preliminary,"blocking_items":assessment.blocking_items})
    db.commit();db.refresh(assessment);return assessment


def get_assessment(db: Session, *, claim: Claim, assessment_id: UUID | None=None) -> tuple[InitialAssessment | None,list[AssessmentSection]]:
    q=select(InitialAssessment).where(InitialAssessment.organization_id==claim.organization_id,InitialAssessment.claim_id==claim.id)
    q=q.where(InitialAssessment.id==assessment_id) if assessment_id else q.order_by(InitialAssessment.version.desc()).limit(1)
    a=db.scalar(q)
    if not a:return None,[]
    sections=list(db.scalars(select(AssessmentSection).where(AssessmentSection.assessment_id==a.id).order_by(AssessmentSection.sort_order.asc())))
    return a,sections


def review_section(db:Session,*,claim:Claim,section:AssessmentSection,user:User,action:str,text:str|None)->AssessmentSection:
    if section.claim_id!=claim.id or section.organization_id!=claim.organization_id: raise HTTPException(status_code=404,detail="Assessment section not found")
    section.status=AssessmentSectionStatus.EDITED if action=="edit" else AssessmentSectionStatus.APPROVED
    section.approved_text=text.strip() if action=="edit" and text else section.draft_text
    section.reviewed_by_id=user.id;section.reviewed_at=datetime.now(UTC)
    assessment=db.get(InitialAssessment,section.assessment_id)
    if assessment and assessment.status==AssessmentStatus.DRAFT: assessment.status=AssessmentStatus.UNDER_REVIEW
    write_audit_log(db,organization_id=claim.organization_id,user_id=user.id,action="REVIEW_ASSESSMENT_SECTION",entity_type="assessment_section",entity_id=section.id,new_values={"action":action,"section_key":section.section_key})
    db.commit();db.refresh(section);return section


def approve_assessment(db:Session,*,claim:Claim,assessment:InitialAssessment,user:User,note:str|None)->InitialAssessment:
    sections=list(db.scalars(select(AssessmentSection).where(AssessmentSection.assessment_id==assessment.id)))
    pending=[s.title for s in sections if s.status==AssessmentSectionStatus.PENDING]
    if pending: raise HTTPException(status_code=409,detail={"message":"All assessment sections must be reviewed before approval","pending_sections":pending})
    assessment.status=AssessmentStatus.APPROVED;assessment.approved_by_id=user.id;assessment.approved_at=datetime.now(UTC)
    write_audit_log(db,organization_id=claim.organization_id,user_id=user.id,action="APPROVE_INITIAL_ASSESSMENT",entity_type="initial_assessment",entity_id=assessment.id,new_values={"version":assessment.version,"preliminary":assessment.is_preliminary,"note":note})
    db.commit();db.refresh(assessment);return assessment
