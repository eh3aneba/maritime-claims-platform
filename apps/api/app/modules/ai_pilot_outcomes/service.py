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

from app.modules.ai_pilot_outcomes.models import (
    AIPilotOutcomeAssessment,
    AIPilotOutcomeReview,
    AIPilotWorkflowObservation,
)
from app.modules.ai_pilot_outcomes.schemas import (
    AIPilotOutcomeCreate,
    AIPilotWorkflowObservationCreate,
)
from app.modules.ai_private_pilot.models import (
    AIPrivatePilotAuthorization,
    AIPrivatePilotIncident,
    AIPrivatePilotRun,
)
from app.modules.audit.service import write_audit_log
from app.modules.users.models import User

BOUNDED_REFERENCE = re.compile(
    r"^(artifact|runbook|ticket|monitor)://[A-Za-z0-9._:/-]{3,450}$")
REVIEW_ROLES = {"product", "quality", "risk"}
TERMINAL_RETRY_STATUSES = {"failed", "review_rejected", "extended", "stopped"}
SAFETY_INCIDENT_CATEGORIES = {"privacy", "security", "cross_tenant"}


def _reference(value: str) -> str:
    reference = value.strip()
    if not BOUNDED_REFERENCE.fullmatch(reference):
        raise HTTPException(422, "Outcome evidence must use a bounded allowlisted reference")
    return reference


def _audit(db: Session, user: User, action: str, item: AIPilotOutcomeAssessment,
           values: dict, details: str) -> None:
    write_audit_log(
        db, organization_id=user.organization_id, user_id=user.id, action=action,
        entity_type="ai_pilot_outcome_assessment", entity_id=item.id,
        new_values=values, details=details,
    )


