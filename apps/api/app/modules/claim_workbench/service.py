from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ai_production_wide.models import AIProductionDecisionLog
from app.modules.claim_intelligence.models import ClaimIntelligenceItem, ClaimIntelligenceSnapshot
from app.modules.claims.models import Claim
from app.modules.evidence_search.qa_synthesis_models import ClaimQaSynthesisRun
from app.modules.financial.models import FinancialFlag, FinancialFlagStatus
from app.modules.recovery_timebar.models import RecoveryTimebarEvaluation, RecoveryTimebarSnapshot
from app.modules.severity_reserve.models import SeverityReserveEvaluation, SeverityReserveSnapshot
from app.modules.tasks.models import ClaimTask, TaskStatus
from app.modules.users.models import User, UserRole
from app.modules.claim_workbench.schemas import WorkbenchFilters

RANKING_VERSION = "12J.1"
MAX_SOURCE_ROWS = 20_000


def _enum(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _hash(payload: dict) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _latest_snapshots(rows) -> dict[UUID, object]:
    latest: dict[UUID, object] = {}
    for row in rows:
        current = latest.get(row.claim_id)
        if current is None or row.snapshot_version > current.snapshot_version:
            latest[row.claim_id] = row
    return latest


def _severity_hint(label: str | None) -> tuple[int, str]:
    normalized = (label or "").lower()
    return {
        "critical": (70, "critical"),
        "high": (50, "urgent"),
        "medium": (25, "elevated"),
        "low": (10, "routine"),
    }.get(normalized, (0, "routine"))


def _financial_hint(label: str | None) -> tuple[int, str]:
    normalized = (label or "").lower()
    return {
        "critical": (65, "critical"),
        "high": (45, "urgent"),
        "medium": (25, "elevated"),
        "low": (10, "routine"),
    }.get(normalized, (15, "elevated"))


def _timebar_hint(row: RecoveryTimebarEvaluation, today: date) -> tuple[int, str]:
    if row.candidate_deadline is not None:
        remaining = (row.candidate_deadline - today).days
        if remaining <= 0:
            return 100, "critical"
        if remaining <= 7:
            return 90, "critical"
        if remaining <= 30:
            return 65, "urgent"
        if remaining <= 90:
            return 35, "elevated"
    urgency = (row.urgency or "").lower()
    return {
        "critical": (80, "critical"),
        "urgent": (60, "urgent"),
        "high": (50, "urgent"),
        "medium": (30, "elevated"),
        "low": (10, "routine"),
    }.get(urgency, (0, "routine"))


def _task_hint(row: ClaimTask, today: date) -> tuple[int, str]:
    priority = _enum(row.priority).lower()
    base = {"critical": 55, "high": 35, "medium": 20, "low": 10}.get(priority, 15)
    due = 0
    if row.due_date is not None:
        remaining = (row.due_date - today).days
        if remaining <= 0:
            due = 45
        elif remaining <= 7:
            due = 35
        elif remaining <= 30:
            due = 20
    weight = min(base + due, 100)
    hint = "critical" if weight >= 80 else "urgent" if weight >= 55 else "elevated" if weight >= 25 else "routine"
    return weight, hint


def _intelligence_hint(row: ClaimIntelligenceItem) -> tuple[int, str]:
    base, hint = _severity_hint(row.severity)
    weight = min(base + min(max(row.urgency_score or 0, 0), 20), 80)
    if weight >= 65:
        hint = "urgent"
    elif weight >= 30:
        hint = "elevated"
    return weight, hint


def _factor(*, source_type: str, source_id: UUID, source_hash: str | None, category: str, label: str,
            weight: int, priority_hint: str, href: str, due_date: date | None = None,
            due_semantics: str = "none") -> dict:
    return {
        "source_type": source_type,
        "source_id": source_id,
        "source_hash": source_hash,
        "category": category,
        "label": label,
        "weight": weight,
        "priority_hint": priority_hint,
        "due_date": due_date,
        "due_semantics": due_semantics,
        "href": href,
    }


def _rank_claim(claim: Claim, factors: list[dict], source_times: list[datetime]) -> dict:
    factors = [factor for factor in factors if factor["weight"] > 0]
    factors.sort(key=lambda f: (-f["weight"], f["source_type"], str(f["source_id"]), f["category"]))
    rank_score = min(sum(factor["weight"] for factor in factors), 999)
    hints = {factor["priority_hint"] for factor in factors}
    if "critical" in hints or rank_score >= 90:
        priority = "critical"
    elif "urgent" in hints or rank_score >= 60:
        priority = "urgent"
    elif "elevated" in hints or rank_score >= 25:
        priority = "elevated"
    else:
        priority = "routine"

    due_factors = [factor for factor in factors if factor["due_date"] is not None]
    due_factors.sort(key=lambda f: (f["due_date"], 0 if f["due_semantics"] == "authoritative_task_due" else 1, str(f["source_id"])))
    nearest = due_factors[0] if due_factors else None
    hash_payload = {
        "ranking_version": RANKING_VERSION,
        "claim_id": str(claim.id),
        "claim_status": _enum(claim.status),
        "handler_id": str(claim.handler_id) if claim.handler_id else None,
        "factors": [
            {
                "source_type": factor["source_type"],
                "source_id": str(factor["source_id"]),
                "source_hash": factor["source_hash"],
                "category": factor["category"],
                "weight": factor["weight"],
                "priority_hint": factor["priority_hint"],
                "due_date": factor["due_date"].isoformat() if factor["due_date"] else None,
                "due_semantics": factor["due_semantics"],
            }
            for factor in factors
        ],
    }
    normalized_times = [_as_utc(value) for value in source_times if value is not None]
    source_state_time = max(normalized_times) if normalized_times else _as_utc(claim.updated_at)
    return {
        "claim_id": claim.id,
        "claim_reference": claim.claim_reference,
        "claim_type": _enum(claim.claim_type),
        "claim_status": _enum(claim.status),
        "handler_id": claim.handler_id,
        "priority": priority,
        "rank_score": rank_score,
        "ranking_version": RANKING_VERSION,
        "rank_hash": _hash(hash_payload),
        "requires_action": bool(factors),
        "nearest_due_date": nearest["due_date"] if nearest else None,
        "nearest_due_semantics": nearest["due_semantics"] if nearest else "none",
        "factors": factors,
        "source_state_time": source_state_time,
    }


def _build_rows(db: Session, user: User) -> list[dict]:
    organization_id = user.organization_id
    claim_stmt = select(Claim).where(Claim.organization_id == organization_id, Claim.deleted_at.is_(None))
    if user.role == UserRole.CLAIMS_HANDLER:
        claim_stmt = claim_stmt.where(Claim.handler_id == user.id)
    claims = list(db.scalars(claim_stmt.order_by(Claim.claim_reference.asc()).limit(MAX_SOURCE_ROWS)))
    if not claims:
        return []
    claim_ids = {claim.id for claim in claims}
    factors_by_claim: dict[UUID, list[dict]] = {claim.id: [] for claim in claims}
    times_by_claim: dict[UUID, list[datetime]] = {claim.id: [] for claim in claims}
    today = datetime.now(UTC).date()

    severity_snapshots = _latest_snapshots(list(db.scalars(
        select(SeverityReserveSnapshot)
        .where(SeverityReserveSnapshot.organization_id == organization_id, SeverityReserveSnapshot.claim_id.in_(claim_ids))
        .limit(MAX_SOURCE_ROWS)
    )))
    severity_snapshot_ids = {row.id for row in severity_snapshots.values()}
    if severity_snapshot_ids:
        for row in db.scalars(select(SeverityReserveEvaluation).where(
            SeverityReserveEvaluation.organization_id == organization_id,
            SeverityReserveEvaluation.snapshot_id.in_(severity_snapshot_ids),
        ).limit(MAX_SOURCE_ROWS)):
            if row.kind != "severity" or row.status in {"not_applicable"}:
                continue
            weight, hint = _severity_hint(row.severity_label)
            if weight:
                factors_by_claim[row.claim_id].append(_factor(
                    source_type="severity_reserve", source_id=row.id, source_hash=row.evaluation_hash,
                    category="handling_severity", label=f"Handling severity: {row.severity_label}",
                    weight=weight, priority_hint=hint, href=f"/claims/{row.claim_id}/severity-reserve",
                ))
                times_by_claim[row.claim_id].append(severity_snapshots[row.claim_id].generated_at)

    recovery_snapshots = _latest_snapshots(list(db.scalars(
        select(RecoveryTimebarSnapshot)
        .where(RecoveryTimebarSnapshot.organization_id == organization_id, RecoveryTimebarSnapshot.claim_id.in_(claim_ids))
        .limit(MAX_SOURCE_ROWS)
    )))
    recovery_snapshot_ids = {row.id for row in recovery_snapshots.values()}
    if recovery_snapshot_ids:
        for row in db.scalars(select(RecoveryTimebarEvaluation).where(
            RecoveryTimebarEvaluation.organization_id == organization_id,
            RecoveryTimebarEvaluation.snapshot_id.in_(recovery_snapshot_ids),
        ).limit(MAX_SOURCE_ROWS)):
            if row.kind != "timebar" or row.status in {"not_applicable", "insufficient_evidence"}:
                continue
            weight, hint = _timebar_hint(row, today)
            if weight:
                label = "Candidate time-bar requires review"
                if row.candidate_deadline is not None:
                    label = f"Candidate time-bar: {row.candidate_deadline.isoformat()}"
                factors_by_claim[row.claim_id].append(_factor(
                    source_type="recovery_timebar", source_id=row.id, source_hash=row.evaluation_hash,
                    category="candidate_timebar", label=label, weight=weight, priority_hint=hint,
                    href=f"/claims/{row.claim_id}/recovery-timebar", due_date=row.candidate_deadline,
                    due_semantics="candidate_timebar",
                ))
                times_by_claim[row.claim_id].append(recovery_snapshots[row.claim_id].generated_at)

    for row in db.scalars(select(FinancialFlag).where(
        FinancialFlag.organization_id == organization_id,
        FinancialFlag.claim_id.in_(claim_ids),
        FinancialFlag.status == FinancialFlagStatus.OPEN,
    ).limit(MAX_SOURCE_ROWS)):
        weight, hint = _financial_hint(row.severity)
        factors_by_claim[row.claim_id].append(_factor(
            source_type="financial_flag", source_id=row.id, source_hash=row.fingerprint,
            category="financial_flag", label=f"Open financial flag: {_enum(row.flag_type).replace('_', ' ')}",
            weight=weight, priority_hint=hint, href=f"/claims/{row.claim_id}/financial",
        ))
        times_by_claim[row.claim_id].append(row.updated_at)

    intelligence_snapshots = _latest_snapshots(list(db.scalars(
        select(ClaimIntelligenceSnapshot)
        .where(ClaimIntelligenceSnapshot.organization_id == organization_id, ClaimIntelligenceSnapshot.claim_id.in_(claim_ids))
        .limit(MAX_SOURCE_ROWS)
    )))
    intelligence_snapshot_ids = {row.id for row in intelligence_snapshots.values()}
    if intelligence_snapshot_ids:
        for row in db.scalars(select(ClaimIntelligenceItem).where(
            ClaimIntelligenceItem.organization_id == organization_id,
            ClaimIntelligenceItem.snapshot_id.in_(intelligence_snapshot_ids),
        ).limit(MAX_SOURCE_ROWS)):
            category = (row.category or "").lower()
            if "missing" not in category and "conflict" not in category:
                continue
            weight, hint = _intelligence_hint(row)
            safe_category = "missing_evidence" if "missing" in category else "conflict"
            factors_by_claim[row.claim_id].append(_factor(
                source_type="claim_intelligence", source_id=row.id, source_hash=row.item_hash,
                category=safe_category,
                label="Missing evidence requires handler review" if safe_category == "missing_evidence" else "Unresolved evidence conflict requires review",
                weight=weight, priority_hint=hint, href=f"/claims/{row.claim_id}/intelligence",
            ))
            times_by_claim[row.claim_id].append(intelligence_snapshots[row.claim_id].generated_at)

    for row in db.scalars(select(ClaimTask).where(
        ClaimTask.organization_id == organization_id,
        ClaimTask.claim_id.in_(claim_ids),
        ClaimTask.status == TaskStatus.OPEN,
    ).limit(MAX_SOURCE_ROWS)):
        weight, hint = _task_hint(row, today)
        factors_by_claim[row.claim_id].append(_factor(
            source_type="claim_task", source_id=row.id, source_hash=None,
            category="open_task", label=f"Open {_enum(row.priority)} task",
            weight=weight, priority_hint=hint, href=f"/claims/{row.claim_id}",
            due_date=row.due_date, due_semantics="authoritative_task_due" if row.due_date else "none",
        ))
        times_by_claim[row.claim_id].append(row.updated_at)

    for row in db.scalars(select(AIProductionDecisionLog).where(
        AIProductionDecisionLog.organization_id == organization_id,
        AIProductionDecisionLog.claim_id.in_(claim_ids),
        AIProductionDecisionLog.status != "human_reviewed",
    ).limit(MAX_SOURCE_ROWS)):
        factors_by_claim[row.claim_id].append(_factor(
            source_type="ai_decision_log", source_id=row.id, source_hash=row.run_hash,
            category="pending_ai_review", label="Pending different-human AI review",
            weight=25, priority_hint="elevated", href=f"/ai-operations?claim_id={row.claim_id}",
        ))
        times_by_claim[row.claim_id].append(row.queued_at)

    for row in db.scalars(select(ClaimQaSynthesisRun).where(
        ClaimQaSynthesisRun.organization_id == organization_id,
        ClaimQaSynthesisRun.claim_id.in_(claim_ids),
    ).limit(MAX_SOURCE_ROWS)):
        if row.status == "completed" and not row.failure_code and not row.fallback_used:
            continue
        factors_by_claim[row.claim_id].append(_factor(
            source_type="ai_operations", source_id=row.id, source_hash=row.output_hash or row.input_hash,
            category="governed_ai_attention", label="Governed Claim Q&A requires operational attention",
            weight=20, priority_hint="elevated", href=f"/ai-operations?claim_id={row.claim_id}",
        ))
        if row.completed_at:
            times_by_claim[row.claim_id].append(row.completed_at)

    rows = [_rank_claim(claim, factors_by_claim[claim.id], times_by_claim[claim.id]) for claim in claims]
    rows.sort(key=lambda row: (
        -row["rank_score"],
        row["nearest_due_date"] or date.max,
        row["claim_reference"],
        str(row["claim_id"]),
    ))
    return rows


def _matches(row: dict, filters: WorkbenchFilters, today: date) -> bool:
    if filters.priority and row["priority"] != filters.priority:
        return False
    if filters.claim_status and row["claim_status"] != filters.claim_status:
        return False
    if filters.claim_type and row["claim_type"] != filters.claim_type:
        return False
    if filters.handler_id and row["handler_id"] != filters.handler_id:
        return False
    if filters.attention_category and not any(f["category"] == filters.attention_category for f in row["factors"]):
        return False
    if filters.source_type and not any(f["source_type"] == filters.source_type for f in row["factors"]):
        return False
    if filters.requires_action is not None and row["requires_action"] != filters.requires_action:
        return False
    if filters.overdue_or_due_soon is not None:
        due_soon = row["nearest_due_date"] is not None and row["nearest_due_date"] <= today + timedelta(days=30)
        if due_soon != filters.overdue_or_due_soon:
            return False
    return True


def query_workbench(db: Session, user: User, filters: WorkbenchFilters, *, page: int, page_size: int) -> dict:
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(422, "Claims Workbench pagination must use page >= 1 and page_size 1..100")
    today = datetime.now(UTC).date()
    rows = [row for row in _build_rows(db, user) if _matches(row, filters, today)]
    start = (page - 1) * page_size
    end = start + page_size
    return {"rows": rows[start:end], "page": page, "page_size": page_size, "total": len(rows), "has_more": end < len(rows)}


def get_claim_row(db: Session, user: User, claim_id: UUID) -> dict:
    rows = _build_rows(db, user)
    for row in rows:
        if row["claim_id"] == claim_id:
            return row
    raise HTTPException(404, "Claims Workbench claim not found")


def dashboard(db: Session, user: User) -> dict:
    rows = _build_rows(db, user)
    today = datetime.now(UTC).date()
    metrics = {
        "claim_count": len(rows),
        "critical_count": sum(row["priority"] == "critical" for row in rows),
        "urgent_count": sum(row["priority"] == "urgent" for row in rows),
        "elevated_count": sum(row["priority"] == "elevated" for row in rows),
        "due_soon_count": sum(row["nearest_due_date"] is not None and row["nearest_due_date"] <= today + timedelta(days=30) for row in rows),
        "missing_evidence_count": sum(any(f["category"] == "missing_evidence" for f in row["factors"]) for row in rows),
        "conflict_count": sum(any(f["category"] == "conflict" for f in row["factors"]) for row in rows),
        "financial_flag_count": sum(any(f["category"] == "financial_flag" for f in row["factors"]) for row in rows),
        "pending_ai_review_count": sum(any(f["category"] == "pending_ai_review" for f in row["factors"]) for row in rows),
    }
    return {
        "metrics": metrics,
        "rows": rows[:100],
        "ranking_version": RANKING_VERSION,
        "operational_triage_only": True,
        "claim_merits_decision": False,
    }
