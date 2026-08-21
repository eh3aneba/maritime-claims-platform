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

from app.core.config import get_settings
from app.modules.ai_final_production.models import AIFinalProductionAuthorization
from app.modules.ai_final_production_outcomes.models import AIFinalProductionOutcomeAssessment
from app.modules.ai_near_universal_production.models import (
    AINearUniversalApproval,
    AINearUniversalAuthorization,
    AINearUniversalDocumentEligibility,
    AINearUniversalIncident,
    AINearUniversalMonitor,
    AINearUniversalRun,
)
from app.modules.ai_near_universal_production.schemas import AINearUniversalCreate, AINearUniversalDocumentCreate
from app.modules.audit.service import write_audit_log
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.processing.models import DocumentProcessingJob, ProcessingJobStatus
from app.modules.users.models import User

REFERENCE = re.compile(r"^(artifact|runbook|ticket|monitor)://[A-Za-z0-9._:/-]{3,450}$")
APPROVAL_ROLES = {
    "security", "privacy", "product", "quality", "operations", "risk",
    "claims_governance", "ai_quality", "legal_data_governance", "business_owner",
    "platform_reliability",
}
ALLOWED_DOCUMENT_TYPES = {"chief_engineer_report", "engine_log"}
SAFETY_CATEGORIES = {"privacy", "security", "cross_tenant"}
BLOCKING_SEVERITIES = {"high", "critical"}


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _reference(value: str) -> str:
    reference = value.strip()
    if not REFERENCE.fullmatch(reference):
        raise HTTPException(422, "Near-universal evidence must use a bounded allowlisted reference")
    return reference


def _hash(payload: dict) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _audit(db: Session, user: User, action: str, entity_type: str, entity_id: UUID,
           values: dict, details: str) -> None:
    write_audit_log(
        db, organization_id=user.organization_id, user_id=user.id, action=action,
        entity_type=entity_type, entity_id=entity_id, new_values=values, details=details,
    )


def _approvals(db: Session, authorization_id: UUID) -> list[AINearUniversalApproval]:
    return list(db.scalars(select(AINearUniversalApproval).where(
        AINearUniversalApproval.authorization_id == authorization_id,
    ).order_by(AINearUniversalApproval.approval_role.asc())))


def _documents(db: Session, authorization_id: UUID) -> list[AINearUniversalDocumentEligibility]:
    return list(db.scalars(select(AINearUniversalDocumentEligibility).where(
        AINearUniversalDocumentEligibility.authorization_id == authorization_id,
    ).order_by(AINearUniversalDocumentEligibility.created_at.asc())))


def _runs(db: Session, authorization_id: UUID) -> list[AINearUniversalRun]:
    return list(db.scalars(select(AINearUniversalRun).where(
        AINearUniversalRun.authorization_id == authorization_id,
    ).order_by(AINearUniversalRun.queued_at.asc(), AINearUniversalRun.id.asc())))


def _monitors(db: Session, authorization_id: UUID) -> list[AINearUniversalMonitor]:
    return list(db.scalars(select(AINearUniversalMonitor).where(
        AINearUniversalMonitor.authorization_id == authorization_id,
    ).order_by(AINearUniversalMonitor.monitored_at.asc(), AINearUniversalMonitor.id.asc())))


def _incidents(db: Session, authorization_id: UUID) -> list[AINearUniversalIncident]:
    return list(db.scalars(select(AINearUniversalIncident).where(
        AINearUniversalIncident.authorization_id == authorization_id,
    ).order_by(AINearUniversalIncident.reported_at.asc(), AINearUniversalIncident.id.asc())))


def latest_near_universal_attempt(db: Session, organization_id: UUID) -> AINearUniversalAuthorization | None:
    return db.scalar(select(AINearUniversalAuthorization).where(
        AINearUniversalAuthorization.organization_id == organization_id,
    ).order_by(AINearUniversalAuthorization.created_at.desc(), AINearUniversalAuthorization.id.desc()))


def _active(item: AINearUniversalAuthorization) -> bool:
    now = datetime.now(UTC)
    return item.status == "authorized" and _as_utc(item.starts_at) <= now < _as_utc(item.expires_at)


def _rollout_bucket(document_id: UUID) -> int:
    return int(sha256(str(document_id).encode()).hexdigest()[:8], 16) % 100


def _controls(item: AINearUniversalAuthorization) -> dict:
    return {
        "rollback_slo_minutes": item.rollback_slo_minutes,
        "monitor_interval_minutes": item.monitor_interval_minutes,
        "required_human_review_rate_bps": 10000,
        "required_different_human_review_rate_bps": 10000,
        "max_reject_rate_bps": item.max_reject_rate_bps,
        "max_edit_rate_bps": item.max_edit_rate_bps,
        "max_unsupported_output_rate_bps": item.max_unsupported_output_rate_bps,
        "min_source_grounding_validity_bps": item.min_source_grounding_validity_bps,
        "max_p95_latency_ms": item.max_p95_latency_ms,
        "max_mean_observed_provider_cost_microusd": item.max_mean_cost_microusd,
        "max_quality_regression_bps": item.max_quality_regression_bps,
        "max_latency_regression_bps": item.max_latency_regression_bps,
        "max_cost_regression_bps": item.max_cost_regression_bps,
        "max_open_high_or_critical_incident_count": 0,
        "max_safety_boundary_incident_count": 0,
    }


def _latest_monitor_pass(db: Session, item: AINearUniversalAuthorization, *, require_fresh: bool) -> bool:
    monitors = _monitors(db, item.id)
    if not monitors or monitors[-1].status != "pass":
        return False
    if not require_fresh:
        return True
    freshness = timedelta(minutes=item.monitor_interval_minutes * 2)
    return _as_utc(monitors[-1].monitored_at) >= datetime.now(UTC) - freshness


def _recovery_complete(db: Session, item: AINearUniversalAuthorization) -> bool:
    monitors = _monitors(db, item.id)
    for incident in _incidents(db, item.id):
        if incident.category in SAFETY_CATEGORIES:
            return False
        if incident.status != "resolved" or incident.resolved_at is None:
            return False
        if not any(
            monitor.status == "pass" and _as_utc(monitor.monitored_at) >= _as_utc(incident.resolved_at)
            for monitor in monitors
        ):
            return False
    return True


