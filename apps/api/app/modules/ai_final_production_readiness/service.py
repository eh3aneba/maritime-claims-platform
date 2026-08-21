import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from statistics import median
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.ai_final_production_readiness.models import (
    AIFinalProductionReadinessAssessment,
    AIFinalProductionReadinessClaimEvidence,
    AIFinalProductionReadinessControlEvidence,
    AIFinalProductionReadinessReview,
)
from app.modules.ai_final_production_readiness.schemas import (
    AIFinalProductionReadinessClaimEvidenceCreate,
    AIFinalProductionReadinessControlEvidenceCreate,
    AIFinalProductionReadinessCreate,
)
from app.modules.ai_high_coverage.models import (
    AIHighCoverageAuthorization,
    AIHighCoverageIncident,
    AIHighCoverageMonitor,
    AIHighCoverageRun,
)
from app.modules.ai_high_coverage_outcomes.models import AIHighCoverageOutcomeAssessment
from app.modules.audit.service import write_audit_log
from app.modules.claims.models import Claim
from app.modules.users.models import User

REFERENCE = re.compile(r"^(artifact|runbook|ticket|monitor)://[A-Za-z0-9._:/-]{3,450}$")
REVIEW_ROLES = {
    "product", "quality", "risk", "operations", "security", "privacy",
    "claims_governance", "ai_quality",
}
CONTROL_KEYS = {
    "kill_switch_rehearsal",
    "fail_closed_no_fallback",
    "audit_traceability",
    "model_change_governance",
    "bundle_rollback_target",
    "unit_economics",
    "operations_oncall_ownership",
    "monitoring_retention_sustainability",
    "privacy_access_control",
    "data_retention_legal_basis",
}
RETRY_STATUSES = {"failed", "review_rejected", "extended", "stopped"}
SAFETY_INCIDENT_CATEGORIES = {"privacy", "security", "cross_tenant"}
BLOCKING_INCIDENT_SEVERITIES = {"critical", "high"}
REQUIRED_WORKFLOWS = {"chief_engineer_report", "engine_log"}


def _reference(value: str) -> str:
    reference = value.strip()
    if not REFERENCE.fullmatch(reference):
        raise HTTPException(422, "Evidence must use a bounded allowlisted reference")
    return reference


def _hash(payload: dict) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _audit(db: Session, user: User, action: str, item: AIFinalProductionReadinessAssessment,
           values: dict, details: str) -> None:
    write_audit_log(
        db, organization_id=user.organization_id, user_id=user.id, action=action,
        entity_type="ai_final_production_readiness_assessment", entity_id=item.id,
        new_values=values, details=details,
    )


