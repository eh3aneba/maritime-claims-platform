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
from app.modules.ai_bounded_full_production.models import (
    AIBoundedFullProductionApproval,
    AIBoundedFullProductionAuthorization,
    AIBoundedFullProductionDocumentEligibility,
    AIBoundedFullProductionIncident,
    AIBoundedFullProductionMonitor,
    AIBoundedFullProductionRun,
)
from app.modules.ai_bounded_full_production.schemas import (
    AIBoundedFullProductionCreate,
    AIBoundedFullProductionDocumentCreate,
)
from app.modules.ai_near_universal_outcomes.models import AINearUniversalOutcomeAssessment
from app.modules.ai_near_universal_production.models import (
    AINearUniversalAuthorization,
    AINearUniversalIncident,
)
from app.modules.ai_near_universal_production.service import (
    _latest_monitor_pass as _near_latest_monitor_pass,
    _mean,
    _rate_bps,
    _recovery_complete as _near_recovery_complete,
    _relative_increase_bps,
    _segment_metrics,
)
from app.modules.audit.service import write_audit_log
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.processing.models import DocumentProcessingJob, ProcessingJobStatus
from app.modules.users.models import User

REFERENCE = re.compile(r"^(artifact|runbook|ticket|monitor)://[A-Za-z0-9._:/-]{3,450}$")
APPROVAL_ROLES = {
    "security", "privacy", "product", "operations", "risk", "claims_governance",
    "ai_quality", "legal_data_governance", "business_owner", "platform_reliability",
    "independent_production_assurance", "data_protection", "executive_production_sponsor",
}
ALLOWED_DOCUMENT_TYPES = {"chief_engineer_report", "engine_log"}
SAFETY_CATEGORIES = {"privacy", "security", "cross_tenant"}
BLOCKING_SEVERITIES = {"high", "critical"}
MIN_COMPLETION_RUNS = 40
MIN_COMPLETION_RUNS_PER_ACTIVE_WORKFLOW = 10


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _reference(value: str) -> str:
    ref = value.strip()
    if not REFERENCE.fullmatch(ref):
        raise HTTPException(422, "Sprint 11R evidence must use a bounded allowlisted reference")
    return ref


def _hash(payload: dict) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _audit(db: Session, user: User, action: str, entity_type: str, entity_id: UUID, values: dict, details: str) -> None:
    write_audit_log(
        db, organization_id=user.organization_id, user_id=user.id, action=action,
        entity_type=entity_type, entity_id=entity_id, new_values=values, details=details,
    )


def _approvals(db: Session, authorization_id: UUID) -> list[AIBoundedFullProductionApproval]:
    return list(db.scalars(select(AIBoundedFullProductionApproval).where(
        AIBoundedFullProductionApproval.authorization_id == authorization_id,
    ).order_by(AIBoundedFullProductionApproval.approval_role.asc())))


def _documents(db: Session, authorization_id: UUID) -> list[AIBoundedFullProductionDocumentEligibility]:
    return list(db.scalars(select(AIBoundedFullProductionDocumentEligibility).where(
        AIBoundedFullProductionDocumentEligibility.authorization_id == authorization_id,
    ).order_by(AIBoundedFullProductionDocumentEligibility.created_at.asc())))


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


def latest_bounded_full_production_attempt(db: Session, organization_id: UUID) -> AIBoundedFullProductionAuthorization | None:
    return db.scalar(select(AIBoundedFullProductionAuthorization).where(
        AIBoundedFullProductionAuthorization.organization_id == organization_id,
    ).order_by(AIBoundedFullProductionAuthorization.created_at.desc(), AIBoundedFullProductionAuthorization.id.desc()))


def _active(item: AIBoundedFullProductionAuthorization) -> bool:
    now = datetime.now(UTC)
    return item.status == "authorized" and _as_utc(item.starts_at) <= now < _as_utc(item.expires_at)


def _rollout_bucket(document_id: UUID) -> int:
    return int(sha256(str(document_id).encode()).hexdigest()[:8], 16) % 100


def _latest_monitor_pass(db: Session, item: AIBoundedFullProductionAuthorization, *, require_fresh: bool) -> bool:
    rows = _monitors(db, item.id)
    if not rows or rows[-1].status != "pass":
        return False
    if not require_fresh:
        return True
    return _as_utc(rows[-1].monitored_at) >= datetime.now(UTC) - timedelta(minutes=item.monitor_interval_minutes * 2)


def _recovery_complete(db: Session, item: AIBoundedFullProductionAuthorization) -> bool:
    monitors = _monitors(db, item.id)
    for incident in _incidents(db, item.id):
        if incident.category in SAFETY_CATEGORIES:
            return False
        if incident.status != "resolved" or incident.resolved_at is None:
            return False
        if not any(m.status == "pass" and _as_utc(m.monitored_at) >= _as_utc(incident.resolved_at) for m in monitors):
            return False
    return True


def _controls(item: AIBoundedFullProductionAuthorization) -> dict:
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
        "minimum_completion_runs": MIN_COMPLETION_RUNS,
        "minimum_completion_runs_per_active_workflow": MIN_COMPLETION_RUNS_PER_ACTIVE_WORKFLOW,
    }