def authorization_response(db: Session, item: AINearUniversalAuthorization) -> dict:
    approvals = _approvals(db, item.id)
    documents = _documents(db, item.id)
    runs = _runs(db, item.id)
    monitors = _monitors(db, item.id)
    incidents = _incidents(db, item.id)
    active_documents = [entry for entry in documents if entry.status == "eligible"]
    reviewed_runs = [entry for entry in runs if entry.status == "human_reviewed"]
    approvals_complete = bool(
        {entry.approval_role for entry in approvals} == APPROVAL_ROLES
        and len(approvals) == len(APPROVAL_ROLES)
        and all(entry.action == "approve" for entry in approvals)
        and len({entry.approver_id for entry in approvals}) == len(APPROVAL_ROLES)
        and all(entry.approver_id != item.requested_by_id for entry in approvals)
    )
    active = _active(item)
    return {
        "id": item.id,
        "outcome_assessment_id": item.outcome_assessment_id,
        "final_production_authorization_id": item.final_production_authorization_id,
        "requested_by_id": item.requested_by_id,
        "finalized_by_id": item.finalized_by_id,
        "revoked_by_id": item.revoked_by_id,
        "attempt_number": item.attempt_number,
        "authorization_key": item.authorization_key,
        "environment": item.environment,
        "authorization_mode": item.authorization_mode,
        "outcome_assessment_hash": item.outcome_assessment_hash,
        "outcome_decision_hash": item.outcome_decision_hash,
        "inherited_hashes": {
            "final_production_decision": item.final_production_decision_hash,
            "final_production_completion": item.final_production_completion_hash,
            "final_readiness_assessment": item.final_readiness_assessment_hash,
            "final_readiness_decision": item.final_readiness_decision_hash,
            "high_coverage_outcome_assessment": item.high_coverage_outcome_assessment_hash,
            "high_coverage_outcome_decision": item.high_coverage_outcome_decision_hash,
            "high_coverage_decision": item.high_coverage_decision_hash,
            "high_coverage_completion": item.high_coverage_completion_hash,
            "broader_outcome_assessment": item.broader_outcome_assessment_hash,
            "broader_outcome_decision": item.broader_outcome_decision_hash,
            "broader_production_decision": item.broader_production_decision_hash,
            "scale_readiness_assessment": item.scale_readiness_assessment_hash,
            "scale_readiness_decision": item.scale_readiness_decision_hash,
            "scale_up_decision": item.scale_up_decision_hash,
            "limited_outcome_assessment": item.inherited_outcome_assessment_hash,
            "limited_outcome_decision": item.inherited_outcome_decision_hash,
        },
        "bundle": {
            "model": item.model, "prompt_bundle_version": item.prompt_bundle_version,
            "schema_bundle_version": item.schema_bundle_version, "max_input_chars": item.max_input_chars,
            "max_output_tokens": item.max_output_tokens,
        },
        "allowed_document_types": item.allowed_document_types,
        "previous_rollout_percentage": item.previous_rollout_percentage,
        "rollout_percentage": item.rollout_percentage,
        "previous_caps": {
            "claims": item.previous_max_claims, "documents": item.previous_max_documents,
            "users": item.previous_max_users, "provider_runs": item.previous_max_provider_runs,
        },
        "max_claims": item.max_claims,
        "max_documents": item.max_documents,
        "max_users": item.max_users,
        "max_provider_runs": item.max_provider_runs,
        "starts_at": item.starts_at,
        "expires_at": item.expires_at,
        "controls": _controls(item),
        "references": {
            "deployment_isolation": item.deployment_isolation_reference,
            "provider_project": item.provider_project_reference,
            "credential_control": item.credential_control_reference,
            "privacy_legal": item.privacy_legal_reference,
            "monitoring": item.monitoring_reference,
            "incident_response": item.incident_response_reference,
            "rollback": item.rollback_reference,
            "platform_reliability": item.platform_reliability_reference,
            "change_ticket": item.change_ticket_reference,
        },
        "status": item.status,
        "outcome": item.outcome,
        "decision_note": item.decision_note,
        "decision_hash": item.decision_hash,
        "decided_at": item.decided_at,
        "completed_at": item.completed_at,
        "completion_note": item.completion_note,
        "completion_hash": item.completion_hash,
        "revoked_at": item.revoked_at,
        "revocation_note": item.revocation_note,
        "approvals": approvals,
        "document_eligibility": documents,
        "runs": runs,
        "monitors": monitors,
        "incidents": incidents,
        "summary": {
            "independent_approvals_complete": approvals_complete,
            "authorization_active": active,
            "active_claim_count": len({entry.claim_id for entry in active_documents}),
            "active_document_count": len(active_documents),
            "participating_user_count": len({entry.requested_by_id for entry in runs if entry.requested_by_id is not None}),
            "provider_run_count": len(runs),
            "human_reviewed_run_count": len(reviewed_runs),
            "pending_human_review_count": len(runs) - len(reviewed_runs),
            "open_incident_count": sum(entry.status == "open" for entry in incidents),
            "latest_monitor_status": monitors[-1].status if monitors else None,
            "monitor_fresh_and_passing": _latest_monitor_pass(db, item, require_fresh=True),
            "rollback_recovery_complete": _recovery_complete(db, item),
            "near_universal_cohort_authorized": active,
            "rollout_percentage": item.rollout_percentage,
            "rollout_above_90_authorized": active,
            "rollout_100_percent_authorized": False,
            "production_wide_authorized": False,
            "restricted_documents_authorized": False,
            "new_document_classes_authorized": False,
            "autonomous_claim_decisions_authorized": False,
            "authoritative_facts_auto_updated": False,
            "different_human_review_required": True,
            "previous_document_eligibility_carried_forward": False,
            "raw_content_stored_in_control_ledger": False,
        },
        "created_at": item.created_at,
    }


def list_authorizations(db: Session, organization_id: UUID) -> list[dict]:
    items = list(db.scalars(select(AINearUniversalAuthorization).where(
        AINearUniversalAuthorization.organization_id == organization_id,
    ).order_by(AINearUniversalAuthorization.created_at.desc()).limit(20)))
    return [authorization_response(db, item) for item in items]


