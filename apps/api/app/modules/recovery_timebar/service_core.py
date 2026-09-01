from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.recovery_timebar.models import (
    RecoveryTimebarDecision,
    RecoveryTimebarEvaluation,
    RecoveryTimebarSnapshot,
)
from app.modules.recovery_timebar.schemas import RecoveryTimebarDecisionWrite
from app.modules.rules.service import evaluate_claim_rules
from app.modules.rules.marine_service import latest_marine_rule_summary
from app.modules.tasks.models import ClaimTask, TaskPriority, TaskSource, TaskStatus, TaskType
from app.modules.users.models import User

ENGINE_VERSION = "12C.1"
DISCLAIMER = (
    "Recovery & Time-bar Intelligence is source-linked decision support only. It does not determine liability, "
    "recoverability, limitation, waiver, suspension, extension, jurisdiction or settlement. Any candidate date is derived "
    "only from reviewed source inputs and requires human/legal verification before reliance or external action."
)
_ALLOWED_PERIOD_UNITS = {"days", "months", "years"}


def _jsonable(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
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


def _fact_source(fact: ClaimFact) -> dict[str, Any]:
    return {
        "kind": "claim_fact",
        "id": str(fact.id),
        "field_path": fact.field_path,
        "document_id": str(fact.source_document_id),
        "extraction_id": str(fact.source_extraction_id),
        "segment_id": str(fact.source_segment_id) if fact.source_segment_id else None,
        "version": fact.version,
    }


def _marine_recovery_rows(db: Session, claim: Claim) -> list[dict[str, Any]]:
    summary = latest_marine_rule_summary(db, claim=claim)
    rows = list(summary.get("marine_rule_evaluations") or [])
    return [
        row
        for row in rows
        if row.get("status") in {"triggered", "insufficient_evidence"}
        and (row.get("rule_id") == "TECH-002" or row.get("family") in {"emergency_services", "charterparty"})
    ]


def _marine_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "kind": "marine_rule_evaluation",
            "id": row.get("rule_id"),
            "rule_version": row.get("rule_version"),
            "status": row.get("status"),
            "evaluation_hash": row.get("evaluation_hash"),
            "source_reference": row.get("source_reference"),
        }
        for row in rows
    ]


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return None
    return None


def _parse_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _add_period(start: date, value: int, unit: str) -> date:
    if unit == "days":
        return start + timedelta(days=value)
    if unit == "months":
        month_index = (start.year * 12 + (start.month - 1)) + value
        year = month_index // 12
        month = month_index % 12 + 1
        return date(year, month, min(start.day, monthrange(year, month)[1]))
    if unit == "years":
        year = start.year + value
        return date(year, start.month, min(start.day, monthrange(year, start.month)[1]))
    raise ValueError("Unsupported period unit")


def _facts(db: Session, claim: Claim) -> list[ClaimFact]:
    return list(
        db.scalars(
            select(ClaimFact)
            .where(
                ClaimFact.organization_id == claim.organization_id,
                ClaimFact.claim_id == claim.id,
            )
            .order_by(ClaimFact.field_path.asc())
        )
    )


def _source_state(
    claim: Claim,
    facts: list[ClaimFact],
    marine_rows: list[dict[str, Any]],
    evaluation_date: date,
) -> dict[str, Any]:
    controlled = [
        fact
        for fact in facts
        if fact.field_path.startswith("recovery.") or fact.field_path.startswith("timebar.")
    ]
    return {
        "claim": {
            "id": str(claim.id),
            "status": claim.status.value,
            "incident_date": claim.incident_date.isoformat(),
            "notification_date": claim.notification_date.isoformat(),
        },
        "controlled_facts": [
            {
                "id": str(fact.id),
                "field_path": fact.field_path,
                "value": fact.value,
                "version": fact.version,
                "document_id": str(fact.source_document_id),
                "extraction_id": str(fact.source_extraction_id),
                "segment_id": str(fact.source_segment_id) if fact.source_segment_id else None,
            }
            for fact in controlled
        ],
        "marine_recovery_rows": [
            {
                "rule_id": row.get("rule_id"),
                "rule_version": row.get("rule_version"),
                "status": row.get("status"),
                "evaluation_hash": row.get("evaluation_hash"),
            }
            for row in marine_rows
        ],
        "evaluation_date": evaluation_date.isoformat(),
        "engine_version": ENGINE_VERSION,
    }


