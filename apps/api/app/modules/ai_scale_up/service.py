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
from app.modules.ai_limited_production.models import AILimitedProductionAuthorization
from app.modules.ai_limited_production_outcomes.models import AILimitedProductionOutcomeAssessment
from app.modules.ai_scale_up.models import (
    AIScaleUpApproval,
    AIScaleUpAuthorization,
    AIScaleUpDocumentEligibility,
    AIScaleUpIncident,
    AIScaleUpMonitor,
    AIScaleUpRun,
)
from app.modules.ai_scale_up.schemas import AIScaleUpCreate, AIScaleUpDocumentCreate
from app.modules.audit.service import write_audit_log
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.processing.models import DocumentProcessingJob, ProcessingJobStatus
from app.modules.users.models import User

REFERENCE = re.compile(r"^(artifact|runbook|ticket|monitor)://[A-Za-z0-9._:/-]{3,450}$")
APPROVAL_ROLES = {"security", "privacy", "product", "operations", "risk"}
ALLOWED_DOCUMENT_TYPES = {"chief_engineer_report", "engine_log"}
TERMINAL_STATUSES = {"held", "rejected", "revoked", "completed", "expired"}
SAFETY_CATEGORIES = {"privacy", "security", "cross_tenant"}


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _reference(value: str) -> str:
    reference = value.strip()
    if not REFERENCE.fullmatch(reference):
        raise HTTPException(422, "Scale-up evidence must use a bounded allowlisted reference")
    return reference


def _audit(db: Session, user: User, action: str, entity_type: str, entity_id: UUID,
           values: dict, details: str) -> None:
    write_audit_log(
        db, organization_id=user.organization_id, user_id=user.id, action=action,
        entity_type=entity_type, entity_id=entity_id, new_values=values, details=details,
    )


def _approvals(db: Session, authorization_id: UUID) -> list[AIScaleUpApproval]:
    return list(db.scalars(select(AIScaleUpApproval).where(
        AIScaleUpApproval.authorization_id == authorization_id,
    ).order_by(AIScaleUpApproval.approval_role.asc())))


def _documents(db: Session, authorization_id: UUID) -> list[AIScaleUpDocumentEligibility]:
    return list(db.scalars(select(AIScaleUpDocumentEligibility).where(
        AIScaleUpDocumentEligibility.authorization_id == authorization_id,
    ).order_by(AIScaleUpDocumentEligibility.created_at.asc())))


def _runs(db: Session, authorization_id: UUID) -> list[AIScaleUpRun]:
    return list(db.scalars(select(AIScaleUpRun).where(
        AIScaleUpRun.authorization_id == authorization_id,
    ).order_by(AIScaleUpRun.queued_at.asc())))


def _monitors(db: Session, authorization_id: UUID) -> list[AIScaleUpMonitor]:
    return list(db.scalars(select(AIScaleUpMonitor).where(
        AIScaleUpMonitor.authorization_id == authorization_id,
    ).order_by(AIScaleUpMonitor.monitored_at.asc())))


def _incidents(db: Session, authorization_id: UUID) -> list[AIScaleUpIncident]:
    return list(db.scalars(select(AIScaleUpIncident).where(
        AIScaleUpIncident.authorization_id == authorization_id,
    ).order_by(AIScaleUpIncident.reported_at.asc())))


def latest_scale_up_attempt(db: Session, organization_id: UUID) -> AIScaleUpAuthorization | None:
    return db.scalar(select(AIScaleUpAuthorization).where(
        AIScaleUpAuthorization.organization_id == organization_id,
    ).order_by(AIScaleUpAuthorization.created_at.desc()))


def _active(item: AIScaleUpAuthorization) -> bool:
    now = datetime.now(UTC)
    return item.status == "authorized" and _as_utc(item.starts_at) <= now < _as_utc(item.expires_at)


def _rollout_bucket(document_id: UUID) -> int:
    return int(sha256(str(document_id).encode()).hexdigest()[:8], 16) % 100


def _latest_monitor_pass(db: Session, item: AIScaleUpAuthorization, *, require_fresh: bool) -> bool:
    monitors = _monitors(db, item.id)
    if not monitors or monitors[-1].status != "pass":
        return False
    if not require_fresh:
        return True
    freshness = timedelta(minutes=item.monitor_interval_minutes * 2)
    return _as_utc(monitors[-1].monitored_at) >= datetime.now(UTC) - freshness


def _controls(item: AIScaleUpAuthorization) -> dict:
    return {
        "rollback_slo_minutes": item.rollback_slo_minutes,
        "monitor_interval_minutes": item.monitor_interval_minutes,
        "max_reject_rate_bps": item.max_reject_rate_bps,
        "max_edit_rate_bps": item.max_edit_rate_bps,
        "max_unsupported_output_rate_bps": item.max_unsupported_output_rate_bps,
        "min_source_grounding_validity_bps": item.min_source_grounding_validity_bps,
        "max_p95_latency_ms": item.max_p95_latency_ms,
        "max_mean_observed_provider_cost_microusd": item.max_mean_cost_microusd,
        "max_quality_regression_bps": item.max_quality_regression_bps,
        "max_latency_regression_bps": item.max_latency_regression_bps,
        "max_cost_regression_bps": item.max_cost_regression_bps,
        "required_human_review_rate_bps": 10000,
        "max_open_incident_count": 0,
        "max_safety_incident_count": 0,
    }


