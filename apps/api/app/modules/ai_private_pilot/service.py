import json
import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.ai_evaluation.models import AIEvaluationSuite
from app.modules.ai_governance.models import AIProviderActivationRequest
from app.modules.ai_private_pilot.models import (
    AIPrivatePilotApproval,
    AIPrivatePilotAuthorization,
    AIPrivatePilotDocumentEligibility,
    AIPrivatePilotIncident,
    AIPrivatePilotRun,
)
from app.modules.ai_private_pilot.schemas import AIPrivatePilotCreate, AIPrivatePilotDocumentCreate
from app.modules.audit.service import write_audit_log
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.processing.models import DocumentProcessingJob, ProcessingJobStatus
from app.modules.users.models import User

ALLOWED_DOCUMENT_TYPES = {"chief_engineer_report", "engine_log"}
APPROVAL_ROLES = {"organization_owner", "data_owner"}
RETRY_STATUSES = {"held", "rejected", "revoked", "completed"}
BOUNDED_REFERENCE = re.compile(
    r"^(artifact|runbook|ticket|monitor)://[A-Za-z0-9._:/-]{3,450}$")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _reference(value: str) -> str:
    result = value.strip()
    if not BOUNDED_REFERENCE.fullmatch(result):
        raise HTTPException(422, "Pilot evidence must use a bounded allowlisted reference")
    return result


def _audit(db: Session, user: User, action: str, kind: str, entity_id: UUID,
           values: dict, details: str) -> None:
    write_audit_log(
        db, organization_id=user.organization_id, user_id=user.id, action=action,
        entity_type=kind, entity_id=entity_id, new_values=values, details=details,
    )


def _activation_active(item: AIProviderActivationRequest) -> bool:
    return (item.status == "staging_authorized"
            and _as_utc(item.evaluation_expires_at) > datetime.now(UTC))


def _promotion_active(item: AIEvaluationSuite) -> bool:
    return (item.status == "staging_promoted" and item.promotion_expires_at is not None
            and _as_utc(item.promotion_expires_at) > datetime.now(UTC))


def _anchors(db: Session, organization_id: UUID,
             suite_id: UUID) -> tuple[AIEvaluationSuite, AIProviderActivationRequest]:
    suite = db.scalar(select(AIEvaluationSuite).where(
        AIEvaluationSuite.id == suite_id,
        AIEvaluationSuite.organization_id == organization_id,
    ))
    if suite is None:
        raise HTTPException(404, "AI evaluation promotion not found")
    activation = db.scalar(select(AIProviderActivationRequest).where(
        AIProviderActivationRequest.id == suite.activation_request_id,
        AIProviderActivationRequest.organization_id == organization_id,
    ))
    if activation is None:
        raise HTTPException(409, "The pilot activation anchor no longer exists")
    if not _activation_active(activation) or not _promotion_active(suite):
        raise HTTPException(409, "Active Sprint 11A authorization and Sprint 11B promotion are required")
    if (suite.activation_model != activation.model
            or suite.prompt_bundle_version != activation.prompt_bundle_version
            or suite.schema_bundle_version != activation.schema_bundle_version
            or suite.max_input_chars != activation.max_input_chars
            or suite.max_output_tokens != activation.max_output_tokens):
        raise HTTPException(409, "The promoted evaluation has drifted from its activation")
    return suite, activation


def _approvals(db: Session, pilot_id: UUID) -> list[AIPrivatePilotApproval]:
    return list(db.scalars(select(AIPrivatePilotApproval).where(
        AIPrivatePilotApproval.pilot_id == pilot_id,
    ).order_by(AIPrivatePilotApproval.approval_role.asc())))


def _documents(db: Session, pilot_id: UUID) -> list[AIPrivatePilotDocumentEligibility]:
    return list(db.scalars(select(AIPrivatePilotDocumentEligibility).where(
        AIPrivatePilotDocumentEligibility.pilot_id == pilot_id,
    ).order_by(AIPrivatePilotDocumentEligibility.created_at.asc())))


def _runs(db: Session, pilot_id: UUID) -> list[AIPrivatePilotRun]:
    return list(db.scalars(select(AIPrivatePilotRun).where(
        AIPrivatePilotRun.pilot_id == pilot_id,
    ).order_by(AIPrivatePilotRun.created_at.asc())))


