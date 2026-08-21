import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from math import ceil
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.ai_broader_production.models import (
    AIBroaderProductionAuthorization,
    AIBroaderProductionIncident,
    AIBroaderProductionMonitor,
    AIBroaderProductionRun,
)
from app.modules.ai_broader_production_outcomes.models import (
    AIBroaderProductionOutcomeAssessment,
    AIBroaderProductionOutcomeObservation,
    AIBroaderProductionOutcomeReview,
)
from app.modules.ai_broader_production_outcomes.schemas import (
    AIBroaderProductionOutcomeCreate,
    AIBroaderProductionOutcomeObservationCreate,
)
from app.modules.ai_scale_up_outcomes.models import AIScaleUpOutcomeAssessment
from app.modules.audit.service import write_audit_log
from app.modules.users.models import User

REFERENCE = re.compile(r"^(artifact|runbook|ticket|monitor)://[A-Za-z0-9._:/-]{3,450}$")
REVIEW_ROLES = {"product", "quality", "risk", "operations", "security", "claims_governance"}
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


def _audit(db: Session, user: User, action: str, item: AIBroaderProductionOutcomeAssessment,
           values: dict, details: str) -> None:
    write_audit_log(
        db, organization_id=user.organization_id, user_id=user.id, action=action,
        entity_type="ai_broader_production_outcome_assessment", entity_id=item.id,
        new_values=values, details=details,
    )