def _outcome(db: Session, organization_id: UUID, outcome_id: UUID) -> AIHighCoverageOutcomeAssessment:
    item = db.scalar(select(AIHighCoverageOutcomeAssessment).where(
        AIHighCoverageOutcomeAssessment.id == outcome_id,
        AIHighCoverageOutcomeAssessment.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Sprint 11L final-readiness recommendation not found")
    return item


def _authorization(db: Session, outcome: AIHighCoverageOutcomeAssessment) -> AIHighCoverageAuthorization:
    item = db.scalar(select(AIHighCoverageAuthorization).where(
        AIHighCoverageAuthorization.id == outcome.high_coverage_authorization_id,
        AIHighCoverageAuthorization.organization_id == outcome.organization_id,
    ))
    if item is None:
        raise HTTPException(409, "The inherited Sprint 11K authorization is missing")
    return item


def _claims(db: Session, assessment_id: UUID) -> list[AIFinalProductionReadinessClaimEvidence]:
    return list(db.scalars(select(AIFinalProductionReadinessClaimEvidence).where(
        AIFinalProductionReadinessClaimEvidence.assessment_id == assessment_id,
    ).order_by(AIFinalProductionReadinessClaimEvidence.observed_at.asc(),
               AIFinalProductionReadinessClaimEvidence.id.asc())))


def _controls(db: Session, assessment_id: UUID) -> list[AIFinalProductionReadinessControlEvidence]:
    return list(db.scalars(select(AIFinalProductionReadinessControlEvidence).where(
        AIFinalProductionReadinessControlEvidence.assessment_id == assessment_id,
    ).order_by(AIFinalProductionReadinessControlEvidence.control_key.asc())))


def _reviews(db: Session, assessment_id: UUID) -> list[AIFinalProductionReadinessReview]:
    return list(db.scalars(select(AIFinalProductionReadinessReview).where(
        AIFinalProductionReadinessReview.assessment_id == assessment_id,
    ).order_by(AIFinalProductionReadinessReview.review_role.asc())))


def _incidents(db: Session, authorization_id: UUID) -> list[AIHighCoverageIncident]:
    return list(db.scalars(select(AIHighCoverageIncident).where(
        AIHighCoverageIncident.authorization_id == authorization_id,
    ).order_by(AIHighCoverageIncident.reported_at.asc(), AIHighCoverageIncident.id.asc())))


def _monitors(db: Session, authorization_id: UUID) -> list[AIHighCoverageMonitor]:
    return list(db.scalars(select(AIHighCoverageMonitor).where(
        AIHighCoverageMonitor.authorization_id == authorization_id,
    ).order_by(AIHighCoverageMonitor.monitored_at.asc(), AIHighCoverageMonitor.id.asc())))


def _runs(db: Session, authorization_id: UUID) -> list[AIHighCoverageRun]:
    return list(db.scalars(select(AIHighCoverageRun).where(
        AIHighCoverageRun.authorization_id == authorization_id,
    ).order_by(AIHighCoverageRun.queued_at.asc(), AIHighCoverageRun.id.asc())))


def _rate_bps(numerator: int, denominator: int) -> int | None:
    return numerator * 10000 // denominator if denominator else None


def _improvement_bps(baseline: int, assisted: int) -> int:
    return (baseline - assisted) * 10000 // baseline


def _median_int(values: list[int]) -> int | None:
    return int(median(values)) if values else None


def _thresholds(item: AIFinalProductionReadinessAssessment) -> dict:
    return {
        "minimum_real_or_design_partner_claim_workflows": item.min_claim_workflows,
        "minimum_median_tfta_improvement_bps": item.min_tfta_improvement_bps,
        "minimum_median_triage_improvement_bps": item.min_triage_improvement_bps,
        "minimum_median_handler_effort_improvement_bps": item.min_handler_effort_improvement_bps,
        "minimum_mean_handler_usefulness_bps": item.min_handler_usefulness_bps,
        "required_human_final_decision_ownership_rate_bps": 10000,
        "maximum_rework_increase_count": 0,
        "required_enterprise_control_count": len(CONTROL_KEYS),
        "required_enterprise_control_pass_rate_bps": 10000,
        "required_technical_11l_pass": True,
        "required_zero_safety_boundary_incident_history": True,
        "required_zero_unresolved_high_or_critical_incidents": True,
        "required_full_non_safety_recovery": True,
    }


def assessment_response(db: Session, item: AIFinalProductionReadinessAssessment) -> dict:
    claims = _claims(db, item.id)
    controls = _controls(db, item.id)
    reviews = _reviews(db, item.id)
    reviews_complete = bool(
        {entry.review_role for entry in reviews} == REVIEW_ROLES
        and len(reviews) == len(REVIEW_ROLES)
        and all(entry.action == "approve" for entry in reviews)
        and len({entry.reviewer_id for entry in reviews}) == len(REVIEW_ROLES)
        and all(entry.reviewer_id != item.requested_by_id for entry in reviews)
    )
    return {
        "id": item.id,
        "high_coverage_outcome_assessment_id": item.high_coverage_outcome_assessment_id,
        "requested_by_id": item.requested_by_id,
        "finalized_by_id": item.finalized_by_id,
        "attempt_number": item.attempt_number,
        "assessment_key": item.assessment_key,
        "assessment_profile": item.assessment_profile,
        "high_coverage_outcome_assessment_hash": item.high_coverage_outcome_assessment_hash,
        "high_coverage_outcome_decision_hash": item.high_coverage_outcome_decision_hash,
        "inherited_hashes": {
            "high_coverage_decision": item.high_coverage_decision_hash,
            "high_coverage_completion": item.high_coverage_completion_hash,
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
        "claim_evidence": claims,
        "control_evidence": controls,
        "reviews": reviews,
        "summary": {
            "claim_evidence_count": len(claims),
            "control_evidence_count": len(controls),
            "thresholds_passed": bool(item.metrics and item.metrics.get("overall_pass")),
            "independent_reviews_complete": reviews_complete,
            "separate_final_production_authorization_recommended": (
                item.status == "recommended"
                and item.outcome == "recommend_separate_final_production_authorization"
            ),
            "rollout_above_75_authorized": False,
            "production_wide_authorized": False,
            "restricted_documents_authorized": False,
            "new_document_classes_authorized": False,
            "autonomous_claim_decisions_authorized": False,
            "authoritative_facts_auto_updated": False,
            "different_human_review_required": True,
            "raw_content_stored": False,
        },
        "created_at": item.created_at,
    }


def list_assessments(db: Session, organization_id: UUID) -> list[dict]:
    items = list(db.scalars(select(AIFinalProductionReadinessAssessment).where(
        AIFinalProductionReadinessAssessment.organization_id == organization_id,
    ).order_by(AIFinalProductionReadinessAssessment.created_at.desc()).limit(25)))
    return [assessment_response(db, item) for item in items]


def get_assessment(db: Session, organization_id: UUID,
                   assessment_id: UUID) -> AIFinalProductionReadinessAssessment:
    item = db.scalar(select(AIFinalProductionReadinessAssessment).where(
        AIFinalProductionReadinessAssessment.id == assessment_id,
        AIFinalProductionReadinessAssessment.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Sprint 11M final Production AI readiness assessment not found")
    return item


def _validate_positive_11l(outcome: AIHighCoverageOutcomeAssessment) -> None:
    metrics = outcome.metrics or {}
    if (
        outcome.status != "recommended"
        or outcome.outcome != "recommend_final_production_readiness_review"
        or not metrics.get("overall_pass")
        or not outcome.assessment_hash
        or not outcome.decision_hash
    ):
        raise HTTPException(409, "A positive immutable Sprint 11L recommendation is required")


def _validate_anchor(db: Session, item: AIFinalProductionReadinessAssessment,
                     outcome: AIHighCoverageOutcomeAssessment,
                     authorization: AIHighCoverageAuthorization) -> None:
    _validate_positive_11l(outcome)
    if (
        outcome.assessment_hash != item.high_coverage_outcome_assessment_hash
        or outcome.decision_hash != item.high_coverage_outcome_decision_hash
        or outcome.high_coverage_decision_hash != item.high_coverage_decision_hash
        or outcome.high_coverage_completion_hash != item.high_coverage_completion_hash
        or outcome.broader_outcome_assessment_hash != item.broader_outcome_assessment_hash
        or outcome.broader_outcome_decision_hash != item.broader_outcome_decision_hash
        or outcome.broader_production_decision_hash != item.broader_production_decision_hash
        or outcome.readiness_assessment_hash != item.readiness_assessment_hash
        or outcome.readiness_decision_hash != item.readiness_decision_hash
        or outcome.scale_up_decision_hash != item.scale_up_decision_hash
        or outcome.inherited_outcome_assessment_hash != item.inherited_outcome_assessment_hash
        or outcome.inherited_outcome_decision_hash != item.inherited_outcome_decision_hash
        or outcome.model != item.model
        or outcome.prompt_bundle_version != item.prompt_bundle_version
        or outcome.schema_bundle_version != item.schema_bundle_version
        or outcome.rollout_percentage != item.rollout_percentage
        or authorization.id != outcome.high_coverage_authorization_id
        or authorization.decision_hash != item.high_coverage_decision_hash
        or authorization.completion_hash != item.high_coverage_completion_hash
        or authorization.model != item.model
        or authorization.prompt_bundle_version != item.prompt_bundle_version
        or authorization.schema_bundle_version != item.schema_bundle_version
        or authorization.status != "completed"
        or not 51 <= authorization.rollout_percentage <= 75
    ):
        raise HTTPException(409, "The persisted Sprint 11L/11K evidence anchor no longer matches")


def create_assessment(db: Session, user: User, payload: AIFinalProductionReadinessCreate) -> dict:
    if not payload.confirm_recommendation_only_review:
        raise HTTPException(422, "Explicit recommendation-only review confirmation is required")
    outcome = _outcome(db, user.organization_id, payload.high_coverage_outcome_assessment_id)
    _validate_positive_11l(outcome)
    authorization = _authorization(db, outcome)
    if authorization.status != "completed" or not authorization.decision_hash or not authorization.completion_hash:
        raise HTTPException(409, "The anchored Sprint 11K authorization must remain completed")
    attempts = list(db.scalars(select(AIFinalProductionReadinessAssessment).where(
        AIFinalProductionReadinessAssessment.high_coverage_outcome_assessment_id == outcome.id,
    ).order_by(AIFinalProductionReadinessAssessment.attempt_number.asc())))
    if attempts and attempts[-1].status not in RETRY_STATUSES:
        raise HTTPException(409, "The current Sprint 11M review is still active")
    item = AIFinalProductionReadinessAssessment(
        organization_id=user.organization_id,
        high_coverage_outcome_assessment_id=outcome.id,
        requested_by_id=user.id,
        attempt_number=len(attempts) + 1,
        assessment_key=payload.assessment_key.strip(),
        high_coverage_outcome_assessment_hash=outcome.assessment_hash,
        high_coverage_outcome_decision_hash=outcome.decision_hash,
        high_coverage_decision_hash=outcome.high_coverage_decision_hash,
        high_coverage_completion_hash=outcome.high_coverage_completion_hash,
        broader_outcome_assessment_hash=outcome.broader_outcome_assessment_hash,
        broader_outcome_decision_hash=outcome.broader_outcome_decision_hash,
        broader_production_decision_hash=outcome.broader_production_decision_hash,
        readiness_assessment_hash=outcome.readiness_assessment_hash,
        readiness_decision_hash=outcome.readiness_decision_hash,
        scale_up_decision_hash=outcome.scale_up_decision_hash,
        inherited_outcome_assessment_hash=outcome.inherited_outcome_assessment_hash,
        inherited_outcome_decision_hash=outcome.inherited_outcome_decision_hash,
        model=outcome.model,
        prompt_bundle_version=outcome.prompt_bundle_version,
        schema_bundle_version=outcome.schema_bundle_version,
        rollout_percentage=outcome.rollout_percentage,
        status="collecting",
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Assessment key or attempt already exists") from exc
    _audit(db, user, "CREATE_AI_FINAL_PRODUCTION_READINESS_ASSESSMENT", item,
           {"11l_assessment_id": str(outcome.id), "attempt_number": item.attempt_number,
            "production_wide_authorized": False, "raw_content_stored": False},
           "Sprint 11M recommendation-only final Production AI readiness review created.")
    db.commit(); db.refresh(item)
    return assessment_response(db, item)


def record_claim_evidence(db: Session, user: User, item: AIFinalProductionReadinessAssessment,
                          payload: AIFinalProductionReadinessClaimEvidenceCreate) -> dict:
    if not payload.confirm_content_free_productivity_evidence:
        raise HTTPException(422, "Explicit content-free productivity evidence confirmation is required")
    if item.status != "collecting":
        raise HTTPException(409, "This final readiness review no longer accepts productivity evidence")
    outcome = _outcome(db, user.organization_id, item.high_coverage_outcome_assessment_id)
    authorization = _authorization(db, outcome)
    _validate_anchor(db, item, outcome, authorization)
    claim = db.scalar(select(Claim).where(
        Claim.id == payload.claim_id, Claim.organization_id == user.organization_id,
    ))
    if claim is None:
        raise HTTPException(404, "Claim not found in this tenant")
    now = datetime.now(UTC)
    reference = _reference(payload.evidence_reference)
    snapshot = {
        "schema": "mcri-ai-final-production-readiness-claim-evidence-v1",
        "assessment_id": str(item.id), "claim_id": str(claim.id),
        "evidence_key": payload.evidence_key.strip(), "workflow_type": payload.workflow_type,
        "baseline_tfta_seconds": payload.baseline_tfta_seconds,
        "assisted_tfta_seconds": payload.assisted_tfta_seconds,
        "baseline_triage_seconds": payload.baseline_triage_seconds,
        "assisted_triage_seconds": payload.assisted_triage_seconds,
        "baseline_handler_effort_seconds": payload.baseline_handler_effort_seconds,
        "assisted_handler_effort_seconds": payload.assisted_handler_effort_seconds,
        "baseline_rework_count": payload.baseline_rework_count,
        "assisted_rework_count": payload.assisted_rework_count,
        "handler_usefulness_rating": payload.handler_usefulness_rating,
        "final_claim_decision_human_owned": payload.final_claim_decision_human_owned,
        "evidence_reference": reference, "observed_at": now.isoformat(), "raw_content_stored": False,
    }
    evidence = AIFinalProductionReadinessClaimEvidence(
        organization_id=user.organization_id, assessment_id=item.id, claim_id=claim.id,
        recorded_by_id=user.id, evidence_key=payload.evidence_key.strip(), workflow_type=payload.workflow_type,
        baseline_tfta_seconds=payload.baseline_tfta_seconds, assisted_tfta_seconds=payload.assisted_tfta_seconds,
        baseline_triage_seconds=payload.baseline_triage_seconds, assisted_triage_seconds=payload.assisted_triage_seconds,
        baseline_handler_effort_seconds=payload.baseline_handler_effort_seconds,
        assisted_handler_effort_seconds=payload.assisted_handler_effort_seconds,
        baseline_rework_count=payload.baseline_rework_count, assisted_rework_count=payload.assisted_rework_count,
        handler_usefulness_rating=payload.handler_usefulness_rating,
        final_claim_decision_human_owned=payload.final_claim_decision_human_owned,
        evidence_reference=reference, note=payload.note.strip(), evidence_hash=_hash(snapshot), observed_at=now,
    )
    db.add(evidence)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This productivity evidence key already exists") from exc
    _audit(db, user, "RECORD_AI_FINAL_PRODUCTION_PRODUCTIVITY_EVIDENCE", item,
           {"claim_id": str(claim.id), "workflow_type": payload.workflow_type,
            "evidence_hash": evidence.evidence_hash, "raw_content_stored": False},
           "Content-free baseline-versus-assisted handler productivity evidence recorded.")
    db.commit(); db.refresh(item)
    return assessment_response(db, item)


def record_control_evidence(db: Session, user: User, item: AIFinalProductionReadinessAssessment,
                            payload: AIFinalProductionReadinessControlEvidenceCreate) -> dict:
    if not payload.confirm_control_evidence:
        raise HTTPException(422, "Explicit enterprise-control evidence confirmation is required")
    if item.status != "collecting":
        raise HTTPException(409, "This final readiness review no longer accepts control evidence")
    outcome = _outcome(db, user.organization_id, item.high_coverage_outcome_assessment_id)
    authorization = _authorization(db, outcome)
    _validate_anchor(db, item, outcome, authorization)
    now = datetime.now(UTC)
    reference = _reference(payload.evidence_reference)
    snapshot = {
        "schema": "mcri-ai-final-production-readiness-control-evidence-v1",
        "assessment_id": str(item.id), "control_key": payload.control_key,
        "passed": payload.passed, "evidence_reference": reference,
        "observed_at": now.isoformat(), "raw_content_stored": False,
    }
    evidence = AIFinalProductionReadinessControlEvidence(
        organization_id=user.organization_id, assessment_id=item.id, recorded_by_id=user.id,
        control_key=payload.control_key, passed=payload.passed, evidence_reference=reference,
        note=payload.note.strip(), evidence_hash=_hash(snapshot), observed_at=now,
    )
    db.add(evidence)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This enterprise control already has evidence") from exc
    _audit(db, user, "RECORD_AI_FINAL_PRODUCTION_CONTROL_EVIDENCE", item,
           {"control_key": payload.control_key, "passed": payload.passed,
            "evidence_hash": evidence.evidence_hash},
           "Bounded Sprint 11M enterprise-control evidence recorded.")
    db.commit(); db.refresh(item)
    return assessment_response(db, item)


def _technical_gate(outcome: AIHighCoverageOutcomeAssessment) -> tuple[bool, list[str], dict]:
    metrics = outcome.metrics or {}
    failures: list[str] = []
    checks = {
        "overall_pass": metrics.get("overall_pass") is True,
        "min_runs": (metrics.get("human_reviewed_run_count") or 0) >= 80,
        "different_human": metrics.get("different_human_review_rate_bps") == 10000,
        "reject": (metrics.get("human_reject_rate_bps") is not None and metrics.get("human_reject_rate_bps") <= 500),
        "edit": (metrics.get("human_edit_rate_bps") is not None and metrics.get("human_edit_rate_bps") <= 2000),
        "usefulness": (metrics.get("mean_usefulness_bps") is not None and metrics.get("mean_usefulness_bps") >= 9000),
        "unsupported": (metrics.get("unsupported_output_rate_bps") is not None and metrics.get("unsupported_output_rate_bps") <= 25),
        "grounding": (metrics.get("source_grounding_validity_bps") is not None and metrics.get("source_grounding_validity_bps") >= 9975),
        "review_effort": (metrics.get("mean_review_seconds") is not None and metrics.get("mean_review_seconds") <= 300),
        "latency": (metrics.get("p95_latency_ms") is not None and metrics.get("p95_latency_ms") <= 15000),
        "cost": (metrics.get("mean_observed_provider_cost_microusd") is not None and metrics.get("mean_observed_provider_cost_microusd") <= 400000),
        "recovery": (metrics.get("rollback_recovery") or {}).get("recovery_rate_bps") == 10000,
        "fresh_monitor": (metrics.get("monitor_history") or {}).get("latest_monitor_fresh") is True,
        "zero_safety": (metrics.get("incident_history") or {}).get("safety_boundary_incident_count") == 0,
        "zero_unresolved_high_critical": (metrics.get("incident_history") or {}).get("unresolved_high_or_critical_count") == 0,
    }
    for key, passed in checks.items():
        if not passed:
            failures.append(f"technical_11l_{key}")
    return not failures, failures, {"checks": checks, "source_metrics": metrics}


def finalize_assessment(db: Session, user: User, item: AIFinalProductionReadinessAssessment,
                        confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit final Production AI readiness finalization is required")
    if item.status != "collecting":
        raise HTTPException(409, "This final readiness assessment is immutable")
    outcome = _outcome(db, user.organization_id, item.high_coverage_outcome_assessment_id)
    authorization = _authorization(db, outcome)
    _validate_anchor(db, item, outcome, authorization)

    claim_evidence = _claims(db, item.id)
    control_evidence = _controls(db, item.id)
    incidents = _incidents(db, authorization.id)
    monitors = _monitors(db, authorization.id)
    runs = _runs(db, authorization.id)
    technical_pass, technical_failures, technical = _technical_gate(outcome)

    tfta = [_improvement_bps(e.baseline_tfta_seconds, e.assisted_tfta_seconds) for e in claim_evidence]
    triage = [_improvement_bps(e.baseline_triage_seconds, e.assisted_triage_seconds) for e in claim_evidence]
    effort = [_improvement_bps(e.baseline_handler_effort_seconds, e.assisted_handler_effort_seconds) for e in claim_evidence]
    usefulness_bps = (sum(e.handler_usefulness_rating for e in claim_evidence) * 2000 // len(claim_evidence)) if claim_evidence else None
    human_owned_rate = _rate_bps(sum(e.final_claim_decision_human_owned for e in claim_evidence), len(claim_evidence))
    baseline_rework = sum(e.baseline_rework_count for e in claim_evidence)
    assisted_rework = sum(e.assisted_rework_count for e in claim_evidence)
    workflow_counts = {workflow: sum(e.workflow_type == workflow for e in claim_evidence) for workflow in REQUIRED_WORKFLOWS}
    controls_by_key = {entry.control_key: entry for entry in control_evidence}
    missing_controls = sorted(CONTROL_KEYS - set(controls_by_key))
    failed_controls = sorted(key for key, entry in controls_by_key.items() if not entry.passed)
    actual_safety_incidents = [entry for entry in incidents if entry.category in SAFETY_INCIDENT_CATEGORIES]
    unresolved_high_critical = [entry for entry in incidents if entry.status == "open" and entry.severity in BLOCKING_INCIDENT_SEVERITIES]
    self_reviewed_runs = [entry for entry in runs if entry.requested_by_id == entry.reviewed_by_id]

    failures = list(technical_failures)
    if len(claim_evidence) < item.min_claim_workflows:
        failures.append("minimum_claim_workflow_evidence")
    if REQUIRED_WORKFLOWS <= set(authorization.allowed_document_types):
        for workflow in REQUIRED_WORKFLOWS:
            if workflow_counts[workflow] == 0:
                failures.append(f"missing_{workflow}_business_value_evidence")
    median_tfta = _median_int(tfta)
    median_triage = _median_int(triage)
    median_effort = _median_int(effort)
    if median_tfta is None or median_tfta < item.min_tfta_improvement_bps:
        failures.append("median_time_to_first_assessment_improvement")
    if median_triage is None or median_triage < item.min_triage_improvement_bps:
        failures.append("median_triage_chronology_improvement")
    if median_effort is None or median_effort < item.min_handler_effort_improvement_bps:
        failures.append("median_net_handler_effort_improvement")
    if usefulness_bps is None or usefulness_bps < item.min_handler_usefulness_bps:
        failures.append("mean_handler_usefulness")
    if human_owned_rate != 10000:
        failures.append("human_final_claim_decision_ownership")
    if assisted_rework > baseline_rework:
        failures.append("ai_caused_rework_increase")
    if missing_controls:
        failures.append("missing_enterprise_controls")
    if failed_controls:
        failures.append("failed_enterprise_controls")
    if actual_safety_incidents:
        failures.append("privacy_security_or_cross_tenant_incident_history")
    if unresolved_high_critical:
        failures.append("unresolved_high_or_critical_incident")
    if self_reviewed_runs:
        failures.append("different_human_review_violation")
    if not monitors or monitors[-1].status != "pass":
        failures.append("final_monitor_not_passing")
    failures = sorted(set(failures))

    metrics = {
        "technical_11l": technical,
        "business_value": {
            "claim_workflow_count": len(claim_evidence),
            "workflow_counts": workflow_counts,
            "median_tfta_improvement_bps": median_tfta,
            "median_triage_improvement_bps": median_triage,
            "median_handler_effort_improvement_bps": median_effort,
            "mean_handler_usefulness_bps": usefulness_bps,
            "human_final_decision_ownership_rate_bps": human_owned_rate,
            "baseline_rework_count": baseline_rework,
            "assisted_rework_count": assisted_rework,
            "rework_increase_count": max(0, assisted_rework - baseline_rework),
        },
        "enterprise_controls": {
            "required_count": len(CONTROL_KEYS),
            "evidence_count": len(control_evidence),
            "missing_controls": missing_controls,
            "failed_controls": failed_controls,
            "pass_rate_bps": _rate_bps(sum(entry.passed for entry in control_evidence), len(CONTROL_KEYS)),
        },
        "safety_validation": {
            "actual_safety_boundary_incident_count": len(actual_safety_incidents),
            "unresolved_high_or_critical_count": len(unresolved_high_critical),
            "self_reviewed_run_count": len(self_reviewed_runs),
            "latest_monitor_status": monitors[-1].status if monitors else None,
        },
        "overall_pass": technical_pass and not failures,
        "raw_content_stored": False,
        "rollout_above_75_authorized": False,
        "production_wide_authorized": False,
        "restricted_documents_authorized": False,
        "new_document_classes_authorized": False,
        "autonomous_claim_decisions_authorized": False,
    }
    assessed_at = datetime.now(UTC)
    snapshot = {
        "schema": "mcri-ai-final-production-readiness-assessment-v1",
        "assessment_id": str(item.id),
        "11l_assessment_hash": item.high_coverage_outcome_assessment_hash,
        "11l_decision_hash": item.high_coverage_outcome_decision_hash,
        "11k_decision_hash": item.high_coverage_decision_hash,
        "11k_completion_hash": item.high_coverage_completion_hash,
        "bundle": {"model": item.model, "prompt": item.prompt_bundle_version,
                   "schema": item.schema_bundle_version, "rollout_percentage": item.rollout_percentage},
        "thresholds": _thresholds(item), "metrics": metrics, "failure_reasons": failures,
        "claim_evidence_hashes": [entry.evidence_hash for entry in claim_evidence],
        "control_evidence_hashes": [entry.evidence_hash for entry in control_evidence],
        "assessed_at": assessed_at.isoformat(), "note": note.strip(),
        "recommendation_only": True, "production_wide_authorized": False,
        "rollout_above_75_authorized": False, "raw_content_stored": False,
    }
    item.metrics = metrics
    item.failure_reasons = failures
    item.assessment_note = note.strip()
    item.assessed_at = assessed_at
    item.finalized_by_id = user.id
    item.assessment_hash = _hash(snapshot)
    item.status = "review_ready"
    _audit(db, user, "FINALIZE_AI_FINAL_PRODUCTION_READINESS_ASSESSMENT", item,
           {"overall_pass": not failures, "failure_reasons": failures,
            "assessment_hash": item.assessment_hash, "production_wide_authorized": False},
           "Immutable Sprint 11M technical + business-value + enterprise-control scorecard finalized.")
    db.commit(); db.refresh(item)
    return assessment_response(db, item)


def record_review(db: Session, user: User, item: AIFinalProductionReadinessAssessment,
                  role: str, action: str, evidence_reference: str | None, note: str) -> dict:
    if item.status not in {"review_ready", "decision_ready"}:
        raise HTTPException(409, "Only a finalized Sprint 11M assessment can be reviewed")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The assessment requester cannot review the final Production readiness package")
    reviews = _reviews(db, item.id)
    if any(entry.review_role == role for entry in reviews):
        raise HTTPException(409, "This review role already has a decision")
    if any(entry.reviewer_id == user.id for entry in reviews):
        raise HTTPException(409, "All eight Sprint 11M review roles require different people")
    reference = _reference(evidence_reference) if evidence_reference else None
    if action == "approve" and not reference:
        raise HTTPException(422, "Approval requires bounded evidence")
    review = AIFinalProductionReadinessReview(
        organization_id=user.organization_id, assessment_id=item.id, reviewer_id=user.id,
        review_role=role, action=action, evidence_reference=reference,
        note=note.strip(), reviewed_at=datetime.now(UTC),
    )
    db.add(review); db.flush()
    if action == "reject":
        item.status = "review_rejected"; item.outcome = "review_rejected"
    else:
        current = _reviews(db, item.id)
        item.status = "decision_ready" if (
            {entry.review_role for entry in current} == REVIEW_ROLES
            and len(current) == len(REVIEW_ROLES)
            and all(entry.action == "approve" for entry in current)
            and len({entry.reviewer_id for entry in current}) == len(REVIEW_ROLES)
            and all(entry.reviewer_id != item.requested_by_id for entry in current)
        ) else "review_ready"
    _audit(db, user, f"{action.upper()}_AI_FINAL_PRODUCTION_READINESS_REVIEW", item,
           {"review_role": role, "action": action, "status": item.status},
           "Independent Sprint 11M final Production AI readiness review recorded.")
    db.commit(); db.refresh(item)
    return assessment_response(db, item)


def decide_outcome(db: Session, user: User, item: AIFinalProductionReadinessAssessment,
                   outcome: str, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit recommendation-only final decision confirmation is required")
    if item.status != "decision_ready":
        raise HTTPException(409, "Eight independent approvals are required")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The requester cannot issue the Sprint 11M final decision")
    reviews = _reviews(db, item.id)
    if user.id in {entry.reviewer_id for entry in reviews}:
        raise HTTPException(409, "The final Admin must be distinct from all eight reviewers")
    if (
        {entry.review_role for entry in reviews} != REVIEW_ROLES
        or len(reviews) != len(REVIEW_ROLES)
        or len({entry.reviewer_id for entry in reviews}) != len(REVIEW_ROLES)
        or any(entry.action != "approve" for entry in reviews)
    ):
        raise HTTPException(409, "Eight distinct independent review roles must remain approved")
    outcome_anchor = _outcome(db, user.organization_id, item.high_coverage_outcome_assessment_id)
    authorization = _authorization(db, outcome_anchor)
    _validate_anchor(db, item, outcome_anchor, authorization)
    if outcome == "recommend_separate_final_production_authorization" and (
        item.failure_reasons or not item.metrics or not item.metrics.get("overall_pass")
    ):
        raise HTTPException(409, "Final authorization recommendation requires zero failed controls")
    snapshot = {
        "schema": "mcri-ai-final-production-readiness-decision-v1",
        "assessment_id": str(item.id), "assessment_hash": item.assessment_hash,
        "11l_decision_hash": item.high_coverage_outcome_decision_hash,
        "reviewers": [{"role": entry.review_role, "reviewer_id": str(entry.reviewer_id),
                       "evidence_reference": entry.evidence_reference} for entry in reviews],
        "final_admin_id": str(user.id), "outcome": outcome, "note": note.strip(),
        "recommendation_only": True, "rollout_above_75_authorized": False,
        "production_wide_authorized": False, "restricted_documents_authorized": False,
        "new_document_classes_authorized": False, "autonomous_claim_decisions_authorized": False,
    }
    item.outcome = outcome
    item.decision_note = note.strip()
    item.decided_at = datetime.now(UTC)
    item.finalized_by_id = user.id
    item.decision_hash = _hash(snapshot)
    item.status = (
        "recommended" if outcome == "recommend_separate_final_production_authorization"
        else "extended" if outcome == "extend_high_coverage_validation"
        else "stopped"
    )
    _audit(db, user, "DECIDE_AI_FINAL_PRODUCTION_READINESS_RECOMMENDATION", item,
           {"status": item.status, "outcome": outcome, "decision_hash": item.decision_hash,
            "production_wide_authorized": False, "rollout_above_75_authorized": False},
           "Recommendation-only Sprint 11M decision; any final Production authorization remains separate.")
    db.commit(); db.refresh(item)
    return assessment_response(db, item)
