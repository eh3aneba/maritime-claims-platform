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

from app.modules.ai_bounded_full_production.models import (
    AIBoundedFullProductionAuthorization,
    AIBoundedFullProductionIncident,
    AIBoundedFullProductionMonitor,
    AIBoundedFullProductionRun,
)
from app.modules.ai_bounded_full_production_outcomes.models import (
    AIBoundedFullProductionOutcomeAssessment,
    AIBoundedFullProductionOutcomeBusinessEvidence,
    AIBoundedFullProductionOutcomeEnterpriseEvidence,
    AIBoundedFullProductionOutcomeObservation,
    AIBoundedFullProductionOutcomeReview,
)
from app.modules.ai_bounded_full_production_outcomes.schemas import (
    AIBoundedFullProductionOutcomeBusinessCreate,
    AIBoundedFullProductionOutcomeCreate,
    AIBoundedFullProductionOutcomeEnterpriseCreate,
    AIBoundedFullProductionOutcomeObservationCreate,
)
from app.modules.ai_near_universal_outcomes.models import AINearUniversalOutcomeAssessment
from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.users.models import User

REFERENCE = re.compile(r"^(artifact|runbook|ticket|monitor)://[A-Za-z0-9._:/-]{3,450}$")
REVIEW_ROLES = {
    "security", "privacy", "product", "operations", "risk", "claims_governance",
    "ai_quality", "legal_data_governance", "business_owner", "platform_reliability",
    "independent_production_assurance", "data_protection", "executive_production_sponsor",
    "enterprise_architecture_resilience",
}
ENTERPRISE_CONTROL_CATEGORIES = {
    "kill_switch_rollback", "monitor_alerting", "audit_hash_traceability", "tenant_isolation",
    "privacy_data_protection", "availability_recovery", "change_control_integrity",
    "unit_economics", "human_escalation_ownership", "incident_executive_ownership",
}
RETRY_STATUSES = {"failed", "review_rejected", "extended", "stopped"}
SAFETY_INCIDENT_CATEGORIES = {"privacy", "security", "cross_tenant"}
BLOCKING_INCIDENT_SEVERITIES = {"critical", "high"}
ALLOWED_WORKFLOWS = {"chief_engineer_report", "engine_log"}


def _reference(value: str) -> str:
    reference = value.strip()
    if not REFERENCE.fullmatch(reference):
        raise HTTPException(422, "Sprint 11S evidence must use a bounded allowlisted reference")
    return reference


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _hash(payload: dict) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _audit(db: Session, user: User, action: str, item: AIBoundedFullProductionOutcomeAssessment,
           values: dict, details: str) -> None:
    write_audit_log(
        db, organization_id=user.organization_id, user_id=user.id, action=action,
        entity_type="ai_bounded_full_production_outcome_assessment", entity_id=item.id,
        new_values=values, details=details,
    )


