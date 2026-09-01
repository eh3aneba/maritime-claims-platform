from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from hashlib import sha256
from math import ceil
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ai_operations.schemas import AIOperationsFilters
from app.modules.ai_production_wide.models import AIProductionDecisionLog
from app.modules.ai_production_wide.service import get_authorization, report_incident, review_decision_log
from app.modules.audit.service import write_audit_log
from app.modules.evidence_search.qa_synthesis_models import ClaimQaSynthesisRun
from app.modules.users.models import User

MAX_SOURCE_ROWS = 10_000


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _hash(payload: dict) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _doc_event(row: AIProductionDecisionLog) -> dict:
    review_state = "completed" if row.status == "human_reviewed" else "pending"
    reasons: list[str] = []
    if review_state == "pending":
        reasons.append("pending_different_human_review")
    if row.human_review_action == "reject":
        reasons.append("human_reject")
    elif row.human_review_action == "edit":
        reasons.append("human_edit")
    if (row.unsupported_output_count or 0) > 0:
        reasons.append("unsupported_output_observed")
    if (
        (row.source_grounding_total_count or 0) > 0
        and (row.source_grounded_output_count or 0) < (row.source_grounding_total_count or 0)
    ):
        reasons.append("grounding_below_complete")
    return {
        "id": row.id,
        "workflow_type": "document_processing",
        "event_time": row.reviewed_at or row.queued_at,
        "claim_id": row.claim_id,
        "document_id": row.document_id,
        "document_type": row.task_type,
        "authorization_id": row.authorization_id,
        "authorization_hash": row.authorization_hash,
        "eligibility_decision_id": row.eligibility_decision_id,
        "eligibility_policy_hash": row.eligibility_policy_hash,
        "eligibility_decision_hash": row.eligibility_decision_hash,
        "status": row.status,
        "failure_code": None,
        "fallback_used": False,
        "provider_call_made": row.status == "human_reviewed",
        "provider": None,
        "model": row.model,
        "prompt_bundle_version": row.prompt_bundle_version,
        "schema_bundle_version": row.schema_bundle_version,
        "human_review_state": review_state,
        "human_review_action": row.human_review_action,
        "requested_by_id": row.requested_by_id,
        "reviewed_by_id": row.reviewed_by_id,
        "run_hash": row.run_hash,
        "review_hash": row.review_hash,
        "retrieval_run_id": None,
        "question_hash": None,
        "result_set_hash": None,
        "input_hash": None,
        "output_hash": None,
        "answer_hash": None,
        "source_count": None,
        "output_candidate_count": row.output_candidate_count,
        "human_edit_count": row.human_edit_count,
        "unsupported_output_count": row.unsupported_output_count,
        "source_grounded_output_count": row.source_grounded_output_count,
        "source_grounding_total_count": row.source_grounding_total_count,
        "input_chars": None,
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "latency_ms": row.latency_ms,
        "observed_provider_cost_microusd": row.observed_provider_cost_microusd,
        "requires_attention": bool(reasons),
        "attention_reasons": reasons,
        "content_free": True,
    }


def _qa_event(row: ClaimQaSynthesisRun) -> dict:
    reasons: list[str] = []
    if row.status != "completed":
        reasons.append(f"synthesis_{row.status}")
    if row.failure_code:
        reasons.append(row.failure_code)
    if row.fallback_used:
        reasons.append("extractive_fallback_used")
    return {
        "id": row.id,
        "workflow_type": "claim_qa_synthesis",
        "event_time": row.completed_at,
        "claim_id": row.claim_id,
        "document_id": None,
        "document_type": None,
        "authorization_id": row.production_authorization_id,
        "authorization_hash": row.authorization_hash,
        "eligibility_decision_id": None,
        "eligibility_policy_hash": row.eligibility_policy_hash,
        "eligibility_decision_hash": None,
        "status": row.status,
        "failure_code": row.failure_code,
        "fallback_used": row.fallback_used,
        "provider_call_made": row.provider_call_made,
        "provider": row.provider,
        "model": row.model,
        "prompt_bundle_version": row.prompt_bundle_version,
        "schema_bundle_version": row.schema_bundle_version,
        "human_review_state": "not_applicable",
        "human_review_action": None,
        "requested_by_id": row.requested_by_id,
        "reviewed_by_id": None,
        "run_hash": None,
        "review_hash": None,
        "retrieval_run_id": row.retrieval_run_id,
        "question_hash": row.question_hash,
        "result_set_hash": row.result_set_hash,
        "input_hash": row.input_hash,
        "output_hash": row.output_hash,
        "answer_hash": row.answer_hash,
        "source_count": row.source_count,
        "output_candidate_count": None,
        "human_edit_count": None,
        "unsupported_output_count": None,
        "source_grounded_output_count": None,
        "source_grounding_total_count": None,
        "input_chars": row.input_chars,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "total_tokens": row.total_tokens,
        "latency_ms": row.latency_ms,
        "observed_provider_cost_microusd": None,
        "requires_attention": bool(reasons),
        "attention_reasons": reasons,
        "content_free": True,
    }