def _incidents(db: Session, pilot_id: UUID) -> list[AIPrivatePilotIncident]:
    return list(db.scalars(select(AIPrivatePilotIncident).where(
        AIPrivatePilotIncident.pilot_id == pilot_id,
    ).order_by(AIPrivatePilotIncident.created_at.asc())))


def _pilot_active(db: Session, item: AIPrivatePilotAuthorization) -> bool:
    now = datetime.now(UTC)
    if (item.status != "authorized" or _as_utc(item.starts_at) > now
            or _as_utc(item.expires_at) <= now):
        return False
    try:
        suite, activation = _anchors(db, item.organization_id, item.evaluation_suite_id)
    except HTTPException:
        return False
    return (suite.id == item.evaluation_suite_id
            and activation.id == item.activation_request_id)


def pilot_response(db: Session, item: AIPrivatePilotAuthorization) -> dict:
    approvals = _approvals(db, item.id)
    documents = _documents(db, item.id)
    runs = _runs(db, item.id)
    incidents = _incidents(db, item.id)
    active_documents = [entry for entry in documents if entry.status == "eligible"]
    reviewed_runs = [entry for entry in runs if entry.status == "human_reviewed"]
    approval_by_role = {entry.approval_role: entry for entry in approvals}
    independent = bool(
        set(approval_by_role) == APPROVAL_ROLES
        and all(entry.action == "approve" for entry in approval_by_role.values())
        and len({entry.approver_id for entry in approval_by_role.values()}) == 2
        and all(entry.approver_id != item.requested_by_id for entry in approval_by_role.values())
    )
    authorization_active = _pilot_active(db, item)
    return {
        "id": item.id, "activation_request_id": item.activation_request_id,
        "evaluation_suite_id": item.evaluation_suite_id,
        "requested_by_id": item.requested_by_id, "finalized_by_id": item.finalized_by_id,
        "revoked_by_id": item.revoked_by_id, "attempt_number": item.attempt_number,
        "pilot_key": item.pilot_key, "data_mode": item.data_mode,
        "allowed_document_types": item.allowed_document_types,
        "max_claims": item.max_claims, "max_documents": item.max_documents,
        "max_users": item.max_users, "max_provider_runs": item.max_provider_runs,
        "starts_at": item.starts_at, "expires_at": item.expires_at,
        "organization_authorization_reference": item.organization_authorization_reference,
        "data_owner_authorization_reference": item.data_owner_authorization_reference,
        "monitoring_reference": item.monitoring_reference,
        "incident_runbook_reference": item.incident_runbook_reference,
        "rollback_reference": item.rollback_reference, "status": item.status,
        "outcome": item.outcome, "decision_note": item.decision_note,
        "decision_hash": item.decision_hash, "decided_at": item.decided_at,
        "completed_at": item.completed_at, "completion_note": item.completion_note,
        "revoked_at": item.revoked_at, "revocation_note": item.revocation_note,
        "approvals": approvals, "document_eligibility": documents,
        "runs": runs, "incidents": incidents, "created_at": item.created_at,
        "summary": {
            "independent_approvals_complete": independent,
            "authorization_active": authorization_active,
            "active_claim_count": len({entry.claim_id for entry in active_documents}),
            "active_document_count": len(active_documents),
            "participating_user_count": len({entry.requested_by_id for entry in runs
                                              if entry.requested_by_id is not None}),
            "provider_run_count": len(runs), "human_reviewed_run_count": len(reviewed_runs),
            "pending_human_review_count": len(runs) - len(reviewed_runs),
            "open_incident_count": sum(entry.status == "open" for entry in incidents),
            "real_non_restricted_documents_authorized": authorization_active,
            "restricted_documents_authorized": False,
            "production_wide_authorized": False,
            "autonomous_claim_decisions_authorized": False,
            "authoritative_facts_auto_updated": False,
            "human_review_required": True,
            "raw_content_stored_in_control_ledger": False,
        },
    }


def list_pilots(db: Session, organization_id: UUID) -> list[dict]:
    items = list(db.scalars(select(AIPrivatePilotAuthorization).where(
        AIPrivatePilotAuthorization.organization_id == organization_id,
    ).order_by(AIPrivatePilotAuthorization.created_at.desc()).limit(20)))
    return [pilot_response(db, item) for item in items]


def get_pilot(db: Session, organization_id: UUID,
              pilot_id: UUID) -> AIPrivatePilotAuthorization:
    item = db.scalar(select(AIPrivatePilotAuthorization).where(
        AIPrivatePilotAuthorization.id == pilot_id,
        AIPrivatePilotAuthorization.organization_id == organization_id,
    ))
    if item is None:
        raise HTTPException(404, "AI private pilot not found")
    return item