def _pilot(db: Session, organization_id: UUID,
           pilot_id: UUID) -> AIPrivatePilotAuthorization:
    item = db.scalar(select(AIPrivatePilotAuthorization).where(
        AIPrivatePilotAuthorization.id == pilot_id,
        AIPrivatePilotAuthorization.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Private AI pilot not found")
    return item


def _runs(db: Session, pilot_id: UUID) -> list[AIPrivatePilotRun]:
    return list(db.scalars(select(AIPrivatePilotRun).where(
        AIPrivatePilotRun.pilot_id == pilot_id,
    ).order_by(AIPrivatePilotRun.queued_at.asc())))


def _incidents(db: Session, pilot_id: UUID) -> list[AIPrivatePilotIncident]:
    return list(db.scalars(select(AIPrivatePilotIncident).where(
        AIPrivatePilotIncident.pilot_id == pilot_id,
    ).order_by(AIPrivatePilotIncident.reported_at.asc())))


def _observations(db: Session, assessment_id: UUID) -> list[AIPilotWorkflowObservation]:
    return list(db.scalars(select(AIPilotWorkflowObservation).where(
        AIPilotWorkflowObservation.assessment_id == assessment_id,
    ).order_by(AIPilotWorkflowObservation.observed_at.asc())))


def _reviews(db: Session, assessment_id: UUID) -> list[AIPilotOutcomeReview]:
    return list(db.scalars(select(AIPilotOutcomeReview).where(
        AIPilotOutcomeReview.assessment_id == assessment_id,
    ).order_by(AIPilotOutcomeReview.review_role.asc())))


def _thresholds(item: AIPilotOutcomeAssessment) -> dict:
    return {
        "min_run_count": item.min_run_count,
        "min_chief_engineer_report_run_count": item.min_ce_run_count,
        "min_engine_log_run_count": item.min_engine_run_count,
        "required_human_review_rate_bps": 10000,
        "required_workflow_completion_rate_bps": 10000,
        "required_boundary_pass_rate_bps": 10000,
        "max_reject_rate_bps": item.max_reject_rate_bps,
        "max_edit_rate_bps": item.max_edit_rate_bps,
        "min_mean_usefulness_bps": item.min_mean_usefulness_bps,
        "max_mean_review_seconds": item.max_mean_review_seconds,
        "max_p95_latency_ms": item.max_p95_latency_ms,
        "max_mean_observed_provider_cost_microusd": item.max_mean_cost_microusd,
        "max_unresolved_incident_count": 0,
        "max_critical_incident_count": 0,
        "max_safety_boundary_incident_count": 0,
    }


def assessment_response(db: Session, item: AIPilotOutcomeAssessment) -> dict:
    observations = _observations(db, item.id)
    reviews = _reviews(db, item.id)
    reviews_complete = bool(
        {review.review_role for review in reviews} == REVIEW_ROLES
        and all(review.action == "approve" for review in reviews)
        and len({review.reviewer_id for review in reviews}) == len(REVIEW_ROLES)
        and all(review.reviewer_id != item.requested_by_id for review in reviews)
    )
    return {
        "id": item.id, "pilot_id": item.pilot_id,
        "requested_by_id": item.requested_by_id,
        "finalized_by_id": item.finalized_by_id,
        "attempt_number": item.attempt_number,
        "assessment_key": item.assessment_key,
        "assessment_profile": item.assessment_profile,
        "thresholds": _thresholds(item), "status": item.status,
        "outcome": item.outcome, "metrics": item.metrics,
        "failure_reasons": item.failure_reasons or [],
        "assessment_note": item.assessment_note,
        "assessment_hash": item.assessment_hash,
        "assessed_at": item.assessed_at,
        "decision_note": item.decision_note,
        "decision_hash": item.decision_hash,
        "decided_at": item.decided_at,
        "observations": observations, "reviews": reviews,
        "summary": {
            "observation_count": len(observations),
            "thresholds_passed": bool(item.metrics and item.metrics.get("overall_pass")),
            "independent_reviews_complete": reviews_complete,
            "exit_recommendation_recorded": item.status in {"recommended", "extended", "stopped"},
            "limited_production_evaluation_recommended": (
                item.status == "recommended"
                and item.outcome == "recommend_limited_production_evaluation"),
            "production_authorized": False,
            "production_wide_authorized": False,
            "restricted_documents_authorized": False,
            "autonomous_claim_decisions_authorized": False,
            "authoritative_facts_auto_updated": False,
            "raw_content_stored": False,
            "human_review_required": True,
        },
        "created_at": item.created_at,
    }


def list_assessments(db: Session, organization_id: UUID) -> list[dict]:
    items = list(db.scalars(select(AIPilotOutcomeAssessment).where(
        AIPilotOutcomeAssessment.organization_id == organization_id,
    ).order_by(AIPilotOutcomeAssessment.created_at.desc()).limit(25)))
    return [assessment_response(db, item) for item in items]


def get_assessment(db: Session, organization_id: UUID,
                   assessment_id: UUID) -> AIPilotOutcomeAssessment:
    item = db.scalar(select(AIPilotOutcomeAssessment).where(
        AIPilotOutcomeAssessment.id == assessment_id,
        AIPilotOutcomeAssessment.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Private-pilot outcome assessment not found")
    return item


def create_assessment(db: Session, user: User, payload: AIPilotOutcomeCreate) -> dict:
    if not payload.confirm_content_free_assessment:
        raise HTTPException(422, "Explicit content-free outcome assessment confirmation is required")
    pilot = _pilot(db, user.organization_id, payload.pilot_id)
    if pilot.status != "completed":
        raise HTTPException(409, "A completed Sprint 11C private pilot is required")
    attempts = list(db.scalars(select(AIPilotOutcomeAssessment).where(
        AIPilotOutcomeAssessment.pilot_id == pilot.id,
    ).order_by(AIPilotOutcomeAssessment.attempt_number.asc())))
    if attempts and attempts[-1].status not in TERMINAL_RETRY_STATUSES:
        raise HTTPException(409, "The current private-pilot outcome assessment is still active")
    item = AIPilotOutcomeAssessment(
        organization_id=user.organization_id, pilot_id=pilot.id,
        requested_by_id=user.id, attempt_number=len(attempts) + 1,
        assessment_key=payload.assessment_key.strip(),
        assessment_profile="private_pilot_exit_v1", status="collecting",
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This outcome assessment key or attempt already exists") from exc
    _audit(db, user, "CREATE_AI_PILOT_OUTCOME_ASSESSMENT", item,
           {"pilot_id": str(pilot.id), "assessment_profile": item.assessment_profile,
            "thresholds": _thresholds(item), "production_authorized": False,
            "raw_content_stored": False},
           "Content-free Sprint 11D outcome assessment created; no AI authorization granted.")
    db.commit(); db.refresh(item)
    return assessment_response(db, item)


def record_observation(db: Session, user: User, item: AIPilotOutcomeAssessment,
                       payload: AIPilotWorkflowObservationCreate) -> dict:
    if item.status != "collecting":
        raise HTTPException(409, "This outcome assessment is immutable")
    if not payload.confirm_content_free_observation:
        raise HTTPException(422, "Explicit content-free workflow observation confirmation is required")
    run = db.scalar(select(AIPrivatePilotRun).where(
        AIPrivatePilotRun.id == payload.pilot_run_id,
        AIPrivatePilotRun.pilot_id == item.pilot_id,
        AIPrivatePilotRun.organization_id == user.organization_id,
    ))
    if run is None:
        raise HTTPException(404, "Reviewed private-pilot run not found")
    if run.status != "human_reviewed" or run.outcome_hash is None:
        raise HTTPException(409, "The private-pilot run requires an immutable human-review outcome")
    if run.task_type not in {"chief_engineer_report", "engine_log"}:
        raise HTTPException(409, "The run workflow is outside the Sprint 11C allowlist")
    reference = _reference(payload.evidence_reference)
    observed_at = datetime.now(UTC)
    snapshot = {
        "schema": "mcri-ai-pilot-workflow-observation-v1",
        "assessment_id": str(item.id), "pilot_run_id": str(run.id),
        "run_outcome_hash": run.outcome_hash, "workflow_type": run.task_type,
        "usefulness_rating": payload.usefulness_rating,
        "review_seconds": payload.review_seconds,
        "workflow_completed": payload.workflow_completed,
        "boundary_control_passed": payload.boundary_control_passed,
        "evidence_reference": reference, "note": payload.note.strip(),
        "observed_at": observed_at.isoformat(), "raw_content_stored": False,
    }
    observation = AIPilotWorkflowObservation(
        organization_id=user.organization_id, assessment_id=item.id,
        pilot_run_id=run.id, observed_by_id=user.id, workflow_type=run.task_type,
        usefulness_rating=payload.usefulness_rating,
        review_seconds=payload.review_seconds,
        workflow_completed=payload.workflow_completed,
        boundary_control_passed=payload.boundary_control_passed,
        evidence_reference=reference, note=payload.note.strip(),
        observation_hash=sha256(json.dumps(snapshot, sort_keys=True,
                                             separators=(",", ":")).encode()).hexdigest(),
        observed_at=observed_at,
    )
    db.add(observation)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This run already has an observation in the assessment") from exc
    _audit(db, user, "RECORD_AI_PILOT_WORKFLOW_OBSERVATION", item,
           {"observation_id": str(observation.id), "pilot_run_id": str(run.id),
            "workflow_type": run.task_type,
            "observation_hash": observation.observation_hash,
            "raw_content_stored": False},
           "Content-free per-workflow usability evidence recorded. " + payload.note.strip())
    db.commit(); db.refresh(item)
    return assessment_response(db, item)


def _rate_bps(numerator: int, denominator: int) -> int | None:
    return numerator * 10000 // denominator if denominator else None


def _workflow_metrics(workflow: str, runs: list[AIPrivatePilotRun],
                      observations_by_run: dict[UUID, AIPilotWorkflowObservation]) -> dict:
    selected = [run for run in runs if run.task_type == workflow]
    observations = [observations_by_run[run.id] for run in selected
                    if run.id in observations_by_run]
    count = len(selected)
    latencies = sorted(run.latency_ms for run in selected if run.latency_ms is not None)
    costs = [run.observed_provider_cost_microusd for run in selected
             if run.observed_provider_cost_microusd is not None]
    review_seconds = [entry.review_seconds for entry in observations]
    return {
        "run_count": count, "observation_count": len(observations),
        "approve_count": sum(run.human_review_action == "approve" for run in selected),
        "edit_count": sum(run.human_review_action == "edit" for run in selected),
        "reject_count": sum(run.human_review_action == "reject" for run in selected),
        "mean_usefulness_bps": _rate_bps(
            sum(entry.usefulness_rating for entry in observations), len(observations) * 5),
        "mean_review_seconds": (
            (sum(review_seconds) + len(review_seconds) - 1) // len(review_seconds)
            if review_seconds else None),
        "p95_latency_ms": (
            latencies[max(ceil(0.95 * len(latencies)) - 1, 0)] if latencies else None),
        "mean_observed_provider_cost_microusd": (
            (sum(costs) + len(costs) - 1) // len(costs) if costs else None),
    }


def finalize_assessment(db: Session, user: User, item: AIPilotOutcomeAssessment,
                        confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit outcome assessment finalization is required")
    if item.status != "collecting":
        raise HTTPException(409, "This outcome assessment is immutable")
    pilot = _pilot(db, user.organization_id, item.pilot_id)
    if pilot.status != "completed":
        raise HTTPException(409, "The anchored private pilot is no longer completed")
    runs = _runs(db, pilot.id)
    incidents = _incidents(db, pilot.id)
    observations = _observations(db, item.id)
    observations_by_run = {entry.pilot_run_id: entry for entry in observations}
    count = len(runs)
    reviewed_count = sum(run.status == "human_reviewed" for run in runs)
    ce_count = sum(run.task_type == "chief_engineer_report" for run in runs)
    engine_count = sum(run.task_type == "engine_log" for run in runs)
    approve_count = sum(run.human_review_action == "approve" for run in runs)
    edit_count = sum(run.human_review_action == "edit" for run in runs)
    reject_count = sum(run.human_review_action == "reject" for run in runs)
    reviewed_action_count = approve_count + edit_count + reject_count
    reject_rate = _rate_bps(reject_count, reviewed_action_count)
    edit_rate = _rate_bps(edit_count, reviewed_action_count)
    usefulness = _rate_bps(
        sum(entry.usefulness_rating for entry in observations), len(observations) * 5)
    mean_review_seconds = (
        (sum(entry.review_seconds for entry in observations) + len(observations) - 1)
        // len(observations) if observations else None)
    latencies = sorted(run.latency_ms for run in runs if run.latency_ms is not None)
    p95_latency = latencies[max(ceil(0.95 * len(latencies)) - 1, 0)] if latencies else None
    costs = [run.observed_provider_cost_microusd for run in runs
             if run.observed_provider_cost_microusd is not None]
    mean_cost = ((sum(costs) + len(costs) - 1) // len(costs)) if costs else None
    midpoint = max(ceil(count / 2), 1)
    first_costs = [run.observed_provider_cost_microusd for run in runs[:midpoint]
                   if run.observed_provider_cost_microusd is not None]
    second_costs = [run.observed_provider_cost_microusd for run in runs[midpoint:]
                    if run.observed_provider_cost_microusd is not None]
    first_mean_cost = ((sum(first_costs) + len(first_costs) - 1) // len(first_costs)
                       if first_costs else None)
    second_mean_cost = ((sum(second_costs) + len(second_costs) - 1) // len(second_costs)
                        if second_costs else None)
    unresolved_incidents = sum(incident.status != "resolved" for incident in incidents)
    critical_incidents = sum(incident.severity == "critical" for incident in incidents)
    safety_incidents = sum(incident.category in SAFETY_INCIDENT_CATEGORIES
                           for incident in incidents)
    completed_observations = sum(entry.workflow_completed for entry in observations)
    passed_boundaries = sum(entry.boundary_control_passed for entry in observations)
    failures: list[str] = []
    if count < item.min_run_count: failures.append("minimum_run_count")
    if ce_count < item.min_ce_run_count: failures.append("chief_engineer_report_coverage")
    if engine_count < item.min_engine_run_count: failures.append("engine_log_coverage")
    if reviewed_count != count: failures.append("human_review_coverage")
    if len(observations) != count: failures.append("workflow_observation_coverage")
    if completed_observations != len(observations): failures.append("workflow_completion")
    if passed_boundaries != len(observations): failures.append("safety_boundary_control")
    if reject_rate is None or reject_rate > item.max_reject_rate_bps:
        failures.append("human_reject_rate")
    if edit_rate is None or edit_rate > item.max_edit_rate_bps:
        failures.append("human_edit_rate")
    if usefulness is None or usefulness < item.min_mean_usefulness_bps:
        failures.append("workflow_usefulness")
    if mean_review_seconds is None or mean_review_seconds > item.max_mean_review_seconds:
        failures.append("mean_human_review_time")
    if p95_latency is None or p95_latency > item.max_p95_latency_ms:
        failures.append("p95_latency")
    if mean_cost is None or mean_cost > item.max_mean_cost_microusd:
        failures.append("mean_observed_provider_cost")
    if unresolved_incidents: failures.append("unresolved_incident")
    if critical_incidents: failures.append("critical_incident")
    if safety_incidents: failures.append("safety_boundary_incident")
    failures = sorted(set(failures))
    metrics = {
        "overall_pass": not failures, "run_count": count,
        "human_reviewed_run_count": reviewed_count,
        "human_review_rate_bps": _rate_bps(reviewed_count, count),
        "workflow_observation_count": len(observations),
        "workflow_completion_rate_bps": _rate_bps(completed_observations, len(observations)),
        "boundary_pass_rate_bps": _rate_bps(passed_boundaries, len(observations)),
        "chief_engineer_report_run_count": ce_count,
        "engine_log_run_count": engine_count,
        "human_approve_count": approve_count, "human_edit_count": edit_count,
        "human_reject_count": reject_count, "human_edit_rate_bps": edit_rate,
        "human_reject_rate_bps": reject_rate,
        "mean_usefulness_bps": usefulness,
        "mean_review_seconds": mean_review_seconds,
        "p95_latency_ms": p95_latency,
        "total_observed_provider_cost_microusd": sum(costs),
        "mean_observed_provider_cost_microusd": mean_cost,
        "cost_trend": {
            "first_half_mean_microusd": first_mean_cost,
            "second_half_mean_microusd": second_mean_cost,
            "delta_microusd": (
                second_mean_cost - first_mean_cost
                if first_mean_cost is not None and second_mean_cost is not None else None),
        },
        "incident_trend": {
            "total_count": len(incidents), "unresolved_count": unresolved_incidents,
            "critical_count": critical_incidents,
            "safety_boundary_count": safety_incidents,
            "by_severity": {severity: sum(incident.severity == severity for incident in incidents)
                            for severity in ("low", "medium", "high", "critical")},
        },
        "workflow_scorecards": {
            workflow: _workflow_metrics(workflow, runs, observations_by_run)
            for workflow in ("chief_engineer_report", "engine_log")
        },
        "raw_content_stored": False, "calculated_provider_billing": False,
        "production_authorized": False,
    }
    snapshot = {
        "schema": "mcri-ai-private-pilot-outcome-assessment-v1",
        "assessment_id": str(item.id), "pilot_id": str(pilot.id),
        "attempt_number": item.attempt_number,
        "assessment_profile": item.assessment_profile,
        "thresholds": _thresholds(item), "metrics": metrics,
        "failure_reasons": failures,
        "run_outcome_hashes": [run.outcome_hash for run in runs],
        "observation_hashes": [entry.observation_hash for entry in observations],
        "assessment_note": note.strip(), "raw_content_stored": False,
        "production_authorized": False, "restricted_documents_authorized": False,
    }
    item.metrics = metrics; item.failure_reasons = failures
    item.assessment_note = note.strip(); item.assessed_at = datetime.now(UTC)
    item.assessment_hash = sha256(json.dumps(snapshot, sort_keys=True,
                                              separators=(",", ":")).encode()).hexdigest()
    item.status = "failed" if failures else "review_ready"
    item.outcome = "thresholds_failed" if failures else "thresholds_passed"
    _audit(db, user, "FINALIZE_AI_PILOT_OUTCOME_ASSESSMENT", item,
           {"status": item.status, "assessment_hash": item.assessment_hash,
            "metrics": metrics, "failure_reasons": failures,
            "production_authorized": False},
           "Deterministic private-pilot exit scorecard finalized. " + note.strip())
    db.commit(); db.refresh(item)
    return assessment_response(db, item)


def record_review(db: Session, user: User, item: AIPilotOutcomeAssessment,
                  review_role: str, action: str, evidence_reference: str | None,
                  note: str) -> dict:
    if item.status not in {"review_ready", "decision_ready"}:
        raise HTTPException(409, "Only a passing outcome assessment can be reviewed")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The assessment requester cannot review this assessment")
    reviews = _reviews(db, item.id)
    if any(review.review_role == review_role for review in reviews):
        raise HTTPException(409, "This outcome review role already has a decision")
    if any(review.reviewer_id == user.id for review in reviews):
        raise HTTPException(409, "Product, Quality and Risk reviews require different people")
    reference = _reference(evidence_reference) if evidence_reference else None
    if action == "approve" and not reference:
        raise HTTPException(422, "Approval requires a bounded review reference")
    review = AIPilotOutcomeReview(
        organization_id=user.organization_id, assessment_id=item.id,
        reviewer_id=user.id, review_role=review_role, action=action,
        evidence_reference=reference, note=note.strip(), reviewed_at=datetime.now(UTC),
    )
    db.add(review); db.flush()
    if action == "reject":
        item.status = "review_rejected"; item.outcome = "review_rejected"
        item.failure_reasons = sorted(set((item.failure_reasons or [])
                                          + [f"{review_role}_review"]))
    else:
        current = _reviews(db, item.id)
        item.status = "decision_ready" if (
            {entry.review_role for entry in current} == REVIEW_ROLES
            and all(entry.action == "approve" for entry in current)
            and len({entry.reviewer_id for entry in current}) == len(REVIEW_ROLES)
        ) else "review_ready"
    _audit(db, user, f"{action.upper()}_AI_PILOT_OUTCOME_REVIEW", item,
           {"review_role": review_role, "action": action,
            "evidence_reference": reference, "status": item.status},
           "Independent Sprint 11D exit review. " + note.strip())
    db.commit(); db.refresh(item)
    return assessment_response(db, item)


def decide_outcome(db: Session, user: User, item: AIPilotOutcomeAssessment,
                   outcome: str, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit recommendation-only confirmation is required")
    if item.status != "decision_ready":
        raise HTTPException(409, "Passing thresholds and three independent reviews are required")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The assessment requester cannot issue the exit decision")
    pilot = _pilot(db, user.organization_id, item.pilot_id)
    if pilot.status != "completed":
        raise HTTPException(409, "The anchored private pilot is no longer completed")
    reviews = _reviews(db, item.id)
    if (len(reviews) != len(REVIEW_ROLES)
            or {review.review_role for review in reviews} != REVIEW_ROLES
            or len({review.reviewer_id for review in reviews}) != len(REVIEW_ROLES)
            or any(review.action != "approve" for review in reviews)):
        raise HTTPException(409, "Product, Quality and Risk approvals must be independent")
    if (outcome == "recommend_limited_production_evaluation"
            and not (item.metrics or {}).get("overall_pass")):
        raise HTTPException(409, "A positive recommendation requires every fixed threshold")
    status_by_outcome = {
        "recommend_limited_production_evaluation": "recommended",
        "extend_private_pilot": "extended",
        "stop_ai_progression": "stopped",
    }
    snapshot = {
        "schema": "mcri-ai-private-pilot-exit-recommendation-v1",
        "assessment_id": str(item.id), "pilot_id": str(pilot.id),
        "assessment_hash": item.assessment_hash,
        "reviewers": [{"role": review.review_role,
                       "reviewer_id": str(review.reviewer_id),
                       "evidence_reference": review.evidence_reference}
                      for review in reviews],
        "outcome": outcome, "decision_note": note.strip(),
        "recommendation_only": True, "production_authorized": False,
        "production_wide_authorized": False,
        "restricted_documents_authorized": False,
        "autonomous_claim_decisions_authorized": False,
        "authoritative_facts_auto_updated": False,
    }
    item.status = status_by_outcome[outcome]; item.outcome = outcome
    item.finalized_by_id = user.id; item.decision_note = note.strip()
    item.decided_at = datetime.now(UTC)
    item.decision_hash = sha256(json.dumps(snapshot, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
    _audit(db, user, "DECIDE_AI_PILOT_EXIT_RECOMMENDATION", item,
           {"status": item.status, "outcome": outcome,
            "decision_hash": item.decision_hash,
            "recommendation_only": True, "production_authorized": False},
           "Sprint 11D recommendation only; a separate later authorization remains mandatory. "
           + note.strip())
    db.commit(); db.refresh(item)
    return assessment_response(db, item)