def _matches(event: dict, filters: AIOperationsFilters) -> bool:
    if filters.workflow_type and event["workflow_type"] != filters.workflow_type:
        return False
    if filters.claim_id and event["claim_id"] != filters.claim_id:
        return False
    if filters.document_id and event["document_id"] != filters.document_id:
        return False
    if filters.document_type and event["document_type"] != filters.document_type:
        return False
    if filters.status and event["status"] != filters.status:
        return False
    if filters.human_review_state and event["human_review_state"] != filters.human_review_state:
        return False
    if filters.human_review_action and event["human_review_action"] != filters.human_review_action:
        return False
    if filters.provider and event["provider"] != filters.provider:
        return False
    if filters.model and event["model"] != filters.model:
        return False
    if filters.authorization_id and event["authorization_id"] != filters.authorization_id:
        return False
    if filters.failure_code and event["failure_code"] != filters.failure_code:
        return False
    if filters.created_from and _as_utc(event["event_time"]) < _as_utc(filters.created_from):
        return False
    if filters.created_to and _as_utc(event["event_time"]) > _as_utc(filters.created_to):
        return False
    if filters.requires_attention is not None and event["requires_attention"] != filters.requires_attention:
        return False
    return True


def _filtered_events(db: Session, organization_id: UUID, filters: AIOperationsFilters) -> list[dict]:
    events: list[dict] = []
    if filters.workflow_type in (None, "document_processing"):
        rows = list(db.scalars(
            select(AIProductionDecisionLog)
            .where(AIProductionDecisionLog.organization_id == organization_id)
            .order_by(AIProductionDecisionLog.queued_at.desc(), AIProductionDecisionLog.id.desc())
            .limit(MAX_SOURCE_ROWS)
        ))
        events.extend(_doc_event(row) for row in rows)
    if filters.workflow_type in (None, "claim_qa_synthesis"):
        rows = list(db.scalars(
            select(ClaimQaSynthesisRun)
            .where(ClaimQaSynthesisRun.organization_id == organization_id)
            .order_by(ClaimQaSynthesisRun.completed_at.desc(), ClaimQaSynthesisRun.id.desc())
            .limit(MAX_SOURCE_ROWS)
        ))
        events.extend(_qa_event(row) for row in rows)
    events = [event for event in events if _matches(event, filters)]
    events.sort(
        key=lambda event: (_as_utc(event["event_time"]), event["workflow_type"], str(event["id"])),
        reverse=True,
    )
    return events


def query_events(
    db: Session,
    organization_id: UUID,
    filters: AIOperationsFilters,
    *,
    page: int,
    page_size: int,
) -> dict:
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(422, "AI Operations pagination must use page >= 1 and page_size 1..100")
    events = _filtered_events(db, organization_id, filters)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "events": events[start:end],
        "page": page,
        "page_size": page_size,
        "total": len(events),
        "has_more": end < len(events),
    }


