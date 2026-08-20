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
from app.modules.ai_governance.models import (
    AIDocumentEligibilityAttestation, AIProviderActivationApproval,
    AIProviderActivationRequest,
)
from app.modules.ai_governance.schemas import (
    AIDocumentEligibilityCreate, AIProviderActivationCreate,
)
from app.modules.audit.service import write_audit_log
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.users.models import User

SUPPORTED_DOCUMENT_TYPES = {
    "chief_engineer_report", "engine_log", "running_hours_record", "pms_record",
    "workshop_report", "quotation", "invoice",
}
APPROVAL_ROLES = {"security", "privacy", "product"}
BOUNDED_REFERENCE = re.compile(r"^(artifact|runbook|ticket|monitor)://[A-Za-z0-9._:/-]{3,450}$")


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _audit(db: Session, user: User, action: str, kind: str, entity_id: UUID,
           values: dict, details: str) -> None:
    write_audit_log(db, organization_id=user.organization_id, user_id=user.id,
                    action=action, entity_type=kind, entity_id=entity_id,
                    new_values=values, details=details)


def _approvals(db: Session, request_id: UUID) -> list[AIProviderActivationApproval]:
    return list(db.scalars(select(AIProviderActivationApproval).where(
        AIProviderActivationApproval.activation_request_id == request_id
    ).order_by(AIProviderActivationApproval.approval_role.asc())))


def _active(item: AIProviderActivationRequest) -> bool:
    return item.status == "staging_authorized" and _as_utc(item.evaluation_expires_at) > datetime.now(UTC)


def activation_response(db: Session, item: AIProviderActivationRequest) -> dict:
    approvals = _approvals(db, item.id)
    by_role = {approval.approval_role: approval for approval in approvals}
    independent = bool(
        set(by_role) == APPROVAL_ROLES
        and all(approval.action == "approve" for approval in by_role.values())
        and len({approval.approver_id for approval in by_role.values()}) == 3
        and all(approval.approver_id != item.requested_by_id for approval in by_role.values())
    )
    return {
        "id": item.id, "requested_by_id": item.requested_by_id,
        "finalized_by_id": item.finalized_by_id, "revoked_by_id": item.revoked_by_id,
        "attempt_number": item.attempt_number, "request_key": item.request_key,
        "environment": item.environment, "provider": item.provider,
        "provider_project_label": item.provider_project_label, "model": item.model,
        "prompt_bundle_version": item.prompt_bundle_version,
        "schema_bundle_version": item.schema_bundle_version, "data_mode": item.data_mode,
        "allowed_document_types": item.allowed_document_types,
        "restricted_documents_allowed": item.restricted_documents_allowed,
        "credential_storage_mode": item.credential_storage_mode,
        "max_input_chars": item.max_input_chars,
        "max_output_tokens": item.max_output_tokens,
        "requests_per_minute": item.requests_per_minute,
        "tokens_per_minute": item.tokens_per_minute,
        "monthly_spend_limit_cents": item.monthly_spend_limit_cents,
        "spend_alert_thresholds": item.spend_alert_thresholds,
        "retention_mode": item.retention_mode,
        "data_residency_region": item.data_residency_region,
        "security_owner_label": item.security_owner_label,
        "privacy_owner_label": item.privacy_owner_label,
        "product_owner_label": item.product_owner_label,
        "incident_owner_label": item.incident_owner_label,
        "kill_switch_owner_label": item.kill_switch_owner_label,
        "credential_control_reference": item.credential_control_reference,
        "spend_limit_reference": item.spend_limit_reference,
        "data_processing_reference": item.data_processing_reference,
        "kill_switch_reference": item.kill_switch_reference,
        "evaluation_expires_at": item.evaluation_expires_at,
        "status": item.status, "outcome": item.outcome,
        "decision_note": item.decision_note, "decision_hash": item.decision_hash,
        "decided_at": item.decided_at, "revoked_at": item.revoked_at,
        "revocation_note": item.revocation_note, "approvals": approvals,
        "created_at": item.created_at,
        "summary": {
            "required_approval_count": len(APPROVAL_ROLES),
            "approval_count": sum(approval.action == "approve" for approval in approvals),
            "independent_approvals_complete": independent,
            "staging_evaluation_authorized": item.status == "staging_authorized",
            "authorization_active": _active(item),
            "provider_configuration_mutated": False,
            "production_authorized": False,
            "restricted_documents_authorized": False,
            "real_claim_data_authorized": False,
            "human_review_required": True,
            "key_material_stored": False,
        },
    }


