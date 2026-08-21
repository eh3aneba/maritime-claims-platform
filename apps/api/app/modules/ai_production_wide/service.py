import json
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from math import ceil
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.ai_bounded_full_production.models import AIBoundedFullProductionAuthorization
from app.modules.ai_bounded_full_production_outcomes.models import AIBoundedFullProductionOutcomeAssessment
from app.modules.ai_production_wide.models import (
    AIProductionDecisionLog,
    AIProductionEligibilityDecision,
    AIProductionWideApproval,
    AIProductionWideAuthorization,
    AIProductionWideIncident,
    AIProductionWideMonitor,
)
from app.modules.ai_production_wide.schemas import AIProductionWideCreate
from app.modules.audit.service import write_audit_log
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.users.models import User

REFERENCE = re.compile(r"^(artifact|runbook|ticket|monitor|policy)://[A-Za-z0-9._:/-]{3,450}$")
APPROVAL_ROLES = {
    "security", "privacy", "product", "operations", "risk", "claims_governance",
    "ai_quality", "legal_data_governance", "business_owner", "platform_reliability",
    "independent_production_assurance", "data_protection", "executive_production_sponsor",
    "enterprise_architecture_resilience", "internal_audit_model_risk",
}
ALLOWED_DOCUMENT_TYPES = {"chief_engineer_report", "engine_log"}
SAFETY_CATEGORIES = {"privacy", "security", "cross_tenant"}
BLOCKING_SEVERITIES = {"high", "critical"}


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _hash(payload: dict) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _reference(value: str) -> str:
    ref = value.strip()
    if not REFERENCE.fullmatch(ref):
        raise HTTPException(422, "Sprint 11T evidence must use an allowlisted reference URI")
    return ref


def _audit(db: Session, user: User, action: str, entity_type: str, entity_id: UUID, values: dict, details: str) -> None:
    write_audit_log(
        db, organization_id=user.organization_id, user_id=user.id, action=action,
        entity_type=entity_type, entity_id=entity_id, new_values=values, details=details,
    )


def _approvals(db: Session, authorization_id: UUID) -> list[AIProductionWideApproval]:
    return list(db.scalars(select(AIProductionWideApproval).where(
        AIProductionWideApproval.authorization_id == authorization_id,
    ).order_by(AIProductionWideApproval.approval_role.asc())))


def _eligibility(db: Session, authorization_id: UUID) -> list[AIProductionEligibilityDecision]:
    return list(db.scalars(select(AIProductionEligibilityDecision).where(
        AIProductionEligibilityDecision.authorization_id == authorization_id,
    ).order_by(AIProductionEligibilityDecision.evaluated_at.asc())))


def _logs(db: Session, authorization_id: UUID) -> list[AIProductionDecisionLog]:
    return list(db.scalars(select(AIProductionDecisionLog).where(
        AIProductionDecisionLog.authorization_id == authorization_id,
    ).order_by(AIProductionDecisionLog.queued_at.asc())))


def _monitors(db: Session, authorization_id: UUID) -> list[AIProductionWideMonitor]:
    return list(db.scalars(select(AIProductionWideMonitor).where(
        AIProductionWideMonitor.authorization_id == authorization_id,
    ).order_by(AIProductionWideMonitor.monitored_at.asc())))


def _incidents(db: Session, authorization_id: UUID) -> list[AIProductionWideIncident]:
    return list(db.scalars(select(AIProductionWideIncident).where(
        AIProductionWideIncident.authorization_id == authorization_id,
    ).order_by(AIProductionWideIncident.reported_at.asc())))


def latest_production_wide_attempt(db: Session, organization_id: UUID) -> AIProductionWideAuthorization | None:
    return db.scalar(select(AIProductionWideAuthorization).where(
        AIProductionWideAuthorization.organization_id == organization_id,
    ).order_by(AIProductionWideAuthorization.created_at.desc(), AIProductionWideAuthorization.id.desc()))


