from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.pilot.models import PilotEvent, PilotFeedback, PilotSession
from app.modules.pilot.schemas import PilotBacklogItem, PilotMetrics, PilotScorecard
from app.modules.users.models import User




def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

AI_EVENT_TO_ACTION = {
    "ai_review_approved": "approved",
    "ai_review_edited": "edited",
    "ai_review_rejected": "rejected",
}


def get_active_session(db: Session, *, organization_id: UUID, claim_id: UUID, user_id: UUID | None = None) -> PilotSession | None:
    query = select(PilotSession).where(
        PilotSession.organization_id == organization_id,
        PilotSession.claim_id == claim_id,
        PilotSession.status == "active",
    )
    if user_id is not None:
        query = query.where(PilotSession.participant_user_id == user_id)
    return db.scalar(query.order_by(PilotSession.started_at.desc()))


def start_session(db: Session, *, claim: Claim, user: User, participant_role: str, objective: str | None, baseline_assessment_minutes: int | None) -> PilotSession:
    existing = get_active_session(db, organization_id=user.organization_id, claim_id=claim.id, user_id=user.id)
    if existing:
        return existing
    row = PilotSession(
        organization_id=user.organization_id,
        claim_id=claim.id,
        participant_user_id=user.id,
        facilitator_user_id=user.id,
        participant_role=participant_role,
        objective=objective,
        baseline_assessment_minutes=baseline_assessment_minutes,
        status="active",
        started_at=datetime.now(UTC),
    )
    db.add(row)
    db.flush()
    record_event(db, session=row, user_id=user.id, event_type="pilot_session_started", source="server")
    write_audit_log(db, organization_id=user.organization_id, user_id=user.id, action="START_PILOT_SESSION", entity_type="pilot_session", entity_id=row.id, new_values={"claim_id": str(claim.id), "participant_role": participant_role})
    return row


def end_session(db: Session, *, session: PilotSession, user: User, status: str, note: str | None) -> PilotSession:
    if session.organization_id != user.organization_id:
        raise ValueError("Pilot session does not belong to the current organization.")
    if session.status != "active":
        raise ValueError("Pilot session is already closed.")
    session.status = status
    session.ended_at = datetime.now(UTC)
    if note:
        data = dict(session.session_data or {})
        data["closing_note"] = note
        session.session_data = data
    record_event(db, session=session, user_id=user.id, event_type="pilot_session_ended", source="server", event_data={"status": status})
    write_audit_log(db, organization_id=user.organization_id, user_id=user.id, action="END_PILOT_SESSION", entity_type="pilot_session", entity_id=session.id, new_values={"status": status})
    return session


def get_session(db: Session, *, session_id: UUID, organization_id: UUID) -> PilotSession | None:
    return db.scalar(select(PilotSession).where(PilotSession.id == session_id, PilotSession.organization_id == organization_id))


def record_event(db: Session, *, session: PilotSession, user_id: UUID | None, event_type: str, source: str = "server", entity_type: str | None = None, entity_id: UUID | None = None, duration_ms: int | None = None, event_data: dict | None = None) -> PilotEvent:
    event = PilotEvent(
        organization_id=session.organization_id,
        session_id=session.id,
        claim_id=session.claim_id,
        user_id=user_id,
        event_type=event_type,
        source=source,
        entity_type=entity_type,
        entity_id=entity_id,
        duration_ms=duration_ms,
        event_data=event_data,
        created_at=datetime.now(UTC),
    )
    db.add(event)
    return event


def record_active_event(db: Session, *, organization_id: UUID, claim_id: UUID, user_id: UUID | None, event_type: str, entity_type: str | None = None, entity_id: UUID | None = None, event_data: dict | None = None) -> PilotEvent | None:
    session = get_active_session(db, organization_id=organization_id, claim_id=claim_id, user_id=user_id)
    if not session:
        return None
    return record_event(db, session=session, user_id=user_id, event_type=event_type, source="server", entity_type=entity_type, entity_id=entity_id, event_data=event_data)


def add_feedback(db: Session, *, session: PilotSession, user: User, category: str, severity: str, verdict: str | None, rating: int | None, comment: str, entity_type: str | None, entity_id: UUID | None) -> PilotFeedback:
    row = PilotFeedback(
        organization_id=user.organization_id,
        session_id=session.id,
        claim_id=session.claim_id,
        user_id=user.id,
        category=category,
        severity=severity,
        verdict=verdict,
        rating=rating,
        comment=comment.strip(),
        entity_type=entity_type,
        entity_id=entity_id,
        created_at=datetime.now(UTC),
    )
    db.add(row)
    record_event(db, session=session, user_id=user.id, event_type="pilot_feedback_added", source="browser", entity_type=entity_type, entity_id=entity_id, event_data={"category": category, "severity": severity, "verdict": verdict, "rating": rating})
    return row


def _backlog_priority(feedback: PilotFeedback) -> str:
    if feedback.severity == "critical":
        return "P0"
    if feedback.severity == "high" or feedback.verdict in {"false_positive", "false_negative"}:
        return "P1"
    if feedback.severity == "medium":
        return "P2"
    return "P3"


def build_backlog(feedback_rows: list[PilotFeedback]) -> list[PilotBacklogItem]:
    items = []
    for row in feedback_rows:
        title = row.comment.strip().splitlines()[0][:120]
        items.append(PilotBacklogItem(
            feedback_id=row.id,
            priority=_backlog_priority(row),
            category=row.category,
            title=title,
            rationale=f"{row.severity.title()} pilot feedback" + (f"; verdict={row.verdict}" if row.verdict else ""),
            entity_type=row.entity_type,
            entity_id=row.entity_id,
        ))
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    return sorted(items, key=lambda item: (order[item.priority], item.category, item.title.lower()))