def authorization_response(db: Session, item: AIScaleUpAuthorization) -> dict:
    approvals = _approvals(db, item.id)
    documents = _documents(db, item.id)
    runs = _runs(db, item.id)
    monitors = _monitors(db, item.id)
    incidents = _incidents(db, item.id)
    active_documents = [entry for entry in documents if entry.status == "eligible"]
    reviewed_runs = [entry for entry in runs if entry.status == "human_reviewed"]
    open_incidents = [entry for entry in incidents if entry.status == "open"]
    approvals_complete = bool(
        {entry.approval_role for entry in approvals} == APPROVAL_ROLES
        and all(entry.action == "approve" for entry in approvals)
        and len({entry.approver_id for entry in approvals}) == len(APPROVAL_ROLES)
        and all(entry.approver_id != item.requested_by_id for entry in approvals)
    )
    return {
        "id": item.id, "outcome_assessment_id": item.outcome_assessment_id,
        "limited_production_authorization_id": item.limited_production_authorization_id,
        "requested_by_id": item.requested_by_id, "finalized_by_id": item.finalized_by_id,
        "revoked_by_id": item.revoked_by_id, "attempt_number": item.attempt_number,
        "authorization_key": item.authorization_key, "environment": item.environment,
        "authorization_mode": item.authorization_mode,
        "outcome_assessment_hash": item.outcome_assessment_hash,
        "outcome_decision_hash": item.outcome_decision_hash,
        "model": item.model, "prompt_bundle_version": item.prompt_bundle_version,
        "schema_bundle_version": item.schema_bundle_version,
        "max_input_chars": item.max_input_chars, "max_output_tokens": item.max_output_tokens,
        "allowed_document_types": item.allowed_document_types,
        "previous_rollout_percentage": item.previous_rollout_percentage,
        "rollout_percentage": item.rollout_percentage,
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
            "change_ticket": item.change_ticket_reference,
        },
        "status": item.status, "outcome": item.outcome,
        "decision_note": item.decision_note, "decision_hash": item.decision_hash,
        "decided_at": item.decided_at, "completed_at": item.completed_at,
        "completion_note": item.completion_note, "revoked_at": item.revoked_at,
        "revocation_note": item.revocation_note,
        "approvals": approvals, "document_eligibility": documents,
        "runs": runs, "monitors": monitors, "incidents": incidents,
        "summary": {
            "independent_approvals_complete": approvals_complete,
            "authorization_active": _active(item),
            "active_claim_count": len({entry.claim_id for entry in active_documents}),
            "active_document_count": len(active_documents),
            "participating_user_count": len({entry.requested_by_id for entry in runs if entry.requested_by_id is not None}),
            "provider_run_count": len(runs),
            "human_reviewed_run_count": len(reviewed_runs),
            "pending_human_review_count": len(runs) - len(reviewed_runs),
            "open_incident_count": len(open_incidents),
            "latest_monitor_status": monitors[-1].status if monitors else None,
            "monitor_fresh_and_passing": _latest_monitor_pass(db, item, require_fresh=True),
            "controlled_scale_up_authorized": _active(item),
            "rollout_percentage": item.rollout_percentage,
            "rollout_above_25_percent_authorized": False,
            "production_wide_authorized": False,
            "restricted_documents_authorized": False,
            "new_document_classes_authorized": False,
            "autonomous_claim_decisions_authorized": False,
            "authoritative_facts_auto_updated": False,
            "human_review_required": True,
            "previous_document_eligibility_carried_forward": False,
            "raw_content_stored_in_control_ledger": False,
        },
        "created_at": item.created_at,
    }


def list_authorizations(db: Session, organization_id: UUID) -> list[dict]:
    items = list(db.scalars(select(AIScaleUpAuthorization).where(
        AIScaleUpAuthorization.organization_id == organization_id,
    ).order_by(AIScaleUpAuthorization.created_at.desc()).limit(20)))
    return [authorization_response(db, item) for item in items]


