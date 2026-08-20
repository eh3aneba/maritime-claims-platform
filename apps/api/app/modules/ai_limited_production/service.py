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
from app.modules.ai_evaluation.models import AIEvaluationSuite
from app.modules.ai_limited_production.models import (
    AILimitedProductionApproval,
    AILimitedProductionAuthorization,
    AILimitedProductionDocumentEligibility,
    AILimitedProductionIncident,
    AILimitedProductionMonitor,
    AILimitedProductionRun,
)
from app.modules.ai_limited_production.schemas import (
    AILimitedProductionCreate,
    AILimitedProductionDocumentCreate,
)
from app.modules.ai_pilot_outcomes.models import AIPilotOutcomeAssessment
from app.modules.ai_private_pilot.models import AIPrivatePilotAuthorization
from app.modules.audit.service import write_audit_log
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.processing.models import DocumentProcessingJob, ProcessingJobStatus
from app.modules.users.models import User

REFERENCE = re.compile(r"^(artifact|runbook|ticket|monitor)://[A-Za-z0-9._:/-]{3,450}$")
APPROVAL_ROLES = {"security", "privacy", "product", "operations"}
ALLOWED_DOCUMENT_TYPES = {"chief_engineer_report", "engine_log"}
RETRY_STATUSES = {"held", "rejected", "revoked", "completed", "expired"}


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _reference(value: str) -> str:
    reference = value.strip()
    if not REFERENCE.fullmatch(reference):
        raise HTTPException(422, "Limited-production evidence must use a bounded reference")
    return reference


def _audit(db: Session, user: User, action: str, entity_type: str, entity_id: UUID,
           values: dict, details: str) -> None:
    write_audit_log(
        db, organization_id=user.organization_id, user_id=user.id, action=action,
        entity_type=entity_type, entity_id=entity_id,
        new_values=values, details=details,
    )


def _approvals(db: Session, authorization_id: UUID) -> list[AILimitedProductionApproval]:
    return list(db.scalars(select(AILimitedProductionApproval).where(
        AILimitedProductionApproval.authorization_id == authorization_id,
    ).order_by(AILimitedProductionApproval.approval_role.asc())))


def _documents(db: Session,
               authorization_id: UUID) -> list[AILimitedProductionDocumentEligibility]:
    return list(db.scalars(select(AILimitedProductionDocumentEligibility).where(
        AILimitedProductionDocumentEligibility.authorization_id == authorization_id,
    ).order_by(AILimitedProductionDocumentEligibility.created_at.asc())))


def _runs(db: Session, authorization_id: UUID) -> list[AILimitedProductionRun]:
    return list(db.scalars(select(AILimitedProductionRun).where(
        AILimitedProductionRun.authorization_id == authorization_id,
    ).order_by(AILimitedProductionRun.queued_at.asc())))


def _monitors(db: Session, authorization_id: UUID) -> list[AILimitedProductionMonitor]:
    return list(db.scalars(select(AILimitedProductionMonitor).where(
        AILimitedProductionMonitor.authorization_id == authorization_id,
    ).order_by(AILimitedProductionMonitor.monitored_at.asc())))


def _incidents(db: Session, authorization_id: UUID) -> list[AILimitedProductionIncident]:
    return list(db.scalars(select(AILimitedProductionIncident).where(
        AILimitedProductionIncident.authorization_id == authorization_id,
    ).order_by(AILimitedProductionIncident.reported_at.asc())))


def _active(item: AILimitedProductionAuthorization) -> bool:
    now = datetime.now(UTC)
    return (item.status == "authorized"
            and _as_utc(item.starts_at) <= now < _as_utc(item.expires_at))


def _rollout_bucket(document_id: UUID) -> int:
    return int(sha256(str(document_id).encode()).hexdigest()[:8], 16) % 100


def _latest_monitor_pass(db: Session, item: AILimitedProductionAuthorization,
                         *, require_fresh: bool) -> bool:
    monitors = _monitors(db, item.id)
    if not monitors:
        return False
    latest = monitors[-1]
    if latest.status != "pass":
        return False
    if not require_fresh:
        return True
    freshness = timedelta(minutes=item.monitor_interval_minutes * 2)
    return _as_utc(latest.monitored_at) >= datetime.now(UTC) - freshness


def _controls(item: AILimitedProductionAuthorization) -> dict:
    return {
        "rollback_slo_minutes": item.rollback_slo_minutes,
        "monitor_interval_minutes": item.monitor_interval_minutes,
        "max_reject_rate_bps": item.max_reject_rate_bps,
        "max_edit_rate_bps": item.max_edit_rate_bps,
        "max_p95_latency_ms": item.max_p95_latency_ms,
        "max_mean_observed_provider_cost_microusd": item.max_mean_cost_microusd,
        "required_human_review_rate_bps": 10000,
        "max_open_incident_count": 0,
    }