def _evaluation_payload(
    *,
    key: str,
    kind: str,
    status: str,
    title: str,
    counterparty: str | None,
    candidate_basis: str | None,
    trigger_date: date | None,
    period_value: int | None,
    period_unit: str | None,
    candidate_deadline: date | None,
    days_remaining: int | None,
    urgency: str,
    rationale: str,
    candidate_implication: str,
    recommended_action: str,
    missing_prerequisites: list[str],
    source_refs: list[dict[str, Any]],
) -> dict[str, Any]:
    row = {
        "evaluation_key": key,
        "kind": kind,
        "status": status,
        "title": title,
        "counterparty": counterparty,
        "candidate_basis": candidate_basis,
        "trigger_date": trigger_date,
        "period_value": period_value,
        "period_unit": period_unit,
        "candidate_deadline": candidate_deadline,
        "days_remaining": days_remaining,
        "urgency": urgency,
        "rationale": rationale,
        "candidate_implication": candidate_implication,
        "recommended_action": recommended_action,
        "missing_prerequisites": missing_prerequisites,
        "source_refs": source_refs,
    }
    row["evaluation_hash"] = _hash(row)
    return row


def _build_recovery_evaluation(
    fact_by_path: dict[str, ClaimFact], marine_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    counterparty_fact = fact_by_path.get("recovery.counterparty")
    basis_fact = fact_by_path.get("recovery.basis")
    preservation_fact = fact_by_path.get("recovery.evidence_preservation")
    notice_fact = fact_by_path.get("recovery.notice_requirement")
    explicit_signal = any((counterparty_fact, basis_fact, preservation_fact, notice_fact))
    marine_signal = bool(marine_rows)
    sources = [
        _fact_source(fact)
        for fact in (counterparty_fact, basis_fact, preservation_fact, notice_fact)
        if fact is not None
    ] + _marine_sources(marine_rows)

    if not explicit_signal and not marine_signal:
        return _evaluation_payload(
            key="recovery-primary",
            kind="recovery",
            status="not_applicable",
            title="No source-linked recovery lead identified",
            counterparty=None,
            candidate_basis=None,
            trigger_date=None,
            period_value=None,
            period_unit=None,
            candidate_deadline=None,
            days_remaining=None,
            urgency="low",
            rationale="No current human-approved recovery fact or relevant marine-rule signal is available.",
            candidate_implication="No recovery investigation is proposed from the current controlled source state.",
            recommended_action="Rebuild if reviewed evidence identifies a potentially responsible counterparty or recovery basis.",
            missing_prerequisites=[],
            source_refs=[],
        )

    counterparty = str(counterparty_fact.value).strip() if counterparty_fact and counterparty_fact.value not in (None, "") else None
    basis = str(basis_fact.value).strip() if basis_fact and basis_fact.value not in (None, "") else None
    triggered_marine_rows = [row for row in marine_rows if row.get("status") == "triggered"]
    if not basis and triggered_marine_rows:
        basis = "; ".join(
            str(row.get("candidate_implication") or row.get("rationale") or row.get("source_reference"))
            for row in triggered_marine_rows[:3]
        )
    missing = []
    if not counterparty:
        missing.append("identified recovery counterparty")
    if not basis:
        missing.append("reviewed recovery basis / reason to investigate")
    status = "triggered" if not missing else "insufficient_evidence"
    urgency = "high" if any(row.get("rule_id") == "TECH-002" and row.get("status") == "triggered" for row in marine_rows) else "medium"
    preservation = str(preservation_fact.value).strip() if preservation_fact and preservation_fact.value not in (None, "") else "Preserve technical, contractual and correspondence evidence relevant to the potential recovery."
    notice = str(notice_fact.value).strip() if notice_fact and notice_fact.value not in (None, "") else None
    action = preservation
    if notice:
        action += f" Reviewed notice requirement: {notice}"
    if missing:
        action += " Obtain and human-review the missing prerequisites before asserting responsibility or recoverability."
    return _evaluation_payload(
        key="recovery-primary",
        kind="recovery",
        status=status,
        title="Potential recovery investigation",
        counterparty=counterparty,
        candidate_basis=basis,
        trigger_date=None,
        period_value=None,
        period_unit=None,
        candidate_deadline=None,
        days_remaining=None,
        urgency=urgency,
        rationale=(
            "Controlled evidence creates a recovery investigation prompt. The engine has not determined fault, contractual "
            "responsibility, causation, recoverability or quantum."
        ),
        candidate_implication=(
            "A handler may need to preserve evidence and investigate a possible third-party recovery route before rights are prejudiced."
        ),
        recommended_action=action,
        missing_prerequisites=missing,
        source_refs=sources,
    )


def _build_timebar_evaluation(
    fact_by_path: dict[str, ClaimFact], recovery: dict[str, Any], evaluation_date: date
) -> dict[str, Any]:
    source_fact = fact_by_path.get("timebar.source_reference")
    trigger_fact = fact_by_path.get("timebar.trigger_date")
    period_value_fact = fact_by_path.get("timebar.period_value")
    period_unit_fact = fact_by_path.get("timebar.period_unit")
    extension_fact = fact_by_path.get("timebar.extension_days")
    label_fact = fact_by_path.get("timebar.label")
    timebar_signal = any((source_fact, trigger_fact, period_value_fact, period_unit_fact, extension_fact, label_fact))
    recovery_signal = recovery["status"] in {"triggered", "insufficient_evidence"}
    sources = [
        _fact_source(fact)
        for fact in (source_fact, trigger_fact, period_value_fact, period_unit_fact, extension_fact, label_fact)
        if fact is not None
    ]

    if not timebar_signal and not recovery_signal:
        return _evaluation_payload(
            key="timebar-primary",
            kind="timebar",
            status="not_applicable",
            title="No source-linked time-bar basis identified",
            counterparty=recovery.get("counterparty"),
            candidate_basis=None,
            trigger_date=None,
            period_value=None,
            period_unit=None,
            candidate_deadline=None,
            days_remaining=None,
            urgency="low",
            rationale="No controlled recovery signal or reviewed time-bar source basis is available.",
            candidate_implication="No candidate deadline is proposed from the current controlled source state.",
            recommended_action="Rebuild if reviewed wording or an approved time-sensitive fact becomes available.",
            missing_prerequisites=[],
            source_refs=[],
        )

    source_reference = str(source_fact.value).strip() if source_fact and source_fact.value not in (None, "") else None
    trigger_date = _parse_date(trigger_fact.value) if trigger_fact else None
    period_value = _parse_positive_int(period_value_fact.value) if period_value_fact else None
    period_unit = str(period_unit_fact.value).strip().lower() if period_unit_fact and period_unit_fact.value not in (None, "") else None
    if period_unit not in _ALLOWED_PERIOD_UNITS:
        period_unit = None
    extension_days = _parse_positive_int(extension_fact.value) if extension_fact else None
    missing = []
    if not source_reference:
        missing.append("reviewed time-bar / notice source reference")
    if not trigger_date:
        missing.append("human-approved trigger date")
    if not period_value:
        missing.append("reviewed period value")
    if not period_unit:
        missing.append("reviewed period unit (days/months/years)")

    candidate_deadline = None
    days_remaining = None
    urgency = "medium"
    status = "insufficient_evidence" if missing else "triggered"
    if not missing and trigger_date and period_value and period_unit:
        candidate_deadline = _add_period(trigger_date, period_value, period_unit)
        if extension_days:
            candidate_deadline += timedelta(days=extension_days)
        days_remaining = (candidate_deadline - evaluation_date).days
        if days_remaining <= 14:
            urgency = "critical"
        elif days_remaining <= 30:
            urgency = "high"
        elif days_remaining <= 90:
            urgency = "medium"
        else:
            urgency = "low"
    title = str(label_fact.value).strip() if label_fact and label_fact.value not in (None, "") else "Candidate recovery / notice deadline"
    basis = source_reference
    if extension_days:
        basis = f"{source_reference}; reviewed extension {extension_days} days"
    return _evaluation_payload(
        key="timebar-primary",
        kind="timebar",
        status=status,
        title=title,
        counterparty=recovery.get("counterparty"),
        candidate_basis=basis,
        trigger_date=trigger_date,
        period_value=period_value,
        period_unit=period_unit,
        candidate_deadline=candidate_deadline,
        days_remaining=days_remaining,
        urgency=urgency,
        rationale=(
            "The candidate date is derived only from the cited reviewed source reference, approved trigger date and reviewed "
            "period inputs. It is not an authoritative limitation or notice conclusion."
        ),
        candidate_implication=(
            "Human/legal verification is required before relying on any candidate date, sending notice, commencing proceedings "
            "or concluding that rights have expired."
        ),
        recommended_action=(
            "Verify the cited wording, governing contract/law/jurisdiction and trigger event. If accepted, create a controlled "
            "diary task; do not send external correspondence automatically."
        ),
        missing_prerequisites=missing,
        source_refs=sources,
    )


def _latest_snapshot(db: Session, *, claim: Claim) -> RecoveryTimebarSnapshot | None:
    return db.scalar(
        select(RecoveryTimebarSnapshot)
        .where(
            RecoveryTimebarSnapshot.organization_id == claim.organization_id,
            RecoveryTimebarSnapshot.claim_id == claim.id,
        )
        .order_by(RecoveryTimebarSnapshot.snapshot_version.desc())
        .limit(1)
    )


def _snapshot_evaluations(db: Session, snapshot_id: UUID) -> list[RecoveryTimebarEvaluation]:
    return list(
        db.scalars(
            select(RecoveryTimebarEvaluation)
            .where(RecoveryTimebarEvaluation.snapshot_id == snapshot_id)
            .order_by(RecoveryTimebarEvaluation.kind.asc(), RecoveryTimebarEvaluation.evaluation_key.asc())
        )
    )


def _latest_decision(db: Session, evaluation_id: UUID) -> RecoveryTimebarDecision | None:
    return db.scalar(
        select(RecoveryTimebarDecision)
        .where(RecoveryTimebarDecision.evaluation_id == evaluation_id)
        .order_by(RecoveryTimebarDecision.decision_number.desc())
        .limit(1)
    )


def snapshot_response(db: Session, snapshot: RecoveryTimebarSnapshot) -> dict[str, Any]:
    evaluations = []
    for row in _snapshot_evaluations(db, snapshot.id):
        evaluations.append(
            {
                "id": row.id,
                "snapshot_id": row.snapshot_id,
                "evaluation_key": row.evaluation_key,
                "kind": row.kind,
                "status": row.status,
                "title": row.title,
                "counterparty": row.counterparty,
                "candidate_basis": row.candidate_basis,
                "trigger_date": row.trigger_date,
                "period_value": row.period_value,
                "period_unit": row.period_unit,
                "candidate_deadline": row.candidate_deadline,
                "days_remaining": row.days_remaining,
                "urgency": row.urgency,
                "rationale": row.rationale,
                "candidate_implication": row.candidate_implication,
                "recommended_action": row.recommended_action,
                "missing_prerequisites": list(row.missing_prerequisites or []),
                "source_refs": list(row.source_refs or []),
                "evaluation_hash": row.evaluation_hash,
                "latest_decision": _latest_decision(db, row.id),
            }
        )
    return {
        "id": snapshot.id,
        "claim_id": snapshot.claim_id,
        "generated_by_id": snapshot.generated_by_id,
        "snapshot_version": snapshot.snapshot_version,
        "engine_version": snapshot.engine_version,
        "evaluation_date": snapshot.evaluation_date,
        "source_state_hash": snapshot.source_state_hash,
        "snapshot_hash": snapshot.snapshot_hash,
        "summary": dict(snapshot.summary or {}),
        "generated_at": snapshot.generated_at,
        "evaluations": evaluations,
    }


def dashboard_response(db: Session, *, claim: Claim) -> dict[str, Any]:
    snapshot = _latest_snapshot(db, claim=claim)
    return {
        "claim_id": claim.id,
        "snapshot": snapshot_response(db, snapshot) if snapshot else None,
        "disclaimer": DISCLAIMER,
    }


def build_recovery_timebar(db: Session, *, claim: Claim, user: User) -> RecoveryTimebarSnapshot:
    evaluate_claim_rules(db, claim=claim, user=user, trigger="recovery_timebar")
    facts = _facts(db, claim)
    fact_by_path = {fact.field_path: fact for fact in facts}
    marine_rows = _marine_recovery_rows(db, claim)
    evaluation_date = datetime.now(UTC).date()
    state = _source_state(claim, facts, marine_rows, evaluation_date)
    source_state_hash = _hash(state)

    existing = db.scalar(
        select(RecoveryTimebarSnapshot).where(
            RecoveryTimebarSnapshot.organization_id == claim.organization_id,
            RecoveryTimebarSnapshot.claim_id == claim.id,
            RecoveryTimebarSnapshot.source_state_hash == source_state_hash,
        )
    )
    if existing is not None:
        return existing

    recovery = _build_recovery_evaluation(fact_by_path, marine_rows)
    timebar = _build_timebar_evaluation(fact_by_path, recovery, evaluation_date)
    payloads = [recovery, timebar]
    summary = {
        "source_linked": True,
        "non_authoritative": True,
        "human_legal_verification_required": True,
        "evaluation_count": 2,
        "triggered_count": sum(1 for row in payloads if row["status"] == "triggered"),
        "insufficient_evidence_count": sum(1 for row in payloads if row["status"] == "insufficient_evidence"),
        "candidate_deadline_count": sum(1 for row in payloads if row["candidate_deadline"] is not None),
        "recoverability_decision_made": False,
        "liability_decision_made": False,
        "authoritative_deadline_created": False,
        "external_correspondence_sent": False,
    }
    snapshot_hash = _hash(
        {
            "engine": ENGINE_VERSION,
            "source_state_hash": source_state_hash,
            "summary": summary,
            "evaluation_hashes": [row["evaluation_hash"] for row in payloads],
        }
    )
    current_max = db.scalar(
        select(func.max(RecoveryTimebarSnapshot.snapshot_version)).where(
            RecoveryTimebarSnapshot.organization_id == claim.organization_id,
            RecoveryTimebarSnapshot.claim_id == claim.id,
        )
    ) or 0
    now = datetime.now(UTC)
    snapshot = RecoveryTimebarSnapshot(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        generated_by_id=user.id,
        snapshot_version=current_max + 1,
        engine_version=ENGINE_VERSION,
        evaluation_date=evaluation_date,
        source_state_hash=source_state_hash,
        snapshot_hash=snapshot_hash,
        summary=summary,
        generated_at=now,
    )
    db.add(snapshot)
    db.flush()
    for payload in payloads:
        db.add(
            RecoveryTimebarEvaluation(
                organization_id=claim.organization_id,
                claim_id=claim.id,
                snapshot_id=snapshot.id,
                **payload,
            )
        )
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="BUILD_RECOVERY_TIMEBAR_INTELLIGENCE",
        entity_type="claim",
        entity_id=claim.id,
        new_values={
            "snapshot_id": str(snapshot.id),
            "snapshot_version": snapshot.snapshot_version,
            "source_state_hash": source_state_hash,
            "snapshot_hash": snapshot_hash,
            **summary,
        },
        details="Built immutable source-linked Recovery & Time-bar Intelligence without making liability/recoverability conclusions.",
    )
    db.commit()
    db.refresh(snapshot)
    return snapshot


