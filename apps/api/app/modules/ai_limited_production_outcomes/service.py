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

from app.modules.ai_limited_production.models import (
    AILimitedProductionAuthorization,
    AILimitedProductionDocumentEligibility,
    AILimitedProductionIncident,
    AILimitedProductionRun,
)
from app.modules.ai_limited_production_outcomes.models import (
    AILimitedProductionOutcomeAssessment,
    AILimitedProductionOutcomeObservation,
    AILimitedProductionOutcomeReview,
)
from app.modules.ai_limited_production_outcomes.schemas import (
    AILimitedProductionOutcomeCreate,
    AILimitedProductionOutcomeObservationCreate,
)
from app.modules.audit.service import write_audit_log
from app.modules.users.models import User

REFERENCE = re.compile(r"^(artifact|runbook|ticket|monitor)://[A-Za-z0-9._:/-]{3,450}$")
REVIEW_ROLES = {"product", "quality", "risk", "operations"}
RETRY_STATUSES = {"failed", "review_rejected", "extended", "stopped"}
SAFETY_INCIDENT_CATEGORIES = {"privacy", "security", "cross_tenant"}
BLOCKING_INCIDENT_SEVERITIES = {"critical", "high"}


def _reference(value: str) -> str:
    reference = value.strip()
    if not REFERENCE.fullmatch(reference):
        raise HTTPException(422, "Outcome evidence must use a bounded allowlisted reference")
    return reference


def _audit(db: Session, user: User, action: str,
           item: AILimitedProductionOutcomeAssessment,
           values: dict, details: str) -> None:
    write_audit_log(
        db, organization_id=user.organization_id, user_id=user.id, action=action,
        entity_type="ai_limited_production_outcome_assessment", entity_id=item.id,
        new_values=values, details=details,
    )