def get_authorization(db: Session, organization_id: UUID, authorization_id: UUID) -> AIScaleUpAuthorization:
    item = db.scalar(select(AIScaleUpAuthorization).where(
        AIScaleUpAuthorization.id == authorization_id,
        AIScaleUpAuthorization.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Controlled scale-up authorization not found")
    return item


def create_authorization(db: Session, user: User, payload: AIScaleUpCreate) -> dict:
    if not payload.confirm_separate_controlled_scale_up:
        raise HTTPException(422, "Explicit separate controlled-scale-up confirmation is required")
    if any(value.tzinfo is None or value.utcoffset() is None for value in (payload.starts_at, payload.expires_at)):
        raise HTTPException(422, "Authorization timestamps must include a timezone")
    starts = payload.starts_at.astimezone(UTC); expires = payload.expires_at.astimezone(UTC)
    now = datetime.now(UTC)
    if starts < now - timedelta(minutes=5) or starts > now + timedelta(days=2):
        raise HTTPException(422, "Scale-up start must be current or within two days")
    if expires <= starts or expires - starts > timedelta(days=30):
        raise HTTPException(422, "Controlled scale-up must expire within 30 days")
    if payload.max_documents < payload.max_claims:
        raise HTTPException(422, "Document cap cannot be lower than the claim cap")
    allowed = list(dict.fromkeys(payload.allowed_document_types))
    if len(allowed) != len(payload.allowed_document_types) or not set(allowed) <= ALLOWED_DOCUMENT_TYPES:
        raise HTTPException(422, "Document allowlist is duplicated or unsupported")

    assessment = db.scalar(select(AILimitedProductionOutcomeAssessment).where(
        AILimitedProductionOutcomeAssessment.id == payload.outcome_assessment_id,
        AILimitedProductionOutcomeAssessment.organization_id == user.organization_id,
    ))
    if (assessment is None or assessment.status != "recommended"
            or assessment.outcome != "recommend_graduation_stage"
            or not (assessment.metrics or {}).get("overall_pass")
            or not assessment.assessment_hash or not assessment.decision_hash):
        raise HTTPException(409, "A passing, positively recommended Sprint 11F assessment is required")
    limited = db.scalar(select(AILimitedProductionAuthorization).where(
        AILimitedProductionAuthorization.id == assessment.authorization_id,
        AILimitedProductionAuthorization.organization_id == user.organization_id,
    ))
    if (limited is None or limited.status != "completed" or not limited.decision_hash
            or assessment.authorization_decision_hash != limited.decision_hash):
        raise HTTPException(409, "The completed Sprint 11E authorization anchor is invalid")
    if assessment.rollout_percentage != limited.rollout_percentage:
        raise HTTPException(409, "Sprint 11F rollout snapshot no longer matches its 11E anchor")
    if payload.rollout_percentage <= assessment.rollout_percentage:
        raise HTTPException(422, "Scale-up rollout must exceed the measured limited-production cohort")
    if sorted(allowed) != sorted(limited.allowed_document_types):
        raise HTTPException(422, "Sprint 11G cannot add or silently remove document classes")

    references = [payload.deployment_isolation_reference, payload.provider_project_reference,
                  payload.credential_control_reference, payload.privacy_legal_reference,
                  payload.monitoring_reference, payload.incident_response_reference,
                  payload.rollback_reference, payload.change_ticket_reference]
    bounded = [_reference(value) for value in references]
    attempts = list(db.scalars(select(AIScaleUpAuthorization).where(
        AIScaleUpAuthorization.outcome_assessment_id == assessment.id,
    ).order_by(AIScaleUpAuthorization.attempt_number.asc())))
    if attempts and attempts[-1].status not in TERMINAL_STATUSES:
        if not (attempts[-1].status == "authorized" and _as_utc(attempts[-1].expires_at) <= now):
            raise HTTPException(409, "A new scale-up attempt requires hold, revocation, completion or expiry")

    item = AIScaleUpAuthorization(
        organization_id=user.organization_id, outcome_assessment_id=assessment.id,
        limited_production_authorization_id=limited.id, requested_by_id=user.id,
        attempt_number=len(attempts) + 1, authorization_key=payload.authorization_key.strip(),
        environment="production", authorization_mode="controlled_scale_up",
        outcome_assessment_hash=assessment.assessment_hash,
        outcome_decision_hash=assessment.decision_hash,
        model=limited.model, prompt_bundle_version=limited.prompt_bundle_version,
        schema_bundle_version=limited.schema_bundle_version,
        max_input_chars=limited.max_input_chars, max_output_tokens=limited.max_output_tokens,
        allowed_document_types=allowed, previous_rollout_percentage=assessment.rollout_percentage,
        rollout_percentage=payload.rollout_percentage,
        max_claims=payload.max_claims, max_documents=payload.max_documents,
        max_users=payload.max_users, max_provider_runs=payload.max_provider_runs,
        starts_at=starts, expires_at=expires,
        deployment_isolation_reference=bounded[0], provider_project_reference=bounded[1],
        credential_control_reference=bounded[2], privacy_legal_reference=bounded[3],
        monitoring_reference=bounded[4], incident_response_reference=bounded[5],
        rollback_reference=bounded[6], change_ticket_reference=bounded[7],
        status="pending_approvals",
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(409, "This scale-up key or attempt already exists") from exc
    _audit(db, user, "CREATE_AI_SCALE_UP_AUTHORIZATION", "ai_scale_up_authorization", item.id,
           {"outcome_assessment_id": str(assessment.id), "assessment_hash": assessment.assessment_hash,
            "decision_hash": assessment.decision_hash, "previous_rollout_percentage": assessment.rollout_percentage,
            "rollout_percentage": item.rollout_percentage, "production_wide_authorized": False,
            "restricted_documents_authorized": False, "new_document_classes_authorized": False},
           "Separate Sprint 11G attempt only; Sprint 11F recommendation granted no scale-up authorization.")
    db.commit(); db.refresh(item); return authorization_response(db, item)


def record_approval(db: Session, user: User, item: AIScaleUpAuthorization, role: str,
                    action: str, evidence_reference: str | None, note: str) -> dict:
    if item.status not in {"pending_approvals", "decision_ready"}:
        raise HTTPException(409, "This scale-up authorization attempt is immutable")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The requester cannot approve the scale-up attempt")
    approvals = _approvals(db, item.id)
    if role not in APPROVAL_ROLES:
        raise HTTPException(422, "Unsupported approval role")
    if any(entry.approval_role == role for entry in approvals):
        raise HTTPException(409, "This approval role already has a decision")
    if any(entry.approver_id == user.id for entry in approvals):
        raise HTTPException(409, "Security, Privacy, Product, Operations and Risk require five different people")
    reference = _reference(evidence_reference) if evidence_reference else None
    if action == "approve" and not reference:
        raise HTTPException(422, "Approval requires bounded evidence")
    approval = AIScaleUpApproval(
        organization_id=user.organization_id, authorization_id=item.id, approver_id=user.id,
        approval_role=role, action=action, evidence_reference=reference,
        note=note.strip(), approved_at=datetime.now(UTC),
    )
    db.add(approval); db.flush()
    if action == "reject":
        item.status = "rejected"; item.outcome = "rejected"; item.finalized_by_id = user.id
        item.decision_note = note.strip(); item.decided_at = datetime.now(UTC)
    else:
        current = _approvals(db, item.id)
        item.status = "decision_ready" if (
            {entry.approval_role for entry in current} == APPROVAL_ROLES
            and all(entry.action == "approve" for entry in current)
            and len({entry.approver_id for entry in current}) == len(APPROVAL_ROLES)
        ) else "pending_approvals"
    _audit(db, user, f"{action.upper()}_AI_SCALE_UP_APPROVAL", "ai_scale_up_authorization", item.id,
           {"approval_role": role, "action": action, "status": item.status, "evidence_reference": reference},
           "Independent Sprint 11G authorization review. " + note.strip())
    db.commit(); db.refresh(item); return authorization_response(db, item)


def _anchor_still_valid(db: Session, item: AIScaleUpAuthorization) -> None:
    assessment = db.scalar(select(AILimitedProductionOutcomeAssessment).where(
        AILimitedProductionOutcomeAssessment.id == item.outcome_assessment_id,
        AILimitedProductionOutcomeAssessment.organization_id == item.organization_id,
    ))
    if (assessment is None or assessment.status != "recommended"
            or assessment.outcome != "recommend_graduation_stage"
            or assessment.assessment_hash != item.outcome_assessment_hash
            or assessment.decision_hash != item.outcome_decision_hash
            or not (assessment.metrics or {}).get("overall_pass")):
        raise HTTPException(409, "Sprint 11F recommendation anchor no longer matches the frozen scale-up request")
    limited = db.scalar(select(AILimitedProductionAuthorization).where(
        AILimitedProductionAuthorization.id == item.limited_production_authorization_id,
        AILimitedProductionAuthorization.organization_id == item.organization_id,
    ))
    if limited is None or limited.status != "completed" or limited.id != assessment.authorization_id:
        raise HTTPException(409, "Completed Sprint 11E anchor is unavailable")
    if (limited.model != item.model or limited.prompt_bundle_version != item.prompt_bundle_version
            or limited.schema_bundle_version != item.schema_bundle_version
            or limited.max_input_chars != item.max_input_chars
            or limited.max_output_tokens != item.max_output_tokens):
        raise HTTPException(409, "Pinned AI bundle differs from the measured Sprint 11E cohort")


def decide_authorization(db: Session, user: User, item: AIScaleUpAuthorization,
                         outcome: str, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit controlled-scale-up decision confirmation is required")
    if item.status != "decision_ready":
        raise HTTPException(409, "Five independent approvals are required")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The requester cannot issue final authorization")
    approvals = _approvals(db, item.id)
    if (len(approvals) != len(APPROVAL_ROLES) or {entry.approval_role for entry in approvals} != APPROVAL_ROLES
            or len({entry.approver_id for entry in approvals}) != len(APPROVAL_ROLES)
            or any(entry.action != "approve" for entry in approvals)):
        raise HTTPException(409, "Five approval roles must remain independent")
    _anchor_still_valid(db, item)
    if outcome == "authorize_scale_up" and _as_utc(item.expires_at) <= datetime.now(UTC):
        raise HTTPException(409, "The scale-up window has expired")
    snapshot = {
        "schema": "mcri-ai-controlled-scale-up-authorization-v1", "authorization_id": str(item.id),
        "outcome_assessment_id": str(item.outcome_assessment_id),
        "outcome_assessment_hash": item.outcome_assessment_hash,
        "outcome_decision_hash": item.outcome_decision_hash,
        "limited_production_authorization_id": str(item.limited_production_authorization_id),
        "bundle": {"model": item.model, "prompt": item.prompt_bundle_version,
                   "schema": item.schema_bundle_version, "max_input_chars": item.max_input_chars,
                   "max_output_tokens": item.max_output_tokens},
        "allowed_document_types": sorted(item.allowed_document_types),
        "previous_rollout_percentage": item.previous_rollout_percentage,
        "rollout_percentage": item.rollout_percentage,
        "limits": {"claims": item.max_claims, "documents": item.max_documents,
                   "users": item.max_users, "provider_runs": item.max_provider_runs},
        "starts_at": _as_utc(item.starts_at).isoformat(), "expires_at": _as_utc(item.expires_at).isoformat(),
        "controls": _controls(item),
        "approvals": [{"role": entry.approval_role, "approver_id": str(entry.approver_id),
                       "evidence_reference": entry.evidence_reference} for entry in approvals],
        "outcome": outcome, "decision_note": note.strip(),
        "controlled_scale_up_only": True, "production_wide_authorized": False,
        "restricted_documents_authorized": False, "new_document_classes_authorized": False,
        "rollout_above_25_percent_authorized": False, "autonomous_claim_decisions_authorized": False,
        "authoritative_facts_auto_updated": False, "human_review_required": True,
        "previous_document_eligibility_carried_forward": False, "raw_content_stored": False,
    }
    item.status = "authorized" if outcome == "authorize_scale_up" else "held"
    item.outcome = outcome; item.finalized_by_id = user.id; item.decision_note = note.strip()
    item.decided_at = datetime.now(UTC)
    item.decision_hash = sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    _audit(db, user, f"{outcome.upper()}_AI_SCALE_UP", "ai_scale_up_authorization", item.id,
           {"status": item.status, "decision_hash": item.decision_hash,
            "rollout_percentage": item.rollout_percentage, "production_wide_authorized": False,
            "restricted_documents_authorized": False},
           "Expiring controlled scale-up decision. " + note.strip())
    db.commit(); db.refresh(item); return authorization_response(db, item)


def attest_document(db: Session, user: User, item: AIScaleUpAuthorization,
                    payload: AIScaleUpDocumentCreate) -> dict:
    if not payload.confirm_new_scale_up_eligibility:
        raise HTTPException(422, "Explicit fresh Sprint 11G document eligibility is required")
    if not _active(item):
        raise HTTPException(409, "An active controlled scale-up authorization is required")
    _anchor_still_valid(db, item)
    document = db.scalar(select(Document).where(
        Document.id == payload.document_id, Document.claim_id == payload.claim_id,
        Document.organization_id == user.organization_id, Document.deleted_at.is_(None),
        Document.is_current.is_(True),
    ))
    if document is None:
        raise HTTPException(404, "Document not found")
    confidentiality = document.confidentiality_level.value if hasattr(document.confidentiality_level, "value") else str(document.confidentiality_level)
    if confidentiality == ConfidentialityLevel.RESTRICTED.value:
        raise HTTPException(409, "Restricted documents are prohibited in Sprint 11G")
    if not document.document_type or document.document_type not in item.allowed_document_types:
        raise HTTPException(409, "Document type is outside the controlled scale-up allowlist")
    bucket = _rollout_bucket(document.id)
    if bucket >= item.rollout_percentage:
        raise HTTPException(409, "Document is outside the deterministic controlled rollout")
    attempts = list(db.scalars(select(AIScaleUpDocumentEligibility).where(
        AIScaleUpDocumentEligibility.authorization_id == item.id,
        AIScaleUpDocumentEligibility.document_id == document.id,
    ).order_by(AIScaleUpDocumentEligibility.attestation_number.asc())))
    if attempts and attempts[-1].status == "eligible":
        raise HTTPException(409, "This document already has active Sprint 11G eligibility")
    active = [entry for entry in _documents(db, item.id) if entry.status == "eligible"]
    if len(active) >= item.max_documents:
        raise HTTPException(409, "Scale-up document cap reached")
    active_claims = {entry.claim_id for entry in active}
    if document.claim_id not in active_claims and len(active_claims) >= item.max_claims:
        raise HTTPException(409, "Scale-up claim cap reached")
    legal = _reference(payload.legal_basis_reference); minimization = _reference(payload.data_minimization_reference)
    change = _reference(payload.change_ticket_reference)
    snapshot = {
        "schema": "mcri-ai-scale-up-document-v1", "authorization_id": str(item.id),
        "claim_id": str(document.claim_id), "document_id": str(document.id), "file_hash": document.file_hash,
        "document_type": document.document_type, "confidentiality_level": confidentiality,
        "rollout_bucket": bucket, "rollout_percentage": item.rollout_percentage,
        "fresh_scale_up_eligibility": True, "previous_eligibility_carried_forward": False,
        "legal_basis_reference": legal, "data_minimization_reference": minimization,
        "change_ticket_reference": change, "restricted_document": False,
    }
    eligibility = AIScaleUpDocumentEligibility(
        organization_id=user.organization_id, authorization_id=item.id, claim_id=document.claim_id,
        document_id=document.id, attested_by_id=user.id, attestation_number=len(attempts) + 1,
        rollout_bucket=bucket, document_type=document.document_type,
        confidentiality_level=confidentiality, legal_basis_reference=legal,
        data_minimization_reference=minimization, change_ticket_reference=change,
        note=payload.note.strip(), snapshot_hash=sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        status="eligible", attested_at=datetime.now(UTC),
    )
    db.add(eligibility); db.flush()
    _audit(db, user, "ATTEST_AI_SCALE_UP_DOCUMENT", "ai_scale_up_document", eligibility.id,
           {"authorization_id": str(item.id), "document_id": str(document.id),
            "rollout_bucket": bucket, "snapshot_hash": eligibility.snapshot_hash,
            "previous_eligibility_carried_forward": False},
           "Fresh document-level Sprint 11G eligibility; no document content copied.")
    db.commit(); db.refresh(item); return authorization_response(db, item)


def revoke_document(db: Session, user: User, item: AIScaleUpAuthorization,
                    eligibility_id: UUID, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit document revocation is required")
    eligibility = db.scalar(select(AIScaleUpDocumentEligibility).where(
        AIScaleUpDocumentEligibility.id == eligibility_id,
        AIScaleUpDocumentEligibility.authorization_id == item.id,
        AIScaleUpDocumentEligibility.organization_id == user.organization_id,
    ))
    if eligibility is None:
        raise HTTPException(404, "Scale-up document eligibility not found")
    if eligibility.status != "eligible":
        raise HTTPException(409, "Document eligibility is already inactive")
    eligibility.status = "revoked"; eligibility.revoked_by_id = user.id
    eligibility.revoked_at = datetime.now(UTC); eligibility.revocation_note = note.strip()
    _audit(db, user, "REVOKE_AI_SCALE_UP_DOCUMENT", "ai_scale_up_document", eligibility.id,
           {"authorization_id": str(item.id), "document_id": str(eligibility.document_id), "status": "revoked"},
           "Document removed from controlled scale-up immediately. " + note.strip())
    db.commit(); db.refresh(item); return authorization_response(db, item)


def require_scale_up_runtime_authorization(
    db: Session, *, organization_id: UUID, document: Document, expected_document_type: str,
    input_char_count: int, requested_by_id: UUID | None = None,
) -> tuple[AIScaleUpAuthorization, AIScaleUpDocumentEligibility]:
    settings = get_settings()
    if settings.app_env.lower().strip() != "production":
        raise HTTPException(409, "Controlled scale-up AI requires the production environment")
    item = latest_scale_up_attempt(db, organization_id)
    if item is None:
        raise HTTPException(409, "No Sprint 11G control plane exists")
    if not _active(item):
        raise HTTPException(409, "No active controlled scale-up authorization exists")
    _anchor_still_valid(db, item)
    if (settings.ai_model != item.model or settings.ai_prompt_bundle_version != item.prompt_bundle_version
            or settings.ai_schema_bundle_version != item.schema_bundle_version
            or settings.ai_max_output_tokens != item.max_output_tokens):
        raise HTTPException(409, "Configured AI bundle differs from the authorized controlled scale-up")
    confidentiality = document.confidentiality_level.value if hasattr(document.confidentiality_level, "value") else str(document.confidentiality_level)
    if confidentiality == ConfidentialityLevel.RESTRICTED.value:
        raise HTTPException(409, "Restricted documents are prohibited")
    if expected_document_type not in item.allowed_document_types or document.document_type != expected_document_type:
        raise HTTPException(409, "Document type is outside the controlled scale-up allowlist")
    if input_char_count > item.max_input_chars:
        raise HTTPException(409, "Document exceeds the authorized input limit")
    if _rollout_bucket(document.id) >= item.rollout_percentage:
        raise HTTPException(409, "Document is outside the deterministic controlled rollout")
    eligibility = db.scalar(select(AIScaleUpDocumentEligibility).where(
        AIScaleUpDocumentEligibility.organization_id == organization_id,
        AIScaleUpDocumentEligibility.authorization_id == item.id,
        AIScaleUpDocumentEligibility.document_id == document.id,
        AIScaleUpDocumentEligibility.status == "eligible",
    ).order_by(AIScaleUpDocumentEligibility.attestation_number.desc()))
    if eligibility is None:
        raise HTTPException(409, "Document requires fresh Sprint 11G eligibility")
    incidents = _incidents(db, item.id)
    if any(entry.status == "open" for entry in incidents):
        raise HTTPException(409, "An open incident blocks controlled scale-up AI")
    if any(entry.category in SAFETY_CATEGORIES for entry in incidents):
        raise HTTPException(409, "Privacy, Security or Cross-tenant incident history blocks further Sprint 11G execution")
    runs = _runs(db, item.id)
    if len(runs) >= item.max_provider_runs:
        raise HTTPException(409, "Controlled scale-up provider-run cap reached")
    participating = {entry.requested_by_id for entry in runs if entry.requested_by_id is not None}
    if requested_by_id is not None and requested_by_id not in participating and len(participating) >= item.max_users:
        raise HTTPException(409, "Controlled scale-up user cap reached")
    if (runs and item.decided_at is not None
            and datetime.now(UTC) > _as_utc(item.decided_at) + timedelta(minutes=item.monitor_interval_minutes * 2)
            and not _latest_monitor_pass(db, item, require_fresh=True)):
        raise HTTPException(409, "A fresh passing Sprint 11G monitor is required")
    return item, eligibility


def reserve_run_if_scale_up(
    db: Session, *, user: User, document: Document, expected_document_type: str,
    input_char_count: int, processing_job_id: UUID,
) -> AIScaleUpRun | None:
    if get_settings().app_env.lower().strip() != "production":
        return None
    latest = latest_scale_up_attempt(db, user.organization_id)
    if latest is None:
        return None
    existing = db.scalar(select(AIScaleUpRun).where(
        AIScaleUpRun.organization_id == user.organization_id,
        AIScaleUpRun.processing_job_id == processing_job_id,
    ))
    if existing is not None:
        return existing
    item, eligibility = require_scale_up_runtime_authorization(
        db, organization_id=user.organization_id, document=document,
        expected_document_type=expected_document_type, input_char_count=input_char_count,
        requested_by_id=user.id,
    )
    run = AIScaleUpRun(
        organization_id=user.organization_id, authorization_id=item.id, eligibility_id=eligibility.id,
        claim_id=document.claim_id, document_id=document.id, requested_by_id=user.id,
        run_key=f"processing-{processing_job_id}", processing_job_id=processing_job_id,
        task_type=expected_document_type, status="queued", queued_at=datetime.now(UTC),
    )
    db.add(run); db.flush()
    _audit(db, user, "RESERVE_AI_SCALE_UP_RUN", "ai_scale_up_run", run.id,
           {"authorization_id": str(item.id), "document_id": str(document.id),
            "processing_job_id": str(processing_job_id), "task_type": expected_document_type,
            "raw_content_stored": False, "human_review_required": True},
           "Content-free controlled-scale-up provider-run reservation.")
    return run


def get_run(db: Session, organization_id: UUID, run_id: UUID) -> AIScaleUpRun:
    run = db.scalar(select(AIScaleUpRun).where(AIScaleUpRun.id == run_id,
                                               AIScaleUpRun.organization_id == organization_id))
    if run is None:
        raise HTTPException(404, "Controlled scale-up run not found")
    return run


def record_run_outcome(db: Session, user: User, run: AIScaleUpRun, *, human_review_action: str,
                       output_candidate_count: int, human_edit_count: int,
                       unsupported_output_count: int, source_grounded_output_count: int,
                       source_grounding_total_count: int, latency_ms: int,
                       observed_provider_cost_microusd: int, evidence_reference: str,
                       note: str, confirm_human_review: bool) -> dict:
    if not confirm_human_review:
        raise HTTPException(422, "Explicit human-review confirmation is required")
    if run.status != "queued":
        raise HTTPException(409, "This run outcome is immutable")
    if run.requested_by_id == user.id:
        raise HTTPException(409, "A different human must review every scale-up AI output")
    job = db.scalar(select(DocumentProcessingJob).where(
        DocumentProcessingJob.id == run.processing_job_id,
        DocumentProcessingJob.organization_id == user.organization_id,
    ))
    if job is None or job.status != ProcessingJobStatus.COMPLETED:
        raise HTTPException(409, "Provider processing must complete before human review")
    if human_edit_count > output_candidate_count or unsupported_output_count > output_candidate_count:
        raise HTTPException(422, "Review counters cannot exceed output candidates")
    if source_grounded_output_count > source_grounding_total_count:
        raise HTTPException(422, "Grounded source count cannot exceed checked source count")
    reference = _reference(evidence_reference)
    snapshot = {
        "schema": "mcri-ai-scale-up-run-outcome-v1", "run_id": str(run.id),
        "authorization_id": str(run.authorization_id), "processing_job_id": str(run.processing_job_id),
        "task_type": run.task_type, "human_review_action": human_review_action,
        "output_candidate_count": output_candidate_count, "human_edit_count": human_edit_count,
        "unsupported_output_count": unsupported_output_count,
        "source_grounded_output_count": source_grounded_output_count,
        "source_grounding_total_count": source_grounding_total_count,
        "latency_ms": latency_ms, "observed_provider_cost_microusd": observed_provider_cost_microusd,
        "evidence_reference": reference, "human_review_completed": True,
        "authoritative_facts_auto_updated": False, "raw_content_stored": False,
    }
    run.reviewed_by_id = user.id; run.status = "human_reviewed"; run.human_review_action = human_review_action
    run.output_candidate_count = output_candidate_count; run.human_edit_count = human_edit_count
    run.unsupported_output_count = unsupported_output_count
    run.source_grounded_output_count = source_grounded_output_count
    run.source_grounding_total_count = source_grounding_total_count
    run.latency_ms = latency_ms; run.observed_provider_cost_microusd = observed_provider_cost_microusd
    run.evidence_reference = reference; run.note = note.strip(); run.reviewed_at = datetime.now(UTC)
    run.outcome_hash = sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    _audit(db, user, "REVIEW_AI_SCALE_UP_RUN", "ai_scale_up_run", run.id,
           {"authorization_id": str(run.authorization_id), "human_review_action": human_review_action,
            "outcome_hash": run.outcome_hash, "authoritative_facts_auto_updated": False},
           "Mandatory different-human Sprint 11G review. " + note.strip())
    db.commit(); item = get_authorization(db, user.organization_id, run.authorization_id)
    return authorization_response(db, item)


def _rate_bps(numerator: int, denominator: int) -> int | None:
    return numerator * 10000 // denominator if denominator else None


def _mean(values: list[int]) -> int | None:
    return (sum(values) + len(values) - 1) // len(values) if values else None


def _regression_bps(first: int | None, second: int | None, *, higher_is_worse: bool = True) -> int | None:
    if first is None or second is None:
        return None
    if higher_is_worse:
        if first == 0: return 0 if second == 0 else 10000
        return max(0, (second - first) * 10000 // first)
    if first == 0: return 0
    return max(0, (first - second) * 10000 // first)


def record_monitor(db: Session, user: User, item: AIScaleUpAuthorization,
                   monitor_key: str, note: str, confirm: bool) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit live monitor confirmation is required")
    if item.status not in {"authorized", "paused"}:
        raise HTTPException(409, "Only an authorized or paused scale-up can be monitored")
    runs = _runs(db, item.id); incidents = _incidents(db, item.id)
    reviewed = [run for run in runs if run.status == "human_reviewed"]
    approved = sum(run.human_review_action == "approve" for run in reviewed)
    edited = sum(run.human_review_action == "edit" for run in reviewed)
    rejected = sum(run.human_review_action == "reject" for run in reviewed)
    actions = approved + edited + rejected
    candidates = sum(run.output_candidate_count or 0 for run in reviewed)
    unsupported = sum(run.unsupported_output_count or 0 for run in reviewed)
    grounded = sum(run.source_grounded_output_count or 0 for run in reviewed)
    grounding_total = sum(run.source_grounding_total_count or 0 for run in reviewed)
    latencies = sorted(run.latency_ms for run in reviewed if run.latency_ms is not None)
    costs = [run.observed_provider_cost_microusd for run in reviewed if run.observed_provider_cost_microusd is not None]
    p95 = latencies[max(ceil(0.95 * len(latencies)) - 1, 0)] if latencies else None
    mean_cost = _mean(costs)
    review_rate = _rate_bps(len(reviewed), len(runs)); reject_rate = _rate_bps(rejected, actions)
    edit_rate = _rate_bps(edited, actions); unsupported_rate = _rate_bps(unsupported, candidates)
    grounding_rate = _rate_bps(grounded, grounding_total)
    open_incidents = sum(entry.status == "open" for entry in incidents)
    safety_incidents = sum(entry.category in SAFETY_CATEGORIES for entry in incidents)

    half = len(reviewed) // 2
    first = reviewed[:half]; second = reviewed[half:] if half else []
    def quality_rate(rows: list[AIScaleUpRun]) -> int | None:
        total = sum(row.source_grounding_total_count or 0 for row in rows)
        good = sum(row.source_grounded_output_count or 0 for row in rows)
        return _rate_bps(good, total)
    first_quality = quality_rate(first); second_quality = quality_rate(second)
    first_latency = _mean([row.latency_ms for row in first if row.latency_ms is not None])
    second_latency = _mean([row.latency_ms for row in second if row.latency_ms is not None])
    first_cost = _mean([row.observed_provider_cost_microusd for row in first if row.observed_provider_cost_microusd is not None])
    second_cost = _mean([row.observed_provider_cost_microusd for row in second if row.observed_provider_cost_microusd is not None])
    quality_regression = (max(0, first_quality - second_quality)
                          if first_quality is not None and second_quality is not None else None)
    latency_regression = _regression_bps(first_latency, second_latency)
    cost_regression = _regression_bps(first_cost, second_cost)

    failures: list[str] = []
    if not runs: failures.append("minimum_observed_run_count")
    if review_rate != 10000: failures.append("human_review_coverage")
    if reject_rate is None or reject_rate > item.max_reject_rate_bps: failures.append("human_reject_rate")
    if edit_rate is None or edit_rate > item.max_edit_rate_bps: failures.append("human_edit_rate")
    if unsupported_rate is None or unsupported_rate > item.max_unsupported_output_rate_bps: failures.append("unsupported_output_rate")
    if grounding_rate is None or grounding_rate < item.min_source_grounding_validity_bps: failures.append("source_grounding_validity")
    if p95 is None or p95 > item.max_p95_latency_ms: failures.append("p95_latency")
    if mean_cost is None or mean_cost > item.max_mean_cost_microusd: failures.append("mean_observed_provider_cost")
    if open_incidents: failures.append("open_incident")
    if safety_incidents: failures.append("privacy_security_or_cross_tenant_incident")
    if len(reviewed) >= 4:
        if quality_regression is not None and quality_regression > item.max_quality_regression_bps: failures.append("quality_regression")
        if latency_regression is not None and latency_regression > item.max_latency_regression_bps: failures.append("latency_regression")
        if cost_regression is not None and cost_regression > item.max_cost_regression_bps: failures.append("cost_regression")
    failures = sorted(set(failures))
    metrics = {
        "overall_pass": not failures, "provider_run_count": len(runs),
        "human_reviewed_run_count": len(reviewed), "human_review_rate_bps": review_rate,
        "human_approve_count": approved, "human_edit_count": edited, "human_reject_count": rejected,
        "human_edit_rate_bps": edit_rate, "human_reject_rate_bps": reject_rate,
        "unsupported_output_rate_bps": unsupported_rate, "source_grounding_validity_bps": grounding_rate,
        "p95_latency_ms": p95, "mean_observed_provider_cost_microusd": mean_cost,
        "total_observed_provider_cost_microusd": sum(costs), "open_incident_count": open_incidents,
        "safety_incident_count": safety_incidents, "rollout_percentage": item.rollout_percentage,
        "trend": {"first_half_grounding_bps": first_quality, "second_half_grounding_bps": second_quality,
                  "quality_regression_bps": quality_regression, "first_half_mean_latency_ms": first_latency,
                  "second_half_mean_latency_ms": second_latency, "latency_regression_bps": latency_regression,
                  "first_half_mean_cost_microusd": first_cost, "second_half_mean_cost_microusd": second_cost,
                  "cost_regression_bps": cost_regression},
        "raw_content_stored": False, "production_wide_authorized": False,
        "restricted_documents_authorized": False, "new_document_classes_authorized": False,
    }
    monitored_at = datetime.now(UTC)
    snapshot = {
        "schema": "mcri-ai-scale-up-monitor-v1", "authorization_id": str(item.id),
        "monitor_key": monitor_key.strip(), "metrics": metrics, "failure_reasons": failures,
        "run_outcome_hashes": [run.outcome_hash for run in runs],
        "incident_states": [{"id": str(entry.id), "severity": entry.severity,
                             "category": entry.category, "status": entry.status} for entry in incidents],
        "monitored_at": monitored_at.isoformat(), "note": note.strip(),
    }
    monitor = AIScaleUpMonitor(
        organization_id=user.organization_id, authorization_id=item.id, initiated_by_id=user.id,
        monitor_key=monitor_key.strip(), metrics=metrics, failure_reasons=failures,
        status="pass" if not failures else "rollback_required",
        monitor_hash=sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        note=note.strip(), monitored_at=monitored_at,
    )
    db.add(monitor)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(409, "This monitor key already exists") from exc
    if failures:
        item.status = "paused"; item.outcome = "monitor_rollback_required"
    _audit(db, user, "RECORD_AI_SCALE_UP_MONITOR", "ai_scale_up_monitor", monitor.id,
           {"authorization_id": str(item.id), "status": monitor.status,
            "monitor_hash": monitor.monitor_hash, "failure_reasons": failures},
           "Content-free Sprint 11G monitor; failure pauses execution and requires rollback. " + note.strip())
    db.commit(); db.refresh(item); return authorization_response(db, item)


def report_incident(db: Session, user: User, item: AIScaleUpAuthorization, *, severity: str,
                    category: str, evidence_reference: str, note: str, confirm: bool) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit pause-and-rollback confirmation is required")
    if item.status != "authorized":
        raise HTTPException(409, "Only an active scale-up authorization can be paused")
    incident = AIScaleUpIncident(
        organization_id=user.organization_id, authorization_id=item.id, reported_by_id=user.id,
        severity=severity, category=category, evidence_reference=_reference(evidence_reference),
        note=note.strip(), status="open", reported_at=datetime.now(UTC),
    )
    db.add(incident); db.flush(); item.status = "paused"; item.outcome = "incident_rollback"
    _audit(db, user, "PAUSE_AI_SCALE_UP_INCIDENT", "ai_scale_up_authorization", item.id,
           {"incident_id": str(incident.id), "severity": severity, "category": category,
            "status": "paused", "rollback_slo_minutes": item.rollback_slo_minutes},
           "Immediate Sprint 11G pause and rollback trigger. " + note.strip())
    db.commit(); db.refresh(item); return authorization_response(db, item)


def resolve_incident(db: Session, user: User, item: AIScaleUpAuthorization, incident_id: UUID,
                     *, resolution_reference: str, resolution_note: str, confirm: bool) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit incident resolution confirmation is required")
    incident = db.scalar(select(AIScaleUpIncident).where(
        AIScaleUpIncident.id == incident_id, AIScaleUpIncident.authorization_id == item.id,
        AIScaleUpIncident.organization_id == user.organization_id,
    ))
    if incident is None: raise HTTPException(404, "Scale-up incident not found")
    if incident.status != "open": raise HTTPException(409, "Incident is already resolved")
    incident.status = "resolved"; incident.resolved_by_id = user.id; incident.resolved_at = datetime.now(UTC)
    incident.resolution_reference = _reference(resolution_reference); incident.resolution_note = resolution_note.strip()
    _audit(db, user, "RESOLVE_AI_SCALE_UP_INCIDENT", "ai_scale_up_authorization", item.id,
           {"incident_id": str(incident.id), "status": item.status, "resumed": False},
           "Incident resolved; fresh passing monitor and explicit Admin resume remain required. " + resolution_note.strip())
    db.commit(); db.refresh(item); return authorization_response(db, item)


def resume_authorization(db: Session, user: User, item: AIScaleUpAuthorization,
                         confirm: bool, note: str) -> dict:
    if not confirm: raise HTTPException(422, "Explicit resume confirmation is required")
    if item.status != "paused": raise HTTPException(409, "Only a paused authorization can resume")
    incidents = _incidents(db, item.id)
    if any(entry.status == "open" for entry in incidents): raise HTTPException(409, "Open incidents block resume")
    if any(entry.category in SAFETY_CATEGORIES for entry in incidents):
        raise HTTPException(409, "Privacy, Security or Cross-tenant incidents require a new authorization attempt")
    if not _latest_monitor_pass(db, item, require_fresh=True):
        raise HTTPException(409, "A fresh passing monitor is required before resume")
    if _as_utc(item.expires_at) <= datetime.now(UTC): raise HTTPException(409, "Expired authorization cannot resume")
    _anchor_still_valid(db, item)
    item.status = "authorized"; item.outcome = "resumed_after_monitor"
    _audit(db, user, "RESUME_AI_SCALE_UP", "ai_scale_up_authorization", item.id,
           {"status": "authorized", "production_wide_authorized": False},
           "Admin resumed only the existing bounded Sprint 11G rollout. " + note.strip())
    db.commit(); db.refresh(item); return authorization_response(db, item)


def revoke_authorization(db: Session, user: User, item: AIScaleUpAuthorization,
                         confirm: bool, note: str) -> dict:
    if not confirm: raise HTTPException(422, "Explicit scale-up kill-switch confirmation is required")
    if item.status in {"revoked", "completed"}: raise HTTPException(409, "Authorization is already terminal")
    item.status = "revoked"; item.outcome = "revoked"; item.revoked_by_id = user.id
    item.revoked_at = datetime.now(UTC); item.revocation_note = note.strip()
    _audit(db, user, "REVOKE_AI_SCALE_UP", "ai_scale_up_authorization", item.id,
           {"status": "revoked", "production_wide_authorized": False},
           "Immediate Sprint 11G kill switch. " + note.strip())
    db.commit(); db.refresh(item); return authorization_response(db, item)


def complete_authorization(db: Session, user: User, item: AIScaleUpAuthorization,
                           confirm: bool, note: str) -> dict:
    if not confirm: raise HTTPException(422, "Explicit scale-up completion confirmation is required")
    if item.status != "authorized": raise HTTPException(409, "Only an active scale-up can complete")
    runs = _runs(db, item.id); incidents = _incidents(db, item.id)
    if not runs or any(run.status != "human_reviewed" for run in runs):
        raise HTTPException(409, "Every Sprint 11G provider run requires completed different-human review")
    if any(entry.status == "open" for entry in incidents): raise HTTPException(409, "Open incidents block completion")
    if any(entry.category in SAFETY_CATEGORIES for entry in incidents):
        raise HTTPException(409, "Privacy, Security or Cross-tenant incident history blocks successful completion")
    if not _latest_monitor_pass(db, item, require_fresh=True):
        raise HTTPException(409, "A fresh passing monitor is required before completion")
    item.status = "completed"; item.outcome = "completed"; item.completed_at = datetime.now(UTC)
    item.completion_note = note.strip()
    _audit(db, user, "COMPLETE_AI_SCALE_UP", "ai_scale_up_authorization", item.id,
           {"status": "completed", "provider_run_count": len(runs),
            "production_wide_authorized": False, "restricted_documents_authorized": False,
            "new_document_classes_authorized": False},
           "Completed bounded Sprint 11G cohort; no wider authorization created. " + note.strip())
    db.commit(); db.refresh(item); return authorization_response(db, item)