def record_decision(
    db: Session,
    *,
    claim: Claim,
    evaluation: RecoveryTimebarEvaluation,
    payload: RecoveryTimebarDecisionWrite,
    user: User,
) -> RecoveryTimebarDecision:
    if evaluation.organization_id != claim.organization_id or evaluation.claim_id != claim.id:
        raise ValueError("Recovery/time-bar evaluation does not belong to this claim")
    latest_snapshot = _latest_snapshot(db, claim=claim)
    if latest_snapshot is None or latest_snapshot.id != evaluation.snapshot_id:
        raise ValueError("Recovery/time-bar evaluation belongs to a superseded snapshot; review the latest snapshot instead")
    if payload.evaluation_hash != evaluation.evaluation_hash:
        raise ValueError("Evaluation hash does not match the immutable evaluation under review")
    if payload.convert_to_task and payload.action in {"dismiss", "not_applicable"}:
        raise ValueError("Dismissed/not-applicable evaluations cannot create controlled tasks")

    previous = _latest_decision(db, evaluation.id)
    if payload.convert_to_task:
        existing_task = db.scalar(
            select(RecoveryTimebarDecision.converted_task_id)
            .where(
                RecoveryTimebarDecision.organization_id == claim.organization_id,
                RecoveryTimebarDecision.claim_id == claim.id,
                RecoveryTimebarDecision.evaluation_id == evaluation.id,
                RecoveryTimebarDecision.converted_task_id.is_not(None),
            )
            .order_by(RecoveryTimebarDecision.decision_number.desc())
            .limit(1)
        )
        if existing_task is not None:
            raise ValueError("A controlled claim task has already been created from this recovery/time-bar evaluation")

    number = (previous.decision_number + 1) if previous else 1
    task: ClaimTask | None = None
    if payload.convert_to_task:
        due_date = payload.edited_due_date or evaluation.candidate_deadline
        title = (
            payload.edited_recommended_action
            if payload.action == "edit" and payload.edited_recommended_action
            else evaluation.title
        )
        description = (
            payload.edited_recommended_action
            if payload.action == "edit" and payload.edited_recommended_action
            else evaluation.recommended_action
        )
        task = ClaimTask(
            organization_id=claim.organization_id,
            claim_id=claim.id,
            requirement_id=None,
            request_batch_id=None,
            assignee_id=claim.handler_id or user.id,
            title=title[:220],
            description=description,
            task_type=TaskType.FOLLOW_UP if evaluation.kind == "timebar" else TaskType.REVIEW,
            status=TaskStatus.OPEN,
            priority=TaskPriority.CRITICAL if evaluation.urgency == "critical" else TaskPriority.HIGH if evaluation.urgency == "high" else TaskPriority.MEDIUM,
            source=TaskSource.AI_SUGGESTION,
            due_date=due_date,
        )
        db.add(task)
        db.flush()

    now = datetime.now(UTC)
    decision_payload = {
        "evaluation_hash": evaluation.evaluation_hash,
        "decision_number": number,
        "action": payload.action,
        "note": payload.note.strip(),
        "edited_candidate_implication": payload.edited_candidate_implication,
        "edited_recommended_action": payload.edited_recommended_action,
        "edited_due_date": payload.edited_due_date.isoformat() if payload.edited_due_date else None,
        "converted_task_id": str(task.id) if task else None,
        "previous_decision_hash": previous.decision_hash if previous else None,
        "decided_by_id": str(user.id),
        "decided_at": now.isoformat(),
    }
    decision = RecoveryTimebarDecision(
        organization_id=claim.organization_id,
        claim_id=claim.id,
        evaluation_id=evaluation.id,
        decided_by_id=user.id,
        converted_task_id=task.id if task else None,
        decision_number=number,
        evaluation_hash=evaluation.evaluation_hash,
        action=payload.action,
        note=payload.note.strip(),
        edited_candidate_implication=payload.edited_candidate_implication,
        edited_recommended_action=payload.edited_recommended_action,
        edited_due_date=payload.edited_due_date,
        previous_decision_hash=previous.decision_hash if previous else None,
        decision_hash=_hash(decision_payload),
        decided_at=now,
    )
    db.add(decision)
    db.flush()
    write_audit_log(
        db,
        organization_id=claim.organization_id,
        user_id=user.id,
        action="REVIEW_RECOVERY_TIMEBAR_EVALUATION",
        entity_type="recovery_timebar_evaluation",
        entity_id=evaluation.id,
        new_values={
            "decision_id": str(decision.id),
            "decision_number": number,
            "action": payload.action,
            "decision_hash": decision.decision_hash,
            "converted_task_id": str(task.id) if task else None,
        },
        details="Human recovery/time-bar disposition recorded separately from immutable source-linked evaluation.",
    )
    db.commit()
    db.refresh(decision)
    return decision