def create_pilot(db: Session, user: User, payload: AIPrivatePilotCreate) -> dict:
    if not payload.confirm_bounded_real_document_pilot:
        raise HTTPException(422, "Explicit bounded real-document pilot confirmation is required")
    if any(value.tzinfo is None or value.utcoffset() is None
           for value in (payload.starts_at, payload.expires_at)):
        raise HTTPException(422, "Pilot timestamps must include a timezone")
    starts = payload.starts_at.astimezone(UTC)
    expires = payload.expires_at.astimezone(UTC)
    now = datetime.now(UTC)
    if starts < now - timedelta(minutes=5) or starts > now + timedelta(days=7):
        raise HTTPException(422, "Pilot start must be current or within the next seven days")
    if expires <= starts or expires - starts > timedelta(days=30):
        raise HTTPException(422, "The private pilot must be time-bounded to 30 days")
    suite, activation = _anchors(db, user.organization_id, payload.evaluation_suite_id)
    anchor_expiry = min(_as_utc(activation.evaluation_expires_at),
                        _as_utc(suite.promotion_expires_at))
    if expires > anchor_expiry:
        raise HTTPException(422, "Pilot expiry cannot exceed its activation or promotion")
    allowed = list(dict.fromkeys(payload.allowed_document_types))
    if len(allowed) != len(payload.allowed_document_types) or not set(allowed) <= ALLOWED_DOCUMENT_TYPES:
        raise HTTPException(422, "Pilot document allowlist is duplicated or unsupported")
    if payload.max_documents < payload.max_claims:
        raise HTTPException(422, "Document cap cannot be lower than the claim cap")
    references = [payload.organization_authorization_reference,
                  payload.data_owner_authorization_reference, payload.monitoring_reference,
                  payload.incident_runbook_reference, payload.rollback_reference]
    bounded = [_reference(value) for value in references]
    attempts = list(db.scalars(select(AIPrivatePilotAuthorization).where(
        AIPrivatePilotAuthorization.organization_id == user.organization_id,
    ).order_by(AIPrivatePilotAuthorization.attempt_number.asc())))
    if attempts:
        latest = attempts[-1]
        if latest.status not in RETRY_STATUSES and not (
                latest.status == "authorized" and _as_utc(latest.expires_at) <= now):
            raise HTTPException(409, "A new pilot requires hold, rejection, completion, revocation or expiry")
    item = AIPrivatePilotAuthorization(
        organization_id=user.organization_id, activation_request_id=activation.id,
        evaluation_suite_id=suite.id, requested_by_id=user.id,
        attempt_number=len(attempts) + 1, pilot_key=payload.pilot_key.strip(),
        data_mode="real_non_restricted", allowed_document_types=allowed,
        max_claims=payload.max_claims, max_documents=payload.max_documents,
        max_users=payload.max_users, max_provider_runs=payload.max_provider_runs,
        starts_at=starts, expires_at=expires,
        organization_authorization_reference=bounded[0],
        data_owner_authorization_reference=bounded[1], monitoring_reference=bounded[2],
        incident_runbook_reference=bounded[3], rollback_reference=bounded[4],
        status="pending_approvals",
    )
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This private-pilot key or attempt already exists") from exc
    _audit(db, user, "CREATE_AI_PRIVATE_PILOT", "ai_private_pilot", item.id,
           {"activation_request_id": str(activation.id), "evaluation_suite_id": str(suite.id),
            "allowed_document_types": allowed,
            "limits": {"claims": item.max_claims, "documents": item.max_documents,
                       "users": item.max_users, "provider_runs": item.max_provider_runs},
            "starts_at": starts.isoformat(), "expires_at": expires.isoformat(),
            "restricted_documents_authorized": False, "production_wide_authorized": False},
           "Append-only governance record; no claim content or provider response stored.")
    db.commit(); db.refresh(item)
    return pilot_response(db, item)


