from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.security import hash_password
from app.modules import ai_runtime
from app.modules.ai_bounded_full_production.models import AIBoundedFullProductionAuthorization
from app.modules.ai_bounded_full_production_outcomes.models import AIBoundedFullProductionOutcomeAssessment
from app.modules.ai_production_wide.models import AIProductionWideAuthorization
from app.modules.documents.models import Document
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_ai_bounded_full_production_outcomes import REVIEWERS as REVIEWERS_11S, _completed_11r
from tests.test_ai_bounded_full_production import FINAL_ADMIN
from tests.test_claims_api import TEST_PASSWORD, login


def setup_function() -> None:
    reset_database()


REVIEWERS = REVIEWERS_11S + [
    ("alpha-11t-internal-audit@example.com", "internal_audit_model_risk"),
]


def _positive_11s() -> dict:
    anchor = _completed_11r()
    with TestingSessionLocal() as db:
        bounded = db.scalar(select(AIBoundedFullProductionAuthorization).where(
            AIBoundedFullProductionAuthorization.id == UUID(anchor["id"])
        ))
        alpha = db.scalar(select(Organization).where(Organization.slug == "alpha"))
        manager = db.scalar(select(User).where(User.email == "alpha-manager@example.com"))
        assert bounded is not None and alpha is not None and manager is not None
        for email, role in REVIEWERS:
            if db.scalar(select(User).where(User.email == email)) is None:
                db.add(User(
                    organization_id=alpha.id, email=email,
                    full_name=f"Sprint 11T {role.replace('_', ' ').title()} Reviewer",
                    password_hash=hash_password(TEST_PASSWORD), role=UserRole.CLAIMS_MANAGER, is_active=True,
                ))
        assessment = AIBoundedFullProductionOutcomeAssessment(
            organization_id=bounded.organization_id,
            bounded_full_authorization_id=bounded.id,
            near_universal_outcome_assessment_id=bounded.near_universal_outcome_assessment_id,
            requested_by_id=manager.id, finalized_by_id=manager.id, attempt_number=1,
            assessment_key=f"11t-positive-11s-{uuid4()}", assessment_profile="bounded_full_outcome_v1",
            bounded_full_decision_hash=bounded.decision_hash, bounded_full_completion_hash=bounded.completion_hash,
            near_universal_outcome_assessment_hash=bounded.near_universal_outcome_assessment_hash,
            near_universal_outcome_decision_hash=bounded.near_universal_outcome_decision_hash,
            near_universal_decision_hash=bounded.near_universal_decision_hash,
            near_universal_completion_hash=bounded.near_universal_completion_hash,
            model=bounded.model, prompt_bundle_version=bounded.prompt_bundle_version,
            schema_bundle_version=bounded.schema_bundle_version, max_input_chars=bounded.max_input_chars,
            max_output_tokens=bounded.max_output_tokens, allowed_document_types=list(bounded.allowed_document_types),
            rollout_percentage=100, max_claims=bounded.max_claims, max_documents=bounded.max_documents,
            max_users=bounded.max_users, max_provider_runs=bounded.max_provider_runs,
            status="recommended", outcome="recommend_separate_production_wide_authorization_review",
            metrics={"overall_pass": True, "source_ledger_revalidated": True,
                     "enterprise_readiness": {"all_required_categories_present": True, "all_controls_passing": True},
                     "business_value": {"workflow_count": 15}}, failure_reasons=[],
            assessment_note="Sprint 11S passed technical, business and enterprise readiness controls.",
            assessment_hash="a" * 64, assessed_at=datetime.now(UTC),
            decision_note="Recommend a separate Production-wide human-reviewed authorization review.",
            decision_hash="b" * 64, decided_at=datetime.now(UTC),
        )
        db.add(assessment); db.commit(); db.refresh(assessment)
        return {"id": str(assessment.id)}


def _payload(assessment_id: str, **overrides) -> dict:
    payload = {
        "bounded_full_outcome_assessment_id": assessment_id,
        "authorization_key": f"production-wide-{uuid4()}",
        "allowed_document_types": ["chief_engineer_report", "engine_log"],
        "starts_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(days=89)).isoformat(),
        "eligibility_policy_version": "production-eligibility-v1",
        "eligibility_policy_reference": "policy://ai-production-wide/eligibility-v1",
        "legal_basis_policy_reference": "policy://ai-production-wide/legal-basis-v1",
        "data_minimization_policy_reference": "policy://ai-production-wide/data-minimization-v1",
        "deployment_isolation_reference": "artifact://ai-production-wide/deployment-isolation",
        "provider_project_reference": "artifact://ai-production-wide/provider-project",
        "credential_control_reference": "artifact://ai-production-wide/credential-control",
        "monitoring_reference": "monitor://ai-production-wide/live-controls",
        "incident_response_reference": "runbook://ai-production-wide/incidents",
        "rollback_reference": "runbook://ai-production-wide/rollback",
        "model_change_control_reference": "policy://ai-production-wide/model-change",
        "internal_audit_reference": "artifact://ai-production-wide/internal-audit",
        "change_ticket_reference": "ticket://ai-production-wide/authorization",
        "confirm_production_wide_human_reviewed_ai": True,
    }
    payload.update(overrides)
    return payload