def get_event(
    db: Session,
    organization_id: UUID,
    workflow_type: str,
    event_id: UUID,
) -> dict:
    if workflow_type == "document_processing":
        row = db.scalar(select(AIProductionDecisionLog).where(
            AIProductionDecisionLog.id == event_id,
            AIProductionDecisionLog.organization_id == organization_id,
        ))
        if row is None:
            raise HTTPException(404, "AI Operations event not found")
        return _doc_event(row)
    if workflow_type == "claim_qa_synthesis":
        row = db.scalar(select(ClaimQaSynthesisRun).where(
            ClaimQaSynthesisRun.id == event_id,
            ClaimQaSynthesisRun.organization_id == organization_id,
        ))
        if row is None:
            raise HTTPException(404, "AI Operations event not found")
        return _qa_event(row)
    raise HTTPException(422, "Unsupported AI Operations workflow type")


def metrics(db: Session, organization_id: UUID, filters: AIOperationsFilters | None = None) -> dict:
    events = _filtered_events(db, organization_id, filters or AIOperationsFilters())
    document_events = [event for event in events if event["workflow_type"] == "document_processing"]
    qa_events = [event for event in events if event["workflow_type"] == "claim_qa_synthesis"]
    provider_runs = sum(1 for event in document_events if event["provider_call_made"]) + sum(
        1 for event in qa_events if event["provider_call_made"]
    )
    blocked_or_fallback = sum(
        1 for event in qa_events if event["status"] in {"blocked", "extractive_bypass"} or event["fallback_used"]
    )
    verification_failures = sum(
        1 for event in qa_events if event["failure_code"] == "grounding_verification_failed"
    )
    authorization_blocks = sum(
        1
        for event in qa_events
        if event["failure_code"]
        and any(
            marker in event["failure_code"]
            for marker in ("authorization", "policy", "restricted", "provider_mismatch", "provider_not_authorized")
        )
    )
    actions = [event["human_review_action"] for event in document_events]
    grounded = sum(event["source_grounded_output_count"] or 0 for event in document_events)
    grounding_total = sum(event["source_grounding_total_count"] or 0 for event in document_events)
    latencies = sorted(event["latency_ms"] for event in events if event["latency_ms"] is not None)
    p95 = latencies[max(0, ceil(len(latencies) * 0.95) - 1)] if latencies else None
    failures_by_workflow: dict[str, int] = {}
    failures_by_model: dict[str, int] = {}
    for event in events:
        failed = (
            event["failure_code"] is not None
            or event["human_review_action"] == "reject"
            or event["status"] in {"provider_error", "verification_failed", "blocked"}
        )
        if not failed:
            continue
        failures_by_workflow[event["workflow_type"]] = failures_by_workflow.get(event["workflow_type"], 0) + 1
        model = event["model"] or "unknown"
        failures_by_model[model] = failures_by_model.get(model, 0) + 1
    return {
        "event_count": len(events),
        "document_processing_count": len(document_events),
        "claim_qa_synthesis_count": len(qa_events),
        "provider_run_count": provider_runs,
        "blocked_or_fallback_count": blocked_or_fallback,
        "verification_failure_count": verification_failures,
        "authorization_or_policy_block_count": authorization_blocks,
        "pending_human_review_count": sum(1 for event in document_events if event["human_review_state"] == "pending"),
        "approve_count": actions.count("approve"),
        "edit_count": actions.count("edit"),
        "reject_count": actions.count("reject"),
        "unsupported_output_count": sum(event["unsupported_output_count"] or 0 for event in document_events),
        "source_grounding_validity_bps": None if grounding_total == 0 else round(grounded * 10_000 / grounding_total),
        "total_tokens": sum(event["total_tokens"] or 0 for event in qa_events),
        "total_observed_provider_cost_microusd": sum(
            event["observed_provider_cost_microusd"] or 0 for event in document_events
        ),
        "mean_latency_ms": None if not latencies else round(sum(latencies) / len(latencies)),
        "p95_latency_ms": p95,
        "requires_attention_count": sum(1 for event in events if event["requires_attention"]),
        "failures_by_workflow": failures_by_workflow,
        "failures_by_model": failures_by_model,
    }


def dashboard(db: Session, organization_id: UUID) -> dict:
    attention_filters = AIOperationsFilters(requires_attention=True)
    attention = _filtered_events(db, organization_id, attention_filters)[:10]
    return {
        "metrics": metrics(db, organization_id),
        "recent_attention": attention,
        "content_free_governance_plane": True,
        "raw_claim_or_model_content_exposed": False,
    }