def authorization_response(db: Session, item: AIBoundedFullProductionAuthorization) -> dict:
    approvals, docs, runs, monitors, incidents = (
        _approvals(db, item.id), _documents(db, item.id), _runs(db, item.id), _monitors(db, item.id), _incidents(db, item.id)
    )
    active_docs = [x for x in docs if x.status == "eligible"]
    reviewed = [x for x in runs if x.status == "human_reviewed"]
    approvals_complete = (
        len(approvals) == len(APPROVAL_ROLES)
        and {x.approval_role for x in approvals} == APPROVAL_ROLES
        and all(x.action == "approve" for x in approvals)
        and len({x.approver_id for x in approvals}) == len(APPROVAL_ROLES)
        and all(x.approver_id != item.requested_by_id for x in approvals)
    )
    active = _active(item)
    return {
        "id": item.id,
        "near_universal_outcome_assessment_id": item.near_universal_outcome_assessment_id,
        "near_universal_authorization_id": item.near_universal_authorization_id,
        "requested_by_id": item.requested_by_id,
        "finalized_by_id": item.finalized_by_id,
        "revoked_by_id": item.revoked_by_id,
        "attempt_number": item.attempt_number,
        "authorization_key": item.authorization_key,
        "environment": item.environment,
        "authorization_mode": item.authorization_mode,
        "near_universal_outcome_assessment_hash": item.near_universal_outcome_assessment_hash,
        "near_universal_outcome_decision_hash": item.near_universal_outcome_decision_hash,
        "near_universal_decision_hash": item.near_universal_decision_hash,
        "near_universal_completion_hash": item.near_universal_completion_hash,
        "bundle": {"model": item.model, "prompt_bundle_version": item.prompt_bundle_version,
                   "schema_bundle_version": item.schema_bundle_version, "max_input_chars": item.max_input_chars,
                   "max_output_tokens": item.max_output_tokens},
        "allowed_document_types": item.allowed_document_types,
        "previous_rollout_percentage": item.previous_rollout_percentage,
        "rollout_percentage": item.rollout_percentage,
        "previous_caps": {"claims": item.previous_max_claims, "documents": item.previous_max_documents,
                          "users": item.previous_max_users, "provider_runs": item.previous_max_provider_runs},
        "max_claims": item.max_claims, "max_documents": item.max_documents,
        "max_users": item.max_users, "max_provider_runs": item.max_provider_runs,
        "starts_at": item.starts_at, "expires_at": item.expires_at,
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
            "data_protection": item.data_protection_reference,
            "executive_sponsor": item.executive_sponsor_reference,
            "change_ticket": item.change_ticket_reference,
        },
        "status": item.status, "outcome": item.outcome,
        "decision_note": item.decision_note, "decision_hash": item.decision_hash, "decided_at": item.decided_at,
        "completed_at": item.completed_at, "completion_note": item.completion_note, "completion_hash": item.completion_hash,
        "revoked_at": item.revoked_at, "revocation_note": item.revocation_note,
        "approvals": approvals, "document_eligibility": docs, "runs": runs, "monitors": monitors, "incidents": incidents,
        "summary": {
            "independent_approvals_complete": approvals_complete,
            "authorization_active": active,
            "active_claim_count": len({x.claim_id for x in active_docs}),
            "active_document_count": len(active_docs),
            "participating_user_count": len({x.requested_by_id for x in runs if x.requested_by_id}),
            "provider_run_count": len(runs), "human_reviewed_run_count": len(reviewed),
            "pending_human_review_count": len(runs) - len(reviewed),
            "open_incident_count": sum(x.status == "open" for x in incidents),
            "latest_monitor_status": monitors[-1].status if monitors else None,
            "monitor_fresh_and_passing": _latest_monitor_pass(db, item, require_fresh=True),
            "rollback_recovery_complete": _recovery_complete(db, item),
            "bounded_100_percent_cohort_authorized": active,
            "rollout_100_percent_authorized": active,
            "production_wide_unbounded_authorized": False,
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
    items = list(db.scalars(select(AIBoundedFullProductionAuthorization).where(
        AIBoundedFullProductionAuthorization.organization_id == organization_id,
    ).order_by(AIBoundedFullProductionAuthorization.created_at.desc()).limit(20)))
    return [authorization_response(db, x) for x in items]


def get_authorization(db: Session, organization_id: UUID, authorization_id: UUID) -> AIBoundedFullProductionAuthorization:
    item = db.scalar(select(AIBoundedFullProductionAuthorization).where(
        AIBoundedFullProductionAuthorization.id == authorization_id,
        AIBoundedFullProductionAuthorization.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Sprint 11R bounded 100% authorization not found")
    return item


def _outcome(db: Session, organization_id: UUID, assessment_id: UUID) -> AINearUniversalOutcomeAssessment:
    item = db.scalar(select(AINearUniversalOutcomeAssessment).where(
        AINearUniversalOutcomeAssessment.id == assessment_id,
        AINearUniversalOutcomeAssessment.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Sprint 11Q outcome assessment not found")
    return item


def _near(db: Session, organization_id: UUID, authorization_id: UUID) -> AINearUniversalAuthorization:
    item = db.scalar(select(AINearUniversalAuthorization).where(
        AINearUniversalAuthorization.id == authorization_id,
        AINearUniversalAuthorization.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(409, "The Sprint 11P anchor is missing")
    return item


def _anchor_still_valid(db: Session, item: AIBoundedFullProductionAuthorization) -> None:
    outcome = _outcome(db, item.organization_id, item.near_universal_outcome_assessment_id)
    near = _near(db, item.organization_id, item.near_universal_authorization_id)
    safety_history = db.scalar(select(AINearUniversalIncident.id).where(
        AINearUniversalIncident.authorization_id == near.id,
        AINearUniversalIncident.category.in_(SAFETY_CATEGORIES),
    ).limit(1))
    if (
        outcome.status != "recommended"
        or outcome.outcome != "recommend_separate_100_percent_authorization_review"
        or not (outcome.metrics or {}).get("overall_pass")
        or bool(outcome.failure_reasons)
        or outcome.assessment_hash != item.near_universal_outcome_assessment_hash
        or outcome.decision_hash != item.near_universal_outcome_decision_hash
        or outcome.near_universal_authorization_id != near.id
        or outcome.near_universal_decision_hash != item.near_universal_decision_hash
        or outcome.near_universal_completion_hash != item.near_universal_completion_hash
        or near.status != "completed"
        or near.decision_hash != item.near_universal_decision_hash
        or near.completion_hash != item.near_universal_completion_hash
        or near.rollout_percentage != item.previous_rollout_percentage
        or not 91 <= near.rollout_percentage <= 99
        or near.model != item.model
        or near.prompt_bundle_version != item.prompt_bundle_version
        or near.schema_bundle_version != item.schema_bundle_version
        or near.max_input_chars != item.max_input_chars
        or near.max_output_tokens != item.max_output_tokens
        or near.allowed_document_types != item.allowed_document_types
        or near.max_claims != item.previous_max_claims
        or near.max_documents != item.previous_max_documents
        or near.max_users != item.previous_max_users
        or near.max_provider_runs != item.previous_max_provider_runs
        or safety_history is not None
        or not _near_latest_monitor_pass(db, near, require_fresh=True)
        or not _near_recovery_complete(db, near)
    ):
        raise HTTPException(409, "The persisted Sprint 11Q/11P evidence anchor no longer matches")


def create_authorization(db: Session, user: User, payload: AIBoundedFullProductionCreate) -> dict:
    if not payload.confirm_separate_bounded_full_production:
        raise HTTPException(422, "Explicit separate Sprint 11R confirmation is required")
    if any(v.tzinfo is None or v.utcoffset() is None for v in (payload.starts_at, payload.expires_at)):
        raise HTTPException(422, "Authorization timestamps must include a timezone")
    starts, expires, now = payload.starts_at.astimezone(UTC), payload.expires_at.astimezone(UTC), datetime.now(UTC)
    if starts < now - timedelta(minutes=5) or starts > now + timedelta(days=2):
        raise HTTPException(422, "Sprint 11R start must be current or within two days")
    if expires <= starts or expires - starts > timedelta(days=30):
        raise HTTPException(422, "Sprint 11R authorization must expire within 30 days")
    if payload.max_documents < payload.max_claims:
        raise HTTPException(422, "Document cap cannot be lower than the claim cap")
    allowed = list(dict.fromkeys(payload.allowed_document_types))
    if len(allowed) != len(payload.allowed_document_types) or not set(allowed) <= ALLOWED_DOCUMENT_TYPES:
        raise HTTPException(422, "Document allowlist is duplicated or unsupported")
    outcome = _outcome(db, user.organization_id, payload.near_universal_outcome_assessment_id)
    if (
        outcome.status != "recommended"
        or outcome.outcome != "recommend_separate_100_percent_authorization_review"
        or not (outcome.metrics or {}).get("overall_pass")
        or outcome.failure_reasons or not outcome.assessment_hash or not outcome.decision_hash
    ):
        raise HTTPException(409, "A passing, positively recommended Sprint 11Q assessment is required")
    near = _near(db, user.organization_id, outcome.near_universal_authorization_id)
    if near.status != "completed" or not near.decision_hash or not near.completion_hash or not 91 <= near.rollout_percentage <= 99:
        raise HTTPException(409, "The completed Sprint 11P anchor is invalid")
    if near.decision_hash != outcome.near_universal_decision_hash or near.completion_hash != outcome.near_universal_completion_hash:
        raise HTTPException(409, "Sprint 11Q no longer matches its Sprint 11P source cohort")
    if not set(allowed) <= set(near.allowed_document_types):
        raise HTTPException(409, "Sprint 11R cannot introduce new document classes")
    safety_history = db.scalar(select(AINearUniversalIncident.id).where(
        AINearUniversalIncident.authorization_id == near.id,
        AINearUniversalIncident.category.in_(SAFETY_CATEGORIES),
    ).limit(1))
    if safety_history is not None or not _near_latest_monitor_pass(db, near, require_fresh=True) or not _near_recovery_complete(db, near):
        raise HTTPException(409, "Sprint 11P safety/recovery evidence is not clean and fresh")
    prior = list(db.scalars(select(AIBoundedFullProductionAuthorization).where(
        AIBoundedFullProductionAuthorization.near_universal_outcome_assessment_id == outcome.id,
    )))
    item = AIBoundedFullProductionAuthorization(
        organization_id=user.organization_id,
        near_universal_outcome_assessment_id=outcome.id,
        near_universal_authorization_id=near.id,
        requested_by_id=user.id,
        attempt_number=len(prior) + 1,
        authorization_key=payload.authorization_key.strip(),
        near_universal_outcome_assessment_hash=outcome.assessment_hash,
        near_universal_outcome_decision_hash=outcome.decision_hash,
        near_universal_decision_hash=near.decision_hash,
        near_universal_completion_hash=near.completion_hash,
        model=near.model, prompt_bundle_version=near.prompt_bundle_version,
        schema_bundle_version=near.schema_bundle_version, max_input_chars=near.max_input_chars,
        max_output_tokens=near.max_output_tokens, allowed_document_types=allowed,
        previous_rollout_percentage=near.rollout_percentage, rollout_percentage=100,
        previous_max_claims=near.max_claims, previous_max_documents=near.max_documents,
        previous_max_users=near.max_users, previous_max_provider_runs=near.max_provider_runs,
        max_claims=payload.max_claims, max_documents=payload.max_documents,
        max_users=payload.max_users, max_provider_runs=payload.max_provider_runs,
        starts_at=starts, expires_at=expires,
        deployment_isolation_reference=_reference(payload.deployment_isolation_reference),
        provider_project_reference=_reference(payload.provider_project_reference),
        credential_control_reference=_reference(payload.credential_control_reference),
        privacy_legal_reference=_reference(payload.privacy_legal_reference),
        monitoring_reference=_reference(payload.monitoring_reference),
        incident_response_reference=_reference(payload.incident_response_reference),
        rollback_reference=_reference(payload.rollback_reference),
        platform_reliability_reference=_reference(payload.platform_reliability_reference),
        data_protection_reference=_reference(payload.data_protection_reference),
        executive_sponsor_reference=_reference(payload.executive_sponsor_reference),
        change_ticket_reference=_reference(payload.change_ticket_reference),
        status="pending_approvals",
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Sprint 11R authorization key or attempt already exists")
    _audit(db, user, "CREATE_AI_BOUNDED_FULL_PRODUCTION_AUTHORIZATION", "ai_bounded_full_production_authorization", item.id,
           {"near_universal_outcome_assessment_id": str(outcome.id), "rollout_percentage": 100,
            "bounded_100_percent_cohort_authorized": False, "production_wide_unbounded_authorized": False},
           "Created an expiring Sprint 11R bounded 100% authorization attempt; no rollout is authorized yet.")
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def record_approval(db: Session, user: User, item: AIBoundedFullProductionAuthorization,
                    role: str, action: str, evidence_reference: str | None, note: str) -> dict:
    if item.status not in {"pending_approvals", "decision_ready"}:
        raise HTTPException(409, "This authorization is not accepting approvals")
    if role not in APPROVAL_ROLES:
        raise HTTPException(422, "Unsupported Sprint 11R approval role")
    if user.id == item.requested_by_id:
        raise HTTPException(409, "The requester cannot approve the Sprint 11R attempt")
    existing = _approvals(db, item.id)
    if any(x.approval_role == role for x in existing):
        raise HTTPException(409, "This approval role already recorded a decision")
    if any(x.approver_id == user.id for x in existing):
        raise HTTPException(409, "Each Sprint 11R approval role requires a distinct human")
    ref = _reference(evidence_reference) if evidence_reference else None
    if action == "approve" and not ref:
        raise HTTPException(422, "Approval requires bounded evidence")
    row = AIBoundedFullProductionApproval(
        organization_id=user.organization_id, authorization_id=item.id, approver_id=user.id,
        approval_role=role, action=action, evidence_reference=ref, note=note.strip(), approved_at=datetime.now(UTC),
    )
    db.add(row); db.flush()
    current = _approvals(db, item.id)
    if action == "reject":
        item.status, item.outcome = "held", "approval_rejected"
    elif (len(current) == len(APPROVAL_ROLES) and {x.approval_role for x in current} == APPROVAL_ROLES
          and all(x.action == "approve" for x in current) and len({x.approver_id for x in current}) == len(APPROVAL_ROLES)):
        item.status = "decision_ready"
    _audit(db, user, f"{action.upper()}_AI_BOUNDED_FULL_PRODUCTION_APPROVAL", "ai_bounded_full_production_authorization",
           item.id, {"approval_role": role, "action": action}, f"Independent Sprint 11R {role} review recorded.")
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def decide_authorization(db: Session, user: User, item: AIBoundedFullProductionAuthorization,
                         outcome: str, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit Admin Sprint 11R decision confirmation is required")
    if item.status != "decision_ready":
        raise HTTPException(409, "Thirteen independent approvals are required before Admin decision")
    approvals = _approvals(db, item.id)
    reviewer_ids = {x.approver_id for x in approvals}
    if (len(approvals) != len(APPROVAL_ROLES) or {x.approval_role for x in approvals} != APPROVAL_ROLES
        or not all(x.action == "approve" for x in approvals) or len(reviewer_ids) != len(APPROVAL_ROLES)
        or any(x.approver_id == item.requested_by_id for x in approvals)):
        raise HTTPException(409, "Independent approval set is incomplete")
    if user.id == item.requested_by_id or user.id in reviewer_ids:
        raise HTTPException(409, "Final Admin must be distinct from the requester and all thirteen reviewers")
    _anchor_still_valid(db, item)
    snapshot = {
        "schema": "mcri-ai-bounded-full-production-authorization-v1",
        "authorization_id": str(item.id), "near_universal_outcome_assessment_id": str(item.near_universal_outcome_assessment_id),
        "near_universal_outcome_assessment_hash": item.near_universal_outcome_assessment_hash,
        "near_universal_outcome_decision_hash": item.near_universal_outcome_decision_hash,
        "near_universal_completion_hash": item.near_universal_completion_hash,
        "bundle": {"model": item.model, "prompt": item.prompt_bundle_version, "schema": item.schema_bundle_version,
                   "max_input_chars": item.max_input_chars, "max_output_tokens": item.max_output_tokens,
                   "provider_project_reference": item.provider_project_reference},
        "rollout_percentage": 100,
        "caps": {"claims": item.max_claims, "documents": item.max_documents,
                 "users": item.max_users, "provider_runs": item.max_provider_runs},
        "approvals": [{"role": x.approval_role, "approver_id": str(x.approver_id), "action": x.action} for x in approvals],
        "outcome": outcome,
        "bounded_100_percent_cohort_authorized": outcome == "authorize_bounded_100_percent_cohort",
        "production_wide_unbounded_authorized": False,
        "restricted_documents_authorized": False, "new_document_classes_authorized": False,
        "autonomous_claim_decisions_authorized": False, "different_human_review_required": True,
    }
    item.finalized_by_id = user.id; item.decision_note = note.strip(); item.decision_hash = _hash(snapshot); item.decided_at = datetime.now(UTC)
    if outcome == "authorize_bounded_100_percent_cohort":
        item.status, item.outcome = "authorized", outcome
    elif outcome == "hold_for_remediation":
        item.status, item.outcome = "held", outcome
    else:
        item.status, item.outcome = "rejected", "reject_progression"
    _audit(db, user, "DECIDE_AI_BOUNDED_FULL_PRODUCTION_AUTHORIZATION", "ai_bounded_full_production_authorization", item.id,
           {"status": item.status, "outcome": item.outcome, "decision_hash": item.decision_hash,
            "bounded_100_percent_cohort_authorized": item.status == "authorized",
            "production_wide_unbounded_authorized": False},
           "Admin recorded the immutable Sprint 11R decision; unbounded Production-wide remains prohibited.")
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def attest_document(db: Session, user: User, item: AIBoundedFullProductionAuthorization,
                    payload: AIBoundedFullProductionDocumentCreate) -> dict:
    if not payload.confirm_new_bounded_full_eligibility:
        raise HTTPException(422, "Explicit fresh Sprint 11R eligibility confirmation is required")
    if not _active(item):
        raise HTTPException(409, "Only an active Sprint 11R authorization may attest documents")
    _anchor_still_valid(db, item)
    document = db.scalar(select(Document).where(
        Document.id == payload.document_id, Document.organization_id == user.organization_id, Document.claim_id == payload.claim_id,
    ))
    if document is None:
        raise HTTPException(404, "Document not found in this tenant and claim")
    confidentiality = document.confidentiality_level.value if hasattr(document.confidentiality_level, "value") else str(document.confidentiality_level)
    if confidentiality not in {ConfidentialityLevel.INTERNAL.value, ConfidentialityLevel.CONFIDENTIAL.value}:
        raise HTTPException(409, "Restricted or unsupported confidentiality is prohibited")
    if document.document_type not in item.allowed_document_types:
        raise HTTPException(409, "Document type is outside the Sprint 11R allowlist")
    bucket = _rollout_bucket(document.id)
    if bucket >= 100:
        raise HTTPException(409, "Document is outside the deterministic Sprint 11R cohort")
    existing = [x for x in _documents(db, item.id) if x.status == "eligible"]
    if any(x.document_id == document.id for x in existing):
        raise HTTPException(409, "Document already has active Sprint 11R eligibility")
    if document.claim_id not in {x.claim_id for x in existing} and len({x.claim_id for x in existing}) >= item.max_claims:
        raise HTTPException(409, "Sprint 11R claim cap reached")
    if len(existing) >= item.max_documents:
        raise HTTPException(409, "Sprint 11R document cap reached")
    attempts = [x for x in _documents(db, item.id) if x.document_id == document.id]
    now = datetime.now(UTC)
    legal, minimum, ticket = (_reference(payload.legal_basis_reference), _reference(payload.data_minimization_reference), _reference(payload.change_ticket_reference))
    snapshot = {"schema": "mcri-ai-bounded-full-document-eligibility-v1", "authorization_id": str(item.id),
                "authorization_decision_hash": item.decision_hash, "document_id": str(document.id), "claim_id": str(document.claim_id),
                "document_type": document.document_type, "confidentiality_level": confidentiality, "rollout_bucket": bucket,
                "legal_basis_reference": legal, "data_minimization_reference": minimum, "change_ticket_reference": ticket,
                "attestation_number": len(attempts) + 1, "attested_at": now.isoformat(), "prior_eligibility_carried_forward": False}
    entry = AIBoundedFullProductionDocumentEligibility(
        organization_id=user.organization_id, authorization_id=item.id, claim_id=document.claim_id, document_id=document.id,
        attested_by_id=user.id, attestation_number=len(attempts) + 1, rollout_bucket=bucket,
        document_type=document.document_type, confidentiality_level=confidentiality, legal_basis_reference=legal,
        data_minimization_reference=minimum, change_ticket_reference=ticket, note=payload.note.strip(),
        snapshot_hash=_hash(snapshot), status="eligible", attested_at=now,
    )
    db.add(entry); db.flush()
    _audit(db, user, "ATTEST_AI_BOUNDED_FULL_PRODUCTION_DOCUMENT", "ai_bounded_full_production_document_eligibility", entry.id,
           {"authorization_id": str(item.id), "document_id": str(document.id), "rollout_bucket": bucket,
            "prior_eligibility_carried_forward": False}, "Fresh Sprint 11R document eligibility recorded without raw content.")
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def revoke_document(db: Session, user: User, item: AIBoundedFullProductionAuthorization,
                    eligibility_id: UUID, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit document eligibility revocation is required")
    entry = db.scalar(select(AIBoundedFullProductionDocumentEligibility).where(
        AIBoundedFullProductionDocumentEligibility.id == eligibility_id,
        AIBoundedFullProductionDocumentEligibility.authorization_id == item.id,
        AIBoundedFullProductionDocumentEligibility.organization_id == user.organization_id,
    ))
    if entry is None:
        raise HTTPException(404, "Sprint 11R document eligibility not found")
    if entry.status != "eligible":
        raise HTTPException(409, "Document eligibility is already inactive")
    entry.status = "revoked"; entry.revoked_by_id = user.id; entry.revoked_at = datetime.now(UTC); entry.revocation_note = note.strip()
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def require_bounded_full_production_runtime_authorization(
    db: Session, *, organization_id: UUID, document: Document,
    expected_document_type: str, input_char_count: int, requested_by_id: UUID | None = None,
) -> tuple[AIBoundedFullProductionAuthorization, AIBoundedFullProductionDocumentEligibility]:
    item = latest_bounded_full_production_attempt(db, organization_id)
    if item is None:
        raise HTTPException(409, "No Sprint 11R control plane exists")
    if not _active(item):
        raise HTTPException(409, "Newest Sprint 11R control plane is inactive; fallback is prohibited")
    _anchor_still_valid(db, item)
    settings = get_settings()
    if (settings.ai_model != item.model or settings.ai_prompt_bundle_version != item.prompt_bundle_version
        or settings.ai_schema_bundle_version != item.schema_bundle_version or settings.ai_max_output_tokens != item.max_output_tokens):
        raise HTTPException(409, "Configured AI bundle differs from the authorized Sprint 11R bundle")
    confidentiality = document.confidentiality_level.value if hasattr(document.confidentiality_level, "value") else str(document.confidentiality_level)
    if confidentiality not in {ConfidentialityLevel.INTERNAL.value, ConfidentialityLevel.CONFIDENTIAL.value}:
        raise HTTPException(409, "Only Internal or Confidential documents are permitted")
    if expected_document_type not in item.allowed_document_types or document.document_type != expected_document_type:
        raise HTTPException(409, "Document type is outside the Sprint 11R allowlist")
    if input_char_count > item.max_input_chars:
        raise HTTPException(409, "Document exceeds the authorized input limit")
    eligibility = db.scalar(select(AIBoundedFullProductionDocumentEligibility).where(
        AIBoundedFullProductionDocumentEligibility.organization_id == organization_id,
        AIBoundedFullProductionDocumentEligibility.authorization_id == item.id,
        AIBoundedFullProductionDocumentEligibility.document_id == document.id,
        AIBoundedFullProductionDocumentEligibility.status == "eligible",
    ).order_by(AIBoundedFullProductionDocumentEligibility.attestation_number.desc()))
    if eligibility is None:
        raise HTTPException(409, "Document requires fresh Sprint 11R eligibility")
    incidents = _incidents(db, item.id)
    if any(x.status == "open" for x in incidents):
        raise HTTPException(409, "An open incident blocks Sprint 11R AI")
    if any(x.category in SAFETY_CATEGORIES for x in incidents):
        raise HTTPException(409, "Privacy, Security or Cross-tenant incident history blocks this Sprint 11R attempt")
    runs = _runs(db, item.id)
    if len(runs) >= item.max_provider_runs:
        raise HTTPException(409, "Sprint 11R provider-run cap reached")
    participating = {x.requested_by_id for x in runs if x.requested_by_id is not None}
    if requested_by_id is not None and requested_by_id not in participating and len(participating) >= item.max_users:
        raise HTTPException(409, "Sprint 11R user cap reached")
    if (runs and item.decided_at is not None and datetime.now(UTC) > _as_utc(item.decided_at) + timedelta(minutes=item.monitor_interval_minutes * 2)
        and not _latest_monitor_pass(db, item, require_fresh=True)):
        raise HTTPException(409, "A fresh passing Sprint 11R monitor is required")
    return item, eligibility


def reserve_run_if_bounded_full_production(
    db: Session, *, user: User, document: Document, expected_document_type: str,
    input_char_count: int, processing_job_id: UUID,
) -> AIBoundedFullProductionRun | None:
    if get_settings().app_env.lower().strip() != "production":
        return None
    latest = latest_bounded_full_production_attempt(db, user.organization_id)
    if latest is None:
        return None
    existing = db.scalar(select(AIBoundedFullProductionRun).where(
        AIBoundedFullProductionRun.organization_id == user.organization_id,
        AIBoundedFullProductionRun.processing_job_id == processing_job_id,
    ))
    if existing is not None:
        return existing
    item, eligibility = require_bounded_full_production_runtime_authorization(
        db, organization_id=user.organization_id, document=document,
        expected_document_type=expected_document_type, input_char_count=input_char_count, requested_by_id=user.id,
    )
    run = AIBoundedFullProductionRun(
        organization_id=user.organization_id, authorization_id=item.id, eligibility_id=eligibility.id,
        claim_id=document.claim_id, document_id=document.id, requested_by_id=user.id,
        run_key=f"processing-{processing_job_id}", processing_job_id=processing_job_id,
        task_type=expected_document_type, status="queued", queued_at=datetime.now(UTC),
    )
    db.add(run); db.flush()
    _audit(db, user, "RESERVE_AI_BOUNDED_FULL_PRODUCTION_RUN", "ai_bounded_full_production_run", run.id,
           {"authorization_id": str(item.id), "document_id": str(document.id), "processing_job_id": str(processing_job_id),
            "task_type": expected_document_type, "raw_content_stored": False, "different_human_review_required": True},
           "Content-free Sprint 11R provider-run reservation.")
    return run


def get_run(db: Session, organization_id: UUID, run_id: UUID) -> AIBoundedFullProductionRun:
    run = db.scalar(select(AIBoundedFullProductionRun).where(
        AIBoundedFullProductionRun.id == run_id, AIBoundedFullProductionRun.organization_id == organization_id,
    ))
    if run is None:
        raise HTTPException(404, "Sprint 11R run not found")
    return run


def record_run_outcome(db: Session, user: User, run: AIBoundedFullProductionRun, *, human_review_action: str,
                       output_candidate_count: int, human_edit_count: int, unsupported_output_count: int,
                       source_grounded_output_count: int, source_grounding_total_count: int, latency_ms: int,
                       observed_provider_cost_microusd: int, evidence_reference: str, note: str,
                       confirm_human_review: bool) -> dict:
    if not confirm_human_review:
        raise HTTPException(422, "Explicit human-review confirmation is required")
    if run.status != "queued":
        raise HTTPException(409, "This run outcome is immutable")
    if run.requested_by_id == user.id:
        raise HTTPException(409, "A different human must review every Sprint 11R AI output")
    job = db.scalar(select(DocumentProcessingJob).where(
        DocumentProcessingJob.id == run.processing_job_id, DocumentProcessingJob.organization_id == user.organization_id,
    ))
    if job is None or job.status != ProcessingJobStatus.COMPLETED:
        raise HTTPException(409, "Provider processing must complete before human review")
    if human_edit_count > output_candidate_count or unsupported_output_count > output_candidate_count:
        raise HTTPException(422, "Review counters cannot exceed output candidates")
    if source_grounded_output_count > source_grounding_total_count or source_grounding_total_count > output_candidate_count:
        raise HTTPException(422, "Grounding counters are inconsistent with output candidates")
    ref = _reference(evidence_reference)
    snapshot = {"schema": "mcri-ai-bounded-full-run-outcome-v1", "run_id": str(run.id),
                "authorization_id": str(run.authorization_id), "processing_job_id": str(run.processing_job_id),
                "task_type": run.task_type, "human_review_action": human_review_action,
                "output_candidate_count": output_candidate_count, "human_edit_count": human_edit_count,
                "unsupported_output_count": unsupported_output_count, "source_grounded_output_count": source_grounded_output_count,
                "source_grounding_total_count": source_grounding_total_count, "latency_ms": latency_ms,
                "observed_provider_cost_microusd": observed_provider_cost_microusd, "evidence_reference": ref,
                "different_human_review_completed": True, "authoritative_facts_auto_updated": False, "raw_content_stored": False}
    run.reviewed_by_id = user.id; run.status = "human_reviewed"; run.human_review_action = human_review_action
    run.output_candidate_count = output_candidate_count; run.human_edit_count = human_edit_count
    run.unsupported_output_count = unsupported_output_count; run.source_grounded_output_count = source_grounded_output_count
    run.source_grounding_total_count = source_grounding_total_count; run.latency_ms = latency_ms
    run.observed_provider_cost_microusd = observed_provider_cost_microusd; run.evidence_reference = ref
    run.note = note.strip(); run.reviewed_at = datetime.now(UTC); run.outcome_hash = _hash(snapshot)
    db.commit()
    return authorization_response(db, get_authorization(db, user.organization_id, run.authorization_id))


def record_monitor(db: Session, user: User, item: AIBoundedFullProductionAuthorization,
                   monitor_key: str, note: str, confirm: bool) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit live monitor confirmation is required")
    if item.status not in {"authorized", "paused"}:
        raise HTTPException(409, "Only an authorized or paused Sprint 11R cohort can be monitored")
    _anchor_still_valid(db, item)
    runs, incidents = _runs(db, item.id), _incidents(db, item.id)
    reviewed = [x for x in runs if x.status == "human_reviewed"]
    different = [x for x in reviewed if x.requested_by_id is not None and x.reviewed_by_id is not None and x.requested_by_id != x.reviewed_by_id]
    actions = [x for x in reviewed if x.human_review_action in {"approve", "edit", "reject"}]
    candidates = sum(x.output_candidate_count or 0 for x in reviewed)
    unsupported = sum(x.unsupported_output_count or 0 for x in reviewed)
    grounded = sum(x.source_grounded_output_count or 0 for x in reviewed)
    grounding_total = sum(x.source_grounding_total_count or 0 for x in reviewed)
    latencies = sorted(x.latency_ms for x in reviewed if x.latency_ms is not None)
    costs = [x.observed_provider_cost_microusd for x in reviewed if x.observed_provider_cost_microusd is not None]
    p95 = latencies[max(ceil(0.95 * len(latencies)) - 1, 0)] if latencies else None
    review_rate = _rate_bps(len(reviewed), len(runs)); different_rate = _rate_bps(len(different), len(runs))
    reject_rate = _rate_bps(sum(x.human_review_action == "reject" for x in actions), len(actions))
    edit_rate = _rate_bps(sum(x.human_review_action == "edit" for x in actions), len(actions))
    unsupported_rate = _rate_bps(unsupported, candidates); grounding_rate = _rate_bps(grounded, grounding_total); mean_cost = _mean(costs)
    half = len(reviewed) // 2; first = _segment_metrics(reviewed[:half]) if half else {}; second = _segment_metrics(reviewed[half:]) if half else {}
    regressions = []
    for key in ("reject_rate_bps", "edit_rate_bps", "unsupported_rate_bps"):
        if first.get(key) is not None and second.get(key) is not None:
            regressions.append(max(0, second[key] - first[key]))
    if first.get("grounding_rate_bps") is not None and second.get("grounding_rate_bps") is not None:
        regressions.append(max(0, first["grounding_rate_bps"] - second["grounding_rate_bps"]))
    quality_regression = max(regressions) if regressions else None
    latency_regression = _relative_increase_bps(first.get("mean_latency_ms"), second.get("mean_latency_ms")) if half else None
    cost_regression = _relative_increase_bps(first.get("mean_cost_microusd"), second.get("mean_cost_microusd")) if half else None
    open_blocking = sum(x.status == "open" and x.severity in BLOCKING_SEVERITIES for x in incidents)
    safety_incidents = sum(x.category in SAFETY_CATEGORIES for x in incidents)
    metrics = {"provider_run_count": len(runs), "human_reviewed_run_count": len(reviewed),
               "human_review_rate_bps": review_rate, "different_human_review_rate_bps": different_rate,
               "human_reject_rate_bps": reject_rate, "human_edit_rate_bps": edit_rate,
               "unsupported_output_rate_bps": unsupported_rate, "source_grounding_validity_bps": grounding_rate,
               "p95_latency_ms": p95, "mean_observed_provider_cost_microusd": mean_cost,
               "quality_grounding_regression_bps": quality_regression, "latency_regression_bps": latency_regression,
               "cost_regression_bps": cost_regression, "open_high_or_critical_incident_count": open_blocking,
               "safety_boundary_incident_count": safety_incidents}
    failures = []
    if review_rate != 10000: failures.append("human_review_coverage")
    if different_rate != 10000: failures.append("different_human_review_coverage")
    if reject_rate is None or reject_rate > item.max_reject_rate_bps: failures.append("reject_rate")
    if edit_rate is None or edit_rate > item.max_edit_rate_bps: failures.append("edit_rate")
    if unsupported_rate is None or unsupported_rate > item.max_unsupported_output_rate_bps: failures.append("unsupported_output_rate")
    if grounding_rate is None or grounding_rate < item.min_source_grounding_validity_bps: failures.append("source_grounding")
    if p95 is None or p95 > item.max_p95_latency_ms: failures.append("p95_latency")
    if mean_cost is None or mean_cost > item.max_mean_cost_microusd: failures.append("mean_provider_cost")
    if len(reviewed) >= 2:
        if quality_regression is None or quality_regression > item.max_quality_regression_bps: failures.append("quality_grounding_regression")
        if latency_regression is None or latency_regression > item.max_latency_regression_bps: failures.append("latency_regression")
        if cost_regression is None or cost_regression > item.max_cost_regression_bps: failures.append("cost_regression")
    if open_blocking: failures.append("open_high_or_critical_incident")
    if safety_incidents: failures.append("privacy_security_or_cross_tenant_incident")
    metrics["overall_pass"] = not failures
    now = datetime.now(UTC)
    snapshot = {"schema": "mcri-ai-bounded-full-monitor-v1", "authorization_id": str(item.id),
                "authorization_decision_hash": item.decision_hash, "metrics": metrics,
                "failure_reasons": failures, "monitor_key": monitor_key, "monitored_at": now.isoformat()}
    monitor = AIBoundedFullProductionMonitor(
        organization_id=user.organization_id, authorization_id=item.id, initiated_by_id=user.id,
        monitor_key=monitor_key, metrics=metrics, failure_reasons=failures,
        status="pass" if not failures else "fail", monitor_hash=_hash(snapshot), note=note.strip(), monitored_at=now,
    )
    db.add(monitor); db.flush()
    if failures and item.status == "authorized":
        item.status, item.outcome = "paused", "monitor_rollback"
        db.add(AIBoundedFullProductionIncident(
            organization_id=user.organization_id, authorization_id=item.id, reported_by_id=user.id,
            severity="high", category="quality", evidence_reference=f"monitor://ai-bounded-full/{monitor.id}",
            note="Automatic rollback incident created by a failing Sprint 11R monitor.", status="open", reported_at=now,
        ))
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def report_incident(db: Session, user: User, item: AIBoundedFullProductionAuthorization, *, severity: str,
                    category: str, evidence_reference: str, note: str, confirm: bool) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit pause-and-rollback confirmation is required")
    if item.status != "authorized":
        raise HTTPException(409, "Only an active Sprint 11R authorization can be paused")
    incident = AIBoundedFullProductionIncident(
        organization_id=user.organization_id, authorization_id=item.id, reported_by_id=user.id,
        severity=severity, category=category, evidence_reference=_reference(evidence_reference), note=note.strip(),
        status="open", reported_at=datetime.now(UTC),
    )
    db.add(incident); item.status, item.outcome = "paused", "incident_rollback"
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def resolve_incident(db: Session, user: User, item: AIBoundedFullProductionAuthorization, incident_id: UUID, *,
                     resolution_reference: str, resolution_note: str, confirm: bool) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit incident resolution confirmation is required")
    incident = db.scalar(select(AIBoundedFullProductionIncident).where(
        AIBoundedFullProductionIncident.id == incident_id, AIBoundedFullProductionIncident.authorization_id == item.id,
        AIBoundedFullProductionIncident.organization_id == user.organization_id,
    ))
    if incident is None: raise HTTPException(404, "Sprint 11R incident not found")
    if incident.status != "open": raise HTTPException(409, "Incident is already resolved")
    incident.status = "resolved"; incident.resolved_by_id = user.id; incident.resolved_at = datetime.now(UTC)
    incident.resolution_reference = _reference(resolution_reference); incident.resolution_note = resolution_note.strip()
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def resume_authorization(db: Session, user: User, item: AIBoundedFullProductionAuthorization, confirm: bool, note: str) -> dict:
    if not confirm: raise HTTPException(422, "Explicit Admin recovery confirmation is required")
    if item.status != "paused": raise HTTPException(409, "Only a paused Sprint 11R authorization can resume")
    incidents = _incidents(db, item.id)
    if any(x.status == "open" for x in incidents): raise HTTPException(409, "Open incidents block recovery")
    if any(x.category in SAFETY_CATEGORIES for x in incidents): raise HTTPException(409, "Safety incidents require a new Sprint 11R attempt")
    if not _latest_monitor_pass(db, item, require_fresh=True) or not _recovery_complete(db, item):
        raise HTTPException(409, "Fresh passing monitor and complete recovery evidence are required")
    if _as_utc(item.expires_at) <= datetime.now(UTC): raise HTTPException(409, "Expired authorization cannot resume")
    _anchor_still_valid(db, item); item.status, item.outcome = "authorized", "resumed_after_monitor"
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def revoke_authorization(db: Session, user: User, item: AIBoundedFullProductionAuthorization, confirm: bool, note: str) -> dict:
    if not confirm: raise HTTPException(422, "Explicit Sprint 11R kill-switch confirmation is required")
    if item.status in {"revoked", "completed"}: raise HTTPException(409, "Authorization is already terminal")
    item.status, item.outcome = "revoked", "revoked"; item.revoked_by_id = user.id; item.revoked_at = datetime.now(UTC); item.revocation_note = note.strip()
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def complete_authorization(db: Session, user: User, item: AIBoundedFullProductionAuthorization, confirm: bool, note: str) -> dict:
    if not confirm: raise HTTPException(422, "Explicit Sprint 11R completion confirmation is required")
    if not _active(item): raise HTTPException(409, "Only an active, unexpired Sprint 11R cohort can complete")
    _anchor_still_valid(db, item)
    runs, incidents, monitors = _runs(db, item.id), _incidents(db, item.id), _monitors(db, item.id)
    if len(runs) < MIN_COMPLETION_RUNS:
        raise HTTPException(409, "Sprint 11R completion requires an adequate minimum run sample")
    if any(x.status != "human_reviewed" or x.requested_by_id == x.reviewed_by_id for x in runs):
        raise HTTPException(409, "Every Sprint 11R provider run requires completed different-human review")
    active_workflows = {x.task_type for x in runs}
    for workflow in active_workflows:
        if sum(x.task_type == workflow and x.status == "human_reviewed" for x in runs) < MIN_COMPLETION_RUNS_PER_ACTIVE_WORKFLOW:
            raise HTTPException(409, "Each active Sprint 11R workflow requires an adequate reviewed sample")
    if any(x.status == "open" for x in incidents): raise HTTPException(409, "Open incidents block completion")
    if any(x.category in SAFETY_CATEGORIES for x in incidents): raise HTTPException(409, "Safety incident history blocks successful completion")
    if not _latest_monitor_pass(db, item, require_fresh=True): raise HTTPException(409, "A fresh passing final monitor is required before completion")
    if not _recovery_complete(db, item): raise HTTPException(409, "All rollback events require complete recovery evidence before completion")
    now = datetime.now(UTC)
    snapshot = {"schema": "mcri-ai-bounded-full-completion-v1", "authorization_id": str(item.id),
                "authorization_decision_hash": item.decision_hash,
                "near_universal_outcome_assessment_hash": item.near_universal_outcome_assessment_hash,
                "near_universal_outcome_decision_hash": item.near_universal_outcome_decision_hash,
                "rollout_percentage": 100, "run_hashes": [x.outcome_hash for x in runs],
                "monitor_hashes": [x.monitor_hash for x in monitors],
                "incident_states": [{"id": str(x.id), "category": x.category, "severity": x.severity,
                                    "status": x.status, "resolution_reference": x.resolution_reference} for x in incidents],
                "completed_at": now.isoformat(), "bounded_100_percent_cohort_authorized": True,
                "production_wide_unbounded_authorized": False, "restricted_documents_authorized": False,
                "new_document_classes_authorized": False, "autonomous_claim_decisions_authorized": False,
                "different_human_review_required": True}
    item.status, item.outcome = "completed", "completed"; item.completed_at = now; item.completion_note = note.strip(); item.completion_hash = _hash(snapshot)
    db.commit(); db.refresh(item)
    return authorization_response(db, item)