def _create(assessment_id: str) -> dict:
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    response = client.post("/api/v1/ai-production-wide/authorizations", json=_payload(assessment_id))
    assert response.status_code == 201, response.text
    return response.json()


def test_11t_requires_positive_11s_fifteen_reviewers_and_preserves_human_boundaries() -> None:
    anchor = _positive_11s()
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    too_long = client.post("/api/v1/ai-production-wide/authorizations", json=_payload(
        anchor["id"], expires_at=(datetime.now(UTC) + timedelta(days=91)).isoformat()))
    assert too_long.status_code == 422

    item = _create(anchor["id"])
    assert item["status"] == "pending_approvals"
    assert item["summary"]["production_wide_human_reviewed_ai_authorized"] is False
    assert item["summary"]["manual_per_document_attestation_required"] is False
    assert item["summary"]["production_eligibility_policy_enforced"] is True
    assert item["summary"]["different_human_review_required"] is True

    self_review = client.post(f"/api/v1/ai-production-wide/authorizations/{item['id']}/approvals", json={
        "approval_role": "security", "action": "approve",
        "evidence_reference": "artifact://ai-production-wide/self-review",
        "note": "Requester must never approve their own Production-wide authorization.",
    })
    assert self_review.status_code == 409

    for email, role in REVIEWERS:
        client.cookies.clear(); login("alpha", email)
        approval = client.post(f"/api/v1/ai-production-wide/authorizations/{item['id']}/approvals", json={
            "approval_role": role, "action": "approve",
            "evidence_reference": f"artifact://ai-production-wide/{role}-approval",
            "note": f"Independent {role} reviewer approved the human-reviewed Production-wide control envelope.",
        })
        assert approval.status_code == 200, approval.text
    assert approval.json()["status"] == "decision_ready"
    assert len(approval.json()["approvals"]) == 15

    client.cookies.clear(); login("alpha", FINAL_ADMIN)
    decided = client.post(f"/api/v1/ai-production-wide/authorizations/{item['id']}/decision", json={
        "outcome": "authorize_production_wide_human_reviewed_ai", "confirm_decision": True,
        "note": "Authorize Production-wide AI only for the exact CE Report and Engine Log scope with mandatory different-human review.",
    })
    assert decided.status_code == 200, decided.text
    result = decided.json()
    assert result["status"] == "authorized"
    assert len(result["decision_hash"]) == 64
    assert result["summary"]["production_wide_human_reviewed_ai_authorized"] is True
    assert result["summary"]["restricted_documents_authorized"] is False
    assert result["summary"]["new_document_classes_authorized"] is False
    assert result["summary"]["autonomous_claim_decisions_authorized"] is False
    assert result["summary"]["authoritative_facts_auto_updated"] is False


def test_11t_attempt_blocks_runtime_fallback_to_11r_when_inactive(monkeypatch) -> None:
    anchor = _positive_11s()
    item = _create(anchor["id"])
    assert item["status"] == "pending_approvals"
    monkeypatch.setattr(ai_runtime, "get_settings", lambda: SimpleNamespace(app_env="production"))
    with TestingSessionLocal() as db:
        authorization = db.scalar(select(AIProductionWideAuthorization).where(AIProductionWideAuthorization.id == UUID(item["id"])))
        document = db.scalar(select(Document).where(
            Document.organization_id == authorization.organization_id,
            Document.document_type.in_(["chief_engineer_report", "engine_log"]),
        )) if authorization else None
        manager = db.scalar(select(User).where(User.email == "alpha-manager@example.com"))
        assert authorization is not None and document is not None and manager is not None
        with pytest.raises(HTTPException) as exc:
            ai_runtime.require_external_ai_runtime_authorization(
                db, organization_id=authorization.organization_id, document=document,
                expected_document_type=document.document_type, input_char_count=100, requested_by_id=manager.id,
            )
        assert exc.value.status_code == 409
        assert "fallback is prohibited" in str(exc.value.detail)