def list_activation_requests(db: Session, organization_id: UUID) -> list[dict]:
    items = list(db.scalars(select(AIProviderActivationRequest).where(
        AIProviderActivationRequest.organization_id == organization_id
    ).order_by(AIProviderActivationRequest.created_at.desc()).limit(25)))
    return [activation_response(db, item) for item in items]


def get_activation_request(db: Session, organization_id: UUID,
                           item_id: UUID) -> AIProviderActivationRequest:
    item = db.scalar(select(AIProviderActivationRequest).where(
        AIProviderActivationRequest.id == item_id,
        AIProviderActivationRequest.organization_id == organization_id,
    ))
    if item is None: raise HTTPException(404, "AI provider activation request not found")
    return item


def create_activation_request(db: Session, user: User,
                              payload: AIProviderActivationCreate) -> dict:
    if payload.evaluation_expires_at.tzinfo is None or payload.evaluation_expires_at.utcoffset() is None:
        raise HTTPException(422, "Evaluation expiry must include a timezone")
    expiry = payload.evaluation_expires_at.astimezone(UTC)
    now = datetime.now(UTC)
    if expiry <= now or expiry - now > timedelta(days=90):
        raise HTTPException(422, "Evaluation authorization must expire within 90 days")
    allowed = list(dict.fromkeys(payload.allowed_document_types))
    if len(allowed) != len(payload.allowed_document_types) or not set(allowed) <= SUPPORTED_DOCUMENT_TYPES:
        raise HTTPException(422, "Document allowlist contains duplicate or unsupported values")
    if payload.restricted_documents_allowed:
        raise HTTPException(422, "Sprint 11A cannot authorize restricted documents")
    alerts = payload.spend_alert_thresholds
    if alerts != sorted(set(alerts)) or any(value <= 0 or value >= 100 for value in alerts):
        raise HTTPException(422, "Spend-alert thresholds must be unique ascending percentages below 100")
    references = [payload.credential_control_reference, payload.spend_limit_reference,
                  payload.data_processing_reference, payload.kill_switch_reference]
    if any(not BOUNDED_REFERENCE.fullmatch(reference.strip()) for reference in references):
        raise HTTPException(422, "Governance evidence must use bounded allowlisted references")
    attempts = list(db.scalars(select(AIProviderActivationRequest).where(
        AIProviderActivationRequest.organization_id == user.organization_id,
        AIProviderActivationRequest.environment == payload.environment,
        AIProviderActivationRequest.provider == payload.provider,
    ).order_by(AIProviderActivationRequest.attempt_number.asc())))
    if attempts and attempts[-1].status not in {"rejected", "held", "revoked"}:
        if not (attempts[-1].status == "staging_authorized"
                and _as_utc(attempts[-1].evaluation_expires_at) <= now):
            raise HTTPException(409, "A new activation attempt requires rejection, hold, revocation or expiry")
    item = AIProviderActivationRequest(
        organization_id=user.organization_id, requested_by_id=user.id,
        attempt_number=len(attempts) + 1, request_key=payload.request_key.strip(),
        environment=payload.environment, provider=payload.provider,
        provider_project_label=payload.provider_project_label.strip(), model=payload.model.strip(),
        prompt_bundle_version=payload.prompt_bundle_version.strip(),
        schema_bundle_version=payload.schema_bundle_version.strip(), data_mode=payload.data_mode,
        allowed_document_types=allowed, restricted_documents_allowed=False,
        credential_storage_mode=payload.credential_storage_mode,
        max_input_chars=payload.max_input_chars, max_output_tokens=payload.max_output_tokens,
        requests_per_minute=payload.requests_per_minute,
        tokens_per_minute=payload.tokens_per_minute,
        monthly_spend_limit_cents=payload.monthly_spend_limit_cents,
        spend_alert_thresholds=alerts, retention_mode=payload.retention_mode,
        data_residency_region=payload.data_residency_region.strip(),
        security_owner_label=payload.security_owner_label.strip(),
        privacy_owner_label=payload.privacy_owner_label.strip(),
        product_owner_label=payload.product_owner_label.strip(),
        incident_owner_label=payload.incident_owner_label.strip(),
        kill_switch_owner_label=payload.kill_switch_owner_label.strip(),
        credential_control_reference=payload.credential_control_reference.strip(),
        spend_limit_reference=payload.spend_limit_reference.strip(),
        data_processing_reference=payload.data_processing_reference.strip(),
        kill_switch_reference=payload.kill_switch_reference.strip(),
        evaluation_expires_at=expiry, status="pending_approvals",
    )
    db.add(item)
    try: db.flush()
    except IntegrityError as exc:
        db.rollback(); raise HTTPException(409, "This activation key or attempt already exists") from exc
    _audit(db, user, "CREATE_AI_PROVIDER_ACTIVATION_REQUEST", "ai_provider_activation_request",
           item.id, {"environment": item.environment, "provider": item.provider,
                     "provider_project_label": item.provider_project_label, "model": item.model,
                     "allowed_document_types": allowed, "restricted_documents_allowed": False,
                     "credential_storage_mode": item.credential_storage_mode,
                     "monthly_spend_limit_cents": item.monthly_spend_limit_cents,
                     "evaluation_expires_at": expiry.isoformat(), "key_material_stored": False},
           "Governance declaration only; no key, provider configuration or external request stored.")
    db.commit(); db.refresh(item); return activation_response(db, item)