def get_authorization(db: Session, organization_id: UUID, authorization_id: UUID) -> AIProductionWideAuthorization:
    item = db.scalar(select(AIProductionWideAuthorization).where(
        AIProductionWideAuthorization.id == authorization_id,
        AIProductionWideAuthorization.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Sprint 11T Production-wide authorization not found")
    return item


def _active(item: AIProductionWideAuthorization) -> bool:
    now = datetime.now(UTC)
    return item.status == "authorized" and _as_utc(item.starts_at) <= now < _as_utc(item.expires_at)


def _anchor(db: Session, item: AIProductionWideAuthorization) -> AIBoundedFullProductionOutcomeAssessment:
    assessment = db.scalar(select(AIBoundedFullProductionOutcomeAssessment).where(
        AIBoundedFullProductionOutcomeAssessment.id == item.bounded_full_outcome_assessment_id,
        AIBoundedFullProductionOutcomeAssessment.organization_id == item.organization_id,
    ))
    if assessment is None:
        raise HTTPException(409, "Sprint 11S anchor no longer exists")
    if (assessment.status != "recommended"
        or assessment.outcome != "recommend_separate_production_wide_authorization_review"
        or not (assessment.metrics or {}).get("overall_pass")
        or assessment.assessment_hash != item.bounded_full_outcome_assessment_hash
        or assessment.decision_hash != item.bounded_full_outcome_decision_hash):
        raise HTTPException(409, "Sprint 11S recommendation/hash chain is no longer valid")
    bounded = db.scalar(select(AIBoundedFullProductionAuthorization).where(
        AIBoundedFullProductionAuthorization.id == assessment.bounded_full_authorization_id,
        AIBoundedFullProductionAuthorization.organization_id == item.organization_id,
    ))
    if bounded is None or bounded.decision_hash != item.bounded_full_decision_hash or bounded.completion_hash != item.bounded_full_completion_hash:
        raise HTTPException(409, "Sprint 11R decision/completion hash chain changed")
    return assessment


def _policy_payload(item: AIProductionWideAuthorization) -> dict:
    return {
        "schema": "mcri-production-eligibility-policy-v1",
        "authorization_id": str(item.id),
        "version": item.eligibility_policy_version,
        "allowed_document_types": sorted(item.allowed_document_types),
        "allowed_confidentiality": ["internal", "confidential"],
        "eligibility_policy_reference": item.eligibility_policy_reference,
        "legal_basis_policy_reference": item.legal_basis_policy_reference,
        "data_minimization_policy_reference": item.data_minimization_policy_reference,
        "bundle": {
            "model": item.model,
            "prompt": item.prompt_bundle_version,
            "schema": item.schema_bundle_version,
            "max_input_chars": item.max_input_chars,
            "max_output_tokens": item.max_output_tokens,
        },
        "different_human_review_required": True,
        "restricted_documents_authorized": False,
        "new_document_classes_authorized": False,
    }


def _row_dict(row) -> dict:
    data = {}
    for column in row.__table__.columns:
        value = getattr(row, column.name)
        data[column.name] = value
    return data


def authorization_response(db: Session, item: AIProductionWideAuthorization) -> dict:
    approvals, eligibility, logs, monitors, incidents = (
        _approvals(db, item.id), _eligibility(db, item.id), _logs(db, item.id), _monitors(db, item.id), _incidents(db, item.id)
    )
    reviewed = [x for x in logs if x.status == "human_reviewed"]
    return {
        **_row_dict(item),
        "approvals": [_row_dict(x) for x in approvals],
        "eligibility_decisions": [_row_dict(x) for x in eligibility],
        "decision_logs": [_row_dict(x) for x in logs],
        "monitors": [_row_dict(x) for x in monitors],
        "incidents": [_row_dict(x) for x in incidents],
        "summary": {
            "production_wide_human_reviewed_ai_authorized": _active(item),
            "eligible_document_decision_count": sum(1 for x in eligibility if x.eligible),
            "provider_run_count": len(logs),
            "human_reviewed_run_count": len(reviewed),
            "different_human_review_required": True,
            "restricted_documents_authorized": False,
            "new_document_classes_authorized": False,
            "autonomous_claim_decisions_authorized": False,
            "authoritative_facts_auto_updated": False,
            "manual_per_document_attestation_required": False,
            "production_eligibility_policy_enforced": True,
        },
    }


def list_authorizations(db: Session, organization_id: UUID) -> list[dict]:
    rows = list(db.scalars(select(AIProductionWideAuthorization).where(
        AIProductionWideAuthorization.organization_id == organization_id,
    ).order_by(AIProductionWideAuthorization.created_at.desc())))
    return [authorization_response(db, x) for x in rows]


def create_authorization(db: Session, user: User, payload: AIProductionWideCreate) -> dict:
    if not payload.confirm_production_wide_human_reviewed_ai:
        raise HTTPException(422, "Explicit Sprint 11T Production-wide human-reviewed confirmation is required")
    assessment = db.scalar(select(AIBoundedFullProductionOutcomeAssessment).where(
        AIBoundedFullProductionOutcomeAssessment.id == payload.bounded_full_outcome_assessment_id,
        AIBoundedFullProductionOutcomeAssessment.organization_id == user.organization_id,
    ))
    if assessment is None:
        raise HTTPException(404, "Sprint 11S assessment not found")
    if (assessment.status != "recommended"
        or assessment.outcome != "recommend_separate_production_wide_authorization_review"
        or not (assessment.metrics or {}).get("overall_pass")
        or not assessment.assessment_hash or not assessment.decision_hash):
        raise HTTPException(409, "A positive immutable Sprint 11S recommendation is required")
    bounded = db.scalar(select(AIBoundedFullProductionAuthorization).where(
        AIBoundedFullProductionAuthorization.id == assessment.bounded_full_authorization_id,
        AIBoundedFullProductionAuthorization.organization_id == user.organization_id,
    ))
    if bounded is None or bounded.status != "completed" or not bounded.decision_hash or not bounded.completion_hash:
        raise HTTPException(409, "Completed Sprint 11R evidence is required")
    allowed = set(payload.allowed_document_types)
    if not allowed or not allowed.issubset(ALLOWED_DOCUMENT_TYPES) or allowed != set(assessment.allowed_document_types):
        raise HTTPException(409, "Sprint 11T may only preserve the exact approved CE Report / Engine Log scope")
    now = datetime.now(UTC)
    starts = _as_utc(payload.starts_at); expires = _as_utc(payload.expires_at)
    if starts < now - timedelta(hours=1) or expires <= now or expires - starts > timedelta(days=90):
        raise HTTPException(422, "Sprint 11T authorization must be current and no longer than 90 days")
    attempts = list(db.scalars(select(AIProductionWideAuthorization).where(
        AIProductionWideAuthorization.organization_id == user.organization_id,
        AIProductionWideAuthorization.bounded_full_outcome_assessment_id == assessment.id,
    )))
    item = AIProductionWideAuthorization(
        organization_id=user.organization_id,
        bounded_full_outcome_assessment_id=assessment.id,
        requested_by_id=user.id,
        attempt_number=len(attempts) + 1,
        authorization_key=payload.authorization_key.strip(),
        bounded_full_outcome_assessment_hash=assessment.assessment_hash,
        bounded_full_outcome_decision_hash=assessment.decision_hash,
        bounded_full_decision_hash=bounded.decision_hash,
        bounded_full_completion_hash=bounded.completion_hash,
        model=assessment.model,
        prompt_bundle_version=assessment.prompt_bundle_version,
        schema_bundle_version=assessment.schema_bundle_version,
        max_input_chars=assessment.max_input_chars,
        max_output_tokens=assessment.max_output_tokens,
        allowed_document_types=sorted(allowed),
        starts_at=starts, expires_at=expires,
        eligibility_policy_version=payload.eligibility_policy_version.strip(),
        eligibility_policy_reference=_reference(payload.eligibility_policy_reference),
        legal_basis_policy_reference=_reference(payload.legal_basis_policy_reference),
        data_minimization_policy_reference=_reference(payload.data_minimization_policy_reference),
        deployment_isolation_reference=_reference(payload.deployment_isolation_reference),
        provider_project_reference=_reference(payload.provider_project_reference),
        credential_control_reference=_reference(payload.credential_control_reference),
        monitoring_reference=_reference(payload.monitoring_reference),
        incident_response_reference=_reference(payload.incident_response_reference),
        rollback_reference=_reference(payload.rollback_reference),
        model_change_control_reference=_reference(payload.model_change_control_reference),
        internal_audit_reference=_reference(payload.internal_audit_reference),
        change_ticket_reference=_reference(payload.change_ticket_reference),
        policy_hash="0" * 64,
    )
    db.add(item); db.flush()
    item.policy_hash = _hash(_policy_payload(item))
    _audit(db, user, "CREATE_AI_PRODUCTION_WIDE_AUTHORIZATION", "ai_production_wide_authorization", item.id,
           {"assessment_id": str(assessment.id), "policy_hash": item.policy_hash, "expires_at": expires.isoformat()},
           "Sprint 11T Production-wide authorization review created; human review remains mandatory.")
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def record_approval(db: Session, user: User, item: AIProductionWideAuthorization,
                    role: str, action: str, evidence_reference: str | None, note: str) -> dict:
    if item.status != "pending_approvals":
        raise HTTPException(409, "Sprint 11T approval set is not open")
    if role not in APPROVAL_ROLES:
        raise HTTPException(422, "Unsupported Sprint 11T approval role")
    if user.id == item.requested_by_id:
        raise HTTPException(409, "Requester may not approve their own Sprint 11T authorization")
    if db.scalar(select(AIProductionWideApproval).where(
        AIProductionWideApproval.authorization_id == item.id,
        AIProductionWideApproval.approval_role == role,
    )) is not None:
        raise HTTPException(409, "This Sprint 11T review role is already recorded")
    if db.scalar(select(AIProductionWideApproval).where(
        AIProductionWideApproval.authorization_id == item.id,
        AIProductionWideApproval.approver_id == user.id,
    )) is not None:
        raise HTTPException(409, "Each Sprint 11T approval requires a distinct human reviewer")
    row = AIProductionWideApproval(
        organization_id=user.organization_id, authorization_id=item.id, approver_id=user.id,
        approval_role=role, action=action,
        evidence_reference=_reference(evidence_reference) if evidence_reference else None,
        note=note.strip(), approved_at=datetime.now(UTC),
    )
    db.add(row); db.flush()
    current = _approvals(db, item.id)
    if action == "reject":
        item.status, item.outcome = "held", "approval_rejected"
    elif (len(current) == len(APPROVAL_ROLES) and {x.approval_role for x in current} == APPROVAL_ROLES
          and all(x.action == "approve" for x in current) and len({x.approver_id for x in current}) == len(APPROVAL_ROLES)):
        item.status = "decision_ready"
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def decide_authorization(db: Session, user: User, item: AIProductionWideAuthorization,
                         outcome: str, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit Admin Sprint 11T decision confirmation is required")
    if item.status != "decision_ready":
        raise HTTPException(409, "Fifteen independent approvals are required before Admin decision")
    approvals = _approvals(db, item.id); reviewer_ids = {x.approver_id for x in approvals}
    if (len(approvals) != 15 or {x.approval_role for x in approvals} != APPROVAL_ROLES
        or not all(x.action == "approve" for x in approvals) or len(reviewer_ids) != 15):
        raise HTTPException(409, "Independent Sprint 11T approval set is incomplete")
    if user.id == item.requested_by_id or user.id in reviewer_ids:
        raise HTTPException(409, "Final Admin must be distinct from requester and all fifteen reviewers")
    _anchor(db, item)
    snapshot = {
        "schema": "mcri-production-wide-authorization-v1",
        "authorization_id": str(item.id),
        "assessment_hash": item.bounded_full_outcome_assessment_hash,
        "assessment_decision_hash": item.bounded_full_outcome_decision_hash,
        "bounded_full_decision_hash": item.bounded_full_decision_hash,
        "bounded_full_completion_hash": item.bounded_full_completion_hash,
        "policy_hash": item.policy_hash,
        "bundle": {"model": item.model, "prompt": item.prompt_bundle_version, "schema": item.schema_bundle_version,
                   "max_input_chars": item.max_input_chars, "max_output_tokens": item.max_output_tokens},
        "approvals": [{"role": x.approval_role, "approver_id": str(x.approver_id)} for x in approvals],
        "outcome": outcome,
        "human_review_required": True,
        "restricted_documents_authorized": False,
        "new_document_classes_authorized": False,
        "autonomous_claim_decisions_authorized": False,
    }
    item.finalized_by_id = user.id; item.decision_note = note.strip(); item.decision_hash = _hash(snapshot); item.decided_at = datetime.now(UTC)
    if outcome == "authorize_production_wide_human_reviewed_ai":
        item.status, item.outcome = "authorized", outcome
    elif outcome == "hold_for_production_remediation":
        item.status, item.outcome = "held", outcome
    else:
        item.status, item.outcome = "rejected", "reject_production_wide_authorization"
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def _assert_runtime(db: Session, item: AIProductionWideAuthorization) -> None:
    if not _active(item):
        raise HTTPException(409, "Newest Sprint 11T control plane is inactive; fallback is prohibited")
    _anchor(db, item)
    settings = get_settings()
    if (settings.ai_model != item.model
        or settings.ai_prompt_bundle_version != item.prompt_bundle_version
        or settings.ai_schema_bundle_version != item.schema_bundle_version
        or settings.ai_max_output_tokens != item.max_output_tokens
        or settings.ai_max_input_chars != item.max_input_chars):
        raise HTTPException(409, "Configured AI bundle differs from the authorized Sprint 11T bundle; change review is required")
    incidents = _incidents(db, item.id)
    if any(x.status == "open" for x in incidents):
        raise HTTPException(409, "An open Sprint 11T incident blocks Production AI")
    if any(x.category in SAFETY_CATEGORIES for x in incidents):
        raise HTTPException(409, "Safety incident history invalidates this Sprint 11T attempt; a fresh authorization is required")
    monitors = _monitors(db, item.id)
    logs = _logs(db, item.id)
    if logs and item.decided_at and datetime.now(UTC) > _as_utc(item.decided_at) + timedelta(minutes=item.monitor_interval_minutes * 2):
        if not monitors or monitors[-1].status != "pass" or _as_utc(monitors[-1].monitored_at) < datetime.now(UTC) - timedelta(minutes=item.monitor_interval_minutes * 2):
            raise HTTPException(409, "A fresh passing Sprint 11T monitor is required")


def evaluate_document_eligibility(db: Session, *, item: AIProductionWideAuthorization, document: Document,
                                  expected_document_type: str, input_char_count: int) -> AIProductionEligibilityDecision:
    _assert_runtime(db, item)
    existing = db.scalar(select(AIProductionEligibilityDecision).where(
        AIProductionEligibilityDecision.authorization_id == item.id,
        AIProductionEligibilityDecision.document_id == document.id,
        AIProductionEligibilityDecision.policy_hash == item.policy_hash,
    ))
    if existing is not None:
        if not existing.eligible:
            raise HTTPException(409, "Document is ineligible under the current Sprint 11T Production Eligibility Policy")
        return existing
    confidentiality = document.confidentiality_level.value if hasattr(document.confidentiality_level, "value") else str(document.confidentiality_level)
    reasons: list[str] = []
    eligible = True
    if document.organization_id != item.organization_id:
        eligible = False; reasons.append("tenant_mismatch")
    if confidentiality not in {ConfidentialityLevel.INTERNAL.value, ConfidentialityLevel.CONFIDENTIAL.value}:
        eligible = False; reasons.append("confidentiality_not_allowed")
    if expected_document_type not in item.allowed_document_types or document.document_type != expected_document_type:
        eligible = False; reasons.append("document_type_not_allowed")
    if input_char_count > item.max_input_chars:
        eligible = False; reasons.append("input_limit_exceeded")
    if not reasons:
        reasons.append("policy_pass")
    snapshot = {
        "schema": "mcri-production-eligibility-decision-v1", "authorization_id": str(item.id),
        "authorization_hash": item.decision_hash, "policy_hash": item.policy_hash,
        "document_id": str(document.id), "claim_id": str(document.claim_id),
        "document_type": document.document_type, "confidentiality_level": confidentiality,
        "eligible": eligible, "reason_codes": reasons,
    }
    row = AIProductionEligibilityDecision(
        organization_id=item.organization_id, authorization_id=item.id, claim_id=document.claim_id,
        document_id=document.id, document_type=document.document_type, confidentiality_level=confidentiality,
        eligible=eligible, reason_codes=reasons, policy_hash=item.policy_hash,
        decision_hash=_hash(snapshot), evaluated_at=datetime.now(UTC),
    )
    db.add(row); db.flush(); db.commit(); db.refresh(row)
    if not eligible:
        raise HTTPException(409, f"Document is ineligible under Sprint 11T policy: {', '.join(reasons)}")
    return row


def require_production_wide_runtime_authorization(db: Session, *, organization_id: UUID, document: Document,
                                                  expected_document_type: str, input_char_count: int,
                                                  requested_by_id: UUID | None = None) -> tuple[AIProductionWideAuthorization, AIProductionEligibilityDecision]:
    item = latest_production_wide_attempt(db, organization_id)
    if item is None:
        raise HTTPException(409, "No Sprint 11T control plane exists")
    decision = evaluate_document_eligibility(
        db, item=item, document=document, expected_document_type=expected_document_type, input_char_count=input_char_count,
    )
    return item, decision


def reserve_run_if_production_wide(db: Session, *, user: User, document: Document, expected_document_type: str,
                                   input_char_count: int, processing_job_id: UUID) -> AIProductionDecisionLog | None:
    if get_settings().app_env.lower().strip() != "production":
        return None
    item = latest_production_wide_attempt(db, user.organization_id)
    if item is None:
        return None
    existing = db.scalar(select(AIProductionDecisionLog).where(AIProductionDecisionLog.processing_job_id == processing_job_id))
    if existing is not None:
        return existing
    item, eligibility = require_production_wide_runtime_authorization(
        db, organization_id=user.organization_id, document=document, expected_document_type=expected_document_type,
        input_char_count=input_char_count, requested_by_id=user.id,
    )
    now = datetime.now(UTC)
    run_key = f"pwdl-{processing_job_id}"
    run_snapshot = {
        "schema": "mcri-ai-decision-log-run-v1", "authorization_id": str(item.id),
        "authorization_hash": item.decision_hash, "eligibility_policy_hash": item.policy_hash,
        "eligibility_decision_hash": eligibility.decision_hash, "claim_id": str(document.claim_id),
        "document_id": str(document.id), "requested_by_id": str(user.id), "task_type": expected_document_type,
        "processing_job_id": str(processing_job_id), "queued_at": now.isoformat(),
    }
    row = AIProductionDecisionLog(
        organization_id=user.organization_id, authorization_id=item.id, eligibility_decision_id=eligibility.id,
        claim_id=document.claim_id, document_id=document.id, requested_by_id=user.id,
        run_key=run_key, processing_job_id=processing_job_id, task_type=expected_document_type,
        model=item.model, prompt_bundle_version=item.prompt_bundle_version, schema_bundle_version=item.schema_bundle_version,
        authorization_hash=item.decision_hash, eligibility_policy_hash=item.policy_hash,
        eligibility_decision_hash=eligibility.decision_hash, run_hash=_hash(run_snapshot), queued_at=now,
    )
    db.add(row); db.commit(); db.refresh(row)
    return row


def review_decision_log(db: Session, user: User, log: AIProductionDecisionLog, *, human_review_action: str,
                        output_candidate_count: int, human_edit_count: int, unsupported_output_count: int,
                        source_grounded_output_count: int, source_grounding_total_count: int, latency_ms: int,
                        observed_provider_cost_microusd: int, evidence_reference: str, note: str,
                        confirm_different_human_review: bool) -> dict:
    if not confirm_different_human_review:
        raise HTTPException(422, "Explicit different-human review confirmation is required")
    if log.status == "human_reviewed":
        raise HTTPException(409, "AI Decision Log entry is already human reviewed")
    if user.id == log.requested_by_id:
        raise HTTPException(409, "Requester may not review their own Production-wide AI run")
    item = get_authorization(db, user.organization_id, log.authorization_id)
    _assert_runtime(db, item)
    reviewed_at = datetime.now(UTC)
    snapshot = {
        "schema": "mcri-ai-decision-log-review-v1", "run_hash": log.run_hash,
        "reviewer_id": str(user.id), "human_review_action": human_review_action,
        "output_candidate_count": output_candidate_count, "human_edit_count": human_edit_count,
        "unsupported_output_count": unsupported_output_count,
        "source_grounded_output_count": source_grounded_output_count,
        "source_grounding_total_count": source_grounding_total_count,
        "latency_ms": latency_ms, "observed_provider_cost_microusd": observed_provider_cost_microusd,
        "evidence_reference": _reference(evidence_reference), "reviewed_at": reviewed_at.isoformat(),
    }
    log.reviewed_by_id=user.id; log.human_review_action=human_review_action; log.output_candidate_count=output_candidate_count
    log.human_edit_count=human_edit_count; log.unsupported_output_count=unsupported_output_count
    log.source_grounded_output_count=source_grounded_output_count; log.source_grounding_total_count=source_grounding_total_count
    log.latency_ms=latency_ms; log.observed_provider_cost_microusd=observed_provider_cost_microusd
    log.evidence_reference=snapshot["evidence_reference"]; log.note=note.strip(); log.review_hash=_hash(snapshot)
    log.reviewed_at=reviewed_at; log.status="human_reviewed"
    db.commit(); db.refresh(log)
    return _row_dict(log)


def _rate(n: int, d: int) -> int:
    return 0 if d <= 0 else round(n * 10000 / d)


def create_monitor(db: Session, user: User, item: AIProductionWideAuthorization, *, monitor_key: str,
                   note: str, confirm: bool) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit Sprint 11T monitor confirmation is required")
    logs = [x for x in _logs(db, item.id) if x.status == "human_reviewed"]
    rejected = sum(1 for x in logs if x.human_review_action == "reject")
    edited = sum(1 for x in logs if x.human_review_action == "edit")
    candidates = sum(x.output_candidate_count or 0 for x in logs)
    unsupported = sum(x.unsupported_output_count or 0 for x in logs)
    grounded = sum(x.source_grounded_output_count or 0 for x in logs)
    grounding_total = sum(x.source_grounding_total_count or 0 for x in logs)
    latency = sorted(x.latency_ms for x in logs if x.latency_ms is not None)
    p95 = latency[max(0, ceil(len(latency) * .95) - 1)] if latency else 0
    costs = [x.observed_provider_cost_microusd or 0 for x in logs]
    metrics = {
        "provider_run_count": len(logs), "human_review_rate_bps": 10000 if logs else 0,
        "different_human_review_rate_bps": _rate(sum(1 for x in logs if x.reviewed_by_id != x.requested_by_id), len(logs)),
        "reject_rate_bps": _rate(rejected, len(logs)), "edit_rate_bps": _rate(edited, len(logs)),
        "unsupported_output_rate_bps": _rate(unsupported, candidates),
        "source_grounding_validity_bps": _rate(grounded, grounding_total),
        "p95_latency_ms": p95, "mean_provider_cost_microusd": round(sum(costs) / len(costs)) if costs else 0,
    }
    failures=[]
    if logs:
        if metrics["different_human_review_rate_bps"] != 10000: failures.append("different_human_review_below_100_percent")
        if metrics["reject_rate_bps"] > 300: failures.append("reject_rate_above_3_percent")
        if metrics["edit_rate_bps"] > 1500: failures.append("edit_rate_above_15_percent")
        if metrics["unsupported_output_rate_bps"] > 10: failures.append("unsupported_output_above_0_10_percent")
        if grounding_total and metrics["source_grounding_validity_bps"] < 9990: failures.append("source_grounding_below_99_90_percent")
        if p95 > 12000: failures.append("p95_latency_above_12_seconds")
        if metrics["mean_provider_cost_microusd"] > 325000: failures.append("mean_cost_above_limit")
    if any(x.status == "open" and x.severity in BLOCKING_SEVERITIES for x in _incidents(db, item.id)):
        failures.append("open_high_or_critical_incident")
    if any(x.category in SAFETY_CATEGORIES for x in _incidents(db, item.id)):
        failures.append("safety_incident_history")
    status = "pass" if not failures else "fail"
    monitored_at=datetime.now(UTC)
    snapshot={"schema":"mcri-production-wide-monitor-v1","authorization_id":str(item.id),"metrics":metrics,"failure_reasons":failures,"monitored_at":monitored_at.isoformat()}
    row=AIProductionWideMonitor(organization_id=user.organization_id,authorization_id=item.id,initiated_by_id=user.id,
        monitor_key=monitor_key.strip(),metrics=metrics,failure_reasons=failures,status=status,monitor_hash=_hash(snapshot),note=note.strip(),monitored_at=monitored_at)
    db.add(row)
    if failures and item.status == "authorized": item.status="paused"
    db.commit(); db.refresh(item)
    return authorization_response(db,item)


def report_incident(db: Session, user: User, item: AIProductionWideAuthorization, *, severity: str, category: str,
                    evidence_reference: str, note: str, confirm_pause: bool) -> dict:
    if not confirm_pause:
        raise HTTPException(422, "Explicit incident pause confirmation is required")
    row=AIProductionWideIncident(organization_id=user.organization_id,authorization_id=item.id,reported_by_id=user.id,
        severity=severity,category=category,evidence_reference=_reference(evidence_reference),note=note.strip(),reported_at=datetime.now(UTC))
    db.add(row)
    if item.status == "authorized": item.status="paused"
    db.commit(); db.refresh(item)
    return authorization_response(db,item)


def resolve_incident(db: Session, user: User, item: AIProductionWideAuthorization, incident_id: UUID, *,
                     resolution_reference: str, resolution_note: str, confirm: bool) -> dict:
    if not confirm: raise HTTPException(422,"Explicit incident resolution confirmation is required")
    row=db.scalar(select(AIProductionWideIncident).where(AIProductionWideIncident.id==incident_id,
        AIProductionWideIncident.authorization_id==item.id,AIProductionWideIncident.organization_id==user.organization_id))
    if row is None: raise HTTPException(404,"Sprint 11T incident not found")
    if row.status != "open": raise HTTPException(409,"Incident is already resolved")
    row.status="resolved"; row.resolved_by_id=user.id; row.resolved_at=datetime.now(UTC)
    row.resolution_reference=_reference(resolution_reference); row.resolution_note=resolution_note.strip()
    db.commit(); db.refresh(item)
    return authorization_response(db,item)


def revoke_authorization(db: Session, user: User, item: AIProductionWideAuthorization, *, confirm: bool, note: str) -> dict:
    if not confirm: raise HTTPException(422,"Explicit Sprint 11T revocation confirmation is required")
    if item.status in {"revoked","rejected"}: raise HTTPException(409,"Authorization is already inactive")
    item.status="revoked"; item.revoked_by_id=user.id; item.revoked_at=datetime.now(UTC); item.revocation_note=note.strip()
    db.commit(); db.refresh(item)
    return authorization_response(db,item)