def pending_review_queue(db: Session, organization_id: UUID, *, page: int, page_size: int) -> dict:
    filters = AIOperationsFilters(workflow_type="document_processing", human_review_state="pending")
    return query_events(db, organization_id, filters, page=page, page_size=page_size)


def review_document_event(db: Session, user: User, event_id: UUID, payload: dict) -> dict:
    row = db.scalar(select(AIProductionDecisionLog).where(
        AIProductionDecisionLog.id == event_id,
        AIProductionDecisionLog.organization_id == user.organization_id,
    ))
    if row is None:
        raise HTTPException(404, "AI Decision Log entry not found")
    review_decision_log(db, user, row, **payload)
    db.refresh(row)
    return _doc_event(row)


def handoff_incident(
    db: Session,
    user: User,
    *,
    workflow_type: str,
    event_id: UUID,
    severity: str,
    category: str,
    evidence_reference: str,
    note: str,
    confirm_incident_handoff: bool,
) -> dict:
    if not confirm_incident_handoff:
        raise HTTPException(422, "Explicit human incident handoff confirmation is required")
    event = get_event(db, user.organization_id, workflow_type, event_id)
    authorization_id = event["authorization_id"]
    if authorization_id is None:
        raise HTTPException(409, "This event has no Production-wide authorization to receive an incident handoff")
    authorization = get_authorization(db, user.organization_id, authorization_id)
    lineage = event.get("run_hash") or event.get("answer_hash") or event.get("result_set_hash") or str(event_id)
    return report_incident(
        db,
        user,
        authorization,
        severity=severity,
        category=category,
        evidence_reference=evidence_reference,
        note=f"Phase 12H operator handoff for {workflow_type}/{event_id}; lineage={lineage}. {note.strip()}",
        confirm_pause=True,
    )


EXPORT_COLUMNS = [
    "id", "workflow_type", "event_time", "claim_id", "document_id", "document_type",
    "authorization_id", "authorization_hash", "eligibility_decision_id", "eligibility_policy_hash",
    "eligibility_decision_hash", "status", "failure_code", "fallback_used", "provider_call_made",
    "provider", "model", "prompt_bundle_version", "schema_bundle_version", "human_review_state",
    "human_review_action", "requested_by_id", "reviewed_by_id", "run_hash", "review_hash",
    "retrieval_run_id", "question_hash", "result_set_hash", "input_hash", "output_hash", "answer_hash",
    "source_count", "output_candidate_count", "human_edit_count", "unsupported_output_count",
    "source_grounded_output_count", "source_grounding_total_count", "input_chars", "input_tokens",
    "output_tokens", "total_tokens", "latency_ms", "observed_provider_cost_microusd",
    "requires_attention", "attention_reasons", "content_free",
]


def export_events(
    db: Session,
    user: User,
    *,
    filters: AIOperationsFilters,
    export_format: str,
    max_rows: int,
) -> tuple[str, str, int]:
    events = _filtered_events(db, user.organization_id, filters)[:max_rows]
    safe_rows: list[dict] = []
    for event in events:
        row = {column: event.get(column) for column in EXPORT_COLUMNS}
        safe_rows.append(row)
    if export_format == "json":
        content = json.dumps(safe_rows, default=str, ensure_ascii=False, indent=2)
        media_type = "application/json"
    elif export_format == "csv":
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=EXPORT_COLUMNS)
        writer.writeheader()
        for row in safe_rows:
            serializable = {
                key: json.dumps(value, default=str) if isinstance(value, (list, dict)) else value
                for key, value in row.items()
            }
            writer.writerow(serializable)
        content = stream.getvalue()
        media_type = "text/csv"
    else:
        raise HTTPException(422, "Unsupported AI Operations export format")
    filter_hash = _hash(filters.model_dump(mode="json", exclude_none=True))
    write_audit_log(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        action="EXPORT_AI_OPERATIONS_GOVERNANCE",
        entity_type="ai_operations_export",
        entity_id=None,
        new_values={
            "format": export_format,
            "row_count": len(events),
            "filter_hash": filter_hash,
            "content_free": True,
            "raw_claim_or_model_content_included": False,
        },
        details="Phase 12H content-free governance export generated by an authorized human operator.",
    )
    db.commit()
    return content, media_type, len(events)