def record_activation_approval(db: Session, user: User, item: AIProviderActivationRequest,
                               approval_role: str, action: str,
                               evidence_reference: str | None, note: str) -> dict:
    if item.status not in {"pending_approvals", "decision_ready"}:
        raise HTTPException(409, "This activation attempt is immutable")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The requester cannot approve this activation")
    approvals = _approvals(db, item.id)
    if any(approval.approval_role == approval_role for approval in approvals):
        raise HTTPException(409, "This approval role already has a decision")
    if any(approval.approver_id == user.id for approval in approvals):
        raise HTTPException(409, "Security, privacy and product require different approvers")
    reference = evidence_reference.strip() if evidence_reference else None
    if action == "approve" and not reference:
        raise HTTPException(422, "Approval requires a bounded review reference")
    if reference and not BOUNDED_REFERENCE.fullmatch(reference):
        raise HTTPException(422, "Approval evidence must use a bounded allowlisted reference")
    approval = AIProviderActivationApproval(
        organization_id=user.organization_id, activation_request_id=item.id,
        approver_id=user.id, approval_role=approval_role, action=action,
        evidence_reference=reference, note=note.strip(), approved_at=datetime.now(UTC),
    )
    db.add(approval); db.flush()
    if action == "reject":
        item.status = "rejected"; item.outcome = "reject"; item.decision_note = note.strip()
        item.finalized_by_id = user.id; item.decided_at = datetime.now(UTC)
    else:
        current = _approvals(db, item.id)
        item.status = "decision_ready" if (
            {entry.approval_role for entry in current} == APPROVAL_ROLES
            and all(entry.action == "approve" for entry in current)
            and len({entry.approver_id for entry in current}) == 3
        ) else "pending_approvals"
    _audit(db, user, f"{action.upper()}_AI_PROVIDER_ACTIVATION", "ai_provider_activation_request",
           item.id, {"approval_role": approval_role, "action": action,
                     "evidence_reference": reference, "status": item.status},
           "Independent human AI-governance review. " + note.strip())
    db.commit(); db.refresh(item); return activation_response(db, item)


