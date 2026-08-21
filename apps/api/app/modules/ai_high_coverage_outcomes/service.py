import json
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import ceil
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.ai_broader_production_outcomes.models import AIBroaderProductionOutcomeAssessment
from app.modules.ai_high_coverage.models import (
    AIHighCoverageAuthorization,
    AIHighCoverageIncident,
    AIHighCoverageMonitor,
    AIHighCoverageRun,
)
from app.modules.ai_high_coverage_outcomes.models import (
    AIHighCoverageOutcomeAssessment,
    AIHighCoverageOutcomeObservation,
    AIHighCoverageOutcomeReview,
)
from app.modules.ai_high_coverage_outcomes.schemas import (
    AIHighCoverageOutcomeCreate,
    AIHighCoverageOutcomeObservationCreate,
)
from app.modules.audit.service import write_audit_log
from app.modules.users.models import User

REFERENCE = re.compile(r"^(artifact|runbook|ticket|monitor)://[A-Za-z0-9._:/-]{3,450}$")
REVIEW_ROLES = {
    "product", "quality", "risk", "operations", "security",
    "claims_governance", "ai_quality",
}
RETRY_STATUSES = {"failed", "review_rejected", "extended", "stopped"}
SAFETY_INCIDENT_CATEGORIES = {"privacy", "security", "cross_tenant"}
BLOCKING_INCIDENT_SEVERITIES = {"critical", "high"}
REQUIRED_WORKFLOWS = {"chief_engineer_report", "engine_log"}


def _reference(value: str) -> str:
    reference = value.strip()
    if not REFERENCE.fullmatch(reference):
        raise HTTPException(422, "Outcome evidence must use a bounded allowlisted reference")
    return reference


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _hash(payload: dict) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _audit(db: Session, user: User, action: str, item: AIHighCoverageOutcomeAssessment,
           values: dict, details: str) -> None:
    write_audit_log(
        db, organization_id=user.organization_id, user_id=user.id, action=action,
        entity_type="ai_high_coverage_outcome_assessment", entity_id=item.id,
        new_values=values, details=details,
    )