def calculate_metrics(db: Session, *, session: PilotSession) -> PilotMetrics:
    events = list(db.scalars(select(PilotEvent).where(PilotEvent.session_id == session.id).order_by(PilotEvent.created_at.asc())))
    feedback = list(db.scalars(select(PilotFeedback).where(PilotFeedback.session_id == session.id).order_by(PilotFeedback.created_at.asc())))
    now = session.ended_at or datetime.now(UTC)
    started_at = _utc(session.started_at)
    now = _utc(now)
    elapsed_seconds = max(0, int((now - started_at).total_seconds()))

    counts = {"approved": 0, "edited": 0, "rejected": 0}
    for event in events:
        action = AI_EVENT_TO_ACTION.get(event.event_type)
        if action:
            counts[action] += int((event.event_data or {}).get("count", 1))
    ai_total = sum(counts.values())

    first_assessment = next((event for event in events if event.event_type == "initial_assessment_generated"), None)
    tta_minutes = None
    reduction = None
    if first_assessment:
        tta_minutes = max(0.0, (_utc(first_assessment.created_at) - started_at).total_seconds() / 60.0)
        if session.baseline_assessment_minutes and session.baseline_assessment_minutes > 0:
            reduction = max(-1000.0, min(100.0, (session.baseline_assessment_minutes - tta_minutes) / session.baseline_assessment_minutes * 100.0))

    ratings = [row.rating for row in feedback if row.rating is not None]
    avg_rating = round(sum(ratings) / len(ratings), 2) if ratings else None
    fp = sum(1 for row in feedback if row.verdict == "false_positive")
    fn = sum(1 for row in feedback if row.verdict == "false_negative")
    correct = sum(1 for row in feedback if row.verdict in {"correct", "true_positive"})
    md_rows = [row for row in feedback if row.category == "missing_document"]
    md_tp = sum(1 for row in md_rows if row.verdict in {"correct", "true_positive"})
    md_fp = sum(1 for row in md_rows if row.verdict == "false_positive")
    md_fn = sum(1 for row in md_rows if row.verdict == "false_negative")
    precision = md_tp / (md_tp + md_fp) if (md_tp + md_fp) else None
    recall_proxy = md_tp / (md_tp + md_fn) if (md_tp + md_fn) else None
    friction = sum(1 for row in feedback if row.category in {"usability", "workflow", "feature_gap"} and row.severity in {"medium", "high", "critical"})
    task_events = [event for event in events if event.event_type == "claim_task_completed"]
    task_ages = [int((event.event_data or {}).get("age_ms")) for event in task_events if (event.event_data or {}).get("age_ms") is not None]
    avg_task_minutes = (sum(task_ages) / len(task_ages) / 60000.0) if task_ages else None
    request_sent_count = sum(1 for event in events if event.event_type == "document_request_sent")

    return PilotMetrics(
        session_id=session.id,
        session_status=session.status,
        elapsed_seconds=elapsed_seconds,
        baseline_assessment_minutes=session.baseline_assessment_minutes,
        time_to_first_assessment_minutes=round(tta_minutes, 2) if tta_minutes is not None else None,
        estimated_time_reduction_percent=round(reduction, 2) if reduction is not None else None,
        ai_review_total=ai_total,
        ai_approved=counts["approved"],
        ai_edited=counts["edited"],
        ai_rejected=counts["rejected"],
        ai_acceptance_rate=round(counts["approved"] / ai_total, 4) if ai_total else None,
        ai_edit_rate=round(counts["edited"] / ai_total, 4) if ai_total else None,
        ai_reject_rate=round(counts["rejected"] / ai_total, 4) if ai_total else None,
        feedback_count=len(feedback),
        average_rating=avg_rating,
        false_positive_count=fp,
        false_negative_count=fn,
        validated_correct_count=correct,
        missing_document_precision=round(precision, 4) if precision is not None else None,
        missing_document_recall_proxy=round(recall_proxy, 4) if recall_proxy is not None else None,
        friction_count=friction,
        tasks_completed=len(task_events),
        average_task_completion_minutes=round(avg_task_minutes, 2) if avg_task_minutes is not None else None,
        document_requests_sent=request_sent_count,
    )


def build_scorecard(db: Session, *, session: PilotSession) -> PilotScorecard:
    metrics = calculate_metrics(db, session=session)
    feedback = list(db.scalars(select(PilotFeedback).where(PilotFeedback.session_id == session.id)))
    targets = {
        "ai_acceptance_rate": 0.80,
        "time_reduction_percent": 30.0,
        "missing_document_precision": 0.90,
        "average_rating": 8.0,
    }
    checks: dict[str, bool | None] = {
        "ai_acceptance_target": None if metrics.ai_acceptance_rate is None else metrics.ai_acceptance_rate >= targets["ai_acceptance_rate"],
        "time_reduction_target": None if metrics.estimated_time_reduction_percent is None else metrics.estimated_time_reduction_percent >= targets["time_reduction_percent"],
        "missing_document_precision_target": None if metrics.missing_document_precision is None else metrics.missing_document_precision >= targets["missing_document_precision"],
        "user_rating_target": None if metrics.average_rating is None else metrics.average_rating >= targets["average_rating"],
        "no_critical_feedback": not any(row.severity == "critical" for row in feedback),
    }
    evaluated = [value for value in checks.values() if value is not None]
    ready = session.status == "completed" and bool(evaluated) and all(evaluated)
    return PilotScorecard(metrics=metrics, targets=targets, checks=checks, ready_for_next_pilot=ready, backlog=build_backlog(feedback))