def authorization_response(db: Session, item: AILimitedProductionAuthorization) -> dict:
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
        "pilot_id": item.pilot_id, "evaluation_suite_id": item.evaluation_suite_id,
        "requested_by_id": item.requested_by_id, "finalized_by_id": item.finalized_by_id,
        "revoked_by_id": item.revoked_by_id, "attempt_number": item.attempt_number,
        "authorization_key": item.authorization_key, "environment": item.environment,
        "evaluation_mode": item.evaluation_mode, "model": item.model,
        "prompt_bundle_version": item.prompt_bundle_version,
        "schema_bundle_version": item.schema_bundle_version,
        "max_input_chars": item.max_input_chars, "max_output_tokens": item.max_output_tokens,
        "allowed_document_types": item.allowed_document_types,
        "rollout_percentage": item.rollout_percentage,
        "max_claims": item.max_claims, "max_documents": item.max_documents,
        "max_users": item.max_users, "max_provider_runs": item.max_provider_runs,
        "starts_at": item.starts_at, "expires_at": item.expires_at,
        "controls": _controls(item),
        "references": {
            "deployment_isolation": item.deployment_isolation_reference,
            "provider_project": item.provider_project_reference,
            "credential_control": item.credential_control_reference,
            "data_processing": item.data_processing_reference,
            "monitoring": item.monitoring_reference,
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
            "participating_user_count": len({entry.requested_by_id for entry in runs
                                              if entry.requested_by_id is not None}),
            "provider_run_count": len(runs),
            "human_reviewed_run_count": len(reviewed_runs),
            "pending_human_review_count": len(runs) - len(reviewed_runs),
            "open_incident_count": len(open_incidents),
            "latest_monitor_status": monitors[-1].status if monitors else None,
            "monitor_fresh_and_passing": _latest_monitor_pass(db, item, require_fresh=True),
            "limited_production_evaluation_authorized": _active(item),
            "production_wide_authorized": False,
            "restricted_documents_authorized": False,
            "rollout_above_declared_percentage_authorized": False,
            "autonomous_claim_decisions_authorized": False,
            "authoritative_facts_auto_updated": False,
            "human_review_required": True,
            "raw_content_stored_in_control_ledger": False,
        },
        "created_at": item.created_at,
    }


def list_authorizations(db: Session, organization_id: UUID) -> list[dict]:
    items = list(db.scalars(select(AILimitedProductionAuthorization).where(
        AILimitedProductionAuthorization.organization_id == organization_id,
    ).order_by(AILimitedProductionAuthorization.created_at.desc()).limit(20)))
    return [authorization_response(db, item) for item in items]


