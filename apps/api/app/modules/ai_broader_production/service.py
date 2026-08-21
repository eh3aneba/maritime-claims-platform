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
from app.modules.ai_broader_production.models import (
    AIBroaderProductionApproval,
    AIBroaderProductionAuthorization,
    AIBroaderProductionDocumentEligibility,
    AIBroaderProductionIncident,
    AIBroaderProductionMonitor,
    AIBroaderProductionRun,
)
from app.modules.ai_broader_production.schemas import AIBroaderProductionCreate, AIBroaderProductionDocumentCreate
from app.modules.ai_scale_up.models import AIScaleUpAuthorization
from app.modules.ai_scale_up_outcomes.models import AIScaleUpOutcomeAssessment
from app.modules.audit.service import write_audit_log
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.processing.models import DocumentProcessingJob, ProcessingJobStatus
from app.modules.users.models import User

REFERENCE = re.compile(r"^(artifact|runbook|ticket|monitor)://[A-Za-z0-9._:/-]{3,450}$")
APPROVAL_ROLES = {"security", "privacy", "product", "operations", "risk", "claims_governance"}
ALLOWED_DOCUMENT_TYPES = {"chief_engineer_report", "engine_log"}
SAFETY_CATEGORIES = {"privacy", "security", "cross_tenant"}
BLOCKING_SEVERITIES = {"high", "critical"}
TERMINAL_STATUSES = {"held", "rejected", "revoked", "completed", "expired"}


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _reference(value: str) -> str:
    reference = value.strip()
    if not REFERENCE.fullmatch(reference):
        raise HTTPException(422, "Broader-production evidence must use a bounded allowlisted reference")
    return reference


def _audit(db: Session, user: User, action: str, entity_type: str, entity_id: UUID,
           values: dict, details: str) -> None:
    write_audit_log(
        db, organization_id=user.organization_id, user_id=user.id, action=action,
        entity_type=entity_type, entity_id=entity_id, new_values=values, details=details,
    )


def _approvals(db: Session, authorization_id: UUID) -> list[AIBroaderProductionApproval]:
    return list(db.scalars(select(AIBroaderProductionApproval).where(
        AIBroaderProductionApproval.authorization_id == authorization_id,
    ).order_by(AIBroaderProductionApproval.approval_role.asc())))


def _documents(db: Session, authorization_id: UUID) -> list[AIBroaderProductionDocumentEligibility]:
    return list(db.scalars(select(AIBroaderProductionDocumentEligibility).where(
        AIBroaderProductionDocumentEligibility.authorization_id == authorization_id,
    ).order_by(AIBroaderProductionDocumentEligibility.created_at.asc())))


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


def latest_broader_production_attempt(db: Session, organization_id: UUID) -> AIBroaderProductionAuthorization | None:
    return db.scalar(select(AIBroaderProductionAuthorization).where(
        AIBroaderProductionAuthorization.organization_id == organization_id,
    ).order_by(AIBroaderProductionAuthorization.created_at.desc()))


def _active(item: AIBroaderProductionAuthorization) -> bool:
    now = datetime.now(UTC)
    return item.status == "authorized" and _as_utc(item.starts_at) <= now < _as_utc(item.expires_at)


def _rollout_bucket(document_id: UUID) -> int:
    return int(sha256(str(document_id).encode()).hexdigest()[:8], 16) % 100