def record_approval(db: Session, user: User, item: AIPrivatePilotAuthorization,
                    role: str, action: str, evidence_reference: str | None,
                    note: str) -> dict:
    if item.status not in {"pending_approvals", "decision_ready"}:
        raise HTTPException(409, "This pilot authorization attempt is immutable")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The pilot requester cannot approve the pilot")
    approvals = _approvals(db, item.id)
    if any(entry.approval_role == role for entry in approvals):
        raise HTTPException(409, "This pilot approval role already has a decision")
    if any(entry.approver_id == user.id for entry in approvals):
        raise HTTPException(409, "Organization and data-owner approvals require different people")
    reference = _reference(evidence_reference) if evidence_reference else None
    if action == "approve" and not reference:
        raise HTTPException(422, "Approval requires bounded evidence")
    approval = AIPrivatePilotApproval(
        organization_id=user.organization_id, pilot_id=item.id, approver_id=user.id,
        approval_role=role, action=action, evidence_reference=reference,
        note=note.strip(), approved_at=datetime.now(UTC),
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
            and len({entry.approver_id for entry in current}) == 2
        ) else "pending_approvals"
    _audit(db, user, f"{action.upper()}_AI_PRIVATE_PILOT", "ai_private_pilot", item.id,
           {"approval_role": role, "action": action,
            "evidence_reference": reference, "status": item.status},
           "Independent private-pilot authorization review. " + note.strip())
    db.commit(); db.refresh(item)
    return pilot_response(db, item)