def _authorization(db: Session, organization_id: UUID,
                   authorization_id: UUID) -> AIBroaderProductionAuthorization:
    item = db.scalar(select(AIBroaderProductionAuthorization).where(
        AIBroaderProductionAuthorization.id == authorization_id,
        AIBroaderProductionAuthorization.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Sprint 11I broader-production authorization not found")
    return item


def _readiness(db: Session, item: AIBroaderProductionAuthorization) -> AIScaleUpOutcomeAssessment:
    readiness = db.scalar(select(AIScaleUpOutcomeAssessment).where(
        AIScaleUpOutcomeAssessment.id == item.readiness_assessment_id,
        AIScaleUpOutcomeAssessment.organization_id == item.organization_id,
    ))
    if readiness is None:
        raise HTTPException(409, "The inherited Sprint 11H readiness anchor is missing")
    return readiness


def _runs(db: Session, authorization_id: UUID) -> list[AIBroaderProductionRun]:
    return list(db.scalars(select(AIBroaderProductionRun).where(
        AIBroaderProductionRun.authorization_id == authorization_id,
    ).order_by(AIBroaderProductionRun.queued_at.asc(), AIBroaderProductionRun.id.asc())))


def _monitors(db: Session, authorization_id: UUID) -> list[AIBroaderProductionMonitor]:
    return list(db.scalars(select(AIBroaderProductionMonitor).where(
        AIBroaderProductionMonitor.authorization_id == authorization_id,
    ).order_by(AIBroaderProductionMonitor.monitored_at.asc(), AIBroaderProductionMonitor.id.asc())))


def _incidents(db: Session, authorization_id: UUID) -> list[AIBroaderProductionIncident]:
    return list(db.scalars(select(AIBroaderProductionIncident).where(
        AIBroaderProductionIncident.authorization_id == authorization_id,
    ).order_by(AIBroaderProductionIncident.reported_at.asc(), AIBroaderProductionIncident.id.asc())))


def _observations(db: Session, assessment_id: UUID) -> list[AIBroaderProductionOutcomeObservation]:
    return list(db.scalars(select(AIBroaderProductionOutcomeObservation).where(
        AIBroaderProductionOutcomeObservation.assessment_id == assessment_id,
    ).order_by(AIBroaderProductionOutcomeObservation.observed_at.asc(),
               AIBroaderProductionOutcomeObservation.id.asc())))


def _reviews(db: Session, assessment_id: UUID) -> list[AIBroaderProductionOutcomeReview]:
    return list(db.scalars(select(AIBroaderProductionOutcomeReview).where(
        AIBroaderProductionOutcomeReview.assessment_id == assessment_id,
    ).order_by(AIBroaderProductionOutcomeReview.review_role.asc())))


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


def _thresholds(item: AIBroaderProductionOutcomeAssessment) -> dict:
    return {
        "minimum_human_reviewed_provider_runs": item.min_reviewed_runs,
        "minimum_reviewed_runs_per_workflow": item.min_runs_per_workflow,
        "required_human_review_rate_bps": 10000,
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
    }


def assessment_response(db: Session, item: AIBroaderProductionOutcomeAssessment) -> dict:
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
        "broader_production_authorization_id": item.broader_production_authorization_id,
        "requested_by_id": item.requested_by_id,
        "finalized_by_id": item.finalized_by_id,
        "attempt_number": item.attempt_number,
        "assessment_key": item.assessment_key,
        "assessment_profile": item.assessment_profile,
        "broader_production_decision_hash": item.broader_production_decision_hash,
        "inherited_hashes": {
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
            "next_broader_stage_recommended": (
                item.status == "recommended" and item.outcome == "recommend_next_broader_stage"
            ),
            "rollout_above_50_authorized": False,
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
    items = list(db.scalars(select(AIBroaderProductionOutcomeAssessment).where(
        AIBroaderProductionOutcomeAssessment.organization_id == organization_id,
    ).order_by(AIBroaderProductionOutcomeAssessment.created_at.desc()).limit(25)))
    return [assessment_response(db, item) for item in items]


def get_assessment(db: Session, organization_id: UUID,
                   assessment_id: UUID) -> AIBroaderProductionOutcomeAssessment:
    item = db.scalar(select(AIBroaderProductionOutcomeAssessment).where(
        AIBroaderProductionOutcomeAssessment.id == assessment_id,
        AIBroaderProductionOutcomeAssessment.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Sprint 11J broader-production outcome assessment not found")
    return item


def _validate_anchor(db: Session, item: AIBroaderProductionOutcomeAssessment,
                     authorization: AIBroaderProductionAuthorization) -> AIScaleUpOutcomeAssessment:
    readiness = _readiness(db, authorization)
    if authorization.status != "completed" or not authorization.decision_hash:
        raise HTTPException(409, "A completed Sprint 11I broader-production cohort is required")
    if (
        authorization.decision_hash != item.broader_production_decision_hash
        or authorization.readiness_assessment_hash != item.readiness_assessment_hash
        or authorization.readiness_decision_hash != item.readiness_decision_hash
        or authorization.scale_up_decision_hash != item.scale_up_decision_hash
        or authorization.inherited_outcome_assessment_hash != item.inherited_outcome_assessment_hash
        or authorization.inherited_outcome_decision_hash != item.inherited_outcome_decision_hash
        or readiness.status != "recommended"
        or readiness.outcome != "recommend_broader_production_stage"
        or not (readiness.metrics or {}).get("overall_pass")
        or readiness.assessment_hash != item.readiness_assessment_hash
        or readiness.decision_hash != item.readiness_decision_hash
        or readiness.scale_up_decision_hash != item.scale_up_decision_hash
        or readiness.outcome_assessment_hash != item.inherited_outcome_assessment_hash
        or readiness.outcome_decision_hash != item.inherited_outcome_decision_hash
        or authorization.model != item.model
        or authorization.prompt_bundle_version != item.prompt_bundle_version
        or authorization.schema_bundle_version != item.schema_bundle_version
        or authorization.rollout_percentage != item.rollout_percentage
        or not 26 <= authorization.rollout_percentage <= 50
    ):
        raise HTTPException(409, "The persisted Sprint 11I/11H evidence anchor no longer matches")
    return readiness


def create_assessment(db: Session, user: User, payload: AIBroaderProductionOutcomeCreate) -> dict:
    if not payload.confirm_content_free_assessment:
        raise HTTPException(422, "Explicit content-free outcome assessment confirmation is required")
    authorization = _authorization(db, user.organization_id, payload.broader_production_authorization_id)
    if authorization.status != "completed" or not authorization.decision_hash:
        raise HTTPException(409, "A completed Sprint 11I broader-production cohort is required")
    readiness = _readiness(db, authorization)
    if (
        readiness.status != "recommended"
        or readiness.outcome != "recommend_broader_production_stage"
        or not (readiness.metrics or {}).get("overall_pass")
        or not readiness.assessment_hash
        or not readiness.decision_hash
        or authorization.readiness_assessment_hash != readiness.assessment_hash
        or authorization.readiness_decision_hash != readiness.decision_hash
    ):
        raise HTTPException(409, "The Sprint 11H readiness anchor inherited by 11I is invalid")
    attempts = list(db.scalars(select(AIBroaderProductionOutcomeAssessment).where(
        AIBroaderProductionOutcomeAssessment.broader_production_authorization_id == authorization.id,
    ).order_by(AIBroaderProductionOutcomeAssessment.attempt_number.asc())))
    if attempts and attempts[-1].status not in RETRY_STATUSES:
        raise HTTPException(409, "The current Sprint 11J assessment is still active")
    item = AIBroaderProductionOutcomeAssessment(
        organization_id=user.organization_id,
        broader_production_authorization_id=authorization.id,
        requested_by_id=user.id,
        attempt_number=len(attempts) + 1,
        assessment_key=payload.assessment_key.strip(),
        broader_production_decision_hash=authorization.decision_hash,
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
        db, user, "CREATE_AI_BROADER_PRODUCTION_OUTCOME_ASSESSMENT", item,
        {"authorization_id": str(authorization.id), "attempt_number": item.attempt_number,
         "rollout_percentage": item.rollout_percentage, "raw_content_stored": False},
        "Sprint 11J content-free broader-production outcome assessment created.",
    )
    db.commit()
    db.refresh(item)
    return assessment_response(db, item)


def record_observation(db: Session, user: User, item: AIBroaderProductionOutcomeAssessment,
                       payload: AIBroaderProductionOutcomeObservationCreate) -> dict:
    if not payload.confirm_content_free_observation:
        raise HTTPException(422, "Explicit content-free observation confirmation is required")
    if item.status != "collecting":
        raise HTTPException(409, "This assessment no longer accepts observations")
    authorization = _authorization(db, user.organization_id, item.broader_production_authorization_id)
    _validate_anchor(db, item, authorization)
    run = db.scalar(select(AIBroaderProductionRun).where(
        AIBroaderProductionRun.id == payload.broader_production_run_id,
        AIBroaderProductionRun.authorization_id == authorization.id,
        AIBroaderProductionRun.organization_id == user.organization_id,
    ))
    if run is None:
        raise HTTPException(404, "Sprint 11I run not found")
    if run.status != "human_reviewed" or not run.outcome_hash:
        raise HTTPException(409, "Only immutable different-human-reviewed runs can be observed")
    now = datetime.now(UTC)
    reference = _reference(payload.evidence_reference)
    snapshot = {
        "schema": "mcri-ai-broader-production-outcome-observation-v1",
        "assessment_id": str(item.id), "run_id": str(run.id),
        "run_outcome_hash": run.outcome_hash, "workflow_type": run.task_type,
        "usefulness_rating": payload.usefulness_rating, "review_seconds": payload.review_seconds,
        "workflow_completed": payload.workflow_completed, "evidence_reference": reference,
        "observed_at": now.isoformat(), "raw_content_stored": False,
    }
    observation = AIBroaderProductionOutcomeObservation(
        organization_id=user.organization_id, assessment_id=item.id,
        broader_production_run_id=run.id, observed_by_id=user.id,
        workflow_type=run.task_type, usefulness_rating=payload.usefulness_rating,
        review_seconds=payload.review_seconds, workflow_completed=payload.workflow_completed,
        evidence_reference=reference, note=payload.note.strip(),
        observation_hash=sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        observed_at=now,
    )
    db.add(observation)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This Sprint 11I run already has an observation") from exc
    _audit(
        db, user, "RECORD_AI_BROADER_PRODUCTION_OUTCOME_OBSERVATION", item,
        {"run_id": str(run.id), "observation_hash": observation.observation_hash,
         "raw_content_stored": False},
        "Content-free Sprint 11J usefulness and operator-effort observation recorded.",
    )
    db.commit()
    db.refresh(item)
    return assessment_response(db, item)


def _cohort_metrics(runs: list[AIBroaderProductionRun], observations_by_run: dict[UUID, AIBroaderProductionOutcomeObservation]) -> dict:
    reviewed = [run for run in runs if run.status == "human_reviewed"]
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


def _trend_metrics(runs: list[AIBroaderProductionRun], observations_by_run: dict[UUID, AIBroaderProductionOutcomeObservation],
                   item: AIBroaderProductionOutcomeAssessment) -> dict:
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
        if isinstance(a, int) and isinstance(b, int):
            deteriorations.append(max(0, b - a))
        else:
            deteriorations.append(10000)
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


def _recovery_metrics(monitors: list[AIBroaderProductionMonitor], incidents: list[AIBroaderProductionIncident]) -> dict:
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


def finalize_assessment(db: Session, user: User, item: AIBroaderProductionOutcomeAssessment,
                        confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit outcome assessment finalization is required")
    if item.status != "collecting":
        raise HTTPException(409, "This outcome assessment is immutable")
    authorization = _authorization(db, user.organization_id, item.broader_production_authorization_id)
    _validate_anchor(db, item, authorization)

    runs = _runs(db, authorization.id)
    monitors = _monitors(db, authorization.id)
    incidents = _incidents(db, authorization.id)
    observations = _observations(db, item.id)
    observations_by_run = {entry.broader_production_run_id: entry for entry in observations}
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
        "observed_provider_cost_microusd", "outcome_hash", "reviewed_by_id",
    )
    incomplete_run_metrics = [str(run.id) for run in runs if any(getattr(run, field) is None for field in required_fields)]

    failures: list[str] = []
    if len(runs) < item.min_reviewed_runs:
        failures.append("minimum_reviewed_run_count")
    if cohort["human_review_rate_bps"] != 10000:
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
    if not monitors or monitors[-1].status != "pass":
        failures.append("final_passing_monitor")
    failures = sorted(set(failures))

    metrics = {
        **cohort,
        "workflow_metrics": workflow_metrics,
        "trend": trend,
        "monitor_history": {
            "count": len(monitors), "pass_count": sum(entry.status == "pass" for entry in monitors),
            "rollback_required_count": sum(entry.status != "pass" for entry in monitors),
            "latest_status": monitors[-1].status if monitors else None,
            "monitor_hashes": [entry.monitor_hash for entry in monitors],
        },
        "incident_history": {
            "total_count": len(incidents),
            "unresolved_high_or_critical_count": len(unresolved_high_or_critical),
            "safety_boundary_incident_count": len(safety_incidents),
        },
        "rollback_recovery": recovery,
        "incomplete_run_metric_ids": incomplete_run_metrics,
        "overall_pass": not failures,
        "raw_content_stored": False,
        "rollout_above_50_authorized": False,
        "production_wide_authorized": False,
        "restricted_documents_authorized": False,
        "new_document_classes_authorized": False,
    }
    assessed_at = datetime.now(UTC)
    snapshot = {
        "schema": "mcri-ai-broader-production-outcome-assessment-v1",
        "assessment_id": str(item.id),
        "broader_production_authorization_id": str(authorization.id),
        "broader_production_decision_hash": authorization.decision_hash,
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
        "recommendation_only": True, "rollout_above_50_authorized": False,
        "production_wide_authorized": False, "restricted_documents_authorized": False,
        "raw_content_stored": False,
    }
    item.metrics = metrics
    item.failure_reasons = failures
    item.assessment_note = note.strip()
    item.assessed_at = assessed_at
    item.finalized_by_id = user.id
    item.assessment_hash = sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    item.status = "review_ready"
    _audit(
        db, user, "FINALIZE_AI_BROADER_PRODUCTION_OUTCOME_ASSESSMENT", item,
        {"status": item.status, "overall_pass": not failures, "failure_reasons": failures,
         "assessment_hash": item.assessment_hash, "rollout_above_50_authorized": False,
         "production_wide_authorized": False},
        "Immutable Sprint 11J broader-production outcome scorecard finalized. " + note.strip(),
    )
    db.commit()
    db.refresh(item)
    return assessment_response(db, item)


def record_review(db: Session, user: User, item: AIBroaderProductionOutcomeAssessment,
                  role: str, action: str, evidence_reference: str | None, note: str) -> dict:
    if item.status not in {"review_ready", "decision_ready"}:
        raise HTTPException(409, "Only a finalized assessment can be reviewed")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The assessment requester cannot review the readiness gate")
    reviews = _reviews(db, item.id)
    if any(review.review_role == role for review in reviews):
        raise HTTPException(409, "This review role already has a decision")
    if any(review.reviewer_id == user.id for review in reviews):
        raise HTTPException(409, "All six Sprint 11J review roles require different people")
    reference = _reference(evidence_reference) if evidence_reference else None
    if action == "approve" and not reference:
        raise HTTPException(422, "Approval requires bounded evidence")
    review = AIBroaderProductionOutcomeReview(
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
        db, user, f"{action.upper()}_AI_BROADER_PRODUCTION_OUTCOME_REVIEW", item,
        {"review_role": role, "action": action, "evidence_reference": reference,
         "status": item.status},
        "Independent Sprint 11J readiness review. " + note.strip(),
    )
    db.commit()
    db.refresh(item)
    return assessment_response(db, item)


def decide_outcome(db: Session, user: User, item: AIBroaderProductionOutcomeAssessment,
                   outcome: str, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit recommendation-only confirmation is required")
    if item.status != "decision_ready":
        raise HTTPException(409, "Six independent approvals are required")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The requester cannot issue the final outcome")
    if not item.metrics or not item.assessment_hash:
        raise HTTPException(409, "A finalized outcome assessment is required")
    authorization = _authorization(db, user.organization_id, item.broader_production_authorization_id)
    _validate_anchor(db, item, authorization)
    reviews = _reviews(db, item.id)
    if (
        {entry.review_role for entry in reviews} != REVIEW_ROLES
        or len(reviews) != len(REVIEW_ROLES)
        or len({entry.reviewer_id for entry in reviews}) != len(REVIEW_ROLES)
        or any(entry.action != "approve" for entry in reviews)
        or any(entry.reviewer_id == item.requested_by_id for entry in reviews)
    ):
        raise HTTPException(409, "Six independent review roles must remain approved")
    if outcome == "recommend_next_broader_stage" and (
        item.failure_reasons or not item.metrics.get("overall_pass")
    ):
        raise HTTPException(409, "Next-stage recommendation requires zero failed controls")
    snapshot = {
        "schema": "mcri-ai-broader-production-readiness-recommendation-v1",
        "assessment_id": str(item.id),
        "broader_production_authorization_id": str(item.broader_production_authorization_id),
        "broader_production_decision_hash": item.broader_production_decision_hash,
        "assessment_hash": item.assessment_hash,
        "reviewers": [
            {"role": entry.review_role, "reviewer_id": str(entry.reviewer_id),
             "evidence_reference": entry.evidence_reference} for entry in reviews
        ],
        "outcome": outcome, "decision_note": note.strip(), "recommendation_only": True,
        "rollout_above_50_authorized": False, "production_wide_authorized": False,
        "restricted_documents_authorized": False, "new_document_classes_authorized": False,
        "autonomous_claim_decisions_authorized": False,
        "authoritative_facts_auto_updated": False,
    }
    item.outcome = outcome
    item.decision_note = note.strip()
    item.decided_at = datetime.now(UTC)
    item.finalized_by_id = user.id
    item.decision_hash = sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if outcome == "recommend_next_broader_stage":
        item.status = "recommended"
    elif outcome == "extend_broader_production":
        item.status = "extended"
    else:
        item.status = "stopped"
    _audit(
        db, user, "DECIDE_AI_BROADER_PRODUCTION_READINESS_RECOMMENDATION", item,
        {"status": item.status, "outcome": outcome, "decision_hash": item.decision_hash,
         "rollout_above_50_authorized": False, "production_wide_authorized": False},
        "Recommendation-only Sprint 11J decision; any >50% or Production-wide stage remains separately governed. " + note.strip(),
    )
    db.commit()
    db.refresh(item)
    return assessment_response(db, item)