def get_authorization(db: Session, organization_id: UUID,
                      authorization_id: UUID) -> AILimitedProductionAuthorization:
    item = db.scalar(select(AILimitedProductionAuthorization).where(
        AILimitedProductionAuthorization.id == authorization_id,
        AILimitedProductionAuthorization.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "Limited-production AI authorization not found")
    return item


def create_authorization(db: Session, user: User,
                         payload: AILimitedProductionCreate) -> dict:
    if not payload.confirm_separate_limited_production_evaluation:
        raise HTTPException(422, "Explicit separate limited-production confirmation is required")
    if any(value.tzinfo is None or value.utcoffset() is None
           for value in (payload.starts_at, payload.expires_at)):
        raise HTTPException(422, "Authorization timestamps must include a timezone")
    starts = payload.starts_at.astimezone(UTC); expires = payload.expires_at.astimezone(UTC)
    now = datetime.now(UTC)
    if starts < now - timedelta(minutes=5) or starts > now + timedelta(days=2):
        raise HTTPException(422, "Limited-production start must be current or within two days")
    if expires <= starts or expires - starts > timedelta(days=14):
        raise HTTPException(422, "Limited-production evaluation must be bounded to 14 days")
    if payload.max_documents < payload.max_claims:
        raise HTTPException(422, "Document cap cannot be lower than the claim cap")
    allowed = list(dict.fromkeys(payload.allowed_document_types))
    if len(allowed) != len(payload.allowed_document_types) or not set(allowed) <= ALLOWED_DOCUMENT_TYPES:
        raise HTTPException(422, "Document allowlist is duplicated or unsupported")
    assessment = db.scalar(select(AIPilotOutcomeAssessment).where(
        AIPilotOutcomeAssessment.id == payload.outcome_assessment_id,
        AIPilotOutcomeAssessment.organization_id == user.organization_id,
    ))
    if (assessment is None or assessment.status != "recommended"
            or assessment.outcome != "recommend_limited_production_evaluation"
            or not (assessment.metrics or {}).get("overall_pass")):
        raise HTTPException(409, "A passing, positively recommended Sprint 11D assessment is required")
    pilot = db.scalar(select(AIPrivatePilotAuthorization).where(
        AIPrivatePilotAuthorization.id == assessment.pilot_id,
        AIPrivatePilotAuthorization.organization_id == user.organization_id,
        AIPrivatePilotAuthorization.status == "completed",
    ))
    if pilot is None:
        raise HTTPException(409, "The Sprint 11D pilot anchor must remain completed")
    suite = db.scalar(select(AIEvaluationSuite).where(
        AIEvaluationSuite.id == pilot.evaluation_suite_id,
        AIEvaluationSuite.organization_id == user.organization_id,
    ))
    if suite is None:
        raise HTTPException(409, "The evaluated model bundle anchor is unavailable")
    references = [
        payload.deployment_isolation_reference, payload.provider_project_reference,
        payload.credential_control_reference, payload.data_processing_reference,
        payload.monitoring_reference, payload.rollback_reference,
        payload.change_ticket_reference,
    ]
    bounded = [_reference(value) for value in references]
    attempts = list(db.scalars(select(AILimitedProductionAuthorization).where(
        AILimitedProductionAuthorization.outcome_assessment_id == assessment.id,
    ).order_by(AILimitedProductionAuthorization.attempt_number.asc())))
    if attempts and attempts[-1].status not in RETRY_STATUSES:
        if not (attempts[-1].status == "authorized"
                and _as_utc(attempts[-1].expires_at) <= now):
            raise HTTPException(409, "A new attempt requires hold, rejection, revocation, completion or expiry")
    item = AILimitedProductionAuthorization(
        organization_id=user.organization_id, outcome_assessment_id=assessment.id,
        pilot_id=pilot.id, evaluation_suite_id=suite.id, requested_by_id=user.id,
        attempt_number=len(attempts) + 1, authorization_key=payload.authorization_key.strip(),
        environment="production", evaluation_mode="limited_production_evaluation",
        model=suite.activation_model, prompt_bundle_version=suite.prompt_bundle_version,
        schema_bundle_version=suite.schema_bundle_version,
        max_input_chars=suite.max_input_chars, max_output_tokens=suite.max_output_tokens,
        allowed_document_types=allowed, rollout_percentage=payload.rollout_percentage,
        max_claims=payload.max_claims, max_documents=payload.max_documents,
        max_users=payload.max_users, max_provider_runs=payload.max_provider_runs,
        starts_at=starts, expires_at=expires,
        deployment_isolation_reference=bounded[0], provider_project_reference=bounded[1],
        credential_control_reference=bounded[2], data_processing_reference=bounded[3],
        monitoring_reference=bounded[4], rollback_reference=bounded[5],
        change_ticket_reference=bounded[6], status="pending_approvals",
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This authorization key or attempt already exists") from exc
    _audit(db, user, "CREATE_AI_LIMITED_PRODUCTION_AUTHORIZATION",
           "ai_limited_production_authorization", item.id,
           {"outcome_assessment_id": str(assessment.id), "evaluation_suite_id": str(suite.id),
            "environment": "production", "evaluation_mode": item.evaluation_mode,
            "rollout_percentage": item.rollout_percentage,
            "limits": {"claims": item.max_claims, "documents": item.max_documents,
                       "users": item.max_users, "provider_runs": item.max_provider_runs},
            "controls": _controls(item), "production_wide_authorized": False,
            "restricted_documents_authorized": False},
           "Separate authorization attempt only; Sprint 11D recommendation did not activate Production.")
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def record_approval(db: Session, user: User, item: AILimitedProductionAuthorization,
                    role: str, action: str, evidence_reference: str | None,
                    note: str) -> dict:
    if item.status not in {"pending_approvals", "decision_ready"}:
        raise HTTPException(409, "This authorization attempt is immutable")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The authorization requester cannot approve the attempt")
    approvals = _approvals(db, item.id)
    if any(entry.approval_role == role for entry in approvals):
        raise HTTPException(409, "This approval role already has a decision")
    if any(entry.approver_id == user.id for entry in approvals):
        raise HTTPException(409, "Security, Privacy, Product and Operations require different people")
    reference = _reference(evidence_reference) if evidence_reference else None
    if action == "approve" and not reference:
        raise HTTPException(422, "Approval requires bounded evidence")
    approval = AILimitedProductionApproval(
        organization_id=user.organization_id, authorization_id=item.id,
        approver_id=user.id, approval_role=role, action=action,
        evidence_reference=reference, note=note.strip(), approved_at=datetime.now(UTC),
    )
    db.add(approval); db.flush()
    if action == "reject":
        item.status = "rejected"; item.outcome = "rejected"
        item.decision_note = note.strip(); item.finalized_by_id = user.id
        item.decided_at = datetime.now(UTC)
    else:
        current = _approvals(db, item.id)
        item.status = "decision_ready" if (
            {entry.approval_role for entry in current} == APPROVAL_ROLES
            and all(entry.action == "approve" for entry in current)
            and len({entry.approver_id for entry in current}) == len(APPROVAL_ROLES)
        ) else "pending_approvals"
    _audit(db, user, f"{action.upper()}_AI_LIMITED_PRODUCTION_APPROVAL",
           "ai_limited_production_authorization", item.id,
           {"approval_role": role, "action": action,
            "evidence_reference": reference, "status": item.status},
           "Independent limited-production evaluation review. " + note.strip())
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def decide_authorization(db: Session, user: User, item: AILimitedProductionAuthorization,
                         outcome: str, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit limited-production decision confirmation is required")
    if item.status != "decision_ready":
        raise HTTPException(409, "Four independent approvals are required")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The requester cannot issue final authorization")
    approvals = _approvals(db, item.id)
    if (len(approvals) != len(APPROVAL_ROLES)
            or {entry.approval_role for entry in approvals} != APPROVAL_ROLES
            or len({entry.approver_id for entry in approvals}) != len(APPROVAL_ROLES)
            or any(entry.action != "approve" for entry in approvals)):
        raise HTTPException(409, "Four approval roles must remain independent")
    if outcome == "authorize_limited_evaluation" and _as_utc(item.expires_at) <= datetime.now(UTC):
        raise HTTPException(409, "The limited-production window has expired")
    snapshot = {
        "schema": "mcri-ai-limited-production-authorization-v1",
        "authorization_id": str(item.id),
        "outcome_assessment_id": str(item.outcome_assessment_id),
        "pilot_id": str(item.pilot_id), "evaluation_suite_id": str(item.evaluation_suite_id),
        "environment": item.environment, "evaluation_mode": item.evaluation_mode,
        "bundle": {"model": item.model, "prompt": item.prompt_bundle_version,
                   "schema": item.schema_bundle_version,
                   "max_input_chars": item.max_input_chars,
                   "max_output_tokens": item.max_output_tokens},
        "allowed_document_types": sorted(item.allowed_document_types),
        "rollout_percentage": item.rollout_percentage,
        "limits": {"claims": item.max_claims, "documents": item.max_documents,
                   "users": item.max_users, "provider_runs": item.max_provider_runs},
        "starts_at": _as_utc(item.starts_at).isoformat(),
        "expires_at": _as_utc(item.expires_at).isoformat(),
        "controls": _controls(item),
        "approvals": [{"role": entry.approval_role,
                       "approver_id": str(entry.approver_id),
                       "evidence_reference": entry.evidence_reference} for entry in approvals],
        "outcome": outcome, "decision_note": note.strip(),
        "limited_production_evaluation_only": True,
        "production_wide_authorized": False, "restricted_documents_authorized": False,
        "autonomous_claim_decisions_authorized": False,
        "authoritative_facts_auto_updated": False, "human_review_required": True,
        "raw_content_stored": False,
    }
    item.status = "authorized" if outcome == "authorize_limited_evaluation" else "held"
    item.outcome = outcome; item.finalized_by_id = user.id
    item.decision_note = note.strip(); item.decided_at = datetime.now(UTC)
    item.decision_hash = sha256(json.dumps(snapshot, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
    _audit(db, user, f"{outcome.upper()}_AI_LIMITED_PRODUCTION",
           "ai_limited_production_authorization", item.id,
           {"status": item.status, "decision_hash": item.decision_hash,
            "rollout_percentage": item.rollout_percentage,
            "production_wide_authorized": False, "restricted_documents_authorized": False},
           "Expiring limited-production evaluation decision. " + note.strip())
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def attest_document(db: Session, user: User, item: AILimitedProductionAuthorization,
                    payload: AILimitedProductionDocumentCreate) -> dict:
    if not payload.confirm_non_restricted_rollout_document:
        raise HTTPException(422, "Explicit non-restricted rollout confirmation is required")
    if not _active(item):
        raise HTTPException(409, "An active limited-production authorization is required")
    document = db.scalar(select(Document).where(
        Document.id == payload.document_id, Document.claim_id == payload.claim_id,
        Document.organization_id == user.organization_id,
        Document.deleted_at.is_(None), Document.is_current.is_(True),
    ))
    if document is None:
        raise HTTPException(404, "Document not found")
    confidentiality = (document.confidentiality_level.value
                       if hasattr(document.confidentiality_level, "value")
                       else str(document.confidentiality_level))
    if confidentiality == ConfidentialityLevel.RESTRICTED.value:
        raise HTTPException(409, "Restricted documents are prohibited")
    if not document.document_type or document.document_type not in item.allowed_document_types:
        raise HTTPException(409, "Document type is outside the limited-production allowlist")
    bucket = _rollout_bucket(document.id)
    if bucket >= item.rollout_percentage:
        raise HTTPException(409, "Document is outside the deterministic rollout percentage")
    legal = _reference(payload.legal_basis_reference)
    minimization = _reference(payload.data_minimization_reference)
    change = _reference(payload.change_ticket_reference)
    attempts = list(db.scalars(select(AILimitedProductionDocumentEligibility).where(
        AILimitedProductionDocumentEligibility.authorization_id == item.id,
        AILimitedProductionDocumentEligibility.document_id == document.id,
    ).order_by(AILimitedProductionDocumentEligibility.attestation_number.asc())))
    if attempts and attempts[-1].status == "eligible":
        raise HTTPException(409, "This document already has active eligibility")
    active = [entry for entry in _documents(db, item.id) if entry.status == "eligible"]
    if len(active) >= item.max_documents:
        raise HTTPException(409, "Limited-production document cap reached")
    active_claims = {entry.claim_id for entry in active}
    if document.claim_id not in active_claims and len(active_claims) >= item.max_claims:
        raise HTTPException(409, "Limited-production claim cap reached")
    snapshot = {
        "schema": "mcri-ai-limited-production-document-v1",
        "authorization_id": str(item.id), "claim_id": str(document.claim_id),
        "document_id": str(document.id), "file_hash": document.file_hash,
        "document_type": document.document_type,
        "confidentiality_level": confidentiality, "rollout_bucket": bucket,
        "rollout_percentage": item.rollout_percentage,
        "legal_basis_reference": legal, "data_minimization_reference": minimization,
        "change_ticket_reference": change, "restricted_document": False,
    }
    eligibility = AILimitedProductionDocumentEligibility(
        organization_id=user.organization_id, authorization_id=item.id,
        claim_id=document.claim_id, document_id=document.id, attested_by_id=user.id,
        attestation_number=len(attempts) + 1, rollout_bucket=bucket,
        document_type=document.document_type, confidentiality_level=confidentiality,
        legal_basis_reference=legal, data_minimization_reference=minimization,
        change_ticket_reference=change, note=payload.note.strip(),
        snapshot_hash=sha256(json.dumps(snapshot, sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest(),
        status="eligible", attested_at=datetime.now(UTC),
    )
    db.add(eligibility); db.flush()
    _audit(db, user, "ATTEST_AI_LIMITED_PRODUCTION_DOCUMENT",
           "ai_limited_production_document", eligibility.id,
           {"authorization_id": str(item.id), "document_id": str(document.id),
            "rollout_bucket": bucket, "snapshot_hash": eligibility.snapshot_hash,
            "restricted_document": False},
           "Document-level production-evaluation eligibility; no document content copied.")
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def revoke_document(db: Session, user: User, item: AILimitedProductionAuthorization,
                    eligibility_id: UUID, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit document revocation is required")
    eligibility = db.scalar(select(AILimitedProductionDocumentEligibility).where(
        AILimitedProductionDocumentEligibility.id == eligibility_id,
        AILimitedProductionDocumentEligibility.authorization_id == item.id,
        AILimitedProductionDocumentEligibility.organization_id == user.organization_id,
    ))
    if eligibility is None:
        raise HTTPException(404, "Limited-production document eligibility not found")
    if eligibility.status != "eligible":
        raise HTTPException(409, "Document eligibility is already inactive")
    eligibility.status = "revoked"; eligibility.revoked_by_id = user.id
    eligibility.revoked_at = datetime.now(UTC); eligibility.revocation_note = note.strip()
    _audit(db, user, "REVOKE_AI_LIMITED_PRODUCTION_DOCUMENT",
           "ai_limited_production_document", eligibility.id,
           {"authorization_id": str(item.id), "document_id": str(eligibility.document_id),
            "status": "revoked"},
           "Document removed from limited-production evaluation immediately. " + note.strip())
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def require_limited_production_runtime_authorization(
    db: Session, *, organization_id: UUID, document: Document,
    expected_document_type: str, input_char_count: int,
    requested_by_id: UUID | None = None,
) -> tuple[AILimitedProductionAuthorization, AILimitedProductionDocumentEligibility]:
    settings = get_settings()
    if settings.app_env.lower().strip() != "production":
        raise HTTPException(409, "Limited-production AI requires the production environment")
    item = db.scalar(select(AILimitedProductionAuthorization).where(
        AILimitedProductionAuthorization.organization_id == organization_id,
        AILimitedProductionAuthorization.status == "authorized",
    ).order_by(AILimitedProductionAuthorization.attempt_number.desc()))
    if item is None or not _active(item):
        raise HTTPException(409, "No active limited-production AI evaluation exists")
    if (settings.ai_model != item.model
            or settings.ai_prompt_bundle_version != item.prompt_bundle_version
            or settings.ai_schema_bundle_version != item.schema_bundle_version
            or settings.ai_max_output_tokens != item.max_output_tokens):
        raise HTTPException(409, "Configured AI bundle differs from the authorized evaluation")
    confidentiality = (document.confidentiality_level.value
                       if hasattr(document.confidentiality_level, "value")
                       else str(document.confidentiality_level))
    if confidentiality == ConfidentialityLevel.RESTRICTED.value:
        raise HTTPException(409, "Restricted documents are prohibited")
    if (expected_document_type not in item.allowed_document_types
            or document.document_type != expected_document_type):
        raise HTTPException(409, "Document type is outside the production-evaluation allowlist")
    if input_char_count > item.max_input_chars:
        raise HTTPException(409, "Document exceeds the authorized input limit")
    if _rollout_bucket(document.id) >= item.rollout_percentage:
        raise HTTPException(409, "Document is outside the deterministic rollout")
    eligibility = db.scalar(select(AILimitedProductionDocumentEligibility).where(
        AILimitedProductionDocumentEligibility.organization_id == organization_id,
        AILimitedProductionDocumentEligibility.authorization_id == item.id,
        AILimitedProductionDocumentEligibility.document_id == document.id,
        AILimitedProductionDocumentEligibility.status == "eligible",
    ).order_by(AILimitedProductionDocumentEligibility.attestation_number.desc()))
    if eligibility is None:
        raise HTTPException(409, "Document requires limited-production eligibility")
    if any(entry.status == "open" for entry in _incidents(db, item.id)):
        raise HTTPException(409, "An open incident blocks limited-production AI")
    runs = _runs(db, item.id)
    if len(runs) >= item.max_provider_runs:
        raise HTTPException(409, "Limited-production provider-run cap reached")
    participating = {entry.requested_by_id for entry in runs if entry.requested_by_id is not None}
    if (requested_by_id is not None and requested_by_id not in participating
            and len(participating) >= item.max_users):
        raise HTTPException(409, "Limited-production user cap reached")
    if (runs and item.decided_at is not None
            and datetime.now(UTC) > _as_utc(item.decided_at)
            + timedelta(minutes=item.monitor_interval_minutes * 2)
            and not _latest_monitor_pass(db, item, require_fresh=True)):
        raise HTTPException(409, "A fresh passing production monitor is required")
    return item, eligibility


def reserve_run_if_limited_production(
    db: Session, *, user: User, document: Document, expected_document_type: str,
    input_char_count: int, processing_job_id: UUID,
) -> AILimitedProductionRun | None:
    if get_settings().app_env.lower().strip() != "production":
        return None
    existing = db.scalar(select(AILimitedProductionRun).where(
        AILimitedProductionRun.organization_id == user.organization_id,
        AILimitedProductionRun.processing_job_id == processing_job_id,
    ))
    if existing is not None:
        return existing
    item, eligibility = require_limited_production_runtime_authorization(
        db, organization_id=user.organization_id, document=document,
        expected_document_type=expected_document_type, input_char_count=input_char_count,
        requested_by_id=user.id,
    )
    run = AILimitedProductionRun(
        organization_id=user.organization_id, authorization_id=item.id,
        eligibility_id=eligibility.id, claim_id=document.claim_id, document_id=document.id,
        requested_by_id=user.id, run_key=f"processing-{processing_job_id}",
        processing_job_id=processing_job_id, task_type=expected_document_type,
        status="queued", queued_at=datetime.now(UTC),
    )
    db.add(run); db.flush()
    _audit(db, user, "RESERVE_AI_LIMITED_PRODUCTION_RUN",
           "ai_limited_production_run", run.id,
           {"authorization_id": str(item.id), "document_id": str(document.id),
            "processing_job_id": str(processing_job_id), "task_type": expected_document_type,
            "status": "queued", "raw_content_stored": False,
            "human_review_required": True},
           "Content-free production-evaluation run reservation.")
    return run


def get_run(db: Session, organization_id: UUID, run_id: UUID) -> AILimitedProductionRun:
    run = db.scalar(select(AILimitedProductionRun).where(
        AILimitedProductionRun.id == run_id,
        AILimitedProductionRun.organization_id == organization_id,
    ))
    if run is None:
        raise HTTPException(404, "Limited-production run not found")
    return run


def record_run_outcome(db: Session, user: User, run: AILimitedProductionRun,
                       *, human_review_action: str, output_candidate_count: int,
                       human_edit_count: int, latency_ms: int,
                       observed_provider_cost_microusd: int,
                       evidence_reference: str, note: str,
                       confirm_human_review: bool) -> dict:
    if not confirm_human_review:
        raise HTTPException(422, "Explicit human-review confirmation is required")
    if run.status != "queued":
        raise HTTPException(409, "This run outcome is immutable")
    if run.requested_by_id == user.id:
        raise HTTPException(409, "A different human must review the AI output")
    job = db.scalar(select(DocumentProcessingJob).where(
        DocumentProcessingJob.id == run.processing_job_id,
        DocumentProcessingJob.organization_id == user.organization_id,
    ))
    if job is None or job.status != ProcessingJobStatus.COMPLETED:
        raise HTTPException(409, "Provider processing must complete before human review")
    if human_edit_count > output_candidate_count:
        raise HTTPException(422, "Human edits cannot exceed output candidates")
    reference = _reference(evidence_reference)
    snapshot = {
        "schema": "mcri-ai-limited-production-run-outcome-v1",
        "run_id": str(run.id), "authorization_id": str(run.authorization_id),
        "processing_job_id": str(run.processing_job_id), "task_type": run.task_type,
        "human_review_action": human_review_action,
        "output_candidate_count": output_candidate_count,
        "human_edit_count": human_edit_count, "latency_ms": latency_ms,
        "observed_provider_cost_microusd": observed_provider_cost_microusd,
        "evidence_reference": reference, "note": note.strip(),
        "human_review_completed": True, "authoritative_facts_auto_updated": False,
        "raw_content_stored": False,
    }
    run.reviewed_by_id = user.id; run.status = "human_reviewed"
    run.human_review_action = human_review_action
    run.output_candidate_count = output_candidate_count; run.human_edit_count = human_edit_count
    run.latency_ms = latency_ms
    run.observed_provider_cost_microusd = observed_provider_cost_microusd
    run.evidence_reference = reference; run.note = note.strip(); run.reviewed_at = datetime.now(UTC)
    run.outcome_hash = sha256(json.dumps(snapshot, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()
    _audit(db, user, "REVIEW_AI_LIMITED_PRODUCTION_RUN",
           "ai_limited_production_run", run.id,
           {"authorization_id": str(run.authorization_id),
            "human_review_action": human_review_action, "outcome_hash": run.outcome_hash,
            "authoritative_facts_auto_updated": False},
           "Mandatory content-free production-evaluation human review. " + note.strip())
    db.commit()
    item = get_authorization(db, user.organization_id, run.authorization_id)
    return authorization_response(db, item)


def _rate_bps(numerator: int, denominator: int) -> int | None:
    return numerator * 10000 // denominator if denominator else None


def record_monitor(db: Session, user: User, item: AILimitedProductionAuthorization,
                   monitor_key: str, note: str, confirm: bool) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit live monitor confirmation is required")
    if item.status not in {"authorized", "paused"}:
        raise HTTPException(409, "Only an authorized or paused evaluation can be monitored")
    runs = _runs(db, item.id); incidents = _incidents(db, item.id)
    reviewed = [run for run in runs if run.status == "human_reviewed"]
    approved = sum(run.human_review_action == "approve" for run in reviewed)
    edited = sum(run.human_review_action == "edit" for run in reviewed)
    rejected = sum(run.human_review_action == "reject" for run in reviewed)
    actions = approved + edited + rejected
    latencies = sorted(run.latency_ms for run in reviewed if run.latency_ms is not None)
    costs = [run.observed_provider_cost_microusd for run in reviewed
             if run.observed_provider_cost_microusd is not None]
    p95 = latencies[max(ceil(0.95 * len(latencies)) - 1, 0)] if latencies else None
    mean_cost = ((sum(costs) + len(costs) - 1) // len(costs)) if costs else None
    review_rate = _rate_bps(len(reviewed), len(runs))
    reject_rate = _rate_bps(rejected, actions)
    edit_rate = _rate_bps(edited, actions)
    open_incidents = sum(entry.status == "open" for entry in incidents)
    failures: list[str] = []
    if not runs: failures.append("minimum_observed_run_count")
    if review_rate != 10000: failures.append("human_review_coverage")
    if reject_rate is None or reject_rate > item.max_reject_rate_bps:
        failures.append("human_reject_rate")
    if edit_rate is None or edit_rate > item.max_edit_rate_bps:
        failures.append("human_edit_rate")
    if p95 is None or p95 > item.max_p95_latency_ms: failures.append("p95_latency")
    if mean_cost is None or mean_cost > item.max_mean_cost_microusd:
        failures.append("mean_observed_provider_cost")
    if open_incidents: failures.append("open_incident")
    failures = sorted(set(failures))
    metrics = {
        "overall_pass": not failures, "provider_run_count": len(runs),
        "human_reviewed_run_count": len(reviewed), "human_review_rate_bps": review_rate,
        "human_approve_count": approved, "human_edit_count": edited,
        "human_reject_count": rejected, "human_edit_rate_bps": edit_rate,
        "human_reject_rate_bps": reject_rate, "p95_latency_ms": p95,
        "total_observed_provider_cost_microusd": sum(costs),
        "mean_observed_provider_cost_microusd": mean_cost,
        "open_incident_count": open_incidents,
        "rollout_percentage": item.rollout_percentage,
        "raw_content_stored": False, "calculated_provider_billing": False,
        "production_wide_authorized": False,
    }
    monitored_at = datetime.now(UTC)
    snapshot = {
        "schema": "mcri-ai-limited-production-monitor-v1",
        "authorization_id": str(item.id), "monitor_key": monitor_key.strip(),
        "metrics": metrics, "failure_reasons": failures,
        "run_outcome_hashes": [run.outcome_hash for run in runs],
        "incident_states": [{"id": str(entry.id), "severity": entry.severity,
                             "category": entry.category, "status": entry.status}
                            for entry in incidents],
        "monitored_at": monitored_at.isoformat(), "note": note.strip(),
        "rollback_slo_minutes": item.rollback_slo_minutes,
    }
    monitor = AILimitedProductionMonitor(
        organization_id=user.organization_id, authorization_id=item.id,
        initiated_by_id=user.id, monitor_key=monitor_key.strip(), metrics=metrics,
        failure_reasons=failures, status="pass" if not failures else "rollback_required",
        monitor_hash=sha256(json.dumps(snapshot, sort_keys=True,
                                       separators=(",", ":")).encode()).hexdigest(),
        note=note.strip(), monitored_at=monitored_at,
    )
    db.add(monitor)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This monitor key already exists") from exc
    if failures:
        item.status = "paused"; item.outcome = "monitor_rollback_required"
    _audit(db, user, "RECORD_AI_LIMITED_PRODUCTION_MONITOR",
           "ai_limited_production_monitor", monitor.id,
           {"authorization_id": str(item.id), "status": monitor.status,
            "monitor_hash": monitor.monitor_hash, "failure_reasons": failures,
            "rollback_slo_minutes": item.rollback_slo_minutes},
           "Live content-free monitor snapshot; failure pauses execution. " + note.strip())
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def report_incident(db: Session, user: User, item: AILimitedProductionAuthorization,
                    *, severity: str, category: str, evidence_reference: str,
                    note: str, confirm: bool) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit pause-and-rollback confirmation is required")
    if item.status != "authorized":
        raise HTTPException(409, "Only an active authorization can be paused")
    reference = _reference(evidence_reference)
    incident = AILimitedProductionIncident(
        organization_id=user.organization_id, authorization_id=item.id,
        reported_by_id=user.id, severity=severity, category=category,
        evidence_reference=reference, note=note.strip(), status="open",
        reported_at=datetime.now(UTC),
    )
    db.add(incident); db.flush(); item.status = "paused"; item.outcome = "incident_rollback"
    _audit(db, user, "PAUSE_AI_LIMITED_PRODUCTION_INCIDENT",
           "ai_limited_production_authorization", item.id,
           {"incident_id": str(incident.id), "severity": severity,
            "category": category, "status": "paused",
            "rollback_slo_minutes": item.rollback_slo_minutes},
           "Immediate production-evaluation pause and rollback trigger. " + note.strip())
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def resolve_incident(db: Session, user: User, item: AILimitedProductionAuthorization,
                     incident_id: UUID, *, resolution_reference: str,
                     resolution_note: str, resume: bool, confirm: bool) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit incident resolution confirmation is required")
    if resume:
        raise HTTPException(
            422,
            "Resolve the incident, record a fresh passing monitor, then use the resume endpoint",
        )
    incident = db.scalar(select(AILimitedProductionIncident).where(
        AILimitedProductionIncident.id == incident_id,
        AILimitedProductionIncident.authorization_id == item.id,
        AILimitedProductionIncident.organization_id == user.organization_id,
    ))
    if incident is None:
        raise HTTPException(404, "Limited-production incident not found")
    if incident.status != "open":
        raise HTTPException(409, "Incident is already resolved")
    reference = _reference(resolution_reference)
    incident.status = "resolved"; incident.resolved_by_id = user.id
    incident.resolved_at = datetime.now(UTC); incident.resolution_reference = reference
    incident.resolution_note = resolution_note.strip(); db.flush()
    _audit(db, user, "RESOLVE_AI_LIMITED_PRODUCTION_INCIDENT",
           "ai_limited_production_authorization", item.id,
           {"incident_id": str(incident.id), "status": item.status,
            "resumed": False, "resolution_reference": reference},
           "Admin incident resolution; resume remains monitor-gated. " + resolution_note.strip())
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def resume_authorization(db: Session, user: User, item: AILimitedProductionAuthorization,
                         confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit resume confirmation is required")
    if item.status != "paused":
        raise HTTPException(409, "Only a paused authorization can resume")
    if any(entry.status == "open" for entry in _incidents(db, item.id)):
        raise HTTPException(409, "Open incidents block resume")
    if not _latest_monitor_pass(db, item, require_fresh=True):
        raise HTTPException(409, "A fresh passing monitor is required before resume")
    if _as_utc(item.expires_at) <= datetime.now(UTC):
        raise HTTPException(409, "Expired authorization cannot resume")
    item.status = "authorized"; item.outcome = "resumed_after_monitor"
    _audit(db, user, "RESUME_AI_LIMITED_PRODUCTION",
           "ai_limited_production_authorization", item.id,
           {"status": "authorized", "monitor_fresh_and_passing": True},
           "Admin resumed the limited evaluation after verified recovery. " + note.strip())
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def revoke_authorization(db: Session, user: User, item: AILimitedProductionAuthorization,
                         confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit kill-switch confirmation is required")
    if item.status not in {"authorized", "paused"}:
        raise HTTPException(409, "Only an authorized or paused evaluation can be revoked")
    item.status = "revoked"; item.outcome = "revoked"; item.revoked_by_id = user.id
    item.revoked_at = datetime.now(UTC); item.revocation_note = note.strip()
    _audit(db, user, "REVOKE_AI_LIMITED_PRODUCTION",
           "ai_limited_production_authorization", item.id,
           {"status": "revoked", "authorization_active": False},
           "Immediate limited-production AI kill switch. " + note.strip())
    db.commit(); db.refresh(item)
    return authorization_response(db, item)


def complete_authorization(db: Session, user: User, item: AILimitedProductionAuthorization,
                           confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit completion confirmation is required")
    if item.status not in {"authorized", "paused"}:
        raise HTTPException(409, "Only an authorized or paused evaluation can complete")
    runs = _runs(db, item.id)
    if not runs or any(run.status != "human_reviewed" for run in runs):
        raise HTTPException(409, "Every provider run requires human review before completion")
    if any(entry.status == "open" for entry in _incidents(db, item.id)):
        raise HTTPException(409, "Every incident must be resolved before completion")
    if not _latest_monitor_pass(db, item, require_fresh=True):
        raise HTTPException(409, "A fresh passing monitor is required before completion")
    item.status = "completed"; item.outcome = "completed"
    item.completed_at = datetime.now(UTC); item.completion_note = note.strip()
    _audit(db, user, "COMPLETE_AI_LIMITED_PRODUCTION",
           "ai_limited_production_authorization", item.id,
           {"status": "completed", "provider_run_count": len(runs),
            "human_reviewed_run_count": len(runs),
            "production_wide_authorized": False},
           "Limited-production evaluation completed; broader Production remains unauthorized. "
           + note.strip())
    db.commit(); db.refresh(item)
    return authorization_response(db, item)
