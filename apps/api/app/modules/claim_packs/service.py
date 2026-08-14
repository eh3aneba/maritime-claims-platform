from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import re
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.assessments.models import (
    AssessmentSection,
    AssessmentStatus,
    InitialAssessment,
)
from app.modules.audit.service import write_audit_log
from app.modules.claim_packs.models import ClaimPackExport, ClaimPackFormat
from app.modules.claim_packs.renderers import render_pdf, render_xlsx
from app.modules.claims.models import Claim
from app.modules.claims.service import get_claim
from app.modules.documents.service import _storage
from app.modules.evidence_matrix.service import build_evidence_matrix
from app.modules.policy_intelligence.service import build_policy_intelligence
from app.modules.financial.models import (
    CostItem,
    FinancialFlag,
    FinancialFlagStatus,
)
from app.modules.rules.models import RequirementStatus
from app.modules.rules.service import get_rule_summary
from app.modules.tasks.models import ClaimTask, TaskStatus
from app.modules.users.models import User


SNAPSHOT_SCHEMA_VERSION = "1.0"
SATISFIED_REQUIREMENT_STATUSES = {
    RequirementStatus.RECEIVED,
    RequirementStatus.UNDER_REVIEW,
    RequirementStatus.ACCEPTED,
    RequirementStatus.NOT_REQUIRED,
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _approved_assessment(db: Session, claim: Claim) -> dict[str, Any] | None:
    assessment = db.scalar(
        select(InitialAssessment)
        .where(
            InitialAssessment.organization_id == claim.organization_id,
            InitialAssessment.claim_id == claim.id,
            InitialAssessment.status == AssessmentStatus.APPROVED,
        )
        .order_by(InitialAssessment.version.desc())
        .limit(1)
    )
    if assessment is None:
        return None
    sections = list(
        db.scalars(
            select(AssessmentSection)
            .where(AssessmentSection.assessment_id == assessment.id)
            .order_by(AssessmentSection.sort_order.asc())
        )
    )
    return {
        "id": str(assessment.id),
        "version": assessment.version,
        "is_preliminary": assessment.is_preliminary,
        "approved_at": _jsonable(assessment.approved_at),
        "readiness_score": assessment.readiness_score,
        "readiness_state": assessment.readiness_state,
        "blocking_items": _jsonable(assessment.blocking_items),
        "sections": [
            {
                "section_key": section.section_key,
                "title": section.title,
                "text": section.approved_text or section.draft_text,
                "sources": _jsonable(section.source_manifest),
            }
            for section in sections
        ],
    }


def build_claim_pack_snapshot(
    db: Session,
    *,
    claim: Claim,
    user: User,
    generation_note: str | None,
    generated_at: datetime,
) -> dict[str, Any]:
    matrix = build_evidence_matrix(
        db,
        claim_id=claim.id,
        organization_id=claim.organization_id,
    ).model_dump(mode="json")
    policy_intelligence = build_policy_intelligence(
        db,
        claim_id=claim.id,
        organization_id=claim.organization_id,
    ).model_dump(mode="json")
    rule_summary = get_rule_summary(db, claim=claim)
    outstanding = [
        requirement
        for requirement in rule_summary.requirements
        if requirement.status not in SATISFIED_REQUIREMENT_STATUSES
    ]
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
    cost_items = list(
        db.scalars(
            select(CostItem)
            .where(
                CostItem.organization_id == claim.organization_id,
                CostItem.claim_id == claim.id,
            )
            .order_by(CostItem.created_at.asc())
        )
    )
    open_flags = list(
        db.scalars(
            select(FinancialFlag)
            .where(
                FinancialFlag.organization_id == claim.organization_id,
                FinancialFlag.claim_id == claim.id,
                FinancialFlag.status == FinancialFlagStatus.OPEN,
            )
            .order_by(FinancialFlag.created_at.asc())
        )
    )
    assessment = _approved_assessment(db, claim)

    totals: dict[str, Decimal] = {}
    for item in cost_items:
        totals[item.currency] = totals.get(item.currency, Decimal("0")) + item.amount

    open_conflicts = matrix["summary"]["open_conflict_count"]
    if open_conflicts or outstanding:
        review_state = "attention_required"
    elif tasks or open_flags or (assessment and assessment["is_preliminary"]):
        review_state = "reviewed_with_open_items"
    else:
        review_state = "reviewed"

    snapshot = {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at": generated_at.isoformat(),
        "generation_note": generation_note,
        "review_aid_only": True,
        "claim": {
            "id": str(claim.id),
            "claim_reference": claim.claim_reference,
            "external_reference": claim.external_reference,
            "claim_type": claim.claim_type.value,
            "claim_subtype": claim.claim_subtype.value,
            "status": claim.status.value,
            "priority": claim.priority.value,
            "incident_date": claim.incident_date.isoformat(),
            "notification_date": claim.notification_date.isoformat(),
            "incident_description": claim.incident_description,
            "currency": claim.currency,
            "estimated_loss": _jsonable(claim.estimated_loss),
            "current_reserve": _jsonable(claim.current_reserve),
            "vessel_name": claim.vessel.name,
            "imo_number": claim.vessel.imo_number,
            "handler_name": claim.handler.full_name if claim.handler else None,
        },
        "generated_by": {
            "id": str(user.id),
            "full_name": user.full_name,
            "email": user.email,
            "role": user.role.value,
        },
        "evidence_matrix": matrix,
        "policy_intelligence": policy_intelligence,
        "outstanding_requirements": [
            {
                "id": str(item.id),
                "rule_id": item.rule_id,
                "document_type": item.document_type,
                "document_label": item.document_label,
                "priority": item.priority.value,
                "status": item.status.value,
                "reason": item.reason,
                "last_evaluated_at": _jsonable(item.last_evaluated_at),
            }
            for item in outstanding
        ],
        "open_tasks": [
            {
                "id": str(task.id),
                "title": task.title,
                "description": task.description,
                "task_type": task.task_type.value,
                "priority": task.priority.value,
                "source": task.source.value,
                "due_date": task.due_date.isoformat() if task.due_date else None,
            }
            for task in tasks
        ],
        "financial": {
            "totals_by_currency": {
                currency: str(amount) for currency, amount in sorted(totals.items())
            },
            "items": [
                {
                    "id": str(item.id),
                    "document_id": str(item.document_id),
                    "document_kind": item.document_kind,
                    "supplier": item.supplier,
                    "document_number": item.document_number,
                    "description": item.description,
                    "amount": str(item.amount),
                    "currency": item.currency,
                    "category": item.category,
                    "review_status": item.review_status.value,
                }
                for item in cost_items
            ],
            "open_flags": [
                {
                    "id": str(flag.id),
                    "flag_type": flag.flag_type.value,
                    "severity": flag.severity,
                    "title": flag.title,
                    "explanation": flag.explanation,
                    "status": flag.status.value,
                }
                for flag in open_flags
            ],
        },
        "approved_assessment": assessment,
        "summary": {
            "approved_fact_count": matrix["summary"]["approved_fact_count"],
            "open_conflict_count": open_conflicts,
            "outstanding_requirement_count": len(outstanding),
            "open_task_count": len(tasks),
            "open_financial_flag_count": len(open_flags),
            "policy_issue_count": policy_intelligence["summary"]["issue_count"],
            "high_priority_policy_issue_count": policy_intelligence["summary"]["high_priority_issue_count"],
            "approved_assessment_version": assessment["version"] if assessment else None,
            "assessment_is_preliminary": (
                assessment["is_preliminary"] if assessment else None
            ),
            "review_state": review_state,
        },
    }
    return _jsonable(snapshot)


def _snapshot_hash(snapshot: dict[str, Any]) -> str:
    canonical = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _safe_reference(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    return safe[:80] or "claim"


def generate_claim_pack(
    db: Session,
    *,
    claim_id: UUID,
    organization_id: UUID,
    user: User,
    export_format: ClaimPackFormat,
    generation_note: str | None,
) -> ClaimPackExport:
    claim = get_claim(
        db,
        claim_id=claim_id,
        organization_id=organization_id,
    )
    generated_at = datetime.now(UTC)
    note = generation_note.strip() if generation_note and generation_note.strip() else None
    snapshot = build_claim_pack_snapshot(
        db,
        claim=claim,
        user=user,
        generation_note=note,
        generated_at=generated_at,
    )
    snapshot_hash = _snapshot_hash(snapshot)
    if export_format == ClaimPackFormat.PDF:
        payload = render_pdf(snapshot)
        mime_type = "application/pdf"
        suffix = "pdf"
    else:
        payload = render_xlsx(snapshot)
        mime_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        suffix = "xlsx"

    export_id = uuid4()
    timestamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    filename = (
        f"{_safe_reference(claim.claim_reference)}-claim-pack-{timestamp}.{suffix}"
    )
    storage_key = (
        f"claim-pack-exports/{organization_id}/{claim.id}/{export_id}/{filename}"
    )
    stored = _storage().save_bytes(payload, storage_key)

    record = ClaimPackExport(
        id=export_id,
        organization_id=organization_id,
        claim_id=claim.id,
        generated_by_id=user.id,
        export_format=export_format,
        snapshot_schema_version=SNAPSHOT_SCHEMA_VERSION,
        snapshot=snapshot,
        snapshot_hash=snapshot_hash,
        generation_note=note,
        filename=filename,
        mime_type=mime_type,
        storage_key=storage_key,
        file_hash=stored.file_hash,
        file_size_bytes=stored.file_size_bytes,
    )
    try:
        db.add(record)
        db.flush()
        write_audit_log(
            db,
            organization_id=organization_id,
            user_id=user.id,
            action="GENERATE_CLAIM_PACK_EXPORT",
            entity_type="claim_pack_export",
            entity_id=record.id,
            new_values={
                "claim_id": str(claim.id),
                "format": export_format.value,
                "snapshot_hash": snapshot_hash,
                "file_hash": stored.file_hash,
                "review_state": snapshot["summary"]["review_state"],
            },
            details="Generated immutable controlled claim-pack snapshot.",
        )
        db.commit()
        db.refresh(record)
        return record
    except Exception:
        db.rollback()
        _storage().delete_physical(storage_key)
        raise


def list_claim_pack_exports(
    db: Session,
    *,
    claim_id: UUID,
    organization_id: UUID,
) -> list[ClaimPackExport]:
    get_claim(db, claim_id=claim_id, organization_id=organization_id)
    return list(
        db.scalars(
            select(ClaimPackExport)
            .where(
                ClaimPackExport.organization_id == organization_id,
                ClaimPackExport.claim_id == claim_id,
            )
            .order_by(ClaimPackExport.created_at.desc())
        )
    )


def get_claim_pack_export(
    db: Session,
    *,
    export_id: UUID,
    claim_id: UUID,
    organization_id: UUID,
) -> ClaimPackExport | None:
    get_claim(db, claim_id=claim_id, organization_id=organization_id)
    return db.scalar(
        select(ClaimPackExport).where(
            ClaimPackExport.id == export_id,
            ClaimPackExport.organization_id == organization_id,
            ClaimPackExport.claim_id == claim_id,
        )
    )