def _authorization(db: Session, organization_id: UUID,
                   authorization_id: UUID) -> AIBoundedFullProductionAuthorization:
    item = db.scalar(select(AIBoundedFullProductionAuthorization).where(
        AIBoundedFullProductionAuthorization.id == authorization_id,
        AIBoundedFullProductionAuthorization.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Sprint 11R bounded-full authorization not found")
    return item


def _near_outcome(db: Session, authorization: AIBoundedFullProductionAuthorization) -> AINearUniversalOutcomeAssessment:
    item = db.scalar(select(AINearUniversalOutcomeAssessment).where(
        AINearUniversalOutcomeAssessment.id == authorization.near_universal_outcome_assessment_id,
        AINearUniversalOutcomeAssessment.organization_id == authorization.organization_id,
    ))
    if item is None:
        raise HTTPException(409, "The inherited Sprint 11Q outcome anchor is missing")
    return item


def _runs(db: Session, authorization_id: UUID) -> list[AIBoundedFullProductionRun]:
    return list(db.scalars(select(AIBoundedFullProductionRun).where(
        AIBoundedFullProductionRun.authorization_id == authorization_id,
    ).order_by(AIBoundedFullProductionRun.queued_at.asc(), AIBoundedFullProductionRun.id.asc())))


def _monitors(db: Session, authorization_id: UUID) -> list[AIBoundedFullProductionMonitor]:
    return list(db.scalars(select(AIBoundedFullProductionMonitor).where(
        AIBoundedFullProductionMonitor.authorization_id == authorization_id,
    ).order_by(AIBoundedFullProductionMonitor.monitored_at.asc(), AIBoundedFullProductionMonitor.id.asc())))


def _incidents(db: Session, authorization_id: UUID) -> list[AIBoundedFullProductionIncident]:
    return list(db.scalars(select(AIBoundedFullProductionIncident).where(
        AIBoundedFullProductionIncident.authorization_id == authorization_id,
    ).order_by(AIBoundedFullProductionIncident.reported_at.asc(), AIBoundedFullProductionIncident.id.asc())))


def _observations(db: Session, assessment_id: UUID) -> list[AIBoundedFullProductionOutcomeObservation]:
    return list(db.scalars(select(AIBoundedFullProductionOutcomeObservation).where(
        AIBoundedFullProductionOutcomeObservation.assessment_id == assessment_id,
    ).order_by(AIBoundedFullProductionOutcomeObservation.observed_at.asc())))


def _business_evidence(db: Session, assessment_id: UUID) -> list[AIBoundedFullProductionOutcomeBusinessEvidence]:
    return list(db.scalars(select(AIBoundedFullProductionOutcomeBusinessEvidence).where(
        AIBoundedFullProductionOutcomeBusinessEvidence.assessment_id == assessment_id,
    ).order_by(AIBoundedFullProductionOutcomeBusinessEvidence.observed_at.asc())))


def _enterprise_evidence(db: Session, assessment_id: UUID) -> list[AIBoundedFullProductionOutcomeEnterpriseEvidence]:
    return list(db.scalars(select(AIBoundedFullProductionOutcomeEnterpriseEvidence).where(
        AIBoundedFullProductionOutcomeEnterpriseEvidence.assessment_id == assessment_id,
    ).order_by(AIBoundedFullProductionOutcomeEnterpriseEvidence.control_category.asc())))


def _reviews(db: Session, assessment_id: UUID) -> list[AIBoundedFullProductionOutcomeReview]:
    return list(db.scalars(select(AIBoundedFullProductionOutcomeReview).where(
        AIBoundedFullProductionOutcomeReview.assessment_id == assessment_id,
    ).order_by(AIBoundedFullProductionOutcomeReview.review_role.asc())))


def _rate_bps(numerator: int, denominator: int) -> int | None:
    return numerator * 10000 // denominator if denominator else None


def _mean(values: list[int]) -> int | None:
    return (sum(values) + len(values) - 1) // len(values) if values else None


def _median(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return (ordered[(len(ordered) - 1) // 2] + ordered[len(ordered) // 2]) // 2


def _improvement_bps(baseline: int, assisted: int) -> int:
    return (baseline - assisted) * 10000 // baseline


def _relative_increase_bps(first: int | None, second: int | None) -> int | None:
    if first is None or second is None:
        return None
    if second <= first:
        return 0
    if first <= 0:
        return 10000
    return (second - first) * 10000 // first


def _fresh_monitor(authorization: AIBoundedFullProductionAuthorization,
                   monitors: list[AIBoundedFullProductionMonitor]) -> bool:
    return bool(
        monitors and monitors[-1].status == "pass"
        and _as_utc(monitors[-1].monitored_at) >= datetime.now(UTC) - timedelta(minutes=authorization.monitor_interval_minutes * 2)
    )


def _recovery_metrics(monitors: list[AIBoundedFullProductionMonitor],
                      incidents: list[AIBoundedFullProductionIncident]) -> dict:
    passing = [entry for entry in monitors if entry.status == "pass"]
    pauses: list[dict] = []
    recovered = 0
    for monitor in monitors:
        if monitor.status == "pass":
            continue
        next_pass = next((entry for entry in passing if _as_utc(entry.monitored_at) > _as_utc(monitor.monitored_at)), None)
        ok = next_pass is not None
        recovered += int(ok)
        pauses.append({"source": "monitor", "id": str(monitor.id), "recovered": ok})
    for incident in incidents:
        if incident.category in SAFETY_INCIDENT_CATEGORIES:
            continue
        next_pass = None
        if incident.status == "resolved" and incident.resolved_at is not None:
            next_pass = next((entry for entry in passing if _as_utc(entry.monitored_at) > _as_utc(incident.resolved_at)), None)
        ok = next_pass is not None
        recovered += int(ok)
        pauses.append({"source": "incident", "id": str(incident.id), "recovered": ok})
    return {
        "pause_count": len(pauses),
        "recovered_pause_count": recovered,
        "recovery_rate_bps": _rate_bps(recovered, len(pauses)) if pauses else 10000,
        "all_non_safety_pauses_recovered": all(entry["recovered"] for entry in pauses),
        "evidence": pauses,
    }


def _thresholds(item: AIBoundedFullProductionOutcomeAssessment) -> dict:
    return {
        "minimum_human_reviewed_provider_runs": item.min_reviewed_runs,
        "minimum_reviewed_runs_per_authorized_workflow": item.min_runs_per_workflow,
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
        "minimum_business_workflows": item.min_business_workflows,
        "min_tfta_improvement_bps": item.min_tfta_improvement_bps,
        "min_triage_improvement_bps": item.min_triage_improvement_bps,
        "min_handler_effort_improvement_bps": item.min_handler_effort_improvement_bps,
        "min_business_usefulness_bps": item.min_business_usefulness_bps,
        "required_human_claim_decision_ownership_rate_bps": 10000,
        "required_enterprise_control_categories": sorted(ENTERPRISE_CONTROL_CATEGORIES),
        "minimum_enterprise_controls": item.min_enterprise_controls,
        "max_unresolved_high_or_critical_incident_count": 0,
        "max_safety_boundary_incident_count": 0,
        "required_non_safety_pause_recovery_rate_bps": 10000,
        "fresh_final_monitor_required": True,
    }


def _validate_authorization_chain(
    db: Session, authorization: AIBoundedFullProductionAuthorization,
) -> AINearUniversalOutcomeAssessment:
    near = _near_outcome(db, authorization)
    monitors = _monitors(db, authorization.id)
    incidents = _incidents(db, authorization.id)
    recovery = _recovery_metrics(monitors, incidents)
    if (
        authorization.status != "completed"
        or authorization.outcome != "authorize_bounded_100_percent_cohort"
        or not authorization.decision_hash
        or not authorization.completion_hash
        or authorization.rollout_percentage != 100
        or near.status != "recommended"
        or near.outcome != "recommend_separate_100_percent_authorization_review"
        or not near.assessment_hash or not near.decision_hash
        or authorization.near_universal_outcome_assessment_hash != near.assessment_hash
        or authorization.near_universal_outcome_decision_hash != near.decision_hash
        or authorization.near_universal_decision_hash != near.near_universal_decision_hash
        or authorization.near_universal_completion_hash != near.near_universal_completion_hash
        or authorization.near_universal_authorization_id != near.near_universal_authorization_id
        or authorization.model != near.model
        or authorization.prompt_bundle_version != near.prompt_bundle_version
        or authorization.schema_bundle_version != near.schema_bundle_version
        or authorization.max_input_chars != near.max_input_chars
        or authorization.max_output_tokens != near.max_output_tokens
        or list(authorization.allowed_document_types) != list(near.allowed_document_types)
        or not _fresh_monitor(authorization, monitors)
        or any(entry.category in SAFETY_INCIDENT_CATEGORIES for entry in incidents)
        or recovery["recovery_rate_bps"] != 10000
    ):
        raise HTTPException(409, "The persisted Sprint 11R/11Q evidence chain is not eligible for Sprint 11S")
    return near


def _validate_anchor(db: Session, item: AIBoundedFullProductionOutcomeAssessment,
                     authorization: AIBoundedFullProductionAuthorization) -> None:
    near = _validate_authorization_chain(db, authorization)
    if (
        authorization.decision_hash != item.bounded_full_decision_hash
        or authorization.completion_hash != item.bounded_full_completion_hash
        or authorization.near_universal_outcome_assessment_id != item.near_universal_outcome_assessment_id
        or near.assessment_hash != item.near_universal_outcome_assessment_hash
        or near.decision_hash != item.near_universal_outcome_decision_hash
        or authorization.near_universal_decision_hash != item.near_universal_decision_hash
        or authorization.near_universal_completion_hash != item.near_universal_completion_hash
        or authorization.model != item.model
        or authorization.prompt_bundle_version != item.prompt_bundle_version
        or authorization.schema_bundle_version != item.schema_bundle_version
        or authorization.max_input_chars != item.max_input_chars
        or authorization.max_output_tokens != item.max_output_tokens
        or list(authorization.allowed_document_types) != list(item.allowed_document_types)
        or authorization.rollout_percentage != item.rollout_percentage
        or authorization.max_claims != item.max_claims
        or authorization.max_documents != item.max_documents
        or authorization.max_users != item.max_users
        or authorization.max_provider_runs != item.max_provider_runs
    ):
        raise HTTPException(409, "The frozen Sprint 11S anchor no longer matches Sprint 11R")


def assessment_response(db: Session, item: AIBoundedFullProductionOutcomeAssessment) -> dict:
    observations = _observations(db, item.id)
    business = _business_evidence(db, item.id)
    enterprise = _enterprise_evidence(db, item.id)
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
        "bounded_full_authorization_id": item.bounded_full_authorization_id,
        "near_universal_outcome_assessment_id": item.near_universal_outcome_assessment_id,
        "requested_by_id": item.requested_by_id,
        "finalized_by_id": item.finalized_by_id,
        "attempt_number": item.attempt_number,
        "assessment_key": item.assessment_key,
        "assessment_profile": item.assessment_profile,
        "bounded_full_decision_hash": item.bounded_full_decision_hash,
        "bounded_full_completion_hash": item.bounded_full_completion_hash,
        "anchor_hashes": {
            "near_universal_outcome_assessment_hash": item.near_universal_outcome_assessment_hash,
            "near_universal_outcome_decision_hash": item.near_universal_outcome_decision_hash,
            "near_universal_decision_hash": item.near_universal_decision_hash,
            "near_universal_completion_hash": item.near_universal_completion_hash,
        },
        "bundle": {
            "model": item.model,
            "prompt_bundle_version": item.prompt_bundle_version,
            "schema_bundle_version": item.schema_bundle_version,
            "max_input_chars": item.max_input_chars,
            "max_output_tokens": item.max_output_tokens,
        },
        "allowed_document_types": item.allowed_document_types,
        "rollout_percentage": item.rollout_percentage,
        "authorization_caps": {
            "claims": item.max_claims, "documents": item.max_documents,
            "users": item.max_users, "provider_runs": item.max_provider_runs,
        },
        "thresholds": _thresholds(item),
        "status": item.status, "outcome": item.outcome,
        "metrics": item.metrics, "failure_reasons": item.failure_reasons or [],
        "assessment_note": item.assessment_note, "assessment_hash": item.assessment_hash,
        "assessed_at": item.assessed_at, "decision_note": item.decision_note,
        "decision_hash": item.decision_hash, "decided_at": item.decided_at,
        "observations": observations, "business_evidence": business,
        "enterprise_evidence": enterprise, "reviews": reviews,
        "summary": {
            "reviews_complete": reviews_complete,
            "recommendation_only": True,
            "bounded_100_percent_measured": item.rollout_percentage == 100,
            "production_wide_unbounded_authorized": False,
            "restricted_documents_authorized": False,
            "new_document_classes_authorized": False,
            "autonomous_claim_decisions_authorized": False,
            "authoritative_facts_auto_updated": False,
            "different_human_review_required": True,
            "raw_content_stored_in_outcome_ledger": False,
        },
        "created_at": item.created_at,
    }


def list_assessments(db: Session, organization_id: UUID) -> list[dict]:
    items = list(db.scalars(select(AIBoundedFullProductionOutcomeAssessment).where(
        AIBoundedFullProductionOutcomeAssessment.organization_id == organization_id,
    ).order_by(AIBoundedFullProductionOutcomeAssessment.created_at.desc()).limit(20)))
    return [assessment_response(db, item) for item in items]


def get_assessment(db: Session, organization_id: UUID,
                   assessment_id: UUID) -> AIBoundedFullProductionOutcomeAssessment:
    item = db.scalar(select(AIBoundedFullProductionOutcomeAssessment).where(
        AIBoundedFullProductionOutcomeAssessment.id == assessment_id,
        AIBoundedFullProductionOutcomeAssessment.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Sprint 11S bounded-full outcome assessment not found")
    return item


def create_assessment(db: Session, user: User, payload: AIBoundedFullProductionOutcomeCreate) -> dict:
    if not payload.confirm_content_free_assessment:
        raise HTTPException(422, "Explicit content-free Sprint 11S confirmation is required")
    authorization = _authorization(db, user.organization_id, payload.bounded_full_authorization_id)
    near = _validate_authorization_chain(db, authorization)
    attempts = list(db.scalars(select(AIBoundedFullProductionOutcomeAssessment).where(
        AIBoundedFullProductionOutcomeAssessment.bounded_full_authorization_id == authorization.id,
    ).order_by(AIBoundedFullProductionOutcomeAssessment.attempt_number.asc())))
    if attempts and attempts[-1].status not in RETRY_STATUSES:
        raise HTTPException(409, "The current Sprint 11S assessment is still active")
    item = AIBoundedFullProductionOutcomeAssessment(
        organization_id=user.organization_id,
        bounded_full_authorization_id=authorization.id,
        near_universal_outcome_assessment_id=near.id,
        requested_by_id=user.id,
        attempt_number=len(attempts) + 1,
        assessment_key=payload.assessment_key.strip(),
        bounded_full_decision_hash=authorization.decision_hash,
        bounded_full_completion_hash=authorization.completion_hash,
        near_universal_outcome_assessment_hash=near.assessment_hash,
        near_universal_outcome_decision_hash=near.decision_hash,
        near_universal_decision_hash=authorization.near_universal_decision_hash,
        near_universal_completion_hash=authorization.near_universal_completion_hash,
        model=authorization.model,
        prompt_bundle_version=authorization.prompt_bundle_version,
        schema_bundle_version=authorization.schema_bundle_version,
        max_input_chars=authorization.max_input_chars,
        max_output_tokens=authorization.max_output_tokens,
        allowed_document_types=list(authorization.allowed_document_types),
        rollout_percentage=authorization.rollout_percentage,
        max_claims=authorization.max_claims,
        max_documents=authorization.max_documents,
        max_users=authorization.max_users,
        max_provider_runs=authorization.max_provider_runs,
        status="collecting",
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Sprint 11S assessment key or attempt already exists") from exc
    _audit(
        db, user, "CREATE_AI_BOUNDED_FULL_PRODUCTION_OUTCOME_ASSESSMENT", item,
        {"authorization_id": str(authorization.id), "attempt_number": item.attempt_number,
         "rollout_percentage": 100, "production_wide_unbounded_authorized": False,
         "raw_content_stored": False},
        "Sprint 11S content-free bounded-100% outcome assessment created.",
    )
    db.commit(); db.refresh(item)
    return assessment_response(db, item)


def record_observation(db: Session, user: User, item: AIBoundedFullProductionOutcomeAssessment,
                       payload: AIBoundedFullProductionOutcomeObservationCreate) -> dict:
    if not payload.confirm_content_free_observation:
        raise HTTPException(422, "Explicit content-free observation confirmation is required")
    if item.status != "collecting":
        raise HTTPException(409, "This Sprint 11S assessment no longer accepts observations")
    authorization = _authorization(db, user.organization_id, item.bounded_full_authorization_id)
    _validate_anchor(db, item, authorization)
    run = db.scalar(select(AIBoundedFullProductionRun).where(
        AIBoundedFullProductionRun.id == payload.bounded_full_run_id,
        AIBoundedFullProductionRun.authorization_id == authorization.id,
        AIBoundedFullProductionRun.organization_id == user.organization_id,
    ))
    if run is None:
        raise HTTPException(404, "Sprint 11R provider run not found")
    if (
        run.status != "human_reviewed" or not run.outcome_hash
        or run.requested_by_id is None or run.reviewed_by_id is None
        or run.requested_by_id == run.reviewed_by_id
    ):
        raise HTTPException(409, "Only immutable different-human-reviewed Sprint 11R runs can be observed")
    now = datetime.now(UTC)
    reference = _reference(payload.evidence_reference)
    snapshot = {
        "schema": "mcri-ai-bounded-full-outcome-observation-v1",
        "assessment_id": str(item.id), "run_id": str(run.id), "run_outcome_hash": run.outcome_hash,
        "workflow_type": run.task_type, "usefulness_rating": payload.usefulness_rating,
        "review_seconds": payload.review_seconds, "workflow_completed": payload.workflow_completed,
        "evidence_reference": reference, "observed_at": now.isoformat(), "raw_content_stored": False,
    }
    row = AIBoundedFullProductionOutcomeObservation(
        organization_id=user.organization_id, assessment_id=item.id,
        bounded_full_run_id=run.id, observed_by_id=user.id, workflow_type=run.task_type,
        usefulness_rating=payload.usefulness_rating, review_seconds=payload.review_seconds,
        workflow_completed=payload.workflow_completed, evidence_reference=reference,
        note=payload.note.strip(), observation_hash=_hash(snapshot), observed_at=now,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This Sprint 11R run already has a Sprint 11S observation") from exc
    db.commit(); db.refresh(item)
    return assessment_response(db, item)


def record_business_evidence(db: Session, user: User, item: AIBoundedFullProductionOutcomeAssessment,
                             payload: AIBoundedFullProductionOutcomeBusinessCreate) -> dict:
    if not payload.confirm_content_free_business_evidence:
        raise HTTPException(422, "Explicit content-free business-value confirmation is required")
    if item.status != "collecting":
        raise HTTPException(409, "This Sprint 11S assessment no longer accepts business evidence")
    authorization = _authorization(db, user.organization_id, item.bounded_full_authorization_id)
    _validate_anchor(db, item, authorization)
    if payload.workflow_type not in item.allowed_document_types or payload.workflow_type not in ALLOWED_WORKFLOWS:
        raise HTTPException(409, "Business evidence workflow is outside the Sprint 11R allowlist")
    claim = db.scalar(select(Claim).where(Claim.id == payload.claim_id, Claim.organization_id == user.organization_id))
    if claim is None:
        raise HTTPException(404, "Claim not found in this tenant")
    now = datetime.now(UTC)
    reference = _reference(payload.evidence_reference)
    snapshot = {
        "schema": "mcri-ai-bounded-full-business-value-v1", "assessment_id": str(item.id),
        "claim_id": str(claim.id), "evidence_key": payload.evidence_key.strip(),
        "workflow_type": payload.workflow_type,
        "baseline_tfta_seconds": payload.baseline_tfta_seconds, "assisted_tfta_seconds": payload.assisted_tfta_seconds,
        "baseline_triage_seconds": payload.baseline_triage_seconds, "assisted_triage_seconds": payload.assisted_triage_seconds,
        "baseline_handler_effort_seconds": payload.baseline_handler_effort_seconds,
        "assisted_handler_effort_seconds": payload.assisted_handler_effort_seconds,
        "baseline_rework_count": payload.baseline_rework_count, "assisted_rework_count": payload.assisted_rework_count,
        "baseline_escalation_count": payload.baseline_escalation_count, "assisted_escalation_count": payload.assisted_escalation_count,
        "baseline_correction_count": payload.baseline_correction_count, "assisted_correction_count": payload.assisted_correction_count,
        "handler_usefulness_rating": payload.handler_usefulness_rating,
        "final_claim_decision_human_owned": payload.final_claim_decision_human_owned,
        "evidence_reference": reference, "observed_at": now.isoformat(), "raw_content_stored": False,
    }
    row = AIBoundedFullProductionOutcomeBusinessEvidence(
        organization_id=user.organization_id, assessment_id=item.id, claim_id=claim.id,
        recorded_by_id=user.id, evidence_key=payload.evidence_key.strip(), workflow_type=payload.workflow_type,
        baseline_tfta_seconds=payload.baseline_tfta_seconds, assisted_tfta_seconds=payload.assisted_tfta_seconds,
        baseline_triage_seconds=payload.baseline_triage_seconds, assisted_triage_seconds=payload.assisted_triage_seconds,
        baseline_handler_effort_seconds=payload.baseline_handler_effort_seconds,
        assisted_handler_effort_seconds=payload.assisted_handler_effort_seconds,
        baseline_rework_count=payload.baseline_rework_count, assisted_rework_count=payload.assisted_rework_count,
        baseline_escalation_count=payload.baseline_escalation_count, assisted_escalation_count=payload.assisted_escalation_count,
        baseline_correction_count=payload.baseline_correction_count, assisted_correction_count=payload.assisted_correction_count,
        handler_usefulness_rating=payload.handler_usefulness_rating,
        final_claim_decision_human_owned=payload.final_claim_decision_human_owned,
        evidence_reference=reference, note=payload.note.strip(), evidence_hash=_hash(snapshot), observed_at=now,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This Sprint 11S business evidence key already exists") from exc
    db.commit(); db.refresh(item)
    return assessment_response(db, item)


def record_enterprise_evidence(db: Session, user: User, item: AIBoundedFullProductionOutcomeAssessment,
                               payload: AIBoundedFullProductionOutcomeEnterpriseCreate) -> dict:
    if not payload.confirm_content_free_enterprise_evidence:
        raise HTTPException(422, "Explicit content-free enterprise-readiness confirmation is required")
    if item.status != "collecting":
        raise HTTPException(409, "This Sprint 11S assessment no longer accepts enterprise evidence")
    authorization = _authorization(db, user.organization_id, item.bounded_full_authorization_id)
    _validate_anchor(db, item, authorization)
    if payload.control_category not in ENTERPRISE_CONTROL_CATEGORIES:
        raise HTTPException(422, "Unsupported Sprint 11S enterprise control category")
    now = datetime.now(UTC)
    reference = _reference(payload.evidence_reference)
    snapshot = {
        "schema": "mcri-ai-bounded-full-enterprise-readiness-evidence-v1",
        "assessment_id": str(item.id), "control_category": payload.control_category,
        "evidence_key": payload.evidence_key.strip(), "passed": payload.passed,
        "evidence_reference": reference, "observed_at": now.isoformat(), "raw_content_stored": False,
    }
    row = AIBoundedFullProductionOutcomeEnterpriseEvidence(
        organization_id=user.organization_id, assessment_id=item.id, recorded_by_id=user.id,
        control_category=payload.control_category, evidence_key=payload.evidence_key.strip(),
        passed=payload.passed, evidence_reference=reference, note=payload.note.strip(),
        evidence_hash=_hash(snapshot), observed_at=now,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This Sprint 11S enterprise control category already has evidence") from exc
    db.commit(); db.refresh(item)
    return assessment_response(db, item)


def _cohort_metrics(runs: list[AIBoundedFullProductionRun],
                    observations_by_run: dict[UUID, AIBoundedFullProductionOutcomeObservation]) -> dict:
    reviewed = [run for run in runs if run.status == "human_reviewed"]
    different = [run for run in reviewed if run.requested_by_id and run.reviewed_by_id and run.requested_by_id != run.reviewed_by_id]
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
        "run_count": len(runs), "human_reviewed_run_count": len(reviewed),
        "human_review_rate_bps": _rate_bps(len(reviewed), len(runs)),
        "different_human_review_rate_bps": _rate_bps(len(different), len(reviewed)),
        "observation_count": len(observations),
        "observation_coverage_rate_bps": _rate_bps(len(observations), len(reviewed)),
        "workflow_completion_rate_bps": _rate_bps(sum(entry.workflow_completed for entry in observations), len(observations)),
        "human_reject_rate_bps": _rate_bps(sum(action == "reject" for action in actions), len(actions)),
        "human_edit_rate_bps": _rate_bps(sum(action == "edit" for action in actions), len(actions)),
        "mean_usefulness_bps": (sum(entry.usefulness_rating for entry in observations) * 2000 // len(observations)) if observations else None,
        "unsupported_output_rate_bps": _rate_bps(unsupported, candidates),
        "source_grounding_validity_bps": _rate_bps(grounded, grounding_total),
        "mean_review_seconds": _mean([entry.review_seconds for entry in observations]),
        "p95_latency_ms": p95, "mean_observed_provider_cost_microusd": _mean(costs),
    }


def _trend_metrics(runs: list[AIBoundedFullProductionRun],
                   observations_by_run: dict[UUID, AIBoundedFullProductionOutcomeObservation],
                   item: AIBoundedFullProductionOutcomeAssessment) -> dict:
    reviewed = [run for run in runs if run.status == "human_reviewed"]
    half = len(reviewed) // 2
    if half == 0 or len(reviewed) - half == 0:
        return {"first_half": {}, "second_half": {}, "quality_regression_bps": None,
                "latency_regression_bps": None, "cost_regression_bps": None, "material_regression": True}
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
    return {
        "first_half": first, "second_half": second, "quality_regression_bps": quality,
        "latency_regression_bps": latency, "cost_regression_bps": cost,
        "material_regression": quality > item.max_quality_regression_bps
        or latency is None or latency > item.max_latency_regression_bps
        or cost is None or cost > item.max_cost_regression_bps,
    }


def _business_metrics(rows: list[AIBoundedFullProductionOutcomeBusinessEvidence]) -> dict:
    tfta = [_improvement_bps(row.baseline_tfta_seconds, row.assisted_tfta_seconds) for row in rows]
    triage = [_improvement_bps(row.baseline_triage_seconds, row.assisted_triage_seconds) for row in rows]
    effort = [_improvement_bps(row.baseline_handler_effort_seconds, row.assisted_handler_effort_seconds) for row in rows]
    return {
        "workflow_count": len(rows), "claim_count": len({row.claim_id for row in rows}),
        "workflow_mix": {workflow: sum(row.workflow_type == workflow for row in rows) for workflow in sorted(ALLOWED_WORKFLOWS)},
        "median_tfta_improvement_bps": _median(tfta), "median_triage_improvement_bps": _median(triage),
        "median_handler_effort_improvement_bps": _median(effort),
        "mean_handler_usefulness_bps": (sum(row.handler_usefulness_rating for row in rows) * 2000 // len(rows)) if rows else None,
        "aggregate_rework_delta": sum(row.assisted_rework_count - row.baseline_rework_count for row in rows),
        "aggregate_escalation_delta": sum(row.assisted_escalation_count - row.baseline_escalation_count for row in rows),
        "aggregate_correction_delta": sum(row.assisted_correction_count - row.baseline_correction_count for row in rows),
        "human_claim_decision_ownership_rate_bps": _rate_bps(sum(row.final_claim_decision_human_owned for row in rows), len(rows)),
    }


def finalize_assessment(db: Session, user: User, item: AIBoundedFullProductionOutcomeAssessment,
                        confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit Sprint 11S finalization is required")
    if item.status != "collecting":
        raise HTTPException(409, "This Sprint 11S assessment is immutable")
    authorization = _authorization(db, user.organization_id, item.bounded_full_authorization_id)
    _validate_anchor(db, item, authorization)
    runs = _runs(db, authorization.id)
    monitors = _monitors(db, authorization.id)
    incidents = _incidents(db, authorization.id)
    observations = _observations(db, item.id)
    business_rows = _business_evidence(db, item.id)
    enterprise_rows = _enterprise_evidence(db, item.id)
    observations_by_run = {entry.bounded_full_run_id: entry for entry in observations}
    cohort = _cohort_metrics(runs, observations_by_run)
    trend = _trend_metrics(runs, observations_by_run, item)
    required_workflows = set(item.allowed_document_types) & ALLOWED_WORKFLOWS
    workflow_metrics = {
        workflow: _cohort_metrics([run for run in runs if run.task_type == workflow], observations_by_run)
        for workflow in sorted(required_workflows)
    }
    unresolved = [incident for incident in incidents if incident.status == "open" and incident.severity in BLOCKING_INCIDENT_SEVERITIES]
    safety = [incident for incident in incidents if incident.category in SAFETY_INCIDENT_CATEGORIES]
    recovery = _recovery_metrics(monitors, incidents)
    business = _business_metrics(business_rows)
    enterprise_categories = {entry.control_category for entry in enterprise_rows}
    enterprise = {
        "control_count": len(enterprise_rows), "categories": sorted(enterprise_categories),
        "all_required_categories_present": enterprise_categories == ENTERPRISE_CONTROL_CATEGORIES,
        "all_controls_passing": bool(enterprise_rows) and all(entry.passed for entry in enterprise_rows),
    }
    required_fields = (
        "human_review_action", "output_candidate_count", "unsupported_output_count",
        "source_grounded_output_count", "source_grounding_total_count", "latency_ms",
        "observed_provider_cost_microusd", "outcome_hash", "requested_by_id", "reviewed_by_id",
    )
    incomplete = [str(run.id) for run in runs if any(getattr(run, field) is None for field in required_fields)]
    self_reviewed = [str(run.id) for run in runs if run.status == "human_reviewed" and run.requested_by_id == run.reviewed_by_id]
    latest_monitor_fresh = _fresh_monitor(authorization, monitors)
    cap_usage = {
        "claims": len({run.claim_id for run in runs}), "documents": len({run.document_id for run in runs}),
        "users": len({run.requested_by_id for run in runs if run.requested_by_id}), "provider_runs": len(runs),
    }
    caps_intact = (
        cap_usage["claims"] <= item.max_claims and cap_usage["documents"] <= item.max_documents
        and cap_usage["users"] <= item.max_users and cap_usage["provider_runs"] <= item.max_provider_runs
    )
    failures: list[str] = []
    if len(runs) < item.min_reviewed_runs: failures.append("minimum_reviewed_run_count")
    if cohort["human_review_rate_bps"] != 10000: failures.append("human_review_coverage")
    if cohort["different_human_review_rate_bps"] != 10000 or self_reviewed: failures.append("different_human_review")
    if cohort["observation_coverage_rate_bps"] != 10000: failures.append("observation_coverage")
    if cohort["workflow_completion_rate_bps"] != 10000: failures.append("workflow_completion")
    for workflow in sorted(required_workflows):
        if workflow_metrics[workflow]["human_reviewed_run_count"] < item.min_runs_per_workflow:
            failures.append(f"minimum_{workflow}_run_count")
    if cohort["human_reject_rate_bps"] is None or cohort["human_reject_rate_bps"] > item.max_reject_rate_bps: failures.append("reject_rate")
    if cohort["human_edit_rate_bps"] is None or cohort["human_edit_rate_bps"] > item.max_edit_rate_bps: failures.append("edit_rate")
    if cohort["mean_usefulness_bps"] is None or cohort["mean_usefulness_bps"] < item.min_mean_usefulness_bps: failures.append("handler_usefulness")
    if cohort["unsupported_output_rate_bps"] is None or cohort["unsupported_output_rate_bps"] > item.max_unsupported_output_rate_bps: failures.append("unsupported_output_rate")
    if cohort["source_grounding_validity_bps"] is None or cohort["source_grounding_validity_bps"] < item.min_source_grounding_validity_bps: failures.append("source_grounding")
    if cohort["mean_review_seconds"] is None or cohort["mean_review_seconds"] > item.max_mean_review_seconds: failures.append("review_effort")
    if cohort["p95_latency_ms"] is None or cohort["p95_latency_ms"] > item.max_p95_latency_ms: failures.append("p95_latency")
    if cohort["mean_observed_provider_cost_microusd"] is None or cohort["mean_observed_provider_cost_microusd"] > item.max_mean_cost_microusd: failures.append("mean_provider_cost")
    if trend["quality_regression_bps"] is None or trend["quality_regression_bps"] > item.max_quality_regression_bps: failures.append("quality_grounding_regression")
    if trend["latency_regression_bps"] is None or trend["latency_regression_bps"] > item.max_latency_regression_bps: failures.append("latency_regression")
    if trend["cost_regression_bps"] is None or trend["cost_regression_bps"] > item.max_cost_regression_bps: failures.append("cost_regression")
    if incomplete: failures.append("incomplete_provider_run_metrics")
    if unresolved: failures.append("unresolved_high_or_critical_incident")
    if safety: failures.append("privacy_security_or_cross_tenant_incident")
    if recovery["recovery_rate_bps"] != 10000: failures.append("rollback_recovery")
    if not latest_monitor_fresh: failures.append("fresh_final_monitor")
    if not caps_intact: failures.append("authorization_caps_exceeded")
    if business["workflow_count"] < item.min_business_workflows: failures.append("minimum_business_workflow_count")
    if business["median_tfta_improvement_bps"] is None or business["median_tfta_improvement_bps"] < item.min_tfta_improvement_bps: failures.append("tfta_business_value")
    if business["median_triage_improvement_bps"] is None or business["median_triage_improvement_bps"] < item.min_triage_improvement_bps: failures.append("triage_business_value")
    if business["median_handler_effort_improvement_bps"] is None or business["median_handler_effort_improvement_bps"] < item.min_handler_effort_improvement_bps: failures.append("handler_effort_business_value")
    if business["mean_handler_usefulness_bps"] is None or business["mean_handler_usefulness_bps"] < item.min_business_usefulness_bps: failures.append("business_handler_usefulness")
    if business["aggregate_rework_delta"] > 0: failures.append("ai_caused_rework_increase")
    if business["aggregate_escalation_delta"] > 0: failures.append("ai_caused_escalation_increase")
    if business["aggregate_correction_delta"] > 0: failures.append("ai_caused_correction_increase")
    if business["human_claim_decision_ownership_rate_bps"] != 10000: failures.append("human_claim_decision_ownership")
    if enterprise["control_count"] < item.min_enterprise_controls or not enterprise["all_required_categories_present"]:
        failures.append("enterprise_control_coverage")
    if not enterprise["all_controls_passing"]: failures.append("enterprise_control_failure")

    metrics = {
        **cohort, "workflow_metrics": workflow_metrics, "trend": trend,
        "rollback_recovery": recovery,
        "monitor_history": {"monitor_count": len(monitors), "latest_monitor_status": monitors[-1].status if monitors else None,
                            "latest_monitor_fresh": latest_monitor_fresh},
        "incident_history": {"incident_count": len(incidents), "unresolved_high_or_critical_count": len(unresolved),
                             "safety_boundary_incident_count": len(safety)},
        "business_value": business, "enterprise_readiness": enterprise,
        "authorization_cap_usage": cap_usage, "authorization_caps_intact": caps_intact,
        "incomplete_run_metric_ids": incomplete, "self_reviewed_run_ids": self_reviewed,
        "source_ledger_revalidated": True, "overall_pass": not failures,
    }
    assessed_at = datetime.now(UTC)
    current = assessment_response(db, item)
    snapshot = {
        "schema": "mcri-ai-bounded-full-production-outcome-assessment-v1",
        "assessment_id": str(item.id), "bounded_full_authorization_id": str(authorization.id),
        "bounded_full_decision_hash": item.bounded_full_decision_hash,
        "bounded_full_completion_hash": item.bounded_full_completion_hash,
        "anchor_hashes": current["anchor_hashes"], "bundle": current["bundle"],
        "rollout_percentage": 100, "authorization_caps": current["authorization_caps"],
        "thresholds": _thresholds(item), "metrics": metrics, "failure_reasons": failures,
        "run_outcome_hashes": [run.outcome_hash for run in runs],
        "observation_hashes": [entry.observation_hash for entry in observations],
        "business_evidence_hashes": [entry.evidence_hash for entry in business_rows],
        "enterprise_evidence_hashes": [entry.evidence_hash for entry in enterprise_rows],
        "monitor_hashes": [entry.monitor_hash for entry in monitors],
        "assessed_at": assessed_at.isoformat(), "note": note.strip(),
        "recommendation_only": True, "production_wide_unbounded_authorized": False,
        "restricted_documents_authorized": False, "new_document_classes_authorized": False,
        "autonomous_claim_decisions_authorized": False, "authoritative_facts_auto_updated": False,
        "different_human_review_required": True, "raw_content_stored": False,
    }
    item.metrics = metrics; item.failure_reasons = failures; item.assessment_note = note.strip()
    item.assessed_at = assessed_at; item.finalized_by_id = user.id; item.assessment_hash = _hash(snapshot)
    item.status = "review_ready"
    _audit(db, user, "FINALIZE_AI_BOUNDED_FULL_PRODUCTION_OUTCOME_ASSESSMENT", item,
           {"overall_pass": not failures, "failure_reasons": failures, "assessment_hash": item.assessment_hash,
            "production_wide_unbounded_authorized": False},
           "Immutable Sprint 11S technical, business-value and enterprise-readiness scorecard finalized.")
    db.commit(); db.refresh(item)
    return assessment_response(db, item)


def record_review(db: Session, user: User, item: AIBoundedFullProductionOutcomeAssessment,
                  role: str, action: str, evidence_reference: str | None, note: str) -> dict:
    if item.status not in {"review_ready", "decision_ready"}:
        raise HTTPException(409, "Only a finalized Sprint 11S assessment can be reviewed")
    if role not in REVIEW_ROLES:
        raise HTTPException(422, "Unsupported Sprint 11S review role")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The assessment requester cannot review the Production-wide readiness gate")
    reviews = _reviews(db, item.id)
    if any(review.review_role == role for review in reviews):
        raise HTTPException(409, "This review role already has a decision")
    if any(review.reviewer_id == user.id for review in reviews):
        raise HTTPException(409, "All fourteen Sprint 11S review roles require different people")
    reference = _reference(evidence_reference) if evidence_reference else None
    if action == "approve" and not reference:
        raise HTTPException(422, "Approval requires bounded evidence")
    row = AIBoundedFullProductionOutcomeReview(
        organization_id=user.organization_id, assessment_id=item.id, reviewer_id=user.id,
        review_role=role, action=action, evidence_reference=reference,
        note=note.strip(), reviewed_at=datetime.now(UTC),
    )
    db.add(row); db.flush()
    current = _reviews(db, item.id)
    if action == "reject":
        item.status = "review_rejected"; item.outcome = "review_rejected"
    else:
        item.status = "decision_ready" if (
            {entry.review_role for entry in current} == REVIEW_ROLES
            and len(current) == len(REVIEW_ROLES) and all(entry.action == "approve" for entry in current)
            and len({entry.reviewer_id for entry in current}) == len(REVIEW_ROLES)
            and all(entry.reviewer_id != item.requested_by_id for entry in current)
        ) else "review_ready"
    _audit(db, user, f"{action.upper()}_AI_BOUNDED_FULL_PRODUCTION_OUTCOME_REVIEW", item,
           {"review_role": role, "action": action, "status": item.status},
           "Independent Sprint 11S enterprise-production-readiness review recorded.")
    db.commit(); db.refresh(item)
    return assessment_response(db, item)


def decide_outcome(db: Session, user: User, item: AIBoundedFullProductionOutcomeAssessment,
                   outcome: str, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit recommendation-only Sprint 11S confirmation is required")
    if item.status != "decision_ready":
        raise HTTPException(409, "Fourteen independent approvals are required")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The requester cannot issue the final Sprint 11S outcome")
    if not item.metrics or not item.assessment_hash:
        raise HTTPException(409, "A finalized Sprint 11S assessment is required")
    authorization = _authorization(db, user.organization_id, item.bounded_full_authorization_id)
    _validate_anchor(db, item, authorization)
    reviews = _reviews(db, item.id)
    reviewer_ids = {entry.reviewer_id for entry in reviews}
    if (
        {entry.review_role for entry in reviews} != REVIEW_ROLES or len(reviews) != len(REVIEW_ROLES)
        or len(reviewer_ids) != len(REVIEW_ROLES) or any(entry.action != "approve" for entry in reviews)
        or any(entry.reviewer_id == item.requested_by_id for entry in reviews)
    ):
        raise HTTPException(409, "Fourteen independent review roles must remain approved")
    if user.id in reviewer_ids:
        raise HTTPException(409, "Final Admin must be distinct from all fourteen Sprint 11S reviewers")
    if outcome == "recommend_separate_production_wide_authorization_review" and (
        item.failure_reasons or not item.metrics.get("overall_pass")
    ):
        raise HTTPException(409, "Production-wide review recommendation requires zero failed controls")
    snapshot = {
        "schema": "mcri-ai-bounded-full-production-wide-readiness-recommendation-v1",
        "assessment_id": str(item.id), "bounded_full_authorization_id": str(item.bounded_full_authorization_id),
        "bounded_full_decision_hash": item.bounded_full_decision_hash,
        "bounded_full_completion_hash": item.bounded_full_completion_hash,
        "assessment_hash": item.assessment_hash,
        "reviewers": [{"role": entry.review_role, "reviewer_id": str(entry.reviewer_id),
                       "evidence_reference": entry.evidence_reference} for entry in reviews],
        "outcome": outcome, "decision_note": note.strip(), "recommendation_only": True,
        "production_wide_unbounded_authorized": False, "restricted_documents_authorized": False,
        "new_document_classes_authorized": False, "autonomous_claim_decisions_authorized": False,
        "authoritative_facts_auto_updated": False, "different_human_review_required": True,
    }
    item.outcome = outcome; item.decision_note = note.strip(); item.decided_at = datetime.now(UTC)
    item.finalized_by_id = user.id; item.decision_hash = _hash(snapshot)
    if outcome == "recommend_separate_production_wide_authorization_review":
        item.status = "recommended"
    elif outcome == "extend_bounded_100_percent_cohort":
        item.status = "extended"
    else:
        item.status = "stopped"
    _audit(db, user, "DECIDE_AI_BOUNDED_FULL_PRODUCTION_WIDE_READINESS", item,
           {"status": item.status, "outcome": outcome, "decision_hash": item.decision_hash,
            "production_wide_unbounded_authorized": False},
           "Recommendation-only Sprint 11S decision; any unbounded Production-wide authorization remains separately governed.")
    db.commit(); db.refresh(item)
    return assessment_response(db, item)
