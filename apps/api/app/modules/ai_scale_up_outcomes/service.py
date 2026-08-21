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

from app.modules.ai_limited_production_outcomes.models import AILimitedProductionOutcomeAssessment
from app.modules.ai_scale_up.models import (
    AIScaleUpAuthorization,
    AIScaleUpIncident,
    AIScaleUpMonitor,
    AIScaleUpRun,
)
from app.modules.ai_scale_up_outcomes.models import (
    AIScaleUpOutcomeAssessment,
    AIScaleUpOutcomeObservation,
    AIScaleUpOutcomeReview,
)
from app.modules.ai_scale_up_outcomes.schemas import (
    AIScaleUpOutcomeCreate,
    AIScaleUpOutcomeObservationCreate,
)
from app.modules.audit.service import write_audit_log
from app.modules.users.models import User

REFERENCE = re.compile(r"^(artifact|runbook|ticket|monitor)://[A-Za-z0-9._:/-]{3,450}$")
REVIEW_ROLES = {"product", "quality", "risk", "operations", "security"}
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


def _audit(db: Session, user: User, action: str, item: AIScaleUpOutcomeAssessment,
           values: dict, details: str) -> None:
    write_audit_log(
        db, organization_id=user.organization_id, user_id=user.id, action=action,
        entity_type="ai_scale_up_outcome_assessment", entity_id=item.id,
        new_values=values, details=details,
    )