def _controls(item: AIBroaderProductionAuthorization) -> dict:
    return {
        "rollback_slo_minutes": item.rollback_slo_minutes,
        "monitor_interval_minutes": item.monitor_interval_minutes,
        "required_human_review_rate_bps": 10000,
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


def _latest_monitor_pass(db: Session, item: AIBroaderProductionAuthorization, *, require_fresh: bool) -> bool:
    monitors = _monitors(db, item.id)
    if not monitors or monitors[-1].status != "pass":
        return False
    if not require_fresh:
        return True
    freshness = timedelta(minutes=item.monitor_interval_minutes * 2)
    return _as_utc(monitors[-1].monitored_at) >= datetime.now(UTC) - freshness


def authorization_response(db: Session, item: AIBroaderProductionAuthorization) -> dict:
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
    return {
        "id": item.id,
        "readiness_assessment_id": item.readiness_assessment_id,
        "scale_up_authorization_id": item.scale_up_authorization_id,
        "requested_by_id": item.requested_by_id,
        "finalized_by_id": item.finalized_by_id,
        "revoked_by_id": item.revoked_by_id,
        "attempt_number": item.attempt_number,
        "authorization_key": item.authorization_key,
        "environment": item.environment,
        "authorization_mode": item.authorization_mode,
        "readiness_assessment_hash": item.readiness_assessment_hash,
        "readiness_decision_hash": item.readiness_decision_hash,
        "scale_up_decision_hash": item.scale_up_decision_hash,
        "inherited_outcome_assessment_hash": item.inherited_outcome_assessment_hash,
        "inherited_outcome_decision_hash": item.inherited_outcome_decision_hash,
        "model": item.model,
        "prompt_bundle_version": item.prompt_bundle_version,
        "schema_bundle_version": item.schema_bundle_version,
        "max_input_chars": item.max_input_chars,
        "max_output_tokens": item.max_output_tokens,
        "allowed_document_types": item.allowed_document_types,
        "previous_rollout_percentage": item.previous_rollout_percentage,
        "rollout_percentage": item.rollout_percentage,
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
            "change_ticket": item.change_ticket_reference,
        },
        "status": item.status,
        "outcome": item.outcome,
        "decision_note": item.decision_note,
        "decision_hash": item.decision_hash,
        "decided_at": item.decided_at,
        "completed_at": item.completed_at,
        "completion_note": item.completion_note,
        "revoked_at": item.revoked_at,
        "revocation_note": item.revocation_note,
        "approvals": approvals,
        "document_eligibility": documents,
        "runs": runs,
        "monitors": monitors,
        "incidents": incidents,
        "summary": {
            "independent_approvals_complete": approvals_complete,
            "authorization_active": _active(item),
            "active_claim_count": len({entry.claim_id for entry in active_documents}),
            "active_document_count": len(active_documents),
            "participating_user_count": len({entry.requested_by_id for entry in runs if entry.requested_by_id is not None}),
            "provider_run_count": len(runs),
            "human_reviewed_run_count": len(reviewed_runs),
            "pending_human_review_count": len(runs) - len(reviewed_runs),
            "open_incident_count": sum(entry.status == "open" for entry in incidents),
            "latest_monitor_status": monitors[-1].status if monitors else None,
            "monitor_fresh_and_passing": _latest_monitor_pass(db, item, require_fresh=True),
            "broader_production_cohort_authorized": _active(item),
            "rollout_percentage": item.rollout_percentage,
            "rollout_above_50_percent_authorized": False,
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
    items = list(db.scalars(select(AIBroaderProductionAuthorization).where(
        AIBroaderProductionAuthorization.organization_id == organization_id,
    ).order_by(AIBroaderProductionAuthorization.created_at.desc()).limit(20)))
    return [authorization_response(db, item) for item in items]


def get_authorization(db: Session, organization_id: UUID, authorization_id: UUID) -> AIBroaderProductionAuthorization:
    item = db.scalar(select(AIBroaderProductionAuthorization).where(
        AIBroaderProductionAuthorization.id == authorization_id,
        AIBroaderProductionAuthorization.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Broader-production authorization not found")
    return item


def _readiness(db: Session, organization_id: UUID, assessment_id: UUID) -> AIScaleUpOutcomeAssessment:
    item = db.scalar(select(AIScaleUpOutcomeAssessment).where(
        AIScaleUpOutcomeAssessment.id == assessment_id,
        AIScaleUpOutcomeAssessment.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Sprint 11H readiness assessment not found")
    return item


def _scale_up(db: Session, organization_id: UUID, authorization_id: UUID) -> AIScaleUpAuthorization:
    item = db.scalar(select(AIScaleUpAuthorization).where(
        AIScaleUpAuthorization.id == authorization_id,
        AIScaleUpAuthorization.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(409, "The Sprint 11G anchor is missing")
    return item


def _anchor_still_valid(db: Session, item: AIBroaderProductionAuthorization) -> None:
    readiness = _readiness(db, item.organization_id, item.readiness_assessment_id)
    scale_up = _scale_up(db, item.organization_id, item.scale_up_authorization_id)
    if (
        readiness.status != "recommended"
        or readiness.outcome != "recommend_broader_production_stage"
        or not (readiness.metrics or {}).get("overall_pass")
        or readiness.assessment_hash != item.readiness_assessment_hash
        or readiness.decision_hash != item.readiness_decision_hash
        or readiness.scale_up_decision_hash != item.scale_up_decision_hash
        or readiness.outcome_assessment_hash != item.inherited_outcome_assessment_hash
        or readiness.outcome_decision_hash != item.inherited_outcome_decision_hash
        or scale_up.status != "completed"
        or scale_up.decision_hash != item.scale_up_decision_hash
        or scale_up.outcome_assessment_hash != item.inherited_outcome_assessment_hash
        or scale_up.outcome_decision_hash != item.inherited_outcome_decision_hash
        or scale_up.model != item.model
        or scale_up.prompt_bundle_version != item.prompt_bundle_version
        or scale_up.schema_bundle_version != item.schema_bundle_version
        or scale_up.rollout_percentage != item.previous_rollout_percentage
    ):
        raise HTTPException(409, "The persisted Sprint 11H/11G/11F evidence anchor no longer matches")


def create_authorization(db: Session, user: User, payload: AIBroaderProductionCreate) -> dict:
    if not payload.confirm_separate_broader_production:
        raise HTTPException(422, "Explicit separate broader-production confirmation is required")
    if any(value.tzinfo is None or value.utcoffset() is None for value in (payload.starts_at, payload.expires_at)):
        raise HTTPException(422, "Authorization timestamps must include a timezone")
    starts = payload.starts_at.astimezone(UTC)
    expires = payload.expires_at.astimezone(UTC)
    now = datetime.now(UTC)
    if starts < now - timedelta(minutes=5) or starts > now + timedelta(days=2):
        raise HTTPException(422, "Broader-production start must be current or within two days")
    if expires <= starts or expires - starts > timedelta(days=30):
        raise HTTPException(422, "Broader-production authorization must expire within 30 days")
    if payload.max_documents < payload.max_claims:
        raise HTTPException(422, "Document cap cannot be lower than the claim cap")
    allowed = list(dict.fromkeys(payload.allowed_document_types))
    if len(allowed) != len(payload.allowed_document_types) or not set(allowed) <= ALLOWED_DOCUMENT_TYPES:
        raise HTTPException(422, "Document allowlist is duplicated or unsupported")

    readiness = _readiness(db, user.organization_id, payload.readiness_assessment_id)
    if (
        readiness.status != "recommended"
        or readiness.outcome != "recommend_broader_production_stage"
        or not (readiness.metrics or {}).get("overall_pass")
        or not readiness.assessment_hash
        or not readiness.decision_hash
    ):
        raise HTTPException(409, "A passing, positively recommended Sprint 11H readiness assessment is required")
    scale_up = _scale_up(db, user.organization_id, readiness.scale_up_authorization_id)
    if (
        scale_up.status != "completed"
        or not scale_up.decision_hash
        or readiness.scale_up_decision_hash != scale_up.decision_hash
        or readiness.outcome_assessment_hash != scale_up.outcome_assessment_hash
        or readiness.outcome_decision_hash != scale_up.outcome_decision_hash
    ):
        raise HTTPException(409, "The completed Sprint 11G anchor is invalid")
    if not 11 <= scale_up.rollout_percentage <= 25:
        raise HTTPException(409, "Sprint 11I requires a completed 11–25 percent Sprint 11G anchor")
    if set(allowed) - set(scale_up.allowed_document_types):
        raise HTTPException(422, "Sprint 11I cannot introduce new document classes")

    attempts = list(db.scalars(select(AIBroaderProductionAuthorization).where(
        AIBroaderProductionAuthorization.readiness_assessment_id == readiness.id,
    ).order_by(AIBroaderProductionAuthorization.attempt_number.asc())))
    if attempts and attempts[-1].status not in TERMINAL_STATUSES:
        raise HTTPException(409, "The current broader-production authorization attempt is still active")

    refs = {
        "deployment_isolation_reference": _reference(payload.deployment_isolation_reference),
        "provider_project_reference": _reference(payload.provider_project_reference),
        "credential_control_reference": _reference(payload.credential_control_reference),
        "privacy_legal_reference": _reference(payload.privacy_legal_reference),
        "monitoring_reference": _reference(payload.monitoring_reference),
        "incident_response_reference": _reference(payload.incident_response_reference),
        "rollback_reference": _reference(payload.rollback_reference),
        "change_ticket_reference": _reference(payload.change_ticket_reference),
    }
    item = AIBroaderProductionAuthorization(
        organization_id=user.organization_id,
        readiness_assessment_id=readiness.id,
        scale_up_authorization_id=scale_up.id,
        requested_by_id=user.id,
        attempt_number=len(attempts) + 1,
        authorization_key=payload.authorization_key.strip(),
        readiness_assessment_hash=readiness.assessment_hash,
        readiness_decision_hash=readiness.decision_hash,
        scale_up_decision_hash=scale_up.decision_hash,
        inherited_outcome_assessment_hash=scale_up.outcome_assessment_hash,
        inherited_outcome_decision_hash=scale_up.outcome_decision_hash,
        model=scale_up.model,
        prompt_bundle_version=scale_up.prompt_bundle_version,
        schema_bundle_version=scale_up.schema_bundle_version,
        max_input_chars=scale_up.max_input_chars,
        max_output_tokens=scale_up.max_output_tokens,
        allowed_document_types=allowed,
        previous_rollout_percentage=scale_up.rollout_percentage,
        rollout_percentage=payload.rollout_percentage,
        max_claims=payload.max_claims,
        max_documents=payload.max_documents,
        max_users=payload.max_users,
        max_provider_runs=payload.max_provider_runs,
        starts_at=starts,
        expires_at=expires,
        status="pending_approvals",
        **refs,
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This broader-production authorization key or attempt already exists") from exc
    _audit(
        db, user, "CREATE_AI_BROADER_PRODUCTION_AUTHORIZATION", "ai_broader_production_authorization", item.id,
        {"readiness_assessment_id": str(readiness.id), "previous_rollout_percentage": scale_up.rollout_percentage,
         "rollout_percentage": item.rollout_percentage, "controls": _controls(item),
         "production_wide_authorized": False, "restricted_documents_authorized": False},
        "Separate bounded Sprint 11I authorization created; no rollout is active before six approvals and Admin decision.",
    )
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def record_approval(db: Session, user: User, item: AIBroaderProductionAuthorization,
                    role: str, action: str, evidence_reference: str | None, note: str) -> dict:
    if item.status not in {"pending_approvals", "decision_ready"}:
        raise HTTPException(409, "This authorization is not accepting approvals")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The authorization requester cannot approve their own attempt")
    approvals = _approvals(db, item.id)
    if any(entry.approval_role == role for entry in approvals):
        raise HTTPException(409, "This approval role already has a decision")
    if any(entry.approver_id == user.id for entry in approvals):
        raise HTTPException(409, "All six approval roles require different people")
    reference = _reference(evidence_reference) if evidence_reference else None
    if action == "approve" and reference is None:
        raise HTTPException(422, "Approval requires bounded evidence")
    entry = AIBroaderProductionApproval(
        organization_id=user.organization_id, authorization_id=item.id,
        approver_id=user.id, approval_role=role, action=action,
        evidence_reference=reference, note=note.strip(), approved_at=datetime.now(UTC),
    )
    db.add(entry)
    db.flush()
    if action == "reject":
        item.status = "rejected"
        item.outcome = "approval_rejected"
    else:
        current = _approvals(db, item.id)
        item.status = "decision_ready" if (
            {e.approval_role for e in current} == APPROVAL_ROLES
            and len(current) == len(APPROVAL_ROLES)
            and all(e.action == "approve" for e in current)
            and len({e.approver_id for e in current}) == len(APPROVAL_ROLES)
            and all(e.approver_id != item.requested_by_id for e in current)
        ) else "pending_approvals"
    _audit(db, user, f"{action.upper()}_AI_BROADER_PRODUCTION_APPROVAL",
           "ai_broader_production_authorization", item.id,
           {"approval_role": role, "action": action, "status": item.status},
           "Independent Sprint 11I authorization review. " + note.strip())
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def decide_authorization(db: Session, user: User, item: AIBroaderProductionAuthorization,
                         outcome: str, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit Admin authorization decision is required")
    if item.status != "decision_ready":
        raise HTTPException(409, "Six independent approvals are required")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The requester cannot issue the final authorization decision")
    _anchor_still_valid(db, item)
    approvals = _approvals(db, item.id)
    if (
        {e.approval_role for e in approvals} != APPROVAL_ROLES
        or len(approvals) != len(APPROVAL_ROLES)
        or any(e.action != "approve" for e in approvals)
        or len({e.approver_id for e in approvals}) != len(APPROVAL_ROLES)
        or any(e.approver_id == item.requested_by_id for e in approvals)
    ):
        raise HTTPException(409, "Six independent approvals must remain valid")
    decided_at = datetime.now(UTC)
    snapshot = {
        "schema": "mcri-ai-broader-production-authorization-v1",
        "authorization_id": str(item.id),
        "readiness_assessment_id": str(item.readiness_assessment_id),
        "readiness_assessment_hash": item.readiness_assessment_hash,
        "readiness_decision_hash": item.readiness_decision_hash,
        "scale_up_decision_hash": item.scale_up_decision_hash,
        "inherited_outcome_hashes": {"assessment": item.inherited_outcome_assessment_hash,
                                     "decision": item.inherited_outcome_decision_hash},
        "bundle": {"model": item.model, "prompt": item.prompt_bundle_version,
                   "schema": item.schema_bundle_version},
        "rollout_percentage": item.rollout_percentage,
        "reviewers": [{"role": e.approval_role, "approver_id": str(e.approver_id),
                       "evidence_reference": e.evidence_reference} for e in approvals],
        "outcome": outcome, "decided_at": decided_at.isoformat(), "note": note.strip(),
        "production_wide_authorized": False, "rollout_above_50_percent_authorized": False,
        "restricted_documents_authorized": False, "new_document_classes_authorized": False,
        "autonomous_claim_decisions_authorized": False,
    }
    item.outcome = outcome
    item.decision_note = note.strip()
    item.decided_at = decided_at
    item.finalized_by_id = user.id
    item.decision_hash = sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if outcome == "authorize_broader_production":
        item.status = "authorized"
    elif outcome == "hold":
        item.status = "held"
    else:
        item.status = "rejected"
    _audit(db, user, "DECIDE_AI_BROADER_PRODUCTION_AUTHORIZATION",
           "ai_broader_production_authorization", item.id,
           {"status": item.status, "outcome": outcome, "decision_hash": item.decision_hash,
            "production_wide_authorized": False, "rollout_above_50_percent_authorized": False},
           "Admin Sprint 11I decision for only this expiring bounded cohort. " + note.strip())
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def attest_document(db: Session, user: User, item: AIBroaderProductionAuthorization,
                    payload: AIBroaderProductionDocumentCreate) -> dict:
    if not payload.confirm_new_broader_production_eligibility:
        raise HTTPException(422, "Explicit fresh Sprint 11I document eligibility confirmation is required")
    if not _active(item):
        raise HTTPException(409, "Only an active broader-production authorization accepts documents")
    _anchor_still_valid(db, item)
    document = db.scalar(select(Document).where(
        Document.id == payload.document_id,
        Document.organization_id == user.organization_id,
        Document.claim_id == payload.claim_id,
        Document.deleted_at.is_(None),
    ))
    if document is None:
        raise HTTPException(404, "Document not found")
    confidentiality = document.confidentiality_level.value if hasattr(document.confidentiality_level, "value") else str(document.confidentiality_level)
    if confidentiality not in {ConfidentialityLevel.INTERNAL.value, ConfidentialityLevel.CONFIDENTIAL.value}:
        raise HTTPException(409, "Only Internal or Confidential documents are permitted")
    if document.document_type not in item.allowed_document_types:
        raise HTTPException(409, "Document type is outside the Sprint 11I allowlist")
    bucket = _rollout_bucket(document.id)
    if bucket >= item.rollout_percentage:
        raise HTTPException(409, "Document is outside the deterministic broader-production rollout")
    existing = [e for e in _documents(db, item.id) if e.status == "eligible"]
    if any(e.document_id == document.id for e in existing):
        raise HTTPException(409, "Document already has active Sprint 11I eligibility")
    claims = {e.claim_id for e in existing}
    if document.claim_id not in claims and len(claims) >= item.max_claims:
        raise HTTPException(409, "Broader-production claim cap reached")
    if len(existing) >= item.max_documents:
        raise HTTPException(409, "Broader-production document cap reached")
    attempts = [e for e in _documents(db, item.id) if e.document_id == document.id]
    now = datetime.now(UTC)
    snapshot = {
        "schema": "mcri-ai-broader-production-document-eligibility-v1",
        "authorization_id": str(item.id), "authorization_decision_hash": item.decision_hash,
        "document_id": str(document.id), "claim_id": str(document.claim_id),
        "document_type": document.document_type, "confidentiality_level": confidentiality,
        "file_hash": document.file_hash, "rollout_bucket": bucket,
        "legal_basis_reference": _reference(payload.legal_basis_reference),
        "data_minimization_reference": _reference(payload.data_minimization_reference),
        "change_ticket_reference": _reference(payload.change_ticket_reference),
        "attestation_number": len(attempts) + 1, "attested_at": now.isoformat(),
    }
    entry = AIBroaderProductionDocumentEligibility(
        organization_id=user.organization_id, authorization_id=item.id,
        claim_id=document.claim_id, document_id=document.id, attested_by_id=user.id,
        attestation_number=len(attempts) + 1, rollout_bucket=bucket,
        document_type=document.document_type, confidentiality_level=confidentiality,
        legal_basis_reference=snapshot["legal_basis_reference"],
        data_minimization_reference=snapshot["data_minimization_reference"],
        change_ticket_reference=snapshot["change_ticket_reference"], note=payload.note.strip(),
        snapshot_hash=sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        status="eligible", attested_at=now,
    )
    db.add(entry)
    db.flush()
    _audit(db, user, "ATTEST_AI_BROADER_PRODUCTION_DOCUMENT", "ai_broader_production_document_eligibility",
           entry.id, {"authorization_id": str(item.id), "document_id": str(document.id),
                      "snapshot_hash": entry.snapshot_hash, "fresh_eligibility": True},
           "Fresh Sprint 11I legal-basis and minimization attestation; no eligibility was carried forward.")
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def revoke_document(db: Session, user: User, item: AIBroaderProductionAuthorization,
                    eligibility_id: UUID, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit document eligibility revocation is required")
    entry = db.scalar(select(AIBroaderProductionDocumentEligibility).where(
        AIBroaderProductionDocumentEligibility.id == eligibility_id,
        AIBroaderProductionDocumentEligibility.authorization_id == item.id,
        AIBroaderProductionDocumentEligibility.organization_id == user.organization_id,
    ))
    if entry is None:
        raise HTTPException(404, "Sprint 11I document eligibility not found")
    if entry.status != "eligible":
        raise HTTPException(409, "Document eligibility is already inactive")
    entry.status = "revoked"
    entry.revoked_by_id = user.id
    entry.revoked_at = datetime.now(UTC)
    entry.revocation_note = note.strip()
    _audit(db, user, "REVOKE_AI_BROADER_PRODUCTION_DOCUMENT", "ai_broader_production_document_eligibility",
           entry.id, {"status": "revoked"}, "Sprint 11I document eligibility revoked. " + note.strip())
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def require_broader_production_runtime_authorization(
    db: Session, *, organization_id: UUID, document: Document, expected_document_type: str,
    input_char_count: int, requested_by_id: UUID | None = None,
) -> tuple[AIBroaderProductionAuthorization, AIBroaderProductionDocumentEligibility]:
    item = latest_broader_production_attempt(db, organization_id)
    if item is None:
        raise HTTPException(409, "No Sprint 11I control plane exists")
    if not _active(item):
        raise HTTPException(409, "No active broader-production authorization exists")
    _anchor_still_valid(db, item)
    settings = get_settings()
    if (
        settings.ai_model != item.model
        or settings.ai_prompt_bundle_version != item.prompt_bundle_version
        or settings.ai_schema_bundle_version != item.schema_bundle_version
        or settings.ai_max_output_tokens != item.max_output_tokens
    ):
        raise HTTPException(409, "Configured AI bundle differs from the authorized Sprint 11I bundle")
    confidentiality = document.confidentiality_level.value if hasattr(document.confidentiality_level, "value") else str(document.confidentiality_level)
    if confidentiality not in {ConfidentialityLevel.INTERNAL.value, ConfidentialityLevel.CONFIDENTIAL.value}:
        raise HTTPException(409, "Only Internal or Confidential documents are permitted")
    if expected_document_type not in item.allowed_document_types or document.document_type != expected_document_type:
        raise HTTPException(409, "Document type is outside the broader-production allowlist")
    if input_char_count > item.max_input_chars:
        raise HTTPException(409, "Document exceeds the authorized input limit")
    if _rollout_bucket(document.id) >= item.rollout_percentage:
        raise HTTPException(409, "Document is outside the deterministic broader-production rollout")
    eligibility = db.scalar(select(AIBroaderProductionDocumentEligibility).where(
        AIBroaderProductionDocumentEligibility.organization_id == organization_id,
        AIBroaderProductionDocumentEligibility.authorization_id == item.id,
        AIBroaderProductionDocumentEligibility.document_id == document.id,
        AIBroaderProductionDocumentEligibility.status == "eligible",
    ).order_by(AIBroaderProductionDocumentEligibility.attestation_number.desc()))
    if eligibility is None:
        raise HTTPException(409, "Document requires fresh Sprint 11I eligibility")
    incidents = _incidents(db, item.id)
    if any(entry.status == "open" for entry in incidents):
        raise HTTPException(409, "An open incident blocks broader-production AI")
    if any(entry.category in SAFETY_CATEGORIES for entry in incidents):
        raise HTTPException(409, "Privacy, Security or Cross-tenant incident history blocks this Sprint 11I attempt")
    runs = _runs(db, item.id)
    if len(runs) >= item.max_provider_runs:
        raise HTTPException(409, "Broader-production provider-run cap reached")
    participating = {entry.requested_by_id for entry in runs if entry.requested_by_id is not None}
    if requested_by_id is not None and requested_by_id not in participating and len(participating) >= item.max_users:
        raise HTTPException(409, "Broader-production user cap reached")
    if (
        runs and item.decided_at is not None
        and datetime.now(UTC) > _as_utc(item.decided_at) + timedelta(minutes=item.monitor_interval_minutes * 2)
        and not _latest_monitor_pass(db, item, require_fresh=True)
    ):
        raise HTTPException(409, "A fresh passing Sprint 11I monitor is required")
    return item, eligibility


def reserve_run_if_broader_production(
    db: Session, *, user: User, document: Document, expected_document_type: str,
    input_char_count: int, processing_job_id: UUID,
) -> AIBroaderProductionRun | None:
    if get_settings().app_env.lower().strip() != "production":
        return None
    latest = latest_broader_production_attempt(db, user.organization_id)
    if latest is None:
        return None
    existing = db.scalar(select(AIBroaderProductionRun).where(
        AIBroaderProductionRun.organization_id == user.organization_id,
        AIBroaderProductionRun.processing_job_id == processing_job_id,
    ))
    if existing is not None:
        return existing
    item, eligibility = require_broader_production_runtime_authorization(
        db, organization_id=user.organization_id, document=document,
        expected_document_type=expected_document_type, input_char_count=input_char_count,
        requested_by_id=user.id,
    )
    run = AIBroaderProductionRun(
        organization_id=user.organization_id, authorization_id=item.id,
        eligibility_id=eligibility.id, claim_id=document.claim_id, document_id=document.id,
        requested_by_id=user.id, run_key=f"processing-{processing_job_id}",
        processing_job_id=processing_job_id, task_type=expected_document_type,
        status="queued", queued_at=datetime.now(UTC),
    )
    db.add(run)
    db.flush()
    _audit(db, user, "RESERVE_AI_BROADER_PRODUCTION_RUN", "ai_broader_production_run", run.id,
           {"authorization_id": str(item.id), "document_id": str(document.id),
            "processing_job_id": str(processing_job_id), "task_type": expected_document_type,
            "raw_content_stored": False, "human_review_required": True},
           "Content-free Sprint 11I provider-run reservation.")
    return run


def get_run(db: Session, organization_id: UUID, run_id: UUID) -> AIBroaderProductionRun:
    run = db.scalar(select(AIBroaderProductionRun).where(
        AIBroaderProductionRun.id == run_id,
        AIBroaderProductionRun.organization_id == organization_id,
    ))
    if run is None:
        raise HTTPException(404, "Broader-production run not found")
    return run


def record_run_outcome(db: Session, user: User, run: AIBroaderProductionRun, *,
                       human_review_action: str, output_candidate_count: int,
                       human_edit_count: int, unsupported_output_count: int,
                       source_grounded_output_count: int, source_grounding_total_count: int,
                       latency_ms: int, observed_provider_cost_microusd: int,
                       evidence_reference: str, note: str, confirm_human_review: bool) -> dict:
    if not confirm_human_review:
        raise HTTPException(422, "Explicit human-review confirmation is required")
    if run.status != "queued":
        raise HTTPException(409, "This run outcome is immutable")
    if run.requested_by_id == user.id:
        raise HTTPException(409, "A different human must review every broader-production AI output")
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
        "schema": "mcri-ai-broader-production-run-outcome-v1", "run_id": str(run.id),
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
    run.outcome_hash = sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    _audit(db, user, "REVIEW_AI_BROADER_PRODUCTION_RUN", "ai_broader_production_run", run.id,
           {"authorization_id": str(run.authorization_id), "human_review_action": human_review_action,
            "outcome_hash": run.outcome_hash, "authoritative_facts_auto_updated": False},
           "Mandatory different-human Sprint 11I review. " + note.strip())
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


def record_monitor(db: Session, user: User, item: AIBroaderProductionAuthorization,
                   monitor_key: str, note: str, confirm: bool) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit live monitor confirmation is required")
    if item.status not in {"authorized", "paused"}:
        raise HTTPException(409, "Only an authorized or paused Sprint 11I cohort can be monitored")
    _anchor_still_valid(db, item)
    runs = _runs(db, item.id)
    incidents = _incidents(db, item.id)
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
    review_rate = _rate_bps(len(reviewed), len(runs))
    reject_rate = _rate_bps(rejected, actions)
    edit_rate = _rate_bps(edited, actions)
    unsupported_rate = _rate_bps(unsupported, candidates)
    grounding_rate = _rate_bps(grounded, grounding_total)
    open_blocking = sum(e.status == "open" and e.severity in BLOCKING_SEVERITIES for e in incidents)
    safety_incidents = sum(e.category in SAFETY_CATEGORIES for e in incidents)

    half = len(reviewed) // 2
    first = reviewed[:half]
    second = reviewed[half:] if half else []
    def grounding(rows: list[AIBroaderProductionRun]) -> int | None:
        total = sum(row.source_grounding_total_count or 0 for row in rows)
        good = sum(row.source_grounded_output_count or 0 for row in rows)
        return _rate_bps(good, total)
    first_grounding = grounding(first)
    second_grounding = grounding(second)
    quality_regression = (max(0, first_grounding - second_grounding)
                          if first_grounding is not None and second_grounding is not None else None)
    first_latency = _mean([row.latency_ms for row in first if row.latency_ms is not None])
    second_latency = _mean([row.latency_ms for row in second if row.latency_ms is not None])
    first_cost = _mean([row.observed_provider_cost_microusd for row in first if row.observed_provider_cost_microusd is not None])
    second_cost = _mean([row.observed_provider_cost_microusd for row in second if row.observed_provider_cost_microusd is not None])
    latency_regression = _relative_increase_bps(first_latency, second_latency)
    cost_regression = _relative_increase_bps(first_cost, second_cost)

    failures: list[str] = []
    if not runs:
        failures.append("minimum_observed_run_count")
    if review_rate != 10000:
        failures.append("human_review_coverage")
    if reject_rate is None or reject_rate > item.max_reject_rate_bps:
        failures.append("human_reject_rate")
    if edit_rate is None or edit_rate > item.max_edit_rate_bps:
        failures.append("human_edit_rate")
    if unsupported_rate is None or unsupported_rate > item.max_unsupported_output_rate_bps:
        failures.append("unsupported_output_rate")
    if grounding_rate is None or grounding_rate < item.min_source_grounding_validity_bps:
        failures.append("source_grounding_validity")
    if p95 is None or p95 > item.max_p95_latency_ms:
        failures.append("p95_latency")
    if mean_cost is None or mean_cost > item.max_mean_cost_microusd:
        failures.append("mean_observed_provider_cost")
    if open_blocking:
        failures.append("open_high_or_critical_incident")
    if safety_incidents:
        failures.append("privacy_security_or_cross_tenant_incident")
    if len(reviewed) >= 4:
        if quality_regression is None or quality_regression > item.max_quality_regression_bps:
            failures.append("quality_regression")
        if latency_regression is None or latency_regression > item.max_latency_regression_bps:
            failures.append("latency_regression")
        if cost_regression is None or cost_regression > item.max_cost_regression_bps:
            failures.append("cost_regression")
    failures = sorted(set(failures))
    metrics = {
        "overall_pass": not failures, "provider_run_count": len(runs),
        "human_reviewed_run_count": len(reviewed), "human_review_rate_bps": review_rate,
        "human_approve_count": approved, "human_edit_count": edited, "human_reject_count": rejected,
        "human_edit_rate_bps": edit_rate, "human_reject_rate_bps": reject_rate,
        "unsupported_output_rate_bps": unsupported_rate,
        "source_grounding_validity_bps": grounding_rate,
        "p95_latency_ms": p95, "mean_observed_provider_cost_microusd": mean_cost,
        "total_observed_provider_cost_microusd": sum(costs),
        "open_high_or_critical_incident_count": open_blocking,
        "safety_incident_count": safety_incidents,
        "rollout_percentage": item.rollout_percentage,
        "trend": {"first_half_grounding_bps": first_grounding,
                  "second_half_grounding_bps": second_grounding,
                  "quality_regression_bps": quality_regression,
                  "first_half_mean_latency_ms": first_latency,
                  "second_half_mean_latency_ms": second_latency,
                  "latency_regression_bps": latency_regression,
                  "first_half_mean_cost_microusd": first_cost,
                  "second_half_mean_cost_microusd": second_cost,
                  "cost_regression_bps": cost_regression},
        "raw_content_stored": False, "production_wide_authorized": False,
        "rollout_above_50_percent_authorized": False,
        "restricted_documents_authorized": False, "new_document_classes_authorized": False,
    }
    monitored_at = datetime.now(UTC)
    snapshot = {
        "schema": "mcri-ai-broader-production-monitor-v1", "authorization_id": str(item.id),
        "monitor_key": monitor_key.strip(), "metrics": metrics,
        "failure_reasons": failures, "run_outcome_hashes": [run.outcome_hash for run in runs],
        "incident_states": [{"id": str(e.id), "severity": e.severity, "category": e.category,
                             "status": e.status} for e in incidents],
        "monitored_at": monitored_at.isoformat(), "note": note.strip(),
    }
    monitor = AIBroaderProductionMonitor(
        organization_id=user.organization_id, authorization_id=item.id,
        initiated_by_id=user.id, monitor_key=monitor_key.strip(), metrics=metrics,
        failure_reasons=failures, status="pass" if not failures else "rollback_required",
        monitor_hash=sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        note=note.strip(), monitored_at=monitored_at,
    )
    db.add(monitor)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This Sprint 11I monitor key already exists") from exc
    if failures:
        item.status = "paused"
        item.outcome = "monitor_rollback_required"
    _audit(db, user, "RECORD_AI_BROADER_PRODUCTION_MONITOR", "ai_broader_production_monitor", monitor.id,
           {"authorization_id": str(item.id), "status": monitor.status,
            "monitor_hash": monitor.monitor_hash, "failure_reasons": failures},
           "Content-free Sprint 11I monitor; any failure pauses execution and requires rollback. " + note.strip())
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def report_incident(db: Session, user: User, item: AIBroaderProductionAuthorization, *,
                    severity: str, category: str, evidence_reference: str,
                    note: str, confirm: bool) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit pause-and-rollback confirmation is required")
    if item.status != "authorized":
        raise HTTPException(409, "Only an active Sprint 11I authorization can be paused")
    incident = AIBroaderProductionIncident(
        organization_id=user.organization_id, authorization_id=item.id,
        reported_by_id=user.id, severity=severity, category=category,
        evidence_reference=_reference(evidence_reference), note=note.strip(),
        status="open", reported_at=datetime.now(UTC),
    )
    db.add(incident)
    db.flush()
    item.status = "paused"
    item.outcome = "incident_rollback"
    _audit(db, user, "PAUSE_AI_BROADER_PRODUCTION_INCIDENT", "ai_broader_production_authorization", item.id,
           {"incident_id": str(incident.id), "severity": severity, "category": category,
            "status": "paused", "rollback_slo_minutes": item.rollback_slo_minutes},
           "Immediate Sprint 11I pause and rollback trigger. " + note.strip())
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def resolve_incident(db: Session, user: User, item: AIBroaderProductionAuthorization,
                     incident_id: UUID, *, resolution_reference: str,
                     resolution_note: str, confirm: bool) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit incident resolution confirmation is required")
    incident = db.scalar(select(AIBroaderProductionIncident).where(
        AIBroaderProductionIncident.id == incident_id,
        AIBroaderProductionIncident.authorization_id == item.id,
        AIBroaderProductionIncident.organization_id == user.organization_id,
    ))
    if incident is None:
        raise HTTPException(404, "Sprint 11I incident not found")
    if incident.status != "open":
        raise HTTPException(409, "Incident is already resolved")
    incident.status = "resolved"
    incident.resolved_by_id = user.id
    incident.resolved_at = datetime.now(UTC)
    incident.resolution_reference = _reference(resolution_reference)
    incident.resolution_note = resolution_note.strip()
    _audit(db, user, "RESOLVE_AI_BROADER_PRODUCTION_INCIDENT", "ai_broader_production_authorization", item.id,
           {"incident_id": str(incident.id), "status": item.status, "resumed": False},
           "Incident resolved; fresh passing monitor and explicit Admin recovery remain required. " + resolution_note.strip())
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def resume_authorization(db: Session, user: User, item: AIBroaderProductionAuthorization,
                         confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit Admin recovery confirmation is required")
    if item.status != "paused":
        raise HTTPException(409, "Only a paused Sprint 11I authorization can resume")
    incidents = _incidents(db, item.id)
    if any(entry.status == "open" for entry in incidents):
        raise HTTPException(409, "Open incidents block recovery")
    if any(entry.category in SAFETY_CATEGORIES for entry in incidents):
        raise HTTPException(409, "Privacy, Security or Cross-tenant incidents require a new Sprint 11I attempt")
    if not _latest_monitor_pass(db, item, require_fresh=True):
        raise HTTPException(409, "A fresh passing monitor is required before recovery")
    if _as_utc(item.expires_at) <= datetime.now(UTC):
        raise HTTPException(409, "Expired authorization cannot resume")
    _anchor_still_valid(db, item)
    item.status = "authorized"
    item.outcome = "resumed_after_monitor"
    _audit(db, user, "RESUME_AI_BROADER_PRODUCTION", "ai_broader_production_authorization", item.id,
           {"status": "authorized", "production_wide_authorized": False},
           "Admin resumed only the existing bounded Sprint 11I cohort. " + note.strip())
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def revoke_authorization(db: Session, user: User, item: AIBroaderProductionAuthorization,
                         confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit Sprint 11I kill-switch confirmation is required")
    if item.status in {"revoked", "completed"}:
        raise HTTPException(409, "Authorization is already terminal")
    item.status = "revoked"
    item.outcome = "revoked"
    item.revoked_by_id = user.id
    item.revoked_at = datetime.now(UTC)
    item.revocation_note = note.strip()
    _audit(db, user, "REVOKE_AI_BROADER_PRODUCTION", "ai_broader_production_authorization", item.id,
           {"status": "revoked", "production_wide_authorized": False},
           "Immediate Sprint 11I kill switch. " + note.strip())
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)


def complete_authorization(db: Session, user: User, item: AIBroaderProductionAuthorization,
                           confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit Sprint 11I completion confirmation is required")
    if item.status != "authorized":
        raise HTTPException(409, "Only an active Sprint 11I cohort can complete")
    _anchor_still_valid(db, item)
    runs = _runs(db, item.id)
    incidents = _incidents(db, item.id)
    if not runs or any(run.status != "human_reviewed" for run in runs):
        raise HTTPException(409, "Every Sprint 11I provider run requires completed different-human review")
    if any(entry.status == "open" for entry in incidents):
        raise HTTPException(409, "Open incidents block completion")
    if any(entry.category in SAFETY_CATEGORIES for entry in incidents):
        raise HTTPException(409, "Privacy, Security or Cross-tenant incident history blocks successful completion")
    if not _latest_monitor_pass(db, item, require_fresh=True):
        raise HTTPException(409, "A fresh passing final monitor is required before completion")
    item.status = "completed"
    item.outcome = "completed"
    item.completed_at = datetime.now(UTC)
    item.completion_note = note.strip()
    _audit(db, user, "COMPLETE_AI_BROADER_PRODUCTION", "ai_broader_production_authorization", item.id,
           {"status": "completed", "provider_run_count": len(runs),
            "production_wide_authorized": False, "rollout_above_50_percent_authorized": False,
            "restricted_documents_authorized": False, "new_document_classes_authorized": False},
           "Completed bounded Sprint 11I cohort; no further rollout is granted. " + note.strip())
    db.commit()
    db.refresh(item)
    return authorization_response(db, item)