def decide_pilot(db: Session, user: User, item: AIPrivatePilotAuthorization,
                 outcome: str, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit private-pilot decision confirmation is required")
    if item.status != "decision_ready":
        raise HTTPException(409, "Two independent pilot approvals are required")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The pilot requester cannot issue final authorization")
    suite, activation = _anchors(db, user.organization_id, item.evaluation_suite_id)
    if suite.id != item.evaluation_suite_id or activation.id != item.activation_request_id:
        raise HTTPException(409, "Pilot anchors no longer match")
    approvals = _approvals(db, item.id)
    if (len(approvals) != 2 or len({entry.approver_id for entry in approvals}) != 2
            or any(entry.action != "approve" for entry in approvals)):
        raise HTTPException(409, "Organization and data-owner approvals must be independent")
    if outcome == "authorize_pilot" and _as_utc(item.expires_at) <= datetime.now(UTC):
        raise HTTPException(409, "The requested pilot period has expired")
    snapshot = {
        "schema": "mcri-ai-private-pilot-v1", "pilot_id": str(item.id),
        "activation_request_id": str(item.activation_request_id),
        "evaluation_suite_id": str(item.evaluation_suite_id),
        "attempt_number": item.attempt_number, "data_mode": item.data_mode,
        "allowed_document_types": sorted(item.allowed_document_types),
        "limits": {"claims": item.max_claims, "documents": item.max_documents,
                   "users": item.max_users, "provider_runs": item.max_provider_runs},
        "starts_at": _as_utc(item.starts_at).isoformat(),
        "expires_at": _as_utc(item.expires_at).isoformat(),
        "references": {"organization_authorization": item.organization_authorization_reference,
                       "data_owner_authorization": item.data_owner_authorization_reference,
                       "monitoring": item.monitoring_reference,
                       "incident_runbook": item.incident_runbook_reference,
                       "rollback": item.rollback_reference},
        "approvals": [{"role": entry.approval_role,
                       "approver_id": str(entry.approver_id),
                       "evidence_reference": entry.evidence_reference} for entry in approvals],
        "outcome": outcome, "decision_note": note.strip(),
        "restricted_documents_authorized": False, "production_wide_authorized": False,
        "autonomous_claim_decisions_authorized": False, "human_review_required": True,
        "raw_content_stored": False,
    }
    item.status = "authorized" if outcome == "authorize_pilot" else "held"
    item.outcome = outcome; item.finalized_by_id = user.id
    item.decision_note = note.strip(); item.decided_at = datetime.now(UTC)
    item.decision_hash = sha256(json.dumps(snapshot, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
    _audit(db, user, f"{outcome.upper()}_AI_PRIVATE_PILOT", "ai_private_pilot", item.id,
           {"status": item.status, "decision_hash": item.decision_hash,
            "expires_at": _as_utc(item.expires_at).isoformat(),
            "restricted_documents_authorized": False, "production_wide_authorized": False},
           "Bounded real non-restricted private-pilot decision. " + note.strip())
    db.commit(); db.refresh(item)
    return pilot_response(db, item)


def attest_document(db: Session, user: User, item: AIPrivatePilotAuthorization,
                    payload: AIPrivatePilotDocumentCreate) -> dict:
    if not payload.confirm_real_non_restricted:
        raise HTTPException(422, "Explicit real non-restricted document confirmation is required")
    if not _pilot_active(db, item):
        raise HTTPException(409, "An active bounded private pilot is required")
    document = db.scalar(select(Document).where(
        Document.id == payload.document_id,
        Document.claim_id == payload.claim_id,
        Document.organization_id == user.organization_id,
        Document.deleted_at.is_(None), Document.is_current.is_(True),
    ))
    if document is None:
        raise HTTPException(404, "Document not found")
    confidentiality = (document.confidentiality_level.value
                       if hasattr(document.confidentiality_level, "value")
                       else str(document.confidentiality_level))
    if confidentiality == ConfidentialityLevel.RESTRICTED.value:
        raise HTTPException(409, "Restricted documents are prohibited in the private pilot")
    if not document.document_type or document.document_type not in item.allowed_document_types:
        raise HTTPException(409, "Document type is outside the private-pilot allowlist")
    authorization_reference = _reference(payload.authorization_reference)
    minimization_reference = _reference(payload.data_minimization_reference)
    attempts = list(db.scalars(select(AIPrivatePilotDocumentEligibility).where(
        AIPrivatePilotDocumentEligibility.pilot_id == item.id,
        AIPrivatePilotDocumentEligibility.document_id == document.id,
    ).order_by(AIPrivatePilotDocumentEligibility.attestation_number.asc())))
    if attempts and attempts[-1].status == "eligible":
        raise HTTPException(409, "This document already has active private-pilot eligibility")
    active = [entry for entry in _documents(db, item.id) if entry.status == "eligible"]
    if len(active) >= item.max_documents:
        raise HTTPException(409, "Private-pilot document cap has been reached")
    active_claims = {entry.claim_id for entry in active}
    if document.claim_id not in active_claims and len(active_claims) >= item.max_claims:
        raise HTTPException(409, "Private-pilot claim cap has been reached")
    snapshot = {
        "schema": "mcri-ai-private-pilot-document-v1", "pilot_id": str(item.id),
        "claim_id": str(document.claim_id), "document_id": str(document.id),
        "file_hash": document.file_hash, "document_type": document.document_type,
        "confidentiality_level": confidentiality,
        "authorization_basis": payload.authorization_basis,
        "authorization_reference": authorization_reference,
        "data_minimization_reference": minimization_reference,
        "restricted_document": False, "human_review_required": True,
    }
    eligibility = AIPrivatePilotDocumentEligibility(
        organization_id=user.organization_id, pilot_id=item.id,
        claim_id=document.claim_id, document_id=document.id, attested_by_id=user.id,
        attestation_number=len(attempts) + 1, document_type=document.document_type,
        confidentiality_level=confidentiality,
        authorization_basis=payload.authorization_basis,
        authorization_reference=authorization_reference,
        data_minimization_reference=minimization_reference, note=payload.note.strip(),
        snapshot_hash=sha256(json.dumps(snapshot, sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest(),
        status="eligible", attested_at=datetime.now(UTC),
    )
    db.add(eligibility); db.flush()
    _audit(db, user, "ATTEST_AI_PRIVATE_PILOT_DOCUMENT", "ai_private_pilot_document",
           eligibility.id, {"pilot_id": str(item.id), "claim_id": str(document.claim_id),
                            "document_id": str(document.id),
                            "document_type": document.document_type,
                            "confidentiality_level": confidentiality,
                            "snapshot_hash": eligibility.snapshot_hash,
                            "restricted_document": False},
           "Document-level authorization metadata only; document content is not copied.")
    db.commit(); db.refresh(item)
    return pilot_response(db, item)


def revoke_document(db: Session, user: User, item: AIPrivatePilotAuthorization,
                    eligibility_id: UUID, confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit pilot-document revocation is required")
    eligibility = db.scalar(select(AIPrivatePilotDocumentEligibility).where(
        AIPrivatePilotDocumentEligibility.id == eligibility_id,
        AIPrivatePilotDocumentEligibility.pilot_id == item.id,
        AIPrivatePilotDocumentEligibility.organization_id == user.organization_id,
    ))
    if eligibility is None:
        raise HTTPException(404, "Private-pilot document eligibility not found")
    if eligibility.status != "eligible":
        raise HTTPException(409, "Private-pilot document eligibility is already inactive")
    eligibility.status = "revoked"; eligibility.revoked_by_id = user.id
    eligibility.revoked_at = datetime.now(UTC); eligibility.revocation_note = note.strip()
    _audit(db, user, "REVOKE_AI_PRIVATE_PILOT_DOCUMENT", "ai_private_pilot_document",
           eligibility.id, {"pilot_id": str(item.id), "document_id": str(eligibility.document_id),
                            "status": "revoked"},
           "Document removed from the real-document pilot immediately. " + note.strip())
    db.commit(); db.refresh(item)
    return pilot_response(db, item)


def require_private_pilot_runtime_authorization(
    db: Session, *, organization_id: UUID, document: Document,
    expected_document_type: str, input_char_count: int,
    requested_by_id: UUID | None = None,
) -> tuple[AIPrivatePilotAuthorization, AIPrivatePilotDocumentEligibility]:
    settings = get_settings()
    if settings.app_env.lower().strip() != "staging":
        raise HTTPException(409, "The bounded real-document AI pilot runs only in staging")
    item = db.scalar(select(AIPrivatePilotAuthorization).where(
        AIPrivatePilotAuthorization.organization_id == organization_id,
        AIPrivatePilotAuthorization.status == "authorized",
    ).order_by(AIPrivatePilotAuthorization.attempt_number.desc()))
    if item is None or not _pilot_active(db, item):
        raise HTTPException(409, "No active bounded real-document AI pilot exists")
    suite, activation = _anchors(db, organization_id, item.evaluation_suite_id)
    if activation.id != item.activation_request_id:
        raise HTTPException(409, "Private-pilot activation anchor does not match")
    if (settings.ai_model != suite.activation_model
            or settings.ai_prompt_bundle_version != suite.prompt_bundle_version
            or settings.ai_schema_bundle_version != suite.schema_bundle_version
            or settings.ai_max_output_tokens != suite.max_output_tokens):
        raise HTTPException(409, "Configured AI bundle differs from the pilot promotion")
    confidentiality = (document.confidentiality_level.value
                       if hasattr(document.confidentiality_level, "value")
                       else str(document.confidentiality_level))
    if confidentiality == ConfidentialityLevel.RESTRICTED.value:
        raise HTTPException(409, "Restricted documents are prohibited in the private pilot")
    if (expected_document_type not in item.allowed_document_types
            or document.document_type != expected_document_type):
        raise HTTPException(409, "Document type is outside the private-pilot allowlist")
    if input_char_count > activation.max_input_chars:
        raise HTTPException(409, "Document exceeds the private-pilot AI input limit")
    eligibility = db.scalar(select(AIPrivatePilotDocumentEligibility).where(
        AIPrivatePilotDocumentEligibility.organization_id == organization_id,
        AIPrivatePilotDocumentEligibility.pilot_id == item.id,
        AIPrivatePilotDocumentEligibility.document_id == document.id,
        AIPrivatePilotDocumentEligibility.status == "eligible",
    ).order_by(AIPrivatePilotDocumentEligibility.attestation_number.desc()))
    if eligibility is None:
        raise HTTPException(409, "Document requires active private-pilot eligibility")
    runs = _runs(db, item.id)
    if len(runs) >= item.max_provider_runs:
        raise HTTPException(409, "Private-pilot provider-run cap has been reached")
    participating = {entry.requested_by_id for entry in runs if entry.requested_by_id is not None}
    if (requested_by_id is not None and requested_by_id not in participating
            and len(participating) >= item.max_users):
        raise HTTPException(409, "Private-pilot user cap has been reached")
    return item, eligibility


def reserve_run_if_private_pilot(
    db: Session, *, user: User, document: Document, expected_document_type: str,
    input_char_count: int, processing_job_id: UUID,
) -> AIPrivatePilotRun | None:
    eligibility = db.scalar(select(AIPrivatePilotDocumentEligibility).where(
        AIPrivatePilotDocumentEligibility.organization_id == user.organization_id,
        AIPrivatePilotDocumentEligibility.document_id == document.id,
        AIPrivatePilotDocumentEligibility.status == "eligible",
    ).order_by(AIPrivatePilotDocumentEligibility.created_at.desc()))
    if eligibility is None:
        return None
    existing = db.scalar(select(AIPrivatePilotRun).where(
        AIPrivatePilotRun.organization_id == user.organization_id,
        AIPrivatePilotRun.processing_job_id == processing_job_id,
    ))
    if existing is not None:
        return existing
    pilot, eligibility = require_private_pilot_runtime_authorization(
        db, organization_id=user.organization_id, document=document,
        expected_document_type=expected_document_type, input_char_count=input_char_count,
        requested_by_id=user.id,
    )
    run = AIPrivatePilotRun(
        organization_id=user.organization_id, pilot_id=pilot.id,
        eligibility_id=eligibility.id, claim_id=document.claim_id,
        document_id=document.id, requested_by_id=user.id,
        run_key=f"processing-{processing_job_id}", processing_job_id=processing_job_id,
        task_type=expected_document_type, status="queued", queued_at=datetime.now(UTC),
    )
    db.add(run); db.flush()
    _audit(db, user, "RESERVE_AI_PRIVATE_PILOT_RUN", "ai_private_pilot_run", run.id,
           {"pilot_id": str(pilot.id), "document_id": str(document.id),
            "processing_job_id": str(processing_job_id), "task_type": expected_document_type,
            "status": "queued", "raw_content_stored": False,
            "human_review_required": True},
           "Content-free provider-run reservation; authoritative claim facts remain unchanged.")
    return run


def get_run(db: Session, organization_id: UUID, run_id: UUID) -> AIPrivatePilotRun:
    run = db.scalar(select(AIPrivatePilotRun).where(
        AIPrivatePilotRun.id == run_id,
        AIPrivatePilotRun.organization_id == organization_id,
    ))
    if run is None:
        raise HTTPException(404, "Private-pilot run not found")
    return run


def record_run_outcome(db: Session, user: User, run: AIPrivatePilotRun,
                       *, human_review_action: str, output_candidate_count: int,
                       human_edit_count: int, latency_ms: int,
                       observed_provider_cost_microusd: int,
                       evidence_reference: str, note: str,
                       confirm_human_review: bool) -> dict:
    if not confirm_human_review:
        raise HTTPException(422, "Explicit human-review confirmation is required")
    if run.status != "queued":
        raise HTTPException(409, "This private-pilot run outcome is immutable")
    if run.requested_by_id == user.id:
        raise HTTPException(409, "A different human must review the private-pilot AI output")
    job = db.scalar(select(DocumentProcessingJob).where(
        DocumentProcessingJob.id == run.processing_job_id,
        DocumentProcessingJob.organization_id == user.organization_id,
    ))
    if job is None or job.status != ProcessingJobStatus.COMPLETED:
        raise HTTPException(409, "The provider processing job must complete before human review")
    if human_edit_count > output_candidate_count:
        raise HTTPException(422, "Human edits cannot exceed output candidates")
    reference = _reference(evidence_reference)
    snapshot = {
        "schema": "mcri-ai-private-pilot-run-outcome-v1", "run_id": str(run.id),
        "pilot_id": str(run.pilot_id), "processing_job_id": str(run.processing_job_id),
        "task_type": run.task_type, "human_review_action": human_review_action,
        "output_candidate_count": output_candidate_count,
        "human_edit_count": human_edit_count, "latency_ms": latency_ms,
        "observed_provider_cost_microusd": observed_provider_cost_microusd,
        "evidence_reference": reference, "note": note.strip(),
        "authoritative_facts_auto_updated": False, "human_review_completed": True,
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
    _audit(db, user, "REVIEW_AI_PRIVATE_PILOT_RUN", "ai_private_pilot_run", run.id,
           {"pilot_id": str(run.pilot_id), "human_review_action": human_review_action,
            "outcome_hash": run.outcome_hash, "authoritative_facts_auto_updated": False},
           "Mandatory content-free human-review outcome. " + note.strip())
    db.commit()
    pilot = get_pilot(db, user.organization_id, run.pilot_id)
    return pilot_response(db, pilot)


def report_incident(db: Session, user: User, item: AIPrivatePilotAuthorization,
                    *, severity: str, category: str, evidence_reference: str,
                    note: str, confirm_pause: bool) -> dict:
    if not confirm_pause:
        raise HTTPException(422, "Explicit incident pause confirmation is required")
    if not _pilot_active(db, item):
        raise HTTPException(409, "Only an authorized pilot can be paused by an incident")
    reference = _reference(evidence_reference)
    incident = AIPrivatePilotIncident(
        organization_id=user.organization_id, pilot_id=item.id, reported_by_id=user.id,
        severity=severity, category=category, evidence_reference=reference,
        note=note.strip(), status="open", reported_at=datetime.now(UTC),
    )
    db.add(incident); db.flush(); item.status = "paused"; item.outcome = "incident_paused"
    _audit(db, user, "PAUSE_AI_PRIVATE_PILOT_INCIDENT", "ai_private_pilot", item.id,
           {"incident_id": str(incident.id), "severity": severity,
            "category": category, "status": "paused"},
           "Immediate application pause; new provider runs are blocked. " + note.strip())
    db.commit(); db.refresh(item)
    return pilot_response(db, item)


def resolve_incident(db: Session, user: User, item: AIPrivatePilotAuthorization,
                     incident_id: UUID, *, resolution_reference: str,
                     resolution_note: str, resume_pilot: bool,
                     confirm_resolution: bool) -> dict:
    if not confirm_resolution:
        raise HTTPException(422, "Explicit incident resolution confirmation is required")
    incident = db.scalar(select(AIPrivatePilotIncident).where(
        AIPrivatePilotIncident.id == incident_id,
        AIPrivatePilotIncident.pilot_id == item.id,
        AIPrivatePilotIncident.organization_id == user.organization_id,
    ))
    if incident is None:
        raise HTTPException(404, "Private-pilot incident not found")
    if incident.status != "open":
        raise HTTPException(409, "Private-pilot incident is already resolved")
    if resume_pilot and item.status != "paused":
        raise HTTPException(409, "Only an incident-paused pilot can be resumed")
    reference = _reference(resolution_reference)
    incident.status = "resolved"; incident.resolved_by_id = user.id
    incident.resolved_at = datetime.now(UTC); incident.resolution_reference = reference
    incident.resolution_note = resolution_note.strip(); db.flush()
    if resume_pilot:
        remaining = db.scalar(select(AIPrivatePilotIncident.id).where(
            AIPrivatePilotIncident.pilot_id == item.id,
            AIPrivatePilotIncident.status == "open",
        ))
        if remaining is not None:
            raise HTTPException(409, "All pilot incidents must be resolved before resuming")
        if _as_utc(item.expires_at) <= datetime.now(UTC):
            raise HTTPException(409, "The private-pilot window has expired")
        _anchors(db, user.organization_id, item.evaluation_suite_id)
        item.status = "authorized"; item.outcome = "incident_resolved"
    _audit(db, user, "RESOLVE_AI_PRIVATE_PILOT_INCIDENT", "ai_private_pilot", item.id,
           {"incident_id": str(incident.id), "resume_pilot": resume_pilot,
            "status": item.status}, "Admin resolved bounded incident evidence. " + resolution_note.strip())
    db.commit(); db.refresh(item)
    return pilot_response(db, item)


def revoke_pilot(db: Session, user: User, item: AIPrivatePilotAuthorization,
                 confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit private-pilot revocation is required")
    if item.status not in {"authorized", "paused"}:
        raise HTTPException(409, "Only an authorized or paused private pilot can be revoked")
    item.status = "revoked"; item.outcome = "revoked"; item.revoked_by_id = user.id
    item.revoked_at = datetime.now(UTC); item.revocation_note = note.strip()
    _audit(db, user, "REVOKE_AI_PRIVATE_PILOT", "ai_private_pilot", item.id,
           {"status": "revoked", "runtime_allowed": False},
           "Immediate private-pilot kill switch. " + note.strip())
    db.commit(); db.refresh(item)
    return pilot_response(db, item)


def complete_pilot(db: Session, user: User, item: AIPrivatePilotAuthorization,
                   confirm: bool, note: str) -> dict:
    if not confirm:
        raise HTTPException(422, "Explicit private-pilot completion is required")
    if item.status not in {"authorized", "paused"}:
        raise HTTPException(409, "Only an authorized or paused pilot can be completed")
    runs = _runs(db, item.id); incidents = _incidents(db, item.id)
    if not runs or any(run.status != "human_reviewed" for run in runs):
        raise HTTPException(409, "Every pilot run must have a recorded human-review outcome")
    if any(incident.status == "open" for incident in incidents):
        raise HTTPException(409, "All pilot incidents must be resolved before completion")
    item.status = "completed"; item.outcome = "completed"
    item.finalized_by_id = user.id; item.completed_at = datetime.now(UTC)
    item.completion_note = note.strip()
    _audit(db, user, "COMPLETE_AI_PRIVATE_PILOT", "ai_private_pilot", item.id,
           {"status": "completed", "provider_run_count": len(runs),
            "human_reviewed_run_count": len(runs), "production_wide_authorized": False},
           "Bounded pilot completed; any production-AI decision remains separate. " + note.strip())
    db.commit(); db.refresh(item)
    return pilot_response(db, item)