def _authorization(db: Session, organization_id: UUID,
                   authorization_id: UUID) -> AILimitedProductionAuthorization:
    item = db.scalar(select(AILimitedProductionAuthorization).where(
        AILimitedProductionAuthorization.id == authorization_id,
        AILimitedProductionAuthorization.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Limited-production AI authorization not found")
    return item


def _runs(db: Session, authorization_id: UUID) -> list[AILimitedProductionRun]:
    return list(db.scalars(select(AILimitedProductionRun).where(
        AILimitedProductionRun.authorization_id == authorization_id,
    ).order_by(AILimitedProductionRun.queued_at.asc(), AILimitedProductionRun.id.asc())))


def _documents(db: Session,
               authorization_id: UUID) -> list[AILimitedProductionDocumentEligibility]:
    return list(db.scalars(select(AILimitedProductionDocumentEligibility).where(
        AILimitedProductionDocumentEligibility.authorization_id == authorization_id,
    ).order_by(AILimitedProductionDocumentEligibility.created_at.asc())))


def _incidents(db: Session, authorization_id: UUID) -> list[AILimitedProductionIncident]:
    return list(db.scalars(select(AILimitedProductionIncident).where(
        AILimitedProductionIncident.authorization_id == authorization_id,
    ).order_by(AILimitedProductionIncident.reported_at.asc())))


def _observations(
    db: Session, assessment_id: UUID
) -> list[AILimitedProductionOutcomeObservation]:
    return list(db.scalars(select(AILimitedProductionOutcomeObservation).where(
        AILimitedProductionOutcomeObservation.assessment_id == assessment_id,
    ).order_by(AILimitedProductionOutcomeObservation.observed_at.asc())))


def _reviews(db: Session, assessment_id: UUID) -> list[AILimitedProductionOutcomeReview]:
    return list(db.scalars(select(AILimitedProductionOutcomeReview).where(
        AILimitedProductionOutcomeReview.assessment_id == assessment_id,
    ).order_by(AILimitedProductionOutcomeReview.review_role.asc())))


def _thresholds(item: AILimitedProductionOutcomeAssessment) -> dict:
    return {
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
    }


def assessment_response(db: Session, item: AILimitedProductionOutcomeAssessment) -> dict:
    observations = _observations(db, item.id)
    reviews = _reviews(db, item.id)
    reviews_complete = bool(
        {review.review_role for review in reviews} == REVIEW_ROLES
        and all(review.action == "approve" for review in reviews)
        and len({review.reviewer_id for review in reviews}) == len(REVIEW_ROLES)
        and all(review.reviewer_id != item.requested_by_id for review in reviews)
    )
    return {
        "id": item.id,
        "authorization_id": item.authorization_id,
        "requested_by_id": item.requested_by_id,
        "finalized_by_id": item.finalized_by_id,
        "attempt_number": item.attempt_number,
        "assessment_key": item.assessment_key,
        "assessment_profile": item.assessment_profile,
        "authorization_decision_hash": item.authorization_decision_hash,
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
            "graduation_recommendation_recorded": item.status in {
                "recommended", "extended", "stopped"
            },
            "graduation_stage_recommended": (
                item.status == "recommended"
                and item.outcome == "recommend_graduation_stage"
            ),
            "production_wide_authorized": False,
            "restricted_documents_authorized": False,
            "rollout_increase_authorized": False,
            "new_document_classes_authorized": False,
            "autonomous_claim_decisions_authorized": False,
            "authoritative_facts_auto_updated": False,
            "human_review_required": True,
            "raw_content_stored": False,
        },
        "created_at": item.created_at,
    }


def list_assessments(db: Session, organization_id: UUID) -> list[dict]:
    items = list(db.scalars(select(AILimitedProductionOutcomeAssessment).where(
        AILimitedProductionOutcomeAssessment.organization_id == organization_id,
    ).order_by(AILimitedProductionOutcomeAssessment.created_at.desc()).limit(25)))
    return [assessment_response(db, item) for item in items]


def get_assessment(
    db: Session, organization_id: UUID, assessment_id: UUID
) -> AILimitedProductionOutcomeAssessment:
    item = db.scalar(select(AILimitedProductionOutcomeAssessment).where(
        AILimitedProductionOutcomeAssessment.id == assessment_id,
        AILimitedProductionOutcomeAssessment.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Limited-production outcome assessment not found")
    return item


def create_assessment(
    db: Session, user: User, payload: AILimitedProductionOutcomeCreate
) -> dict:
    if not payload.confirm_content_free_assessment:
        raise HTTPException(422, "Explicit content-free outcome assessment confirmation is required")
    authorization = _authorization(db, user.organization_id, payload.authorization_id)
    if authorization.status != "completed":
        raise HTTPException(409, "A completed Sprint 11E limited-production evaluation is required")
    if not authorization.decision_hash:
        raise HTTPException(409, "The completed authorization requires an immutable decision hash")
    attempts = list(db.scalars(select(AILimitedProductionOutcomeAssessment).where(
        AILimitedProductionOutcomeAssessment.authorization_id == authorization.id,
    ).order_by(AILimitedProductionOutcomeAssessment.attempt_number.asc())))
    if attempts and attempts[-1].status not in RETRY_STATUSES:
        raise HTTPException(409, "The current limited-production outcome assessment is still active")
    item = AILimitedProductionOutcomeAssessment(
        organization_id=user.organization_id,
        authorization_id=authorization.id,
        requested_by_id=user.id,
        attempt_number=len(attempts) + 1,
        assessment_key=payload.assessment_key.strip(),
        assessment_profile="limited_production_graduation_v1",
        authorization_decision_hash=authorization.decision_hash,
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
        raise HTTPException(409, "This outcome assessment key or attempt already exists") from exc
    _audit(
        db, user, "CREATE_AI_LIMITED_PRODUCTION_OUTCOME_ASSESSMENT", item,
        {
            "authorization_id": str(authorization.id),
            "assessment_profile": item.assessment_profile,
            "authorization_decision_hash": authorization.decision_hash,
            "bundle": {
                "model": item.model,
                "prompt": item.prompt_bundle_version,
                "schema": item.schema_bundle_version,
            },
            "rollout_percentage": item.rollout_percentage,
            "thresholds": _thresholds(item),
            "production_wide_authorized": False,
            "restricted_documents_authorized": False,
            "raw_content_stored": False,
        },
        "Content-free Sprint 11F outcome assessment created; no wider authorization granted.",
    )
    db.commit()
    db.refresh(item)
    return assessment_response(db, item)


def record_observation(
    db: Session,
    user: User,
    item: AILimitedProductionOutcomeAssessment,
    payload: AILimitedProductionOutcomeObservationCreate,
) -> dict:
    if item.status != "collecting":
        raise HTTPException(409, "This outcome assessment is immutable")
    if not payload.confirm_content_free_observation:
        raise HTTPException(422, "Explicit content-free observation confirmation is required")
    if payload.source_grounded_output_count > payload.source_grounding_total_count:
        raise HTTPException(422, "Grounded output count cannot exceed the grounding total")
    run = db.scalar(select(AILimitedProductionRun).where(
        AILimitedProductionRun.id == payload.limited_run_id,
        AILimitedProductionRun.authorization_id == item.authorization_id,
        AILimitedProductionRun.organization_id == user.organization_id,
    ))
    if run is None:
        raise HTTPException(404, "Reviewed limited-production run not found")
    if run.status != "human_reviewed" or run.outcome_hash is None:
        raise HTTPException(409, "The limited-production run requires immutable human review")
    if run.output_candidate_count is None:
        raise HTTPException(409, "The limited-production run lacks candidate-count evidence")
    if payload.unsupported_output_count > run.output_candidate_count:
        raise HTTPException(422, "Unsupported outputs cannot exceed the recorded candidate count")
    if payload.source_grounding_total_count > run.output_candidate_count:
        raise HTTPException(422, "Grounding denominator cannot exceed the recorded candidate count")
    reference = _reference(payload.evidence_reference)
    observed_at = datetime.now(UTC)
    snapshot = {
        "schema": "mcri-ai-limited-production-outcome-observation-v1",
        "assessment_id": str(item.id),
        "limited_run_id": str(run.id),
        "run_outcome_hash": run.outcome_hash,
        "workflow_type": run.task_type,
        "usefulness_rating": payload.usefulness_rating,
        "review_seconds": payload.review_seconds,
        "unsupported_output_count": payload.unsupported_output_count,
        "source_grounded_output_count": payload.source_grounded_output_count,
        "source_grounding_total_count": payload.source_grounding_total_count,
        "workflow_completed": payload.workflow_completed,
        "evidence_reference": reference,
        "note": payload.note.strip(),
        "observed_at": observed_at.isoformat(),
        "raw_content_stored": False,
    }
    observation = AILimitedProductionOutcomeObservation(
        organization_id=user.organization_id,
        assessment_id=item.id,
        limited_run_id=run.id,
        observed_by_id=user.id,
        workflow_type=run.task_type,
        usefulness_rating=payload.usefulness_rating,
        review_seconds=payload.review_seconds,
        unsupported_output_count=payload.unsupported_output_count,
        source_grounded_output_count=payload.source_grounded_output_count,
        source_grounding_total_count=payload.source_grounding_total_count,
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
        raise HTTPException(
            409, "This limited-production run already has an observation in the assessment"
        ) from exc
    _audit(
        db, user, "RECORD_AI_LIMITED_PRODUCTION_OUTCOME_OBSERVATION", item,
        {
            "observation_id": str(observation.id),
            "limited_run_id": str(run.id),
            "workflow_type": run.task_type,
            "observation_hash": observation.observation_hash,
            "raw_content_stored": False,
        },
        "Content-free limited-production usefulness and grounding evidence recorded.",
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


def _cohort_metrics(
    runs: list[AILimitedProductionRun],
    observations_by_run: dict[UUID, AILimitedProductionOutcomeObservation],
) -> dict:
    observations = [observations_by_run[run.id] for run in runs if run.id in observations_by_run]
    reviewed = [run for run in runs if run.status == "human_reviewed" and run.outcome_hash]
    approved = sum(run.human_review_action == "approve" for run in reviewed)
    edited = sum(run.human_review_action == "edit" for run in reviewed)
    rejected = sum(run.human_review_action == "reject" for run in reviewed)
    actions = approved + edited + rejected
    candidate_total = sum((run.output_candidate_count or 0) for run in reviewed)
    unsupported_total = sum(entry.unsupported_output_count for entry in observations)
    grounding_valid_total = sum(entry.source_grounded_output_count for entry in observations)
    grounding_total = sum(entry.source_grounding_total_count for entry in observations)
    review_seconds = [entry.review_seconds for entry in observations]
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
        "mean_review_seconds": _mean_ceiling(review_seconds),
        "output_candidate_count": candidate_total,
        "unsupported_output_count": unsupported_total,
        "unsupported_output_rate_bps": _rate_bps(unsupported_total, candidate_total),
        "source_grounded_output_count": grounding_valid_total,
        "source_grounding_total_count": grounding_total,
        "source_grounding_validity_bps": _rate_bps(grounding_valid_total, grounding_total),
        "p95_latency_ms": _p95(latencies),
        "mean_latency_ms": _mean_ceiling(latencies),
        "total_observed_provider_cost_microusd": sum(costs),
        "mean_observed_provider_cost_microusd": _mean_ceiling(costs),
    }


def _trend_metrics(
    runs: list[AILimitedProductionRun],
    observations_by_run: dict[UUID, AILimitedProductionOutcomeObservation],
    item: AILimitedProductionOutcomeAssessment,
) -> dict:
    split = (len(runs) + 1) // 2
    first_runs = runs[:split]
    second_runs = runs[split:]
    first = _cohort_metrics(first_runs, observations_by_run) if first_runs else {}
    second = _cohort_metrics(second_runs, observations_by_run) if second_runs else {}

    def positive_delta(key: str) -> int | None:
        first_value = first.get(key)
        second_value = second.get(key)
        if not isinstance(first_value, int) or not isinstance(second_value, int):
            return None
        return max(second_value - first_value, 0)

    grounding_drop = None
    first_grounding = first.get("source_grounding_validity_bps")
    second_grounding = second.get("source_grounding_validity_bps")
    if isinstance(first_grounding, int) and isinstance(second_grounding, int):
        grounding_drop = max(first_grounding - second_grounding, 0)
    quality_candidates = [
        positive_delta("human_reject_rate_bps"),
        positive_delta("human_edit_rate_bps"),
        positive_delta("unsupported_output_rate_bps"),
        grounding_drop,
    ]
    quality_regression = max(
        [value for value in quality_candidates if value is not None], default=None)
    latency_regression = _relative_increase_bps(
        first.get("mean_latency_ms"), second.get("mean_latency_ms"))
    cost_regression = _relative_increase_bps(
        first.get("mean_observed_provider_cost_microusd"),
        second.get("mean_observed_provider_cost_microusd"),
    )
    material = (
        quality_regression is None
        or latency_regression is None
        or cost_regression is None
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


def _workflow_metrics(
    workflow: str,
    runs: list[AILimitedProductionRun],
    observations_by_run: dict[UUID, AILimitedProductionOutcomeObservation],
) -> dict:
    return _cohort_metrics(
        [run for run in runs if run.task_type == workflow], observations_by_run)


def finalize_assessment(
    db: Session,
    user: User,
    item: AILimitedProductionOutcomeAssessment,
    confirm: bool,
    note: str,
) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit outcome assessment finalization is required")
    if item.status != "collecting":
        raise HTTPException(409, "This outcome assessment is immutable")
    authorization = _authorization(db, user.organization_id, item.authorization_id)
    if authorization.status != "completed":
        raise HTTPException(409, "The anchored Sprint 11E evaluation is no longer completed")
    if (
        authorization.decision_hash != item.authorization_decision_hash
        or authorization.model != item.model
        or authorization.prompt_bundle_version != item.prompt_bundle_version
        or authorization.schema_bundle_version != item.schema_bundle_version
        or authorization.rollout_percentage != item.rollout_percentage
    ):
        raise HTTPException(409, "The anchored limited-production bundle no longer matches")

    runs = _runs(db, authorization.id)
    documents = _documents(db, authorization.id)
    incidents = _incidents(db, authorization.id)
    observations = _observations(db, item.id)
    observations_by_run = {entry.limited_run_id: entry for entry in observations}
    cohort = _cohort_metrics(runs, observations_by_run)
    trend = _trend_metrics(runs, observations_by_run, item)
    ce = _workflow_metrics("chief_engineer_report", runs, observations_by_run)
    engine = _workflow_metrics("engine_log", runs, observations_by_run)
    authorized_document_types = {
        entry.document_type for entry in documents if entry.status == "eligible"
    }
    run_types = {run.task_type for run in runs}
    unresolved_high_or_critical = [
        incident for incident in incidents
        if incident.status == "open" and incident.severity in BLOCKING_INCIDENT_SEVERITIES
    ]
    safety_incidents = [
        incident for incident in incidents if incident.category in SAFETY_INCIDENT_CATEGORIES
    ]

    failures: list[str] = []
    if not runs:
        failures.append("provider_run_evidence")
    if cohort["human_review_rate_bps"] != 10000:
        failures.append("human_review_coverage")
    if cohort["observation_coverage_rate_bps"] != 10000:
        failures.append("observation_coverage")
    if cohort["workflow_completion_rate_bps"] != 10000:
        failures.append("workflow_completion")
    if {"chief_engineer_report", "engine_log"} <= authorized_document_types:
        if not {"chief_engineer_report", "engine_log"} <= run_types:
            failures.append("authorized_workflow_representation")
    if (
        cohort["human_reject_rate_bps"] is None
        or cohort["human_reject_rate_bps"] > item.max_reject_rate_bps
    ):
        failures.append("human_reject_rate")
    if (
        cohort["human_edit_rate_bps"] is None
        or cohort["human_edit_rate_bps"] > item.max_edit_rate_bps
    ):
        failures.append("human_edit_rate")
    if (
        cohort["mean_usefulness_bps"] is None
        or cohort["mean_usefulness_bps"] < item.min_mean_usefulness_bps
    ):
        failures.append("mean_usefulness")
    if (
        cohort["unsupported_output_rate_bps"] is None
        or cohort["unsupported_output_rate_bps"] > item.max_unsupported_output_rate_bps
    ):
        failures.append("unsupported_output_rate")
    if (
        cohort["source_grounding_validity_bps"] is None
        or cohort["source_grounding_validity_bps"] < item.min_source_grounding_validity_bps
    ):
        failures.append("source_grounding_validity")
    if (
        cohort["mean_review_seconds"] is None
        or cohort["mean_review_seconds"] > item.max_mean_review_seconds
    ):
        failures.append("mean_review_seconds")
    if cohort["p95_latency_ms"] is None or cohort["p95_latency_ms"] > item.max_p95_latency_ms:
        failures.append("p95_latency")
    if (
        cohort["mean_observed_provider_cost_microusd"] is None
        or cohort["mean_observed_provider_cost_microusd"] > item.max_mean_cost_microusd
    ):
        failures.append("mean_observed_provider_cost")
    if trend["material_regression"]:
        failures.append("second_half_material_regression")
    if unresolved_high_or_critical:
        failures.append("unresolved_high_or_critical_incident")
    if safety_incidents:
        failures.append("privacy_security_or_cross_tenant_incident")
    failures = sorted(set(failures))

    metrics = {
        **cohort,
        "chief_engineer_report": ce,
        "engine_log": engine,
        "authorized_document_types": sorted(authorized_document_types),
        "run_document_types": sorted(run_types),
        "trend": trend,
        "incident_trend": {
            "total_count": len(incidents),
            "unresolved_high_or_critical_count": len(unresolved_high_or_critical),
            "safety_boundary_incident_count": len(safety_incidents),
            "by_severity": {
                severity: sum(incident.severity == severity for incident in incidents)
                for severity in sorted({incident.severity for incident in incidents})
            },
        },
        "overall_pass": not failures,
        "raw_content_stored": False,
        "production_wide_authorized": False,
        "restricted_documents_authorized": False,
        "rollout_increase_authorized": False,
    }
    assessed_at = datetime.now(UTC)
    snapshot = {
        "schema": "mcri-ai-limited-production-outcome-assessment-v1",
        "assessment_id": str(item.id),
        "authorization_id": str(authorization.id),
        "authorization_decision_hash": authorization.decision_hash,
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
        "incident_states": [
            {
                "id": str(incident.id),
                "severity": incident.severity,
                "category": incident.category,
                "status": incident.status,
            }
            for incident in incidents
        ],
        "assessed_at": assessed_at.isoformat(),
        "note": note.strip(),
        "graduation_is_recommendation_only": True,
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
        db, user, "FINALIZE_AI_LIMITED_PRODUCTION_OUTCOME_ASSESSMENT", item,
        {
            "status": item.status,
            "overall_pass": not failures,
            "failure_reasons": failures,
            "assessment_hash": item.assessment_hash,
            "production_wide_authorized": False,
            "restricted_documents_authorized": False,
            "rollout_increase_authorized": False,
        },
        "Immutable limited-production outcome scorecard finalized. " + note.strip(),
    )
    db.commit()
    db.refresh(item)
    return assessment_response(db, item)


def record_review(
    db: Session,
    user: User,
    item: AILimitedProductionOutcomeAssessment,
    role: str,
    action: str,
    evidence_reference: str | None,
    note: str,
) -> dict:
    if item.status not in {"review_ready", "decision_ready"}:
        raise HTTPException(409, "Only a finalized assessment can be reviewed")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The assessment requester cannot review the outcome gate")
    reviews = _reviews(db, item.id)
    if any(review.review_role == role for review in reviews):
        raise HTTPException(409, "This review role already has a decision")
    if any(review.reviewer_id == user.id for review in reviews):
        raise HTTPException(409, "Product, Quality, Risk and Operations require different people")
    reference = _reference(evidence_reference) if evidence_reference else None
    if action == "approve" and not reference:
        raise HTTPException(422, "Approval requires bounded evidence")
    review = AILimitedProductionOutcomeReview(
        organization_id=user.organization_id,
        assessment_id=item.id,
        reviewer_id=user.id,
        review_role=role,
        action=action,
        evidence_reference=reference,
        note=note.strip(),
        reviewed_at=datetime.now(UTC),
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
            and all(entry.action == "approve" for entry in current)
            and len({entry.reviewer_id for entry in current}) == len(REVIEW_ROLES)
            and all(entry.reviewer_id != item.requested_by_id for entry in current)
        ) else "review_ready"
    _audit(
        db, user, f"{action.upper()}_AI_LIMITED_PRODUCTION_OUTCOME_REVIEW", item,
        {
            "review_role": role,
            "action": action,
            "evidence_reference": reference,
            "status": item.status,
        },
        "Independent limited-production outcome review. " + note.strip(),
    )
    db.commit()
    db.refresh(item)
    return assessment_response(db, item)


def decide_outcome(
    db: Session,
    user: User,
    item: AILimitedProductionOutcomeAssessment,
    outcome: str,
    confirm: bool,
    note: str,
) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit recommendation-only confirmation is required")
    if item.status != "decision_ready":
        raise HTTPException(409, "Four independent approvals are required")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The requester cannot issue the final outcome")
    if not item.metrics:
        raise HTTPException(409, "A finalized outcome assessment is required")
    reviews = _reviews(db, item.id)
    if (
        {entry.review_role for entry in reviews} != REVIEW_ROLES
        or len(reviews) != len(REVIEW_ROLES)
        or len({entry.reviewer_id for entry in reviews}) != len(REVIEW_ROLES)
        or any(entry.action != "approve" for entry in reviews)
        or any(entry.reviewer_id == item.requested_by_id for entry in reviews)
    ):
        raise HTTPException(409, "Four independent review roles must remain approved")
    if outcome == "recommend_graduation_stage" and (
        item.failure_reasons or not item.metrics.get("overall_pass")
    ):
        raise HTTPException(409, "Graduation recommendation requires zero failed controls")

    snapshot = {
        "schema": "mcri-ai-limited-production-graduation-recommendation-v1",
        "assessment_id": str(item.id),
        "authorization_id": str(item.authorization_id),
        "authorization_decision_hash": item.authorization_decision_hash,
        "assessment_hash": item.assessment_hash,
        "bundle": {
            "model": item.model,
            "prompt": item.prompt_bundle_version,
            "schema": item.schema_bundle_version,
            "rollout_percentage": item.rollout_percentage,
        },
        "reviewers": [
            {
                "role": entry.review_role,
                "reviewer_id": str(entry.reviewer_id),
                "evidence_reference": entry.evidence_reference,
            }
            for entry in reviews
        ],
        "outcome": outcome,
        "decision_note": note.strip(),
        "recommendation_only": True,
        "production_wide_authorized": False,
        "restricted_documents_authorized": False,
        "rollout_increase_authorized": False,
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
    if outcome == "recommend_graduation_stage":
        item.status = "recommended"
    elif outcome == "extend_limited_production_evaluation":
        item.status = "extended"
    else:
        item.status = "stopped"
    _audit(
        db, user, "DECIDE_AI_LIMITED_PRODUCTION_GRADUATION_RECOMMENDATION", item,
        {
            "status": item.status,
            "outcome": outcome,
            "decision_hash": item.decision_hash,
            "production_wide_authorized": False,
            "restricted_documents_authorized": False,
            "rollout_increase_authorized": False,
        },
        "Recommendation-only Sprint 11F decision; wider Production remains separately governed. "
        + note.strip(),
    )
    db.commit()
    db.refresh(item)
    return assessment_response(db, item)