def _authorization(db: Session, organization_id: UUID,
                   authorization_id: UUID) -> AIHighCoverageAuthorization:
    item = db.scalar(select(AIHighCoverageAuthorization).where(
        AIHighCoverageAuthorization.id == authorization_id,
        AIHighCoverageAuthorization.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Sprint 11K high-coverage authorization not found")
    return item


def _broader_outcome(db: Session, authorization: AIHighCoverageAuthorization) -> AIBroaderProductionOutcomeAssessment:
    item = db.scalar(select(AIBroaderProductionOutcomeAssessment).where(
        AIBroaderProductionOutcomeAssessment.id == authorization.outcome_assessment_id,
        AIBroaderProductionOutcomeAssessment.organization_id == authorization.organization_id,
    ))
    if item is None:
        raise HTTPException(409, "The inherited Sprint 11J outcome anchor is missing")
    return item


def _runs(db: Session, authorization_id: UUID) -> list[AIHighCoverageRun]:
    return list(db.scalars(select(AIHighCoverageRun).where(
        AIHighCoverageRun.authorization_id == authorization_id,
    ).order_by(AIHighCoverageRun.queued_at.asc(), AIHighCoverageRun.id.asc())))


def _monitors(db: Session, authorization_id: UUID) -> list[AIHighCoverageMonitor]:
    return list(db.scalars(select(AIHighCoverageMonitor).where(
        AIHighCoverageMonitor.authorization_id == authorization_id,
    ).order_by(AIHighCoverageMonitor.monitored_at.asc(), AIHighCoverageMonitor.id.asc())))


def _incidents(db: Session, authorization_id: UUID) -> list[AIHighCoverageIncident]:
    return list(db.scalars(select(AIHighCoverageIncident).where(
        AIHighCoverageIncident.authorization_id == authorization_id,
    ).order_by(AIHighCoverageIncident.reported_at.asc(), AIHighCoverageIncident.id.asc())))


def _observations(db: Session, assessment_id: UUID) -> list[AIHighCoverageOutcomeObservation]:
    return list(db.scalars(select(AIHighCoverageOutcomeObservation).where(
        AIHighCoverageOutcomeObservation.assessment_id == assessment_id,
    ).order_by(AIHighCoverageOutcomeObservation.observed_at.asc(),
               AIHighCoverageOutcomeObservation.id.asc())))


def _reviews(db: Session, assessment_id: UUID) -> list[AIHighCoverageOutcomeReview]:
    return list(db.scalars(select(AIHighCoverageOutcomeReview).where(
        AIHighCoverageOutcomeReview.assessment_id == assessment_id,
    ).order_by(AIHighCoverageOutcomeReview.review_role.asc())))


def _rate_bps(numerator: int, denominator: int) -> int | None:
    return numerator * 10000 // denominator if denominator else None


def _mean(values: list[int]) -> int | None:
    return (sum(values) + len(values) - 1) // len(values) if values else None


def _relative_increase_bps(first: int | None, second: int | None) -> int | None:
    if first is None or second is None:
        return None
    if second <= first:
        return 0
    if first <= 0:
        return 10000
    return (second - first) * 10000 // first


def _thresholds(item: AIHighCoverageOutcomeAssessment) -> dict:
    return {
        "minimum_human_reviewed_provider_runs": item.min_reviewed_runs,
        "minimum_reviewed_runs_per_workflow": item.min_runs_per_workflow,
        "required_human_review_rate_bps": 10000,
        "required_different_human_review_rate_bps": 10000,
        "required_observation_coverage_rate_bps": 10000,
        "required_workflow_completion_rate_bps": 10000,
        "max_reject_rate_bps": item.max_reject_rate_bps,
        "max_edit_rate_bps": item.max_edit_rate_bps,
        "min_mean_usefulness_bps": item.min_mean_usefulness_bps,
        "max_unsupported_output_rate_bps": item.max_unsupported_output_rate_bps,
        "min_source_grounding_validity_bps": item.min_source_grounding_validity_bps,
        "max_mean_review_seconds": item.max_mean_review_seconds,
        "max_p95_latency_ms": item.max_p95_latency_ms,
        "max_mean_observed_provider_cost_microusd": item.max_mean_cost_microusd,
        "max_quality_regression_bps": item.max_quality_regression_bps,
        "max_latency_regression_bps": item.max_latency_regression_bps,
        "max_cost_regression_bps": item.max_cost_regression_bps,
        "max_unresolved_high_or_critical_incident_count": 0,
        "max_safety_boundary_incident_count": 0,
        "required_non_safety_pause_recovery_rate_bps": 10000,
        "fresh_final_monitor_required": True,
    }


def assessment_response(db: Session, item: AIHighCoverageOutcomeAssessment) -> dict:
    observations = _observations(db, item.id)
    reviews = _reviews(db, item.id)
    reviews_complete = bool(
        {review.review_role for review in reviews} == REVIEW_ROLES
        and len(reviews) == len(REVIEW_ROLES)
        and all(review.action == "approve" for review in reviews)
        and len({review.reviewer_id for review in reviews}) == len(REVIEW_ROLES)
        and all(review.reviewer_id != item.requested_by_id for review in reviews)
    )
    return {
        "id": item.id,
        "high_coverage_authorization_id": item.high_coverage_authorization_id,
        "requested_by_id": item.requested_by_id,
        "finalized_by_id": item.finalized_by_id,
        "attempt_number": item.attempt_number,
        "assessment_key": item.assessment_key,
        "assessment_profile": item.assessment_profile,
        "high_coverage_decision_hash": item.high_coverage_decision_hash,
        "high_coverage_completion_hash": item.high_coverage_completion_hash,
        "inherited_hashes": {
            "broader_outcome_assessment": item.broader_outcome_assessment_hash,
            "broader_outcome_decision": item.broader_outcome_decision_hash,
            "broader_production_decision": item.broader_production_decision_hash,
            "readiness_assessment": item.readiness_assessment_hash,
            "readiness_decision": item.readiness_decision_hash,
            "scale_up_decision": item.scale_up_decision_hash,
            "limited_outcome_assessment": item.inherited_outcome_assessment_hash,
            "limited_outcome_decision": item.inherited_outcome_decision_hash,
        },
        "bundle": {
            "model": item.model,
            "prompt_bundle_version": item.prompt_bundle_version,
            "schema_bundle_version": item.schema_bundle_version,
        },
        "rollout_percentage": item.rollout_percentage,
        "thresholds": _thresholds(item),
        "status": item.status,
        "outcome": item.outcome,
        "metrics": item.metrics,
        "failure_reasons": item.failure_reasons or [],
        "assessment_note": item.assessment_note,
        "assessment_hash": item.assessment_hash,
        "assessed_at": item.assessed_at,
        "decision_note": item.decision_note,
        "decision_hash": item.decision_hash,
        "decided_at": item.decided_at,
        "observations": observations,
        "reviews": reviews,
        "summary": {
            "observation_count": len(observations),
            "thresholds_passed": bool(item.metrics and item.metrics.get("overall_pass")),
            "independent_reviews_complete": reviews_complete,
            "final_production_readiness_review_recommended": (
                item.status == "recommended"
                and item.outcome == "recommend_final_production_readiness_review"
            ),
            "rollout_above_75_authorized": False,
            "production_wide_authorized": False,
            "restricted_documents_authorized": False,
            "new_document_classes_authorized": False,
            "autonomous_claim_decisions_authorized": False,
            "authoritative_facts_auto_updated": False,
            "human_review_required": True,
            "raw_content_stored": False,
        },
        "created_at": item.created_at,
    }


def list_assessments(db: Session, organization_id: UUID) -> list[dict]:
    items = list(db.scalars(select(AIHighCoverageOutcomeAssessment).where(
        AIHighCoverageOutcomeAssessment.organization_id == organization_id,
    ).order_by(AIHighCoverageOutcomeAssessment.created_at.desc()).limit(25)))
    return [assessment_response(db, item) for item in items]


def get_assessment(db: Session, organization_id: UUID,
                   assessment_id: UUID) -> AIHighCoverageOutcomeAssessment:
    item = db.scalar(select(AIHighCoverageOutcomeAssessment).where(
        AIHighCoverageOutcomeAssessment.id == assessment_id,
        AIHighCoverageOutcomeAssessment.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Sprint 11L high-coverage outcome assessment not found")
    return item


def _validate_anchor(db: Session, item: AIHighCoverageOutcomeAssessment,
                     authorization: AIHighCoverageAuthorization) -> AIBroaderProductionOutcomeAssessment:
    broader_outcome = _broader_outcome(db, authorization)
    if authorization.status != "completed" or not authorization.decision_hash or not authorization.completion_hash:
        raise HTTPException(409, "A completed Sprint 11K high-coverage cohort is required")
    if (
        authorization.decision_hash != item.high_coverage_decision_hash
        or authorization.completion_hash != item.high_coverage_completion_hash
        or authorization.outcome_assessment_hash != item.broader_outcome_assessment_hash
        or authorization.outcome_decision_hash != item.broader_outcome_decision_hash
        or authorization.broader_production_decision_hash != item.broader_production_decision_hash
        or authorization.readiness_assessment_hash != item.readiness_assessment_hash
        or authorization.readiness_decision_hash != item.readiness_decision_hash
        or authorization.scale_up_decision_hash != item.scale_up_decision_hash
        or authorization.inherited_outcome_assessment_hash != item.inherited_outcome_assessment_hash
        or authorization.inherited_outcome_decision_hash != item.inherited_outcome_decision_hash
        or broader_outcome.status != "recommended"
        or broader_outcome.outcome != "recommend_next_broader_stage"
        or not (broader_outcome.metrics or {}).get("overall_pass")
        or broader_outcome.assessment_hash != item.broader_outcome_assessment_hash
        or broader_outcome.decision_hash != item.broader_outcome_decision_hash
        or authorization.model != item.model
        or authorization.prompt_bundle_version != item.prompt_bundle_version
        or authorization.schema_bundle_version != item.schema_bundle_version
        or authorization.rollout_percentage != item.rollout_percentage
        or not 51 <= authorization.rollout_percentage <= 75
    ):
        raise HTTPException(409, "The persisted Sprint 11K/11J evidence anchor no longer matches")
    return broader_outcome


def create_assessment(db: Session, user: User, payload: AIHighCoverageOutcomeCreate) -> dict:
    if not payload.confirm_content_free_assessment:
        raise HTTPException(422, "Explicit content-free outcome assessment confirmation is required")
    authorization = _authorization(db, user.organization_id, payload.high_coverage_authorization_id)
    if authorization.status != "completed" or not authorization.decision_hash or not authorization.completion_hash:
        raise HTTPException(409, "A completed Sprint 11K high-coverage cohort is required")
    broader_outcome = _broader_outcome(db, authorization)
    if (
        broader_outcome.status != "recommended"
        or broader_outcome.outcome != "recommend_next_broader_stage"
        or not (broader_outcome.metrics or {}).get("overall_pass")
        or not broader_outcome.assessment_hash
        or not broader_outcome.decision_hash
        or authorization.outcome_assessment_hash != broader_outcome.assessment_hash
        or authorization.outcome_decision_hash != broader_outcome.decision_hash
        or not 51 <= authorization.rollout_percentage <= 75
    ):
        raise HTTPException(409, "The Sprint 11J recommendation inherited by 11K is invalid")
    attempts = list(db.scalars(select(AIHighCoverageOutcomeAssessment).where(
        AIHighCoverageOutcomeAssessment.high_coverage_authorization_id == authorization.id,
    ).order_by(AIHighCoverageOutcomeAssessment.attempt_number.asc())))
    if attempts and attempts[-1].status not in RETRY_STATUSES:
        raise HTTPException(409, "The current Sprint 11L assessment is still active")
    item = AIHighCoverageOutcomeAssessment(
        organization_id=user.organization_id,
        high_coverage_authorization_id=authorization.id,
        requested_by_id=user.id,
        attempt_number=len(attempts) + 1,
        assessment_key=payload.assessment_key.strip(),
        high_coverage_decision_hash=authorization.decision_hash,
        high_coverage_completion_hash=authorization.completion_hash,
        broader_outcome_assessment_hash=authorization.outcome_assessment_hash,
        broader_outcome_decision_hash=authorization.outcome_decision_hash,
        broader_production_decision_hash=authorization.broader_production_decision_hash,
        readiness_assessment_hash=authorization.readiness_assessment_hash,
        readiness_decision_hash=authorization.readiness_decision_hash,
        scale_up_decision_hash=authorization.scale_up_decision_hash,
        inherited_outcome_assessment_hash=authorization.inherited_outcome_assessment_hash,
        inherited_outcome_decision_hash=authorization.inherited_outcome_decision_hash,
        model=authorization.model,
        prompt_bundle_version=authorization.prompt_bundle_version,
        schema_bundle_version=authorization.schema_bundle_version,
        rollout_percentage=authorization.rollout_percentage,
        status="collecting",
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Assessment key or attempt already exists") from exc
    _audit(
        db, user, "CREATE_AI_HIGH_COVERAGE_OUTCOME_ASSESSMENT", item,
        {"authorization_id": str(authorization.id), "attempt_number": item.attempt_number,
         "rollout_percentage": item.rollout_percentage, "raw_content_stored": False},
        "Sprint 11L content-free high-coverage outcome assessment created.",
    )
    db.commit()
    db.refresh(item)
    return assessment_response(db, item)


def record_observation(db: Session, user: User, item: AIHighCoverageOutcomeAssessment,
                       payload: AIHighCoverageOutcomeObservationCreate) -> dict:
    if not payload.confirm_content_free_observation:
        raise HTTPException(422, "Explicit content-free observation confirmation is required")
    if item.status != "collecting":
        raise HTTPException(409, "This assessment no longer accepts observations")
    authorization = _authorization(db, user.organization_id, item.high_coverage_authorization_id)
    _validate_anchor(db, item, authorization)
    run = db.scalar(select(AIHighCoverageRun).where(
        AIHighCoverageRun.id == payload.high_coverage_run_id,
        AIHighCoverageRun.authorization_id == authorization.id,
        AIHighCoverageRun.organization_id == user.organization_id,
    ))
    if run is None:
        raise HTTPException(404, "Sprint 11K run not found")
    if (
        run.status != "human_reviewed"
        or not run.outcome_hash
        or run.requested_by_id is None
        or run.reviewed_by_id is None
        or run.requested_by_id == run.reviewed_by_id
    ):
        raise HTTPException(409, "Only immutable different-human-reviewed Sprint 11K runs can be observed")
    now = datetime.now(UTC)
    reference = _reference(payload.evidence_reference)
    snapshot = {
        "schema": "mcri-ai-high-coverage-outcome-observation-v1",
        "assessment_id": str(item.id), "run_id": str(run.id),
        "run_outcome_hash": run.outcome_hash, "workflow_type": run.task_type,
        "usefulness_rating": payload.usefulness_rating, "review_seconds": payload.review_seconds,
        "workflow_completed": payload.workflow_completed, "evidence_reference": reference,
        "observed_at": now.isoformat(), "raw_content_stored": False,
    }
    observation = AIHighCoverageOutcomeObservation(
        organization_id=user.organization_id, assessment_id=item.id,
        high_coverage_run_id=run.id, observed_by_id=user.id,
        workflow_type=run.task_type, usefulness_rating=payload.usefulness_rating,
        review_seconds=payload.review_seconds, workflow_completed=payload.workflow_completed,
        evidence_reference=reference, note=payload.note.strip(),
        observation_hash=_hash(snapshot), observed_at=now,
    )
    db.add(observation)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This Sprint 11K run already has an observation") from exc
    _audit(
        db, user, "RECORD_AI_HIGH_COVERAGE_OUTCOME_OBSERVATION", item,
        {"run_id": str(run.id), "observation_hash": observation.observation_hash,
         "raw_content_stored": False},
        "Content-free Sprint 11L usefulness and operator-effort observation recorded.",
    )
    db.commit()
    db.refresh(item)
    return assessment_response(db, item)


def _cohort_metrics(runs: list[AIHighCoverageRun],
                    observations_by_run: dict[UUID, AIHighCoverageOutcomeObservation]) -> dict:
    reviewed = [run for run in runs if run.status == "human_reviewed"]
    different_human = [
        run for run in reviewed
        if run.requested_by_id is not None and run.reviewed_by_id is not None
        and run.requested_by_id != run.reviewed_by_id
    ]
    actions = [run.human_review_action for run in reviewed if run.human_review_action in {"approve", "edit", "reject"}]
    candidates = sum(run.output_candidate_count or 0 for run in reviewed)
    unsupported = sum(run.unsupported_output_count or 0 for run in reviewed)
    grounded = sum(run.source_grounded_output_count or 0 for run in reviewed)
    grounding_total = sum(run.source_grounding_total_count or 0 for run in reviewed)
    latencies = sorted(run.latency_ms for run in reviewed if run.latency_ms is not None)
    costs = [run.observed_provider_cost_microusd for run in reviewed if run.observed_provider_cost_microusd is not None]
    observations = [observations_by_run[run.id] for run in reviewed if run.id in observations_by_run]
    p95 = latencies[max(ceil(0.95 * len(latencies)) - 1, 0)] if latencies else None
    return {
        "run_count": len(runs),
        "human_reviewed_run_count": len(reviewed),
        "human_review_rate_bps": _rate_bps(len(reviewed), len(runs)),
        "different_human_review_rate_bps": _rate_bps(len(different_human), len(reviewed)),
        "observation_count": len(observations),
        "observation_coverage_rate_bps": _rate_bps(len(observations), len(reviewed)),
        "workflow_completion_rate_bps": _rate_bps(sum(entry.workflow_completed for entry in observations), len(observations)),
        "human_reject_rate_bps": _rate_bps(sum(action == "reject" for action in actions), len(actions)),
        "human_edit_rate_bps": _rate_bps(sum(action == "edit" for action in actions), len(actions)),
        "mean_usefulness_bps": (sum(entry.usefulness_rating for entry in observations) * 2000 // len(observations)) if observations else None,
        "unsupported_output_rate_bps": _rate_bps(unsupported, candidates),
        "source_grounding_validity_bps": _rate_bps(grounded, grounding_total),
        "mean_review_seconds": _mean([entry.review_seconds for entry in observations]),
        "p95_latency_ms": p95,
        "mean_observed_provider_cost_microusd": _mean(costs),
    }


def _trend_metrics(runs: list[AIHighCoverageRun], observations_by_run: dict[UUID, AIHighCoverageOutcomeObservation],
                   item: AIHighCoverageOutcomeAssessment) -> dict:
    reviewed = [run for run in runs if run.status == "human_reviewed"]
    half = len(reviewed) // 2
    if half == 0 or len(reviewed) - half == 0:
        return {"first_half": {}, "second_half": {}, "quality_regression_bps": None,
                "latency_regression_bps": None, "cost_regression_bps": None,
                "material_regression": True}
    first = _cohort_metrics(reviewed[:half], observations_by_run)
    second = _cohort_metrics(reviewed[half:], observations_by_run)
    deteriorations: list[int] = []
    for key in ("human_reject_rate_bps", "human_edit_rate_bps", "unsupported_output_rate_bps"):
        a, b = first.get(key), second.get(key)
        deteriorations.append(max(0, b - a) if isinstance(a, int) and isinstance(b, int) else 10000)
    ga, gb = first.get("source_grounding_validity_bps"), second.get("source_grounding_validity_bps")
    deteriorations.append(max(0, ga - gb) if isinstance(ga, int) and isinstance(gb, int) else 10000)
    quality = max(deteriorations)
    latency = _relative_increase_bps(first.get("p95_latency_ms"), second.get("p95_latency_ms"))
    cost = _relative_increase_bps(first.get("mean_observed_provider_cost_microusd"), second.get("mean_observed_provider_cost_microusd"))
    material = (
        quality > item.max_quality_regression_bps
        or latency is None or latency > item.max_latency_regression_bps
        or cost is None or cost > item.max_cost_regression_bps
    )
    return {"first_half": first, "second_half": second,
            "quality_regression_bps": quality, "latency_regression_bps": latency,
            "cost_regression_bps": cost, "material_regression": material}


def _recovery_metrics(monitors: list[AIHighCoverageMonitor], incidents: list[AIHighCoverageIncident]) -> dict:
    passing = [entry for entry in monitors if entry.status == "pass"]
    pauses: list[dict] = []
    recovered = 0
    paused_seconds = 0
    for monitor in monitors:
        if monitor.status == "pass":
            continue
        next_pass = next((entry for entry in passing if _as_utc(entry.monitored_at) > _as_utc(monitor.monitored_at)), None)
        ok = next_pass is not None
        recovered += int(ok)
        if ok:
            paused_seconds += max(0, int((_as_utc(next_pass.monitored_at) - _as_utc(monitor.monitored_at)).total_seconds()))
        pauses.append({"source": "monitor", "id": str(monitor.id), "recovered": ok})
    for incident in incidents:
        if incident.category in SAFETY_INCIDENT_CATEGORIES:
            continue
        next_pass = None
        if incident.status == "resolved" and incident.resolved_at is not None:
            next_pass = next((entry for entry in passing if _as_utc(entry.monitored_at) > _as_utc(incident.resolved_at)), None)
        ok = next_pass is not None
        recovered += int(ok)
        if ok:
            paused_seconds += max(0, int((_as_utc(next_pass.monitored_at) - _as_utc(incident.reported_at)).total_seconds()))
        pauses.append({"source": "incident", "id": str(incident.id), "recovered": ok})
    return {
        "pause_count": len(pauses), "recovered_pause_count": recovered,
        "recovery_rate_bps": _rate_bps(recovered, len(pauses)) if pauses else 10000,
        "paused_duration_seconds": paused_seconds,
        "all_non_safety_pauses_recovered": all(entry["recovered"] for entry in pauses),
        "evidence": pauses,
    }


def finalize_assessment(db: Session, user: User, item: AIHighCoverageOutcomeAssessment,
                        confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit outcome assessment finalization is required")
    if item.status != "collecting":
        raise HTTPException(409, "This outcome assessment is immutable")
    authorization = _authorization(db, user.organization_id, item.high_coverage_authorization_id)
    _validate_anchor(db, item, authorization)

    runs = _runs(db, authorization.id)
    monitors = _monitors(db, authorization.id)
    incidents = _incidents(db, authorization.id)
    observations = _observations(db, item.id)
    observations_by_run = {entry.high_coverage_run_id: entry for entry in observations}
    cohort = _cohort_metrics(runs, observations_by_run)
    trend = _trend_metrics(runs, observations_by_run, item)
    workflow_metrics = {
        workflow: _cohort_metrics([run for run in runs if run.task_type == workflow], observations_by_run)
        for workflow in sorted(REQUIRED_WORKFLOWS)
    }
    unresolved_high_or_critical = [
        incident for incident in incidents
        if incident.status == "open" and incident.severity in BLOCKING_INCIDENT_SEVERITIES
    ]
    safety_incidents = [incident for incident in incidents if incident.category in SAFETY_INCIDENT_CATEGORIES]
    recovery = _recovery_metrics(monitors, incidents)
    required_fields = (
        "human_review_action", "output_candidate_count", "unsupported_output_count",
        "source_grounded_output_count", "source_grounding_total_count", "latency_ms",
        "observed_provider_cost_microusd", "outcome_hash", "requested_by_id", "reviewed_by_id",
    )
    incomplete_run_metrics = [str(run.id) for run in runs if any(getattr(run, field) is None for field in required_fields)]
    self_reviewed_run_ids = [
        str(run.id) for run in runs
        if run.status == "human_reviewed" and run.requested_by_id == run.reviewed_by_id
    ]
    latest_monitor_fresh = bool(
        monitors and monitors[-1].status == "pass"
        and _as_utc(monitors[-1].monitored_at) >= datetime.now(UTC) - timedelta(minutes=authorization.monitor_interval_minutes * 2)
    )

    failures: list[str] = []
    if len(runs) < item.min_reviewed_runs:
        failures.append("minimum_reviewed_run_count")
    if cohort["human_review_rate_bps"] != 10000:
        failures.append("human_review_coverage")
    if cohort["different_human_review_rate_bps"] != 10000 or self_reviewed_run_ids:
        failures.append("different_human_review_coverage")
    if cohort["observation_coverage_rate_bps"] != 10000:
        failures.append("observation_coverage")
    if cohort["workflow_completion_rate_bps"] != 10000:
        failures.append("workflow_completion")
    if incomplete_run_metrics:
        failures.append("run_metric_completeness")
    if REQUIRED_WORKFLOWS <= set(authorization.allowed_document_types):
        for workflow in REQUIRED_WORKFLOWS:
            if workflow_metrics[workflow]["human_reviewed_run_count"] < item.min_runs_per_workflow:
                failures.append(f"minimum_{workflow}_representation")
    if cohort["human_reject_rate_bps"] is None or cohort["human_reject_rate_bps"] > item.max_reject_rate_bps:
        failures.append("human_reject_rate")
    if cohort["human_edit_rate_bps"] is None or cohort["human_edit_rate_bps"] > item.max_edit_rate_bps:
        failures.append("human_edit_rate")
    if cohort["mean_usefulness_bps"] is None or cohort["mean_usefulness_bps"] < item.min_mean_usefulness_bps:
        failures.append("mean_usefulness")
    if cohort["unsupported_output_rate_bps"] is None or cohort["unsupported_output_rate_bps"] > item.max_unsupported_output_rate_bps:
        failures.append("unsupported_output_rate")
    if cohort["source_grounding_validity_bps"] is None or cohort["source_grounding_validity_bps"] < item.min_source_grounding_validity_bps:
        failures.append("source_grounding_validity")
    if cohort["mean_review_seconds"] is None or cohort["mean_review_seconds"] > item.max_mean_review_seconds:
        failures.append("mean_review_seconds")
    if cohort["p95_latency_ms"] is None or cohort["p95_latency_ms"] > item.max_p95_latency_ms:
        failures.append("p95_latency")
    if cohort["mean_observed_provider_cost_microusd"] is None or cohort["mean_observed_provider_cost_microusd"] > item.max_mean_cost_microusd:
        failures.append("mean_observed_provider_cost")
    if trend["material_regression"]:
        failures.append("second_half_material_regression")
    if unresolved_high_or_critical:
        failures.append("unresolved_high_or_critical_incident")
    if safety_incidents:
        failures.append("privacy_security_or_cross_tenant_incident")
    if not recovery["all_non_safety_pauses_recovered"]:
        failures.append("rollback_recovery_evidence")
    if not latest_monitor_fresh:
        failures.append("fresh_final_passing_monitor")
    failures = sorted(set(failures))

    metrics = {
        **cohort,
        "workflow_metrics": workflow_metrics,
        "trend": trend,
        "monitor_history": {
            "count": len(monitors), "pass_count": sum(entry.status == "pass" for entry in monitors),
            "rollback_required_count": sum(entry.status != "pass" for entry in monitors),
            "latest_status": monitors[-1].status if monitors else None,
            "latest_monitor_fresh": latest_monitor_fresh,
            "monitor_hashes": [entry.monitor_hash for entry in monitors],
        },
        "incident_history": {
            "total_count": len(incidents),
            "unresolved_high_or_critical_count": len(unresolved_high_or_critical),
            "safety_boundary_incident_count": len(safety_incidents),
        },
        "rollback_recovery": recovery,
        "incomplete_run_metric_ids": incomplete_run_metrics,
        "self_reviewed_run_ids": self_reviewed_run_ids,
        "overall_pass": not failures,
        "raw_content_stored": False,
        "rollout_above_75_authorized": False,
        "production_wide_authorized": False,
        "restricted_documents_authorized": False,
        "new_document_classes_authorized": False,
    }
    assessed_at = datetime.now(UTC)
    snapshot = {
        "schema": "mcri-ai-high-coverage-outcome-assessment-v1",
        "assessment_id": str(item.id),
        "high_coverage_authorization_id": str(authorization.id),
        "high_coverage_decision_hash": authorization.decision_hash,
        "high_coverage_completion_hash": authorization.completion_hash,
        "broader_outcome_hashes": {"assessment": authorization.outcome_assessment_hash,
                                   "decision": authorization.outcome_decision_hash},
        "broader_production_decision_hash": authorization.broader_production_decision_hash,
        "readiness_hashes": {"assessment": authorization.readiness_assessment_hash,
                             "decision": authorization.readiness_decision_hash},
        "scale_up_decision_hash": authorization.scale_up_decision_hash,
        "limited_outcome_hashes": {"assessment": authorization.inherited_outcome_assessment_hash,
                                   "decision": authorization.inherited_outcome_decision_hash},
        "bundle": {"model": item.model, "prompt": item.prompt_bundle_version,
                   "schema": item.schema_bundle_version, "rollout_percentage": item.rollout_percentage},
        "thresholds": _thresholds(item), "metrics": metrics, "failure_reasons": failures,
        "run_outcome_hashes": [run.outcome_hash for run in runs],
        "observation_hashes": [entry.observation_hash for entry in observations],
        "monitor_hashes": [entry.monitor_hash for entry in monitors],
        "incident_states": [
            {"id": str(entry.id), "severity": entry.severity, "category": entry.category,
             "status": entry.status, "reported_at": _as_utc(entry.reported_at).isoformat(),
             "resolved_at": _as_utc(entry.resolved_at).isoformat() if entry.resolved_at else None}
            for entry in incidents
        ],
        "assessed_at": assessed_at.isoformat(), "note": note.strip(),
        "recommendation_only": True, "rollout_above_75_authorized": False,
        "production_wide_authorized": False, "restricted_documents_authorized": False,
        "raw_content_stored": False,
    }
    item.metrics = metrics
    item.failure_reasons = failures
    item.assessment_note = note.strip()
    item.assessed_at = assessed_at
    item.finalized_by_id = user.id
    item.assessment_hash = _hash(snapshot)
    item.status = "review_ready"
    _audit(
        db, user, "FINALIZE_AI_HIGH_COVERAGE_OUTCOME_ASSESSMENT", item,
        {"status": item.status, "overall_pass": not failures, "failure_reasons": failures,
         "assessment_hash": item.assessment_hash, "rollout_above_75_authorized": False,
         "production_wide_authorized": False},
        "Immutable Sprint 11L high-coverage outcome scorecard finalized. " + note.strip(),
    )
    db.commit()
    db.refresh(item)
    return assessment_response(db, item)


def record_review(db: Session, user: User, item: AIHighCoverageOutcomeAssessment,
                  role: str, action: str, evidence_reference: str | None, note: str) -> dict:
    if item.status not in {"review_ready", "decision_ready"}:
        raise HTTPException(409, "Only a finalized assessment can be reviewed")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The assessment requester cannot review the final-readiness gate")
    reviews = _reviews(db, item.id)
    if any(review.review_role == role for review in reviews):
        raise HTTPException(409, "This review role already has a decision")
    if any(review.reviewer_id == user.id for review in reviews):
        raise HTTPException(409, "All seven Sprint 11L review roles require different people")
    reference = _reference(evidence_reference) if evidence_reference else None
    if action == "approve" and not reference:
        raise HTTPException(422, "Approval requires bounded evidence")
    review = AIHighCoverageOutcomeReview(
        organization_id=user.organization_id, assessment_id=item.id, reviewer_id=user.id,
        review_role=role, action=action, evidence_reference=reference,
        note=note.strip(), reviewed_at=datetime.now(UTC),
    )
    db.add(review)
    db.flush()
    if action == "reject":
        item.status = "review_rejected"
        item.outcome = "review_rejected"
    else:
        current = _reviews(db, item.id)
        item.status = "decision_ready" if (
            {entry.review_role for entry in current} == REVIEW_ROLES
            and len(current) == len(REVIEW_ROLES)
            and all(entry.action == "approve" for entry in current)
            and len({entry.reviewer_id for entry in current}) == len(REVIEW_ROLES)
            and all(entry.reviewer_id != item.requested_by_id for entry in current)
        ) else "review_ready"
    _audit(
        db, user, f"{action.upper()}_AI_HIGH_COVERAGE_OUTCOME_REVIEW", item,
        {"review_role": role, "action": action, "evidence_reference": reference,
         "status": item.status},
        "Independent Sprint 11L final-readiness review. " + note.strip(),
    )
    db.commit()
    db.refresh(item)
    return assessment_response(db, item)


def decide_outcome(db: Session, user: User, item: AIHighCoverageOutcomeAssessment,
                   outcome: str, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit recommendation-only confirmation is required")
    if item.status != "decision_ready":
        raise HTTPException(409, "Seven independent approvals are required")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The requester cannot issue the final outcome")
    if not item.metrics or not item.assessment_hash:
        raise HTTPException(409, "A finalized outcome assessment is required")
    authorization = _authorization(db, user.organization_id, item.high_coverage_authorization_id)
    _validate_anchor(db, item, authorization)
    reviews = _reviews(db, item.id)
    if (
        {entry.review_role for entry in reviews} != REVIEW_ROLES
        or len(reviews) != len(REVIEW_ROLES)
        or len({entry.reviewer_id for entry in reviews}) != len(REVIEW_ROLES)
        or any(entry.action != "approve" for entry in reviews)
        or any(entry.reviewer_id == item.requested_by_id for entry in reviews)
    ):
        raise HTTPException(409, "Seven independent review roles must remain approved")
    if outcome == "recommend_final_production_readiness_review" and (
        item.failure_reasons or not item.metrics.get("overall_pass")
    ):
        raise HTTPException(409, "Final-readiness recommendation requires zero failed controls")
    snapshot = {
        "schema": "mcri-ai-high-coverage-final-readiness-recommendation-v1",
        "assessment_id": str(item.id),
        "high_coverage_authorization_id": str(item.high_coverage_authorization_id),
        "high_coverage_decision_hash": item.high_coverage_decision_hash,
        "high_coverage_completion_hash": item.high_coverage_completion_hash,
        "assessment_hash": item.assessment_hash,
        "reviewers": [
            {"role": entry.review_role, "reviewer_id": str(entry.reviewer_id),
             "evidence_reference": entry.evidence_reference} for entry in reviews
        ],
        "outcome": outcome, "decision_note": note.strip(), "recommendation_only": True,
        "rollout_above_75_authorized": False, "production_wide_authorized": False,
        "restricted_documents_authorized": False, "new_document_classes_authorized": False,
        "autonomous_claim_decisions_authorized": False,
        "authoritative_facts_auto_updated": False,
    }
    item.outcome = outcome
    item.decision_note = note.strip()
    item.decided_at = datetime.now(UTC)
    item.finalized_by_id = user.id
    item.decision_hash = _hash(snapshot)
    if outcome == "recommend_final_production_readiness_review":
        item.status = "recommended"
    elif outcome == "extend_high_coverage_51_75":
        item.status = "extended"
    else:
        item.status = "stopped"
    _audit(
        db, user, "DECIDE_AI_HIGH_COVERAGE_FINAL_READINESS_RECOMMENDATION", item,
        {"status": item.status, "outcome": outcome, "decision_hash": item.decision_hash,
         "rollout_above_75_authorized": False, "production_wide_authorized": False},
        "Recommendation-only Sprint 11L decision; any >75% or Production-wide stage remains separately governed. " + note.strip(),
    )
    db.commit()
    db.refresh(item)
    return assessment_response(db, item)