def _authorization(db: Session, organization_id: UUID,
                   authorization_id: UUID) -> AIScaleUpAuthorization:
    item = db.scalar(select(AIScaleUpAuthorization).where(
        AIScaleUpAuthorization.id == authorization_id,
        AIScaleUpAuthorization.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Controlled scale-up authorization not found")
    return item


def _inherited_outcome(db: Session, item: AIScaleUpAuthorization) -> AILimitedProductionOutcomeAssessment:
    outcome = db.scalar(select(AILimitedProductionOutcomeAssessment).where(
        AILimitedProductionOutcomeAssessment.id == item.outcome_assessment_id,
        AILimitedProductionOutcomeAssessment.organization_id == item.organization_id,
    ))
    if outcome is None:
        raise HTTPException(409, "The inherited Sprint 11F outcome anchor is missing")
    return outcome


def _runs(db: Session, authorization_id: UUID) -> list[AIScaleUpRun]:
    return list(db.scalars(select(AIScaleUpRun).where(
        AIScaleUpRun.authorization_id == authorization_id,
    ).order_by(AIScaleUpRun.queued_at.asc(), AIScaleUpRun.id.asc())))


def _monitors(db: Session, authorization_id: UUID) -> list[AIScaleUpMonitor]:
    return list(db.scalars(select(AIScaleUpMonitor).where(
        AIScaleUpMonitor.authorization_id == authorization_id,
    ).order_by(AIScaleUpMonitor.monitored_at.asc(), AIScaleUpMonitor.id.asc())))


def _incidents(db: Session, authorization_id: UUID) -> list[AIScaleUpIncident]:
    return list(db.scalars(select(AIScaleUpIncident).where(
        AIScaleUpIncident.authorization_id == authorization_id,
    ).order_by(AIScaleUpIncident.reported_at.asc(), AIScaleUpIncident.id.asc())))


def _observations(db: Session, assessment_id: UUID) -> list[AIScaleUpOutcomeObservation]:
    return list(db.scalars(select(AIScaleUpOutcomeObservation).where(
        AIScaleUpOutcomeObservation.assessment_id == assessment_id,
    ).order_by(AIScaleUpOutcomeObservation.observed_at.asc())))


def _reviews(db: Session, assessment_id: UUID) -> list[AIScaleUpOutcomeReview]:
    return list(db.scalars(select(AIScaleUpOutcomeReview).where(
        AIScaleUpOutcomeReview.assessment_id == assessment_id,
    ).order_by(AIScaleUpOutcomeReview.review_role.asc())))


def _thresholds(item: AIScaleUpOutcomeAssessment) -> dict:
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


def assessment_response(db: Session, item: AIScaleUpOutcomeAssessment) -> dict:
    observations = _observations(db, item.id)
    reviews = _reviews(db, item.id)
    reviews_complete = bool(
        {review.review_role for review in reviews} == REVIEW_ROLES
        and all(review.action == "approve" for review in reviews)
        and len(reviews) == len(REVIEW_ROLES)
        and len({review.reviewer_id for review in reviews}) == len(REVIEW_ROLES)
        and all(review.reviewer_id != item.requested_by_id for review in reviews)
    )
    return {
        "id": item.id,
        "scale_up_authorization_id": item.scale_up_authorization_id,
        "requested_by_id": item.requested_by_id,
        "finalized_by_id": item.finalized_by_id,
        "attempt_number": item.attempt_number,
        "assessment_key": item.assessment_key,
        "assessment_profile": item.assessment_profile,
        "scale_up_decision_hash": item.scale_up_decision_hash,
        "inherited_outcome_hashes": {
            "assessment_hash": item.outcome_assessment_hash,
            "decision_hash": item.outcome_decision_hash,
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
            "production_readiness_recommendation_recorded": item.status in {
                "recommended", "extended", "stopped"
            },
            "broader_production_stage_recommended": (
                item.status == "recommended"
                and item.outcome == "recommend_broader_production_stage"
            ),
            "rollout_increase_authorized": False,
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
    items = list(db.scalars(select(AIScaleUpOutcomeAssessment).where(
        AIScaleUpOutcomeAssessment.organization_id == organization_id,
    ).order_by(AIScaleUpOutcomeAssessment.created_at.desc()).limit(25)))
    return [assessment_response(db, item) for item in items]


def get_assessment(db: Session, organization_id: UUID,
                   assessment_id: UUID) -> AIScaleUpOutcomeAssessment:
    item = db.scalar(select(AIScaleUpOutcomeAssessment).where(
        AIScaleUpOutcomeAssessment.id == assessment_id,
        AIScaleUpOutcomeAssessment.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Controlled scale-up outcome assessment not found")
    return item


def _validate_anchor(db: Session, item: AIScaleUpOutcomeAssessment,
                     authorization: AIScaleUpAuthorization) -> AILimitedProductionOutcomeAssessment:
    inherited = _inherited_outcome(db, authorization)
    if authorization.status != "completed" or not authorization.decision_hash:
        raise HTTPException(409, "A completed Sprint 11G controlled scale-up is required")
    if (
        authorization.decision_hash != item.scale_up_decision_hash
        or authorization.outcome_assessment_hash != item.outcome_assessment_hash
        or authorization.outcome_decision_hash != item.outcome_decision_hash
        or inherited.assessment_hash != item.outcome_assessment_hash
        or inherited.decision_hash != item.outcome_decision_hash
        or authorization.model != item.model
        or authorization.prompt_bundle_version != item.prompt_bundle_version
        or authorization.schema_bundle_version != item.schema_bundle_version
        or authorization.rollout_percentage != item.rollout_percentage
    ):
        raise HTTPException(409, "The persisted Sprint 11G/11F evidence anchor no longer matches")
    return inherited


def create_assessment(db: Session, user: User, payload: AIScaleUpOutcomeCreate) -> dict:
    if not payload.confirm_content_free_assessment:
        raise HTTPException(422, "Explicit content-free outcome assessment confirmation is required")
    authorization = _authorization(db, user.organization_id, payload.scale_up_authorization_id)
    if authorization.status != "completed" or not authorization.decision_hash:
        raise HTTPException(409, "A completed Sprint 11G controlled scale-up is required")
    inherited = _inherited_outcome(db, authorization)
    if (
        not inherited.assessment_hash
        or not inherited.decision_hash
        or authorization.outcome_assessment_hash != inherited.assessment_hash
        or authorization.outcome_decision_hash != inherited.decision_hash
    ):
        raise HTTPException(409, "The Sprint 11F hashes inherited by 11G are invalid")
    attempts = list(db.scalars(select(AIScaleUpOutcomeAssessment).where(
        AIScaleUpOutcomeAssessment.scale_up_authorization_id == authorization.id,
    ).order_by(AIScaleUpOutcomeAssessment.attempt_number.asc())))
    if attempts and attempts[-1].status not in RETRY_STATUSES:
        raise HTTPException(409, "The current controlled-scale-up outcome assessment is still active")
    item = AIScaleUpOutcomeAssessment(
        organization_id=user.organization_id,
        scale_up_authorization_id=authorization.id,
        requested_by_id=user.id,
        attempt_number=len(attempts) + 1,
        assessment_key=payload.assessment_key.strip(),
        assessment_profile="controlled_scale_up_readiness_v1",
        scale_up_decision_hash=authorization.decision_hash,
        outcome_assessment_hash=authorization.outcome_assessment_hash,
        outcome_decision_hash=authorization.outcome_decision_hash,
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
        raise HTTPException(409, "This scale-up outcome assessment key or attempt already exists") from exc
    _audit(
        db, user, "CREATE_AI_SCALE_UP_OUTCOME_ASSESSMENT", item,
        {
            "scale_up_authorization_id": str(authorization.id),
            "scale_up_decision_hash": authorization.decision_hash,
            "outcome_assessment_hash": authorization.outcome_assessment_hash,
            "outcome_decision_hash": authorization.outcome_decision_hash,
            "rollout_percentage": authorization.rollout_percentage,
            "thresholds": _thresholds(item),
            "production_wide_authorized": False,
            "rollout_increase_authorized": False,
            "raw_content_stored": False,
        },
        "Content-free Sprint 11H outcome assessment created; no broader Production authorization granted.",
    )
    db.commit()
    db.refresh(item)
    return assessment_response(db, item)


def record_observation(db: Session, user: User, item: AIScaleUpOutcomeAssessment,
                       payload: AIScaleUpOutcomeObservationCreate) -> dict:
    if item.status != "collecting":
        raise HTTPException(409, "This outcome assessment is immutable")
    if not payload.confirm_content_free_observation:
        raise HTTPException(422, "Explicit content-free observation confirmation is required")
    run = db.scalar(select(AIScaleUpRun).where(
        AIScaleUpRun.id == payload.scale_up_run_id,
        AIScaleUpRun.authorization_id == item.scale_up_authorization_id,
        AIScaleUpRun.organization_id == user.organization_id,
    ))
    if run is None:
        raise HTTPException(404, "Reviewed controlled-scale-up run not found")
    if (
        run.status != "human_reviewed"
        or run.outcome_hash is None
        or run.reviewed_by_id is None
        or run.reviewed_by_id == run.requested_by_id
    ):
        raise HTTPException(409, "The scale-up run requires immutable different-human review")
    reference = _reference(payload.evidence_reference)
    observed_at = datetime.now(UTC)
    snapshot = {
        "schema": "mcri-ai-scale-up-outcome-observation-v1",
        "assessment_id": str(item.id),
        "scale_up_run_id": str(run.id),
        "run_outcome_hash": run.outcome_hash,
        "workflow_type": run.task_type,
        "usefulness_rating": payload.usefulness_rating,
        "review_seconds": payload.review_seconds,
        "workflow_completed": payload.workflow_completed,
        "evidence_reference": reference,
        "note": payload.note.strip(),
        "observed_at": observed_at.isoformat(),
        "run_metrics_reused": True,
        "raw_content_stored": False,
    }
    observation = AIScaleUpOutcomeObservation(
        organization_id=user.organization_id,
        assessment_id=item.id,
        scale_up_run_id=run.id,
        observed_by_id=user.id,
        workflow_type=run.task_type,
        usefulness_rating=payload.usefulness_rating,
        review_seconds=payload.review_seconds,
        workflow_completed=payload.workflow_completed,
        evidence_reference=reference,
        note=payload.note.strip(),
        observation_hash=sha256(json.dumps(
            snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        observed_at=observed_at,
    )
    db.add(observation)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This scale-up run already has an outcome observation") from exc
    _audit(
        db, user, "RECORD_AI_SCALE_UP_OUTCOME_OBSERVATION", item,
        {"observation_id": str(observation.id), "scale_up_run_id": str(run.id),
         "observation_hash": observation.observation_hash, "raw_content_stored": False},
        "Content-free Sprint 11H usefulness and operator-effort evidence recorded.",
    )
    db.commit()
    db.refresh(item)
    return assessment_response(db, item)


def _rate_bps(numerator: int, denominator: int) -> int | None:
    return numerator * 10000 // denominator if denominator else None


def _mean_ceiling(values: list[int]) -> int | None:
    return (sum(values) + len(values) - 1) // len(values) if values else None


def _p95(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(ceil(0.95 * len(ordered)) - 1, 0)]


def _relative_increase_bps(first: int | None, second: int | None) -> int | None:
    if first is None or second is None:
        return None
    if second <= first:
        return 0
    if first <= 0:
        return 10000
    return (second - first) * 10000 // first


def _cohort_metrics(runs: list[AIScaleUpRun],
                    observations_by_run: dict[UUID, AIScaleUpOutcomeObservation]) -> dict:
    observations = [observations_by_run[run.id] for run in runs if run.id in observations_by_run]
    reviewed = [
        run for run in runs
        if run.status == "human_reviewed" and run.outcome_hash
        and run.reviewed_by_id is not None and run.reviewed_by_id != run.requested_by_id
    ]
    approved = sum(run.human_review_action == "approve" for run in reviewed)
    edited = sum(run.human_review_action == "edit" for run in reviewed)
    rejected = sum(run.human_review_action == "reject" for run in reviewed)
    actions = approved + edited + rejected
    candidates = sum(run.output_candidate_count or 0 for run in reviewed)
    unsupported = sum(run.unsupported_output_count or 0 for run in reviewed)
    grounded = sum(run.source_grounded_output_count or 0 for run in reviewed)
    grounding_total = sum(run.source_grounding_total_count or 0 for run in reviewed)
    latencies = [run.latency_ms for run in reviewed if run.latency_ms is not None]
    costs = [run.observed_provider_cost_microusd for run in reviewed
             if run.observed_provider_cost_microusd is not None]
    return {
        "run_count": len(runs),
        "human_reviewed_run_count": len(reviewed),
        "human_review_rate_bps": _rate_bps(len(reviewed), len(runs)),
        "observation_count": len(observations),
        "observation_coverage_rate_bps": _rate_bps(len(observations), len(runs)),
        "workflow_completed_count": sum(entry.workflow_completed for entry in observations),
        "workflow_completion_rate_bps": _rate_bps(
            sum(entry.workflow_completed for entry in observations), len(observations)),
        "human_approve_count": approved,
        "human_edit_count": edited,
        "human_reject_count": rejected,
        "human_edit_rate_bps": _rate_bps(edited, actions),
        "human_reject_rate_bps": _rate_bps(rejected, actions),
        "mean_usefulness_bps": _rate_bps(
            sum(entry.usefulness_rating for entry in observations), len(observations) * 5),
        "mean_review_seconds": _mean_ceiling([entry.review_seconds for entry in observations]),
        "output_candidate_count": candidates,
        "unsupported_output_count": unsupported,
        "unsupported_output_rate_bps": _rate_bps(unsupported, candidates),
        "source_grounded_output_count": grounded,
        "source_grounding_total_count": grounding_total,
        "source_grounding_validity_bps": _rate_bps(grounded, grounding_total),
        "p95_latency_ms": _p95(latencies),
        "mean_latency_ms": _mean_ceiling(latencies),
        "total_observed_provider_cost_microusd": sum(costs),
        "mean_observed_provider_cost_microusd": _mean_ceiling(costs),
    }


def _trend_metrics(runs: list[AIScaleUpRun],
                   observations_by_run: dict[UUID, AIScaleUpOutcomeObservation],
                   item: AIScaleUpOutcomeAssessment) -> dict:
    split = (len(runs) + 1) // 2
    first = _cohort_metrics(runs[:split], observations_by_run)
    second = _cohort_metrics(runs[split:], observations_by_run)

    def deterioration(key: str) -> int | None:
        a = first.get(key); b = second.get(key)
        if not isinstance(a, int) or not isinstance(b, int):
            return None
        return max(b - a, 0)

    grounding_drop = None
    first_grounding = first.get("source_grounding_validity_bps")
    second_grounding = second.get("source_grounding_validity_bps")
    if isinstance(first_grounding, int) and isinstance(second_grounding, int):
        grounding_drop = max(first_grounding - second_grounding, 0)
    quality_values = [
        deterioration("human_reject_rate_bps"), deterioration("human_edit_rate_bps"),
        deterioration("unsupported_output_rate_bps"), grounding_drop,
    ]
    quality_regression = max([value for value in quality_values if value is not None], default=None)
    latency_regression = _relative_increase_bps(
        first.get("mean_latency_ms"), second.get("mean_latency_ms"))
    cost_regression = _relative_increase_bps(
        first.get("mean_observed_provider_cost_microusd"),
        second.get("mean_observed_provider_cost_microusd"))
    material = (
        quality_regression is None or latency_regression is None or cost_regression is None
        or quality_regression > item.max_quality_regression_bps
        or latency_regression > item.max_latency_regression_bps
        or cost_regression > item.max_cost_regression_bps
    )
    return {
        "first_half": first,
        "second_half": second,
        "quality_regression_bps": quality_regression,
        "latency_regression_bps": latency_regression,
        "cost_regression_bps": cost_regression,
        "material_regression": material,
    }


def _recovery_metrics(monitors: list[AIScaleUpMonitor], incidents: list[AIScaleUpIncident]) -> dict:
    pauses: list[dict] = []
    recovered = 0
    paused_seconds = 0
    passing_monitors = [m for m in monitors if m.status == "pass"]
    for monitor in [m for m in monitors if m.status == "rollback_required"]:
        next_pass = next((m for m in passing_monitors if _as_utc(m.monitored_at) > _as_utc(monitor.monitored_at)), None)
        ok = next_pass is not None
        if ok:
            recovered += 1
            paused_seconds += max(0, int((_as_utc(next_pass.monitored_at) - _as_utc(monitor.monitored_at)).total_seconds()))
        pauses.append({"source": "monitor", "id": str(monitor.id), "recovered": ok})
    for incident in [i for i in incidents if i.category not in SAFETY_INCIDENT_CATEGORIES]:
        next_pass = None
        if incident.status == "resolved" and incident.resolved_at is not None:
            next_pass = next((m for m in passing_monitors if _as_utc(m.monitored_at) > _as_utc(incident.resolved_at)), None)
        ok = next_pass is not None
        if ok:
            recovered += 1
            paused_seconds += max(0, int((_as_utc(next_pass.monitored_at) - _as_utc(incident.reported_at)).total_seconds()))
        pauses.append({"source": "incident", "id": str(incident.id), "recovered": ok})
    return {
        "pause_count": len(pauses),
        "recovered_pause_count": recovered,
        "recovery_rate_bps": _rate_bps(recovered, len(pauses)) if pauses else 10000,
        "paused_duration_seconds": paused_seconds,
        "all_non_safety_pauses_recovered": all(entry["recovered"] for entry in pauses),
        "evidence": pauses,
    }


def finalize_assessment(db: Session, user: User, item: AIScaleUpOutcomeAssessment,
                        confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit outcome assessment finalization is required")
    if item.status != "collecting":
        raise HTTPException(409, "This outcome assessment is immutable")
    authorization = _authorization(db, user.organization_id, item.scale_up_authorization_id)
    _validate_anchor(db, item, authorization)

    runs = _runs(db, authorization.id)
    monitors = _monitors(db, authorization.id)
    incidents = _incidents(db, authorization.id)
    observations = _observations(db, item.id)
    observations_by_run = {entry.scale_up_run_id: entry for entry in observations}
    cohort = _cohort_metrics(runs, observations_by_run)
    trend = _trend_metrics(runs, observations_by_run, item) if runs else {
        "first_half": {}, "second_half": {}, "quality_regression_bps": None,
        "latency_regression_bps": None, "cost_regression_bps": None,
        "material_regression": True,
    }
    workflow_metrics = {
        workflow: _cohort_metrics([run for run in runs if run.task_type == workflow], observations_by_run)
        for workflow in sorted(REQUIRED_WORKFLOWS)
    }
    unresolved_high_or_critical = [
        incident for incident in incidents
        if incident.status == "open" and incident.severity in BLOCKING_INCIDENT_SEVERITIES
    ]
    safety_incidents = [
        incident for incident in incidents if incident.category in SAFETY_INCIDENT_CATEGORIES
    ]
    recovery = _recovery_metrics(monitors, incidents)
    required_fields = (
        "human_review_action", "output_candidate_count", "unsupported_output_count",
        "source_grounded_output_count", "source_grounding_total_count", "latency_ms",
        "observed_provider_cost_microusd", "outcome_hash", "reviewed_by_id",
    )
    incomplete_run_metrics = [
        str(run.id) for run in runs if any(getattr(run, field) is None for field in required_fields)
    ]

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
            "count": len(monitors),
            "pass_count": sum(m.status == "pass" for m in monitors),
            "rollback_required_count": sum(m.status == "rollback_required" for m in monitors),
            "latest_status": monitors[-1].status if monitors else None,
            "monitor_hashes": [m.monitor_hash for m in monitors],
        },
        "incident_history": {
            "total_count": len(incidents),
            "unresolved_high_or_critical_count": len(unresolved_high_or_critical),
            "safety_boundary_incident_count": len(safety_incidents),
            "by_severity": {
                severity: sum(i.severity == severity for i in incidents)
                for severity in sorted({i.severity for i in incidents})
            },
        },
        "rollback_recovery": recovery,
        "incomplete_run_metric_ids": incomplete_run_metrics,
        "overall_pass": not failures,
        "raw_content_stored": False,
        "rollout_increase_authorized": False,
        "production_wide_authorized": False,
        "restricted_documents_authorized": False,
        "new_document_classes_authorized": False,
    }
    assessed_at = datetime.now(UTC)
    snapshot = {
        "schema": "mcri-ai-scale-up-outcome-assessment-v1",
        "assessment_id": str(item.id),
        "scale_up_authorization_id": str(authorization.id),
        "scale_up_decision_hash": authorization.decision_hash,
        "inherited_outcome_hashes": {
            "assessment": authorization.outcome_assessment_hash,
            "decision": authorization.outcome_decision_hash,
        },
        "bundle": {
            "model": item.model,
            "prompt": item.prompt_bundle_version,
            "schema": item.schema_bundle_version,
            "rollout_percentage": item.rollout_percentage,
        },
        "thresholds": _thresholds(item),
        "metrics": metrics,
        "failure_reasons": failures,
        "run_outcome_hashes": [run.outcome_hash for run in runs],
        "observation_hashes": [entry.observation_hash for entry in observations],
        "monitor_hashes": [entry.monitor_hash for entry in monitors],
        "incident_states": [
            {"id": str(i.id), "severity": i.severity, "category": i.category,
             "status": i.status, "reported_at": _as_utc(i.reported_at).isoformat(),
             "resolved_at": _as_utc(i.resolved_at).isoformat() if i.resolved_at else None}
            for i in incidents
        ],
        "assessed_at": assessed_at.isoformat(),
        "note": note.strip(),
        "recommendation_only": True,
        "production_wide_authorized": False,
        "restricted_documents_authorized": False,
        "rollout_increase_authorized": False,
        "raw_content_stored": False,
    }
    item.metrics = metrics
    item.failure_reasons = failures
    item.assessment_note = note.strip()
    item.assessed_at = assessed_at
    item.finalized_by_id = user.id
    item.assessment_hash = sha256(json.dumps(
        snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    item.status = "review_ready"
    _audit(
        db, user, "FINALIZE_AI_SCALE_UP_OUTCOME_ASSESSMENT", item,
        {"status": item.status, "overall_pass": not failures,
         "failure_reasons": failures, "assessment_hash": item.assessment_hash,
         "production_wide_authorized": False, "rollout_increase_authorized": False},
        "Immutable Sprint 11H controlled-scale-up outcome scorecard finalized. " + note.strip(),
    )
    db.commit()
    db.refresh(item)
    return assessment_response(db, item)


def record_review(db: Session, user: User, item: AIScaleUpOutcomeAssessment,
                  role: str, action: str, evidence_reference: str | None,
                  note: str) -> dict:
    if item.status not in {"review_ready", "decision_ready"}:
        raise HTTPException(409, "Only a finalized assessment can be reviewed")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The assessment requester cannot review the readiness gate")
    reviews = _reviews(db, item.id)
    if any(review.review_role == role for review in reviews):
        raise HTTPException(409, "This review role already has a decision")
    if any(review.reviewer_id == user.id for review in reviews):
        raise HTTPException(409, "Product, Quality, Risk, Operations and Security require different people")
    reference = _reference(evidence_reference) if evidence_reference else None
    if action == "approve" and not reference:
        raise HTTPException(422, "Approval requires bounded evidence")
    review = AIScaleUpOutcomeReview(
        organization_id=user.organization_id, assessment_id=item.id,
        reviewer_id=user.id, review_role=role, action=action,
        evidence_reference=reference, note=note.strip(), reviewed_at=datetime.now(UTC),
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
        db, user, f"{action.upper()}_AI_SCALE_UP_OUTCOME_REVIEW", item,
        {"review_role": role, "action": action,
         "evidence_reference": reference, "status": item.status},
        "Independent Sprint 11H readiness review. " + note.strip(),
    )
    db.commit()
    db.refresh(item)
    return assessment_response(db, item)


def decide_outcome(db: Session, user: User, item: AIScaleUpOutcomeAssessment,
                   outcome: str, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit recommendation-only confirmation is required")
    if item.status != "decision_ready":
        raise HTTPException(409, "Five independent approvals are required")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The requester cannot issue the final outcome")
    if not item.metrics or not item.assessment_hash:
        raise HTTPException(409, "A finalized outcome assessment is required")
    authorization = _authorization(db, user.organization_id, item.scale_up_authorization_id)
    _validate_anchor(db, item, authorization)
    reviews = _reviews(db, item.id)
    if (
        {entry.review_role for entry in reviews} != REVIEW_ROLES
        or len(reviews) != len(REVIEW_ROLES)
        or len({entry.reviewer_id for entry in reviews}) != len(REVIEW_ROLES)
        or any(entry.action != "approve" for entry in reviews)
        or any(entry.reviewer_id == item.requested_by_id for entry in reviews)
    ):
        raise HTTPException(409, "Five independent review roles must remain approved")
    if outcome == "recommend_broader_production_stage" and (
        item.failure_reasons or not item.metrics.get("overall_pass")
    ):
        raise HTTPException(409, "Broader-production recommendation requires zero failed controls")

    snapshot = {
        "schema": "mcri-ai-scale-up-production-readiness-recommendation-v1",
        "assessment_id": str(item.id),
        "scale_up_authorization_id": str(item.scale_up_authorization_id),
        "scale_up_decision_hash": item.scale_up_decision_hash,
        "assessment_hash": item.assessment_hash,
        "inherited_outcome_hashes": {
            "assessment": item.outcome_assessment_hash,
            "decision": item.outcome_decision_hash,
        },
        "bundle": {"model": item.model, "prompt": item.prompt_bundle_version,
                   "schema": item.schema_bundle_version,
                   "rollout_percentage": item.rollout_percentage},
        "reviewers": [
            {"role": entry.review_role, "reviewer_id": str(entry.reviewer_id),
             "evidence_reference": entry.evidence_reference}
            for entry in reviews
        ],
        "outcome": outcome,
        "decision_note": note.strip(),
        "recommendation_only": True,
        "rollout_increase_authorized": False,
        "production_wide_authorized": False,
        "restricted_documents_authorized": False,
        "new_document_classes_authorized": False,
        "autonomous_claim_decisions_authorized": False,
        "authoritative_facts_auto_updated": False,
    }
    item.outcome = outcome
    item.decision_note = note.strip()
    item.decided_at = datetime.now(UTC)
    item.finalized_by_id = user.id
    item.decision_hash = sha256(json.dumps(
        snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if outcome == "recommend_broader_production_stage":
        item.status = "recommended"
    elif outcome == "extend_controlled_scale_up":
        item.status = "extended"
    else:
        item.status = "stopped"
    _audit(
        db, user, "DECIDE_AI_SCALE_UP_PRODUCTION_READINESS_RECOMMENDATION", item,
        {"status": item.status, "outcome": outcome,
         "decision_hash": item.decision_hash,
         "production_wide_authorized": False, "rollout_increase_authorized": False},
        "Recommendation-only Sprint 11H decision; broader Production remains separately governed. "
        + note.strip(),
    )
    db.commit()
    db.refresh(item)
    return assessment_response(db, item)