def get_authorization(db: Session, organization_id: UUID, authorization_id: UUID) -> AINearUniversalAuthorization:
    item = db.scalar(select(AINearUniversalAuthorization).where(
        AINearUniversalAuthorization.id == authorization_id,
        AINearUniversalAuthorization.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Sprint 11P near-universal authorization not found")
    return item


def _outcome(db: Session, organization_id: UUID, assessment_id: UUID) -> AIFinalProductionOutcomeAssessment:
    item = db.scalar(select(AIFinalProductionOutcomeAssessment).where(
        AIFinalProductionOutcomeAssessment.id == assessment_id,
        AIFinalProductionOutcomeAssessment.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Sprint 11O outcome assessment not found")
    return item


def _final_authorization(db: Session, organization_id: UUID, authorization_id: UUID) -> AIFinalProductionAuthorization:
    item = db.scalar(select(AIFinalProductionAuthorization).where(
        AIFinalProductionAuthorization.id == authorization_id,
        AIFinalProductionAuthorization.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(409, "The Sprint 11N anchor is missing")
    return item


def _anchor_still_valid(db: Session, item: AINearUniversalAuthorization) -> None:
    outcome = _outcome(db, item.organization_id, item.outcome_assessment_id)
    final = _final_authorization(db, item.organization_id, item.final_production_authorization_id)
    if (
        outcome.status != "recommended"
        or outcome.outcome != "recommend_separate_91_100_authorization_review"
        or not (outcome.metrics or {}).get("overall_pass")
        or bool(outcome.failure_reasons)
        or outcome.assessment_hash != item.outcome_assessment_hash
        or outcome.decision_hash != item.outcome_decision_hash
        or outcome.final_production_authorization_id != final.id
        or outcome.final_production_decision_hash != item.final_production_decision_hash
        or outcome.final_production_completion_hash != item.final_production_completion_hash
        or outcome.final_readiness_assessment_hash != item.final_readiness_assessment_hash
        or outcome.final_readiness_decision_hash != item.final_readiness_decision_hash
        or outcome.high_coverage_outcome_assessment_hash != item.high_coverage_outcome_assessment_hash
        or outcome.high_coverage_outcome_decision_hash != item.high_coverage_outcome_decision_hash
        or outcome.high_coverage_decision_hash != item.high_coverage_decision_hash
        or outcome.high_coverage_completion_hash != item.high_coverage_completion_hash
        or outcome.broader_outcome_assessment_hash != item.broader_outcome_assessment_hash
        or outcome.broader_outcome_decision_hash != item.broader_outcome_decision_hash
        or outcome.broader_production_decision_hash != item.broader_production_decision_hash
        or outcome.scale_readiness_assessment_hash != item.scale_readiness_assessment_hash
        or outcome.scale_readiness_decision_hash != item.scale_readiness_decision_hash
        or outcome.scale_up_decision_hash != item.scale_up_decision_hash
        or outcome.inherited_outcome_assessment_hash != item.inherited_outcome_assessment_hash
        or outcome.inherited_outcome_decision_hash != item.inherited_outcome_decision_hash
        or outcome.model != item.model
        or outcome.prompt_bundle_version != item.prompt_bundle_version
        or outcome.schema_bundle_version != item.schema_bundle_version
        or outcome.max_input_chars != item.max_input_chars
        or outcome.max_output_tokens != item.max_output_tokens
        or outcome.allowed_document_types != item.allowed_document_types
        or outcome.rollout_percentage != item.previous_rollout_percentage
        or outcome.max_claims != item.previous_max_claims
        or outcome.max_documents != item.previous_max_documents
        or outcome.max_users != item.previous_max_users
        or outcome.max_provider_runs != item.previous_max_provider_runs
        or final.status != "completed"
        or final.decision_hash != item.final_production_decision_hash
        or final.completion_hash != item.final_production_completion_hash
        or final.model != item.model
        or final.prompt_bundle_version != item.prompt_bundle_version
        or final.schema_bundle_version != item.schema_bundle_version
        or final.max_input_chars != item.max_input_chars
        or final.max_output_tokens != item.max_output_tokens
        or final.allowed_document_types != item.allowed_document_types
        or final.rollout_percentage != item.previous_rollout_percentage
        or final.max_claims != item.previous_max_claims
        or final.max_documents != item.previous_max_documents
        or final.max_users != item.previous_max_users
        or final.max_provider_runs != item.previous_max_provider_runs
    ):
        raise HTTPException(409, "The persisted Sprint 11O/11N evidence anchor no longer matches")


def create_authorization(db: Session, user: User, payload: AINearUniversalCreate) -> dict:
    if not payload.confirm_separate_near_universal:
        raise HTTPException(422, "Explicit separate Sprint 11P confirmation is required")
    if any(value.tzinfo is None or value.utcoffset() is None for value in (payload.starts_at, payload.expires_at)):
        raise HTTPException(422, "Authorization timestamps must include a timezone")
    starts = payload.starts_at.astimezone(UTC)
    expires = payload.expires_at.astimezone(UTC)
    now = datetime.now(UTC)
    if starts < now - timedelta(minutes=5) or starts > now + timedelta(days=2):
        raise HTTPException(422, "Sprint 11P start must be current or within two days")
    if expires <= starts or expires - starts > timedelta(days=21):
        raise HTTPException(422, "Sprint 11P authorization must expire within 21 days")
    if payload.max_documents < payload.max_claims:
        raise HTTPException(422, "Document cap cannot be lower than the claim cap")
    allowed = list(dict.fromkeys(payload.allowed_document_types))
    if len(allowed) != len(payload.allowed_document_types) or not set(allowed) <= ALLOWED_DOCUMENT_TYPES:
        raise HTTPException(422, "Document allowlist is duplicated or unsupported")

    outcome = _outcome(db, user.organization_id, payload.outcome_assessment_id)
    if (
        outcome.status != "recommended"
        or outcome.outcome != "recommend_separate_91_100_authorization_review"
        or not (outcome.metrics or {}).get("overall_pass")
        or outcome.failure_reasons
        or not outcome.assessment_hash
        or not outcome.decision_hash
    ):
        raise HTTPException(409, "A passing, positively recommended Sprint 11O assessment is required")
    final = _final_authorization(db, user.organization_id, outcome.final_production_authorization_id)
    if (
        final.status != "completed"
        or not final.decision_hash or not final.completion_hash
        or final.decision_hash != outcome.final_production_decision_hash
        or final.completion_hash != outcome.final_production_completion_hash
        or final.rollout_percentage != outcome.rollout_percentage
        or not 76 <= final.rollout_percentage <= 90
        or final.model != outcome.model
        or final.prompt_bundle_version != outcome.prompt_bundle_version
        or final.schema_bundle_version != outcome.schema_bundle_version
        or final.max_input_chars != outcome.max_input_chars
        or final.max_output_tokens != outcome.max_output_tokens
    ):
        raise HTTPException(409, "The completed Sprint 11N anchor is invalid")
    if not set(allowed) <= set(final.allowed_document_types):
        raise HTTPException(409, "Sprint 11P cannot introduce new document classes")

    prior = list(db.scalars(select(AINearUniversalAuthorization).where(
        AINearUniversalAuthorization.outcome_assessment_id == outcome.id,
    )))
    item = AINearUniversalAuthorization(
        organization_id=user.organization_id,
        outcome_assessment_id=outcome.id,
        final_production_authorization_id=final.id,
        requested_by_id=user.id,
        attempt_number=len(prior) + 1,
        authorization_key=payload.authorization_key.strip(),
        outcome_assessment_hash=outcome.assessment_hash,
        outcome_decision_hash=outcome.decision_hash,
        final_production_decision_hash=outcome.final_production_decision_hash,
        final_production_completion_hash=outcome.final_production_completion_hash,
        final_readiness_assessment_hash=outcome.final_readiness_assessment_hash,
        final_readiness_decision_hash=outcome.final_readiness_decision_hash,
        high_coverage_outcome_assessment_hash=outcome.high_coverage_outcome_assessment_hash,
        high_coverage_outcome_decision_hash=outcome.high_coverage_outcome_decision_hash,
        high_coverage_decision_hash=outcome.high_coverage_decision_hash,
        high_coverage_completion_hash=outcome.high_coverage_completion_hash,
        broader_outcome_assessment_hash=outcome.broader_outcome_assessment_hash,
        broader_outcome_decision_hash=outcome.broader_outcome_decision_hash,
        broader_production_decision_hash=outcome.broader_production_decision_hash,
        scale_readiness_assessment_hash=outcome.scale_readiness_assessment_hash,
        scale_readiness_decision_hash=outcome.scale_readiness_decision_hash,
        scale_up_decision_hash=outcome.scale_up_decision_hash,
        inherited_outcome_assessment_hash=outcome.inherited_outcome_assessment_hash,
        inherited_outcome_decision_hash=outcome.inherited_outcome_decision_hash,
        model=final.model,
        prompt_bundle_version=final.prompt_bundle_version,
        schema_bundle_version=final.schema_bundle_version,
        max_input_chars=final.max_input_chars,
        max_output_tokens=final.max_output_tokens,
        allowed_document_types=allowed,
        previous_rollout_percentage=final.rollout_percentage,
        rollout_percentage=payload.rollout_percentage,
        previous_max_claims=final.max_claims,
        previous_max_documents=final.max_documents,
        previous_max_users=final.max_users,
        previous_max_provider_runs=final.max_provider_runs,
        max_claims=payload.max_claims,
        max_documents=payload.max_documents,
        max_users=payload.max_users,
        max_provider_runs=payload.max_provider_runs,
        starts_at=starts,
        expires_at=expires,
        deployment_isolation_reference=_reference(payload.deployment_isolation_reference),
        provider_project_reference=_reference(payload.provider_project_reference),
        credential_control_reference=_reference(payload.credential_control_reference),
        privacy_legal_reference=_reference(payload.privacy_legal_reference),
        monitoring_reference=_reference(payload.monitoring_reference),
        incident_response_reference=_reference(payload.incident_response_reference),
        rollback_reference=_reference(payload.rollback_reference),
        platform_reliability_reference=_reference(payload.platform_reliability_reference),
        change_ticket_reference=_reference(payload.change_ticket_reference),
        status="pending_approvals",
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Sprint 11P authorization key or attempt already exists")
    _audit(db, user, "CREATE_AI_NEAR_UNIVERSAL_AUTHORIZATION", "ai_near_universal_authorization", item.id,
           {"outcome_assessment_id": str(outcome.id), "previous_rollout_percentage": final.rollout_percentage,
            "rollout_percentage": payload.rollout_percentage, "rollout_100_percent_authorized": False,
            "production_wide_authorized": False},
           "Created an expiring Sprint 11P 91–99% authorization attempt; no rollout is authorized yet.")
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def record_approval(db: Session, user: User, item: AINearUniversalAuthorization,
                    role: str, action: str, evidence_reference: str | None, note: str) -> dict:
    if item.status not in {"pending_approvals", "decision_ready"}:
        raise HTTPException(409, "This authorization is not accepting approvals")
    if role not in APPROVAL_ROLES:
        raise HTTPException(422, "Unsupported Sprint 11P approval role")
    if user.id == item.requested_by_id:
        raise HTTPException(409, "The requester cannot approve the Sprint 11P attempt")
    existing = _approvals(db, item.id)
    if any(entry.approval_role == role for entry in existing):
        raise HTTPException(409, "This approval role already recorded a decision")
    if any(entry.approver_id == user.id for entry in existing):
        raise HTTPException(409, "Each Sprint 11P approval role requires a distinct human")
    reference = _reference(evidence_reference) if evidence_reference else None
    if action == "approve" and reference is None:
        raise HTTPException(422, "Approval requires bounded evidence")
    approval = AINearUniversalApproval(
        organization_id=user.organization_id, authorization_id=item.id, approver_id=user.id,
        approval_role=role, action=action, evidence_reference=reference, note=note.strip(),
        approved_at=datetime.now(UTC),
    )
    db.add(approval)
    db.flush()
    _audit(db, user, f"{action.upper()}_AI_NEAR_UNIVERSAL_APPROVAL", "ai_near_universal_authorization",
           item.id, {"approval_role": role, "action": action}, f"Independent Sprint 11P {role} review recorded.")
    approvals = _approvals(db, item.id)
    if action == "reject":
        item.status = "held"
        item.outcome = "approval_rejected"
    elif (
        len(approvals) == len(APPROVAL_ROLES)
        and {entry.approval_role for entry in approvals} == APPROVAL_ROLES
        and all(entry.action == "approve" for entry in approvals)
        and len({entry.approver_id for entry in approvals}) == len(APPROVAL_ROLES)
    ):
        item.status = "decision_ready"
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def decide_authorization(db: Session, user: User, item: AINearUniversalAuthorization,
                         outcome: str, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit Admin Sprint 11P decision confirmation is required")
    if item.status != "decision_ready":
        raise HTTPException(409, "Eleven independent approvals are required before Admin decision")
    approvals = _approvals(db, item.id)
    reviewer_ids = {entry.approver_id for entry in approvals}
    if (
        len(approvals) != len(APPROVAL_ROLES)
        or {entry.approval_role for entry in approvals} != APPROVAL_ROLES
        or not all(entry.action == "approve" for entry in approvals)
        or len(reviewer_ids) != len(APPROVAL_ROLES)
        or any(entry.approver_id == item.requested_by_id for entry in approvals)
    ):
        raise HTTPException(409, "Independent approval set is incomplete")
    if user.id == item.requested_by_id or user.id in reviewer_ids:
        raise HTTPException(409, "Final Admin must be distinct from the requester and all eleven reviewers")
    _anchor_still_valid(db, item)
    snapshot = {
        "schema": "mcri-ai-near-universal-authorization-v1",
        "authorization_id": str(item.id),
        "outcome_assessment_id": str(item.outcome_assessment_id),
        "outcome_assessment_hash": item.outcome_assessment_hash,
        "outcome_decision_hash": item.outcome_decision_hash,
        "final_production_completion_hash": item.final_production_completion_hash,
        "bundle": {"model": item.model, "prompt": item.prompt_bundle_version,
                   "schema": item.schema_bundle_version, "max_input_chars": item.max_input_chars,
                   "max_output_tokens": item.max_output_tokens,
                   "provider_project_reference": item.provider_project_reference},
        "rollout_percentage": item.rollout_percentage,
        "caps": {"claims": item.max_claims, "documents": item.max_documents,
                 "users": item.max_users, "provider_runs": item.max_provider_runs},
        "approvals": [{"role": entry.approval_role, "approver_id": str(entry.approver_id), "action": entry.action}
                      for entry in approvals],
        "outcome": outcome,
        "rollout_100_percent_authorized": False,
        "production_wide_authorized": False,
        "restricted_documents_authorized": False,
        "autonomous_claim_decisions_authorized": False,
    }
    item.finalized_by_id = user.id
    item.decision_note = note.strip()
    item.decision_hash = _hash(snapshot)
    item.decided_at = datetime.now(UTC)
    if outcome == "authorize_near_universal_91_99_cohort":
        item.status = "authorized"
        item.outcome = outcome
    elif outcome == "hold_for_remediation":
        item.status = "held"
        item.outcome = outcome
    else:
        item.status = "rejected"
        item.outcome = "reject_progression"
    _audit(db, user, "DECIDE_AI_NEAR_UNIVERSAL_AUTHORIZATION", "ai_near_universal_authorization", item.id,
           {"status": item.status, "outcome": item.outcome, "decision_hash": item.decision_hash,
            "rollout_100_percent_authorized": False, "production_wide_authorized": False},
           "Admin recorded the immutable Sprint 11P decision without widening to 100% or Production-wide.")
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def attest_document(db: Session, user: User, item: AINearUniversalAuthorization,
                    payload: AINearUniversalDocumentCreate) -> dict:
    if not payload.confirm_new_near_universal_eligibility:
        raise HTTPException(422, "Explicit fresh Sprint 11P eligibility confirmation is required")
    if not _active(item):
        raise HTTPException(409, "Only an active Sprint 11P authorization may attest documents")
    _anchor_still_valid(db, item)
    document = db.scalar(select(Document).where(
        Document.id == payload.document_id,
        Document.organization_id == user.organization_id,
        Document.claim_id == payload.claim_id,
    ))
    if document is None:
        raise HTTPException(404, "Document not found in this tenant and claim")
    confidentiality = document.confidentiality_level.value if hasattr(document.confidentiality_level, "value") else str(document.confidentiality_level)
    if confidentiality not in {ConfidentialityLevel.INTERNAL.value, ConfidentialityLevel.CONFIDENTIAL.value}:
        raise HTTPException(409, "Restricted or unsupported confidentiality is prohibited")
    if document.document_type not in item.allowed_document_types:
        raise HTTPException(409, "Document type is outside the Sprint 11P allowlist")
    bucket = _rollout_bucket(document.id)
    if bucket >= item.rollout_percentage:
        raise HTTPException(409, "Document is outside the deterministic Sprint 11P rollout")
    existing = [entry for entry in _documents(db, item.id) if entry.status == "eligible"]
    if any(entry.document_id == document.id for entry in existing):
        raise HTTPException(409, "Document already has active Sprint 11P eligibility")
    claims = {entry.claim_id for entry in existing}
    if document.claim_id not in claims and len(claims) >= item.max_claims:
        raise HTTPException(409, "Sprint 11P claim cap reached")
    if len(existing) >= item.max_documents:
        raise HTTPException(409, "Sprint 11P document cap reached")
    attempts = [entry for entry in _documents(db, item.id) if entry.document_id == document.id]
    now = datetime.now(UTC)
    legal = _reference(payload.legal_basis_reference)
    minimum = _reference(payload.data_minimization_reference)
    ticket = _reference(payload.change_ticket_reference)
    snapshot = {
        "schema": "mcri-ai-near-universal-document-eligibility-v1",
        "authorization_id": str(item.id), "authorization_decision_hash": item.decision_hash,
        "document_id": str(document.id), "claim_id": str(document.claim_id),
        "document_type": document.document_type, "confidentiality_level": confidentiality,
        "rollout_bucket": bucket, "legal_basis_reference": legal,
        "data_minimization_reference": minimum, "change_ticket_reference": ticket,
        "attestation_number": len(attempts) + 1, "attested_at": now.isoformat(),
        "prior_eligibility_carried_forward": False,
    }
    entry = AINearUniversalDocumentEligibility(
        organization_id=user.organization_id, authorization_id=item.id,
        claim_id=document.claim_id, document_id=document.id, attested_by_id=user.id,
        attestation_number=len(attempts) + 1, rollout_bucket=bucket,
        document_type=document.document_type, confidentiality_level=confidentiality,
        legal_basis_reference=legal, data_minimization_reference=minimum,
        change_ticket_reference=ticket, note=payload.note.strip(), snapshot_hash=_hash(snapshot),
        status="eligible", attested_at=now,
    )
    db.add(entry)
    db.flush()
    _audit(db, user, "ATTEST_AI_NEAR_UNIVERSAL_DOCUMENT", "ai_near_universal_document_eligibility", entry.id,
           {"authorization_id": str(item.id), "document_id": str(document.id),
            "rollout_bucket": bucket, "prior_eligibility_carried_forward": False},
           "Fresh Sprint 11P document eligibility recorded without raw content.")
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def revoke_document(db: Session, user: User, item: AINearUniversalAuthorization,
                    eligibility_id: UUID, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit document eligibility revocation is required")
    entry = db.scalar(select(AINearUniversalDocumentEligibility).where(
        AINearUniversalDocumentEligibility.id == eligibility_id,
        AINearUniversalDocumentEligibility.authorization_id == item.id,
        AINearUniversalDocumentEligibility.organization_id == user.organization_id,
    ))
    if entry is None:
        raise HTTPException(404, "Sprint 11P document eligibility not found")
    if entry.status != "eligible":
        raise HTTPException(409, "Document eligibility is already inactive")
    entry.status = "revoked"
    entry.revoked_by_id = user.id
    entry.revoked_at = datetime.now(UTC)
    entry.revocation_note = note.strip()
    _audit(db, user, "REVOKE_AI_NEAR_UNIVERSAL_DOCUMENT", "ai_near_universal_document_eligibility", entry.id,
           {"status": "revoked"}, "Sprint 11P document eligibility revoked.")
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def require_near_universal_runtime_authorization(
    db: Session, *, organization_id: UUID, document: Document,
    expected_document_type: str, input_char_count: int, requested_by_id: UUID | None = None,
) -> tuple[AINearUniversalAuthorization, AINearUniversalDocumentEligibility]:
    item = latest_near_universal_attempt(db, organization_id)
    if item is None:
        raise HTTPException(409, "No Sprint 11P control plane exists")
    if not _active(item):
        raise HTTPException(409, "Newest Sprint 11P control plane is inactive; fallback is prohibited")
    _anchor_still_valid(db, item)
    settings = get_settings()
    if (
        settings.ai_model != item.model
        or settings.ai_prompt_bundle_version != item.prompt_bundle_version
        or settings.ai_schema_bundle_version != item.schema_bundle_version
        or settings.ai_max_output_tokens != item.max_output_tokens
    ):
        raise HTTPException(409, "Configured AI bundle differs from the authorized Sprint 11P bundle")
    confidentiality = document.confidentiality_level.value if hasattr(document.confidentiality_level, "value") else str(document.confidentiality_level)
    if confidentiality not in {ConfidentialityLevel.INTERNAL.value, ConfidentialityLevel.CONFIDENTIAL.value}:
        raise HTTPException(409, "Only Internal or Confidential documents are permitted")
    if expected_document_type not in item.allowed_document_types or document.document_type != expected_document_type:
        raise HTTPException(409, "Document type is outside the Sprint 11P allowlist")
    if input_char_count > item.max_input_chars:
        raise HTTPException(409, "Document exceeds the authorized input limit")
    if _rollout_bucket(document.id) >= item.rollout_percentage:
        raise HTTPException(409, "Document is outside the deterministic Sprint 11P rollout")
    eligibility = db.scalar(select(AINearUniversalDocumentEligibility).where(
        AINearUniversalDocumentEligibility.organization_id == organization_id,
        AINearUniversalDocumentEligibility.authorization_id == item.id,
        AINearUniversalDocumentEligibility.document_id == document.id,
        AINearUniversalDocumentEligibility.status == "eligible",
    ).order_by(AINearUniversalDocumentEligibility.attestation_number.desc()))
    if eligibility is None:
        raise HTTPException(409, "Document requires fresh Sprint 11P eligibility")
    incidents = _incidents(db, item.id)
    if any(entry.status == "open" for entry in incidents):
        raise HTTPException(409, "An open incident blocks Sprint 11P AI")
    if any(entry.category in SAFETY_CATEGORIES for entry in incidents):
        raise HTTPException(409, "Privacy, Security or Cross-tenant incident history blocks this Sprint 11P attempt")
    runs = _runs(db, item.id)
    if len(runs) >= item.max_provider_runs:
        raise HTTPException(409, "Sprint 11P provider-run cap reached")
    participating = {entry.requested_by_id for entry in runs if entry.requested_by_id is not None}
    if requested_by_id is not None and requested_by_id not in participating and len(participating) >= item.max_users:
        raise HTTPException(409, "Sprint 11P user cap reached")
    if (
        runs and item.decided_at is not None
        and datetime.now(UTC) > _as_utc(item.decided_at) + timedelta(minutes=item.monitor_interval_minutes * 2)
        and not _latest_monitor_pass(db, item, require_fresh=True)
    ):
        raise HTTPException(409, "A fresh passing Sprint 11P monitor is required")
    return item, eligibility


def reserve_run_if_near_universal(
    db: Session, *, user: User, document: Document, expected_document_type: str,
    input_char_count: int, processing_job_id: UUID,
) -> AINearUniversalRun | None:
    if get_settings().app_env.lower().strip() != "production":
        return None
    latest = latest_near_universal_attempt(db, user.organization_id)
    if latest is None:
        return None
    existing = db.scalar(select(AINearUniversalRun).where(
        AINearUniversalRun.organization_id == user.organization_id,
        AINearUniversalRun.processing_job_id == processing_job_id,
    ))
    if existing is not None:
        return existing
    item, eligibility = require_near_universal_runtime_authorization(
        db, organization_id=user.organization_id, document=document,
        expected_document_type=expected_document_type, input_char_count=input_char_count,
        requested_by_id=user.id,
    )
    run = AINearUniversalRun(
        organization_id=user.organization_id, authorization_id=item.id, eligibility_id=eligibility.id,
        claim_id=document.claim_id, document_id=document.id, requested_by_id=user.id,
        run_key=f"processing-{processing_job_id}", processing_job_id=processing_job_id,
        task_type=expected_document_type, status="queued", queued_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()
    _audit(db, user, "RESERVE_AI_NEAR_UNIVERSAL_RUN", "ai_near_universal_run", run.id,
           {"authorization_id": str(item.id), "document_id": str(document.id),
            "processing_job_id": str(processing_job_id), "task_type": expected_document_type,
            "raw_content_stored": False, "different_human_review_required": True},
           "Content-free Sprint 11P provider-run reservation.")
    return run


def get_run(db: Session, organization_id: UUID, run_id: UUID) -> AINearUniversalRun:
    run = db.scalar(select(AINearUniversalRun).where(
        AINearUniversalRun.id == run_id,
        AINearUniversalRun.organization_id == organization_id,
    ))
    if run is None:
        raise HTTPException(404, "Sprint 11P run not found")
    return run


def record_run_outcome(
    db: Session, user: User, run: AINearUniversalRun, *, human_review_action: str,
    output_candidate_count: int, human_edit_count: int, unsupported_output_count: int,
    source_grounded_output_count: int, source_grounding_total_count: int, latency_ms: int,
    observed_provider_cost_microusd: int, evidence_reference: str, note: str,
    confirm_human_review: bool,
) -> dict:
    if not confirm_human_review:
        raise HTTPException(422, "Explicit human-review confirmation is required")
    if run.status != "queued":
        raise HTTPException(409, "This run outcome is immutable")
    if run.requested_by_id == user.id:
        raise HTTPException(409, "A different human must review every Sprint 11P AI output")
    job = db.scalar(select(DocumentProcessingJob).where(
        DocumentProcessingJob.id == run.processing_job_id,
        DocumentProcessingJob.organization_id == user.organization_id,
    ))
    if job is None or job.status != ProcessingJobStatus.COMPLETED:
        raise HTTPException(409, "Provider processing must complete before human review")
    if human_edit_count > output_candidate_count or unsupported_output_count > output_candidate_count:
        raise HTTPException(422, "Review counters cannot exceed output candidates")
    if source_grounded_output_count > source_grounding_total_count or source_grounding_total_count > output_candidate_count:
        raise HTTPException(422, "Grounding counters are inconsistent with output candidates")
    reference = _reference(evidence_reference)
    snapshot = {
        "schema": "mcri-ai-near-universal-run-outcome-v1", "run_id": str(run.id),
        "authorization_id": str(run.authorization_id), "processing_job_id": str(run.processing_job_id),
        "task_type": run.task_type, "human_review_action": human_review_action,
        "output_candidate_count": output_candidate_count, "human_edit_count": human_edit_count,
        "unsupported_output_count": unsupported_output_count,
        "source_grounded_output_count": source_grounded_output_count,
        "source_grounding_total_count": source_grounding_total_count,
        "latency_ms": latency_ms, "observed_provider_cost_microusd": observed_provider_cost_microusd,
        "evidence_reference": reference, "different_human_review_completed": True,
        "authoritative_facts_auto_updated": False, "raw_content_stored": False,
    }
    run.reviewed_by_id = user.id
    run.status = "human_reviewed"
    run.human_review_action = human_review_action
    run.output_candidate_count = output_candidate_count
    run.human_edit_count = human_edit_count
    run.unsupported_output_count = unsupported_output_count
    run.source_grounded_output_count = source_grounded_output_count
    run.source_grounding_total_count = source_grounding_total_count
    run.latency_ms = latency_ms
    run.observed_provider_cost_microusd = observed_provider_cost_microusd
    run.evidence_reference = reference
    run.note = note.strip()
    run.reviewed_at = datetime.now(UTC)
    run.outcome_hash = _hash(snapshot)
    _audit(db, user, "REVIEW_AI_NEAR_UNIVERSAL_RUN", "ai_near_universal_run", run.id,
           {"authorization_id": str(run.authorization_id), "human_review_action": human_review_action,
            "outcome_hash": run.outcome_hash, "authoritative_facts_auto_updated": False},
           "Mandatory different-human Sprint 11P review.")
    db.commit()
    return authorization_response(db, get_authorization(db, user.organization_id, run.authorization_id))


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


def _segment_metrics(rows: list[AINearUniversalRun]) -> dict:
    actions = [row for row in rows if row.human_review_action in {"approve", "edit", "reject"}]
    candidates = sum(row.output_candidate_count or 0 for row in rows)
    unsupported = sum(row.unsupported_output_count or 0 for row in rows)
    grounding_total = sum(row.source_grounding_total_count or 0 for row in rows)
    grounded = sum(row.source_grounded_output_count or 0 for row in rows)
    latencies = [row.latency_ms for row in rows if row.latency_ms is not None]
    costs = [row.observed_provider_cost_microusd for row in rows if row.observed_provider_cost_microusd is not None]
    return {
        "reject_rate_bps": _rate_bps(sum(row.human_review_action == "reject" for row in actions), len(actions)),
        "edit_rate_bps": _rate_bps(sum(row.human_review_action == "edit" for row in actions), len(actions)),
        "unsupported_rate_bps": _rate_bps(unsupported, candidates),
        "grounding_rate_bps": _rate_bps(grounded, grounding_total),
        "mean_latency_ms": _mean(latencies), "mean_cost_microusd": _mean(costs),
    }


def record_monitor(db: Session, user: User, item: AINearUniversalAuthorization,
                   monitor_key: str, note: str, confirm: bool) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit live monitor confirmation is required")
    if item.status not in {"authorized", "paused"}:
        raise HTTPException(409, "Only an authorized or paused Sprint 11P cohort can be monitored")
    _anchor_still_valid(db, item)
    runs = _runs(db, item.id)
    incidents = _incidents(db, item.id)
    reviewed = [run for run in runs if run.status == "human_reviewed"]
    different = [run for run in reviewed if run.requested_by_id is not None and run.reviewed_by_id is not None
                 and run.requested_by_id != run.reviewed_by_id]
    actions = [run for run in reviewed if run.human_review_action in {"approve", "edit", "reject"}]
    candidates = sum(run.output_candidate_count or 0 for run in reviewed)
    unsupported = sum(run.unsupported_output_count or 0 for run in reviewed)
    grounded = sum(run.source_grounded_output_count or 0 for run in reviewed)
    grounding_total = sum(run.source_grounding_total_count or 0 for run in reviewed)
    latencies = sorted(run.latency_ms for run in reviewed if run.latency_ms is not None)
    costs = [run.observed_provider_cost_microusd for run in reviewed if run.observed_provider_cost_microusd is not None]
    p95 = latencies[max(ceil(0.95 * len(latencies)) - 1, 0)] if latencies else None
    review_rate = _rate_bps(len(reviewed), len(runs))
    different_rate = _rate_bps(len(different), len(runs))
    reject_rate = _rate_bps(sum(run.human_review_action == "reject" for run in actions), len(actions))
    edit_rate = _rate_bps(sum(run.human_review_action == "edit" for run in actions), len(actions))
    unsupported_rate = _rate_bps(unsupported, candidates)
    grounding_rate = _rate_bps(grounded, grounding_total)
    mean_cost = _mean(costs)
    half = len(reviewed) // 2
    first = _segment_metrics(reviewed[:half]) if half else {}
    second = _segment_metrics(reviewed[half:]) if half else {}
    regressions: list[int] = []
    for key in ("reject_rate_bps", "edit_rate_bps", "unsupported_rate_bps"):
        if first.get(key) is not None and second.get(key) is not None:
            regressions.append(max(0, second[key] - first[key]))
    if first.get("grounding_rate_bps") is not None and second.get("grounding_rate_bps") is not None:
        regressions.append(max(0, first["grounding_rate_bps"] - second["grounding_rate_bps"]))
    quality_regression = max(regressions) if regressions else None
    latency_regression = _relative_increase_bps(first.get("mean_latency_ms"), second.get("mean_latency_ms")) if half else None
    cost_regression = _relative_increase_bps(first.get("mean_cost_microusd"), second.get("mean_cost_microusd")) if half else None
    open_blocking = sum(entry.status == "open" and entry.severity in BLOCKING_SEVERITIES for entry in incidents)
    safety_incidents = sum(entry.category in SAFETY_CATEGORIES for entry in incidents)
    metrics = {
        "provider_run_count": len(runs), "human_reviewed_run_count": len(reviewed),
        "human_review_rate_bps": review_rate, "different_human_review_rate_bps": different_rate,
        "human_reject_rate_bps": reject_rate, "human_edit_rate_bps": edit_rate,
        "unsupported_output_rate_bps": unsupported_rate,
        "source_grounding_validity_bps": grounding_rate, "p95_latency_ms": p95,
        "mean_observed_provider_cost_microusd": mean_cost,
        "quality_grounding_regression_bps": quality_regression,
        "latency_regression_bps": latency_regression, "cost_regression_bps": cost_regression,
        "open_high_or_critical_incident_count": open_blocking,
        "safety_boundary_incident_count": safety_incidents,
    }
    failures: list[str] = []
    if review_rate != 10000:
        failures.append("human_review_coverage")
    if different_rate != 10000:
        failures.append("different_human_review_coverage")
    if reject_rate is None or reject_rate > item.max_reject_rate_bps:
        failures.append("reject_rate")
    if edit_rate is None or edit_rate > item.max_edit_rate_bps:
        failures.append("edit_rate")
    if unsupported_rate is None or unsupported_rate > item.max_unsupported_output_rate_bps:
        failures.append("unsupported_output_rate")
    if grounding_rate is None or grounding_rate < item.min_source_grounding_validity_bps:
        failures.append("source_grounding")
    if p95 is None or p95 > item.max_p95_latency_ms:
        failures.append("p95_latency")
    if mean_cost is None or mean_cost > item.max_mean_cost_microusd:
        failures.append("mean_provider_cost")
    if len(reviewed) >= 2:
        if quality_regression is None or quality_regression > item.max_quality_regression_bps:
            failures.append("quality_grounding_regression")
        if latency_regression is None or latency_regression > item.max_latency_regression_bps:
            failures.append("latency_regression")
        if cost_regression is None or cost_regression > item.max_cost_regression_bps:
            failures.append("cost_regression")
    if open_blocking:
        failures.append("open_high_or_critical_incident")
    if safety_incidents:
        failures.append("privacy_security_or_cross_tenant_incident")
    metrics["overall_pass"] = not failures
    now = datetime.now(UTC)
    snapshot = {
        "schema": "mcri-ai-near-universal-monitor-v1", "authorization_id": str(item.id),
        "authorization_decision_hash": item.decision_hash, "metrics": metrics,
        "failure_reasons": failures, "monitor_key": monitor_key, "monitored_at": now.isoformat(),
    }
    monitor = AINearUniversalMonitor(
        organization_id=user.organization_id, authorization_id=item.id, initiated_by_id=user.id,
        monitor_key=monitor_key, metrics=metrics, failure_reasons=failures,
        status="pass" if not failures else "fail", monitor_hash=_hash(snapshot),
        note=note.strip(), monitored_at=now,
    )
    db.add(monitor)
    db.flush()
    if failures and item.status == "authorized":
        item.status = "paused"
        item.outcome = "monitor_rollback"
        db.add(AINearUniversalIncident(
            organization_id=user.organization_id, authorization_id=item.id, reported_by_id=user.id,
            severity="high", category="quality", evidence_reference=f"monitor://ai-near-universal/{monitor.id}",
            note="Automatic rollback incident created by a failing Sprint 11P monitor.",
            status="open", reported_at=now,
        ))
        db.flush()
    _audit(db, user, "RECORD_AI_NEAR_UNIVERSAL_MONITOR", "ai_near_universal_authorization", item.id,
           {"monitor_id": str(monitor.id), "monitor_status": monitor.status,
            "failure_reasons": failures, "authorization_status": item.status},
           "Sprint 11P live monitor recorded; failures pause and roll back execution.")
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def report_incident(db: Session, user: User, item: AINearUniversalAuthorization, *, severity: str,
                    category: str, evidence_reference: str, note: str, confirm: bool) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit pause-and-rollback confirmation is required")
    if item.status != "authorized":
        raise HTTPException(409, "Only an active Sprint 11P authorization can be paused")
    incident = AINearUniversalIncident(
        organization_id=user.organization_id, authorization_id=item.id, reported_by_id=user.id,
        severity=severity, category=category, evidence_reference=_reference(evidence_reference),
        note=note.strip(), status="open", reported_at=datetime.now(UTC),
    )
    db.add(incident)
    db.flush()
    item.status = "paused"
    item.outcome = "incident_rollback"
    _audit(db, user, "PAUSE_AI_NEAR_UNIVERSAL_INCIDENT", "ai_near_universal_authorization", item.id,
           {"incident_id": str(incident.id), "severity": severity, "category": category,
            "status": "paused", "rollback_slo_minutes": item.rollback_slo_minutes},
           "Immediate Sprint 11P pause and rollback trigger.")
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def resolve_incident(db: Session, user: User, item: AINearUniversalAuthorization, incident_id: UUID, *,
                     resolution_reference: str, resolution_note: str, confirm: bool) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit incident resolution confirmation is required")
    incident = db.scalar(select(AINearUniversalIncident).where(
        AINearUniversalIncident.id == incident_id,
        AINearUniversalIncident.authorization_id == item.id,
        AINearUniversalIncident.organization_id == user.organization_id,
    ))
    if incident is None:
        raise HTTPException(404, "Sprint 11P incident not found")
    if incident.status != "open":
        raise HTTPException(409, "Incident is already resolved")
    incident.status = "resolved"
    incident.resolved_by_id = user.id
    incident.resolved_at = datetime.now(UTC)
    incident.resolution_reference = _reference(resolution_reference)
    incident.resolution_note = resolution_note.strip()
    _audit(db, user, "RESOLVE_AI_NEAR_UNIVERSAL_INCIDENT", "ai_near_universal_authorization", item.id,
           {"incident_id": str(incident.id), "status": item.status, "resumed": False},
           "Incident resolved; fresh passing monitor and explicit Admin recovery remain required.")
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def resume_authorization(db: Session, user: User, item: AINearUniversalAuthorization,
                         confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit Admin recovery confirmation is required")
    if item.status != "paused":
        raise HTTPException(409, "Only a paused Sprint 11P authorization can resume")
    incidents = _incidents(db, item.id)
    if any(entry.status == "open" for entry in incidents):
        raise HTTPException(409, "Open incidents block recovery")
    if any(entry.category in SAFETY_CATEGORIES for entry in incidents):
        raise HTTPException(409, "Privacy, Security or Cross-tenant incidents require a new Sprint 11P attempt")
    if not _latest_monitor_pass(db, item, require_fresh=True) or not _recovery_complete(db, item):
        raise HTTPException(409, "Fresh passing monitor and complete recovery evidence are required")
    if _as_utc(item.expires_at) <= datetime.now(UTC):
        raise HTTPException(409, "Expired authorization cannot resume")
    _anchor_still_valid(db, item)
    item.status = "authorized"
    item.outcome = "resumed_after_monitor"
    _audit(db, user, "RESUME_AI_NEAR_UNIVERSAL", "ai_near_universal_authorization", item.id,
           {"status": "authorized", "rollout_100_percent_authorized": False,
            "production_wide_authorized": False},
           "Admin resumed only the existing bounded Sprint 11P cohort.")
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def revoke_authorization(db: Session, user: User, item: AINearUniversalAuthorization,
                         confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit Sprint 11P kill-switch confirmation is required")
    if item.status in {"revoked", "completed"}:
        raise HTTPException(409, "Authorization is already terminal")
    item.status = "revoked"
    item.outcome = "revoked"
    item.revoked_by_id = user.id
    item.revoked_at = datetime.now(UTC)
    item.revocation_note = note.strip()
    _audit(db, user, "REVOKE_AI_NEAR_UNIVERSAL", "ai_near_universal_authorization", item.id,
           {"status": "revoked", "rollout_100_percent_authorized": False,
            "production_wide_authorized": False}, "Immediate Sprint 11P kill switch.")
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def complete_authorization(db: Session, user: User, item: AINearUniversalAuthorization,
                           confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit Sprint 11P completion confirmation is required")
    if not _active(item):
        raise HTTPException(409, "Only an active, unexpired Sprint 11P cohort can complete")
    _anchor_still_valid(db, item)
    runs = _runs(db, item.id)
    incidents = _incidents(db, item.id)
    monitors = _monitors(db, item.id)
    if not runs or any(
        run.status != "human_reviewed" or run.requested_by_id == run.reviewed_by_id
        for run in runs
    ):
        raise HTTPException(409, "Every Sprint 11P provider run requires completed different-human review")
    if any(entry.status == "open" for entry in incidents):
        raise HTTPException(409, "Open incidents block completion")
    if any(entry.category in SAFETY_CATEGORIES for entry in incidents):
        raise HTTPException(409, "Privacy, Security or Cross-tenant incident history blocks successful completion")
    if not _latest_monitor_pass(db, item, require_fresh=True):
        raise HTTPException(409, "A fresh passing final monitor is required before completion")
    if not _recovery_complete(db, item):
        raise HTTPException(409, "All rollback events require complete recovery evidence before completion")
    now = datetime.now(UTC)
    snapshot = {
        "schema": "mcri-ai-near-universal-completion-v1",
        "authorization_id": str(item.id), "authorization_decision_hash": item.decision_hash,
        "outcome_assessment_hash": item.outcome_assessment_hash,
        "outcome_decision_hash": item.outcome_decision_hash,
        "rollout_percentage": item.rollout_percentage,
        "run_hashes": [run.outcome_hash for run in runs],
        "monitor_hashes": [monitor.monitor_hash for monitor in monitors],
        "incidents": [{"id": str(incident.id), "category": incident.category,
                       "severity": incident.severity, "status": incident.status,
                       "resolution_reference": incident.resolution_reference} for incident in incidents],
        "completed_at": now.isoformat(),
        "rollout_100_percent_authorized": False, "production_wide_authorized": False,
        "restricted_documents_authorized": False, "new_document_classes_authorized": False,
        "autonomous_claim_decisions_authorized": False,
    }
    item.status = "completed"
    item.outcome = "completed"
    item.completed_at = now
    item.completion_note = note.strip()
    item.completion_hash = _hash(snapshot)
    _audit(db, user, "COMPLETE_AI_NEAR_UNIVERSAL", "ai_near_universal_authorization", item.id,
           {"status": "completed", "provider_run_count": len(runs),
            "completion_hash": item.completion_hash, "rollout_100_percent_authorized": False,
            "production_wide_authorized": False, "restricted_documents_authorized": False,
            "new_document_classes_authorized": False},
           "Completed bounded Sprint 11P cohort; no 100% or Production-wide permission is granted.")
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)