def decide_activation_request(db: Session, user: User, item: AIProviderActivationRequest,
                              outcome: str, confirm: bool, note: str) -> dict:
    if not confirm: raise HTTPException(422, "Explicit activation decision confirmation is required")
    if item.status != "decision_ready":
        raise HTTPException(409, "Three independent approvals are required")
    if item.requested_by_id == user.id:
        raise HTTPException(409, "The requester cannot issue final authorization")
    approvals = _approvals(db, item.id)
    if len(approvals) != 3 or len({approval.approver_id for approval in approvals}) != 3:
        raise HTTPException(409, "Security, privacy and product approvals must be independent")
    if outcome == "authorize_staging" and _as_utc(item.evaluation_expires_at) <= datetime.now(UTC):
        raise HTTPException(409, "The requested evaluation period has expired")
    snapshot = {
        "schema": "mcri-ai-provider-activation-v1", "request_id": str(item.id),
        "attempt_number": item.attempt_number, "environment": item.environment,
        "provider": item.provider, "provider_project_label": item.provider_project_label,
        "model": item.model, "prompt_bundle_version": item.prompt_bundle_version,
        "schema_bundle_version": item.schema_bundle_version, "data_mode": item.data_mode,
        "allowed_document_types": sorted(item.allowed_document_types),
        "restricted_documents_allowed": False,
        "credential_storage_mode": item.credential_storage_mode,
        "limits": {"max_input_chars": item.max_input_chars,
                   "max_output_tokens": item.max_output_tokens,
                   "requests_per_minute": item.requests_per_minute,
                   "tokens_per_minute": item.tokens_per_minute,
                   "monthly_spend_limit_cents": item.monthly_spend_limit_cents,
                   "spend_alert_thresholds": item.spend_alert_thresholds},
        "retention_mode": item.retention_mode,
        "data_residency_region": item.data_residency_region,
        "owners": {"security": item.security_owner_label, "privacy": item.privacy_owner_label,
                   "product": item.product_owner_label, "incident": item.incident_owner_label,
                   "kill_switch": item.kill_switch_owner_label},
        "references": {"credential_control": item.credential_control_reference,
                       "spend_limit": item.spend_limit_reference,
                       "data_processing": item.data_processing_reference,
                       "kill_switch": item.kill_switch_reference},
        "evaluation_expires_at": _as_utc(item.evaluation_expires_at).isoformat(),
        "approvals": [{"role": approval.approval_role,
                       "approver_id": str(approval.approver_id),
                       "evidence_reference": approval.evidence_reference,
                       "note": approval.note} for approval in approvals],
        "outcome": outcome, "decision_note": note.strip(),
        "provider_configuration_mutated": False, "production_authorized": False,
        "restricted_documents_authorized": False, "real_claim_data_authorized": False,
        "human_review_required": True, "key_material_stored": False,
    }
    item.status = "staging_authorized" if outcome == "authorize_staging" else "held"
    item.outcome = outcome; item.decision_note = note.strip(); item.finalized_by_id = user.id
    item.decision_hash = sha256(json.dumps(snapshot, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
    item.decided_at = datetime.now(UTC)
    _audit(db, user, f"{outcome.upper()}_AI_PROVIDER_ACTIVATION",
           "ai_provider_activation_request", item.id,
           {"status": item.status, "decision_hash": item.decision_hash,
            "evaluation_expires_at": _as_utc(item.evaluation_expires_at).isoformat(),
            "provider_configuration_mutated": False, "production_authorized": False,
            "restricted_documents_authorized": False, "key_material_stored": False},
           "Bounded staging authorization record only; no external provider mutation. " + note.strip())
    db.commit(); db.refresh(item); return activation_response(db, item)


def revoke_activation_request(db: Session, user: User, item: AIProviderActivationRequest,
                              confirm: bool, note: str) -> dict:
    if not confirm: raise HTTPException(422, "Explicit kill-switch confirmation is required")
    if item.status != "staging_authorized":
        raise HTTPException(409, "Only an authorized staging activation can be revoked")
    item.status = "revoked"; item.revoked_by_id = user.id
    item.revoked_at = datetime.now(UTC); item.revocation_note = note.strip()
    _audit(db, user, "REVOKE_AI_PROVIDER_ACTIVATION", "ai_provider_activation_request",
           item.id, {"status": item.status, "runtime_allowed": False},
           "Immediate application kill-switch record; subsequent external AI queueing is blocked. "
           + note.strip())
    db.commit(); db.refresh(item); return activation_response(db, item)


def list_document_eligibility(db: Session, organization_id: UUID) -> list[AIDocumentEligibilityAttestation]:
    return list(db.scalars(select(AIDocumentEligibilityAttestation).where(
        AIDocumentEligibilityAttestation.organization_id == organization_id
    ).order_by(AIDocumentEligibilityAttestation.created_at.desc()).limit(50)))


def get_document_eligibility(db: Session, organization_id: UUID,
                             item_id: UUID) -> AIDocumentEligibilityAttestation:
    item = db.scalar(select(AIDocumentEligibilityAttestation).where(
        AIDocumentEligibilityAttestation.id == item_id,
        AIDocumentEligibilityAttestation.organization_id == organization_id,
    ))
    if item is None: raise HTTPException(404, "AI document eligibility attestation not found")
    return item


def attest_document_eligibility(db: Session, user: User,
                                payload: AIDocumentEligibilityCreate) -> AIDocumentEligibilityAttestation:
    if not payload.confirm_eligible:
        raise HTTPException(422, "Explicit document eligibility confirmation is required")
    activation = get_activation_request(db, user.organization_id, payload.activation_request_id)
    if not _active(activation):
        raise HTTPException(409, "An active staging AI authorization is required")
    document = db.scalar(select(Document).where(
        Document.id == payload.document_id, Document.claim_id == payload.claim_id,
        Document.organization_id == user.organization_id, Document.deleted_at.is_(None),
    ))
    if document is None: raise HTTPException(404, "Document not found")
    confidentiality = (document.confidentiality_level.value
                       if hasattr(document.confidentiality_level, "value")
                       else str(document.confidentiality_level))
    if confidentiality == ConfidentialityLevel.RESTRICTED.value:
        raise HTTPException(409, "Restricted documents cannot be attested in Sprint 11A")
    if not document.document_type or document.document_type not in activation.allowed_document_types:
        raise HTTPException(409, "Document type is not in the active AI allowlist")
    reference = payload.evidence_reference.strip()
    if not BOUNDED_REFERENCE.fullmatch(reference):
        raise HTTPException(422, "Eligibility evidence must use a bounded allowlisted reference")
    attempts = list(db.scalars(select(AIDocumentEligibilityAttestation).where(
        AIDocumentEligibilityAttestation.document_id == document.id
    ).order_by(AIDocumentEligibilityAttestation.attestation_number.asc())))
    if attempts and attempts[-1].status == "eligible":
        raise HTTPException(409, "This document already has an active eligibility attestation")
    snapshot = {
        "schema": "mcri-ai-document-eligibility-v1",
        "activation_request_id": str(activation.id), "claim_id": str(document.claim_id),
        "document_id": str(document.id), "file_hash": document.file_hash,
        "document_type": document.document_type, "confidentiality_level": confidentiality,
        "data_mode": payload.data_mode, "evidence_reference": reference,
        "restricted_document": False, "real_claim_authorization": False,
    }
    item = AIDocumentEligibilityAttestation(
        organization_id=user.organization_id, activation_request_id=activation.id,
        claim_id=document.claim_id, document_id=document.id, attested_by_id=user.id,
        attestation_number=len(attempts) + 1, data_mode=payload.data_mode,
        document_type=document.document_type, confidentiality_level=confidentiality,
        evidence_reference=reference, note=payload.note.strip(),
        snapshot_hash=sha256(json.dumps(snapshot, sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest(),
        status="eligible", attested_at=datetime.now(UTC),
    )
    db.add(item); db.flush()
    _audit(db, user, "ATTEST_AI_DOCUMENT_ELIGIBILITY", "ai_document_eligibility", item.id,
           {"activation_request_id": str(activation.id), "document_id": str(document.id),
            "document_type": item.document_type, "data_mode": item.data_mode,
            "confidentiality_level": confidentiality, "snapshot_hash": item.snapshot_hash,
            "real_claim_authorization": False},
           "Manager/Admin synthetic or de-identified staging attestation; no document content stored.")
    db.commit(); db.refresh(item); return item


def revoke_document_eligibility(db: Session, user: User,
                                item: AIDocumentEligibilityAttestation,
                                confirm: bool, note: str) -> AIDocumentEligibilityAttestation:
    if not confirm: raise HTTPException(422, "Explicit eligibility revocation is required")
    if item.status != "eligible": raise HTTPException(409, "Eligibility is already inactive")
    item.status = "revoked"; item.revoked_by_id = user.id
    item.revoked_at = datetime.now(UTC); item.revocation_note = note.strip()
    _audit(db, user, "REVOKE_AI_DOCUMENT_ELIGIBILITY", "ai_document_eligibility", item.id,
           {"status": item.status, "document_id": str(item.document_id)},
           "Document-level external AI eligibility revoked. " + note.strip())
    db.commit(); db.refresh(item); return item


def require_external_ai_runtime_authorization(
    db: Session, *, organization_id: UUID, document: Document,
    expected_document_type: str, input_char_count: int,
    requested_by_id: UUID | None = None,
) -> object:
    settings = get_settings()
    if settings.app_env.lower().strip() == "production":
        from app.modules.ai_limited_production.service import (
            require_limited_production_runtime_authorization,
        )

        authorization, _ = require_limited_production_runtime_authorization(
            db, organization_id=organization_id, document=document,
            expected_document_type=expected_document_type,
            input_char_count=input_char_count, requested_by_id=requested_by_id,
        )
        return authorization
    if settings.app_env.lower().strip() != "staging":
        raise HTTPException(
            409, "External AI requires a separately authorized staging or production evaluation")
    item = db.scalar(select(AIProviderActivationRequest).where(
        AIProviderActivationRequest.organization_id == organization_id,
        AIProviderActivationRequest.environment == "staging",
        AIProviderActivationRequest.provider == "openai",
        AIProviderActivationRequest.status == "staging_authorized",
    ).order_by(AIProviderActivationRequest.attempt_number.desc()))
    if item is None or not _active(item):
        raise HTTPException(409, "No active external AI staging authorization exists")
    if item.model != settings.ai_model:
        raise HTTPException(409, "Configured AI model differs from the authorized pinned model")
    if item.prompt_bundle_version != settings.ai_prompt_bundle_version:
        raise HTTPException(409, "Configured prompt bundle differs from the authorized version")
    if item.schema_bundle_version != settings.ai_schema_bundle_version:
        raise HTTPException(409, "Configured schema bundle differs from the authorized version")
    if item.max_output_tokens != settings.ai_max_output_tokens:
        raise HTTPException(409, "Configured output-token cap differs from the authorized limit")
    confidentiality = (document.confidentiality_level.value
                       if hasattr(document.confidentiality_level, "value")
                       else str(document.confidentiality_level))
    if confidentiality == ConfidentialityLevel.RESTRICTED.value:
        raise HTTPException(409, "Restricted documents are not authorized for external AI")
    if (expected_document_type not in item.allowed_document_types
            or document.document_type != expected_document_type):
        raise HTTPException(409, "Document type is not authorized for this AI task")
    if input_char_count > item.max_input_chars:
        raise HTTPException(409, "Document exceeds the authorized external AI input limit")
    eligibility = db.scalar(select(AIDocumentEligibilityAttestation).where(
        AIDocumentEligibilityAttestation.organization_id == organization_id,
        AIDocumentEligibilityAttestation.document_id == document.id,
        AIDocumentEligibilityAttestation.activation_request_id == item.id,
        AIDocumentEligibilityAttestation.status == "eligible",
    ).order_by(AIDocumentEligibilityAttestation.attestation_number.desc()))
    if eligibility is None:
        # Sprint 11C is a separate, narrower authorization path for real but
        # non-restricted documents. Import locally to keep the two control
        # planes independently testable and avoid a module import cycle.
        from app.modules.ai_private_pilot.models import AIPrivatePilotDocumentEligibility
        from app.modules.ai_private_pilot.service import require_private_pilot_runtime_authorization

        pilot_eligibility = db.scalar(select(AIPrivatePilotDocumentEligibility.id).where(
            AIPrivatePilotDocumentEligibility.organization_id == organization_id,
            AIPrivatePilotDocumentEligibility.document_id == document.id,
            AIPrivatePilotDocumentEligibility.status == "eligible",
        ))
        if pilot_eligibility is None:
            raise HTTPException(
                409, "Document requires a current synthetic/de-identified eligibility attestation")
        require_private_pilot_runtime_authorization(
            db, organization_id=organization_id, document=document,
            expected_document_type=expected_document_type,
            input_char_count=input_char_count, requested_by_id=requested_by_id,
        )
    return item
