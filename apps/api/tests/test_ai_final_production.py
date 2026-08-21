from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.security import hash_password
from app.modules import ai_runtime
from app.modules.ai_final_production.models import AIFinalProductionAuthorization
from app.modules.ai_final_production_readiness.models import AIFinalProductionReadinessAssessment
from app.modules.ai_high_coverage.models import AIHighCoverageAuthorization
from app.modules.ai_high_coverage_outcomes.models import AIHighCoverageOutcomeAssessment
from app.modules.documents.models import Document
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_ai_final_production_readiness import _positive_11l
from tests.test_claims_api import TEST_PASSWORD, login


def setup_function() -> None:
    reset_database()


def _add_11n_users() -> None:
    with TestingSessionLocal() as db:
        alpha = db.scalar(select(Organization).where(Organization.slug == "alpha"))
        assert alpha is not None
        for email, name in [
            ("alpha-privacy-11n@example.com", "Alpha 11N Privacy Reviewer"),
            ("alpha-legal-11n@example.com", "Alpha 11N Legal Data Reviewer"),
            ("alpha-business-owner-11n@example.com", "Alpha 11N Business Owner"),
        ]:
            if db.scalar(select(User).where(User.email == email)) is None:
                db.add(User(
                    organization_id=alpha.id,
                    email=email,
                    full_name=name,
                    password_hash=hash_password(TEST_PASSWORD),
                    role=UserRole.CLAIMS_MANAGER,
                    is_active=True,
                ))
        db.commit()


def _positive_11m() -> dict:
    anchor = _positive_11l()
    _add_11n_users()
    with TestingSessionLocal() as db:
        outcome = db.scalar(select(AIHighCoverageOutcomeAssessment).where(
            AIHighCoverageOutcomeAssessment.id == UUID(anchor["id"])))
        high = db.scalar(select(AIHighCoverageAuthorization).where(
            AIHighCoverageAuthorization.id == UUID(anchor["authorization_id"])))
        manager = db.scalar(select(User).where(User.email == "alpha-manager@example.com"))
        assert outcome is not None and high is not None and manager is not None
        readiness = AIFinalProductionReadinessAssessment(
            organization_id=high.organization_id,
            high_coverage_outcome_assessment_id=outcome.id,
            requested_by_id=manager.id,
            finalized_by_id=manager.id,
            attempt_number=1,
            assessment_key=f"11n-positive-11m-{uuid4()}",
            assessment_profile="final_production_ai_readiness_v1",
            high_coverage_outcome_assessment_hash=outcome.assessment_hash,
            high_coverage_outcome_decision_hash=outcome.decision_hash,
            high_coverage_decision_hash=high.decision_hash,
            high_coverage_completion_hash=high.completion_hash,
            broader_outcome_assessment_hash=outcome.broader_outcome_assessment_hash,
            broader_outcome_decision_hash=outcome.broader_outcome_decision_hash,
            broader_production_decision_hash=outcome.broader_production_decision_hash,
            readiness_assessment_hash=outcome.readiness_assessment_hash,
            readiness_decision_hash=outcome.readiness_decision_hash,
            scale_up_decision_hash=outcome.scale_up_decision_hash,
            inherited_outcome_assessment_hash=outcome.inherited_outcome_assessment_hash,
            inherited_outcome_decision_hash=outcome.inherited_outcome_decision_hash,
            model=high.model,
            prompt_bundle_version=high.prompt_bundle_version,
            schema_bundle_version=high.schema_bundle_version,
            rollout_percentage=high.rollout_percentage,
            status="recommended",
            outcome="recommend_separate_final_production_authorization",
            metrics={
                "overall_pass": True,
                "technical": {"overall_pass": True},
                "business_value": {"claim_workflow_count": 10, "overall_pass": True},
                "enterprise_controls": {"pass_rate_bps": 10000, "overall_pass": True},
            },
            failure_reasons=[],
            assessment_note="Sprint 11M technical, business-value and enterprise controls passed.",
            assessment_hash="1" * 64,
            assessed_at=datetime.now(UTC),
            decision_note="Recommend only a separate bounded final Production authorization.",
            decision_hash="2" * 64,
            decided_at=datetime.now(UTC),
        )
        db.add(readiness)
        db.commit()
        db.refresh(readiness)
        return {"id": str(readiness.id), "high_id": str(high.id)}


def _payload(readiness_id: str, **overrides) -> dict:
    payload = {
        "readiness_assessment_id": readiness_id,
        "authorization_key": f"final-production-{uuid4()}",
        "allowed_document_types": ["chief_engineer_report", "engine_log"],
        "rollout_percentage": 80,
        "max_claims": 50,
        "max_documents": 150,
        "max_users": 50,
        "max_provider_runs": 750,
        "starts_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
        "deployment_isolation_reference": "artifact://ai-final-production/deployment-isolation",
        "provider_project_reference": "artifact://ai-final-production/provider-project",
        "credential_control_reference": "artifact://ai-final-production/credential-control",
        "privacy_legal_reference": "artifact://ai-final-production/privacy-legal",
        "monitoring_reference": "monitor://ai-final-production/live-controls",
        "incident_response_reference": "runbook://ai-final-production/incident-response",
        "rollback_reference": "runbook://ai-final-production/rollback-15-minutes",
        "change_ticket_reference": "ticket://ai-final-production/change-001",
        "confirm_separate_final_production": True,
    }
    payload.update(overrides)
    return payload


def _create_authorization(readiness_id: str) -> dict:
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    response = client.post("/api/v1/ai-final-production/authorizations", json=_payload(readiness_id))
    assert response.status_code == 201, response.text
    return response.json()


def test_11n_requires_positive_11m_nine_reviewers_and_separate_admin() -> None:
    readiness = _positive_11m()
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")

    above_90 = client.post(
        "/api/v1/ai-final-production/authorizations",
        json=_payload(readiness["id"], rollout_percentage=91),
    )
    assert above_90.status_code == 422

    item = _create_authorization(readiness["id"])
    assert item["previous_rollout_percentage"] == 75
    assert item["rollout_percentage"] == 80
    assert item["summary"]["rollout_above_75_authorized"] is False
    assert item["summary"]["rollout_above_90_authorized"] is False
    assert item["summary"]["production_wide_authorized"] is False
    assert item["summary"]["restricted_documents_authorized"] is False
    assert item["summary"]["autonomous_claim_decisions_authorized"] is False
    assert item["summary"]["different_human_review_required"] is True

    self_review = client.post(
        f"/api/v1/ai-final-production/authorizations/{item['id']}/approvals",
        json={
            "approval_role": "security",
            "action": "approve",
            "evidence_reference": "artifact://ai-final-production/self-review",
            "note": "The requester must not approve the Sprint 11N authorization.",
        },
    )
    assert self_review.status_code == 409

    reviewers = [
        ("alpha-security@example.com", "security"),
        ("alpha-privacy-11n@example.com", "privacy"),
        ("alpha-product@example.com", "product"),
        ("alpha-operations@example.com", "operations"),
        ("alpha-risk@example.com", "risk"),
        ("alpha-governance@example.com", "claims_governance"),
        ("alpha-ai-quality@example.com", "ai_quality"),
        ("alpha-legal-11n@example.com", "legal_data_governance"),
        ("alpha-business-owner-11n@example.com", "business_owner"),
    ]
    for email, role in reviewers:
        client.cookies.clear()
        login("alpha", email)
        approval = client.post(
            f"/api/v1/ai-final-production/authorizations/{item['id']}/approvals",
            json={
                "approval_role": role,
                "action": "approve",
                "evidence_reference": f"artifact://ai-final-production/{role}-approval",
                "note": f"Independent {role} reviewer verified the bounded Sprint 11N controls.",
            },
        )
        assert approval.status_code == 200, approval.text
    assert approval.json()["status"] == "decision_ready"

    client.cookies.clear()
    login("alpha", "alpha-11k-admin@example.com")
    decided = client.post(
        f"/api/v1/ai-final-production/authorizations/{item['id']}/decision",
        json={
            "outcome": "authorize_final_production_cohort",
            "confirm_decision": True,
            "note": "Authorize only this exact expiring 80-percent Sprint 11N cohort.",
        },
    )
    assert decided.status_code == 200, decided.text
    result = decided.json()
    assert result["status"] == "authorized"
    assert len(result["decision_hash"]) == 64
    assert result["summary"]["rollout_above_75_authorized"] is True
    assert result["summary"]["rollout_above_90_authorized"] is False
    assert result["summary"]["production_wide_authorized"] is False
    assert result["summary"]["restricted_documents_authorized"] is False
    assert result["summary"]["new_document_classes_authorized"] is False
    assert result["summary"]["autonomous_claim_decisions_authorized"] is False
    assert result["summary"]["authoritative_facts_auto_updated"] is False


def test_11n_attempt_blocks_runtime_fallback_to_11k_when_inactive(monkeypatch) -> None:
    readiness = _positive_11m()
    item = _create_authorization(readiness["id"])
    assert item["status"] == "pending_approvals"

    monkeypatch.setattr(ai_runtime, "get_settings", lambda: SimpleNamespace(app_env="production"))
    with TestingSessionLocal() as db:
        authorization = db.scalar(select(AIFinalProductionAuthorization).where(
            AIFinalProductionAuthorization.id == UUID(item["id"])))
        document = db.scalar(select(Document).where(
            Document.organization_id == authorization.organization_id,
            Document.document_type.in_(["chief_engineer_report", "engine_log"]),
        ))
        manager = db.scalar(select(User).where(User.email == "alpha-manager@example.com"))
        assert authorization is not None and document is not None and manager is not None
        with pytest.raises(HTTPException) as exc:
            ai_runtime.require_external_ai_runtime_authorization(
                db,
                organization_id=authorization.organization_id,
                document=document,
                expected_document_type=document.document_type,
                input_char_count=100,
                requested_by_id=manager.id,
            )
        assert exc.value.status_code == 409
        assert "fallback is prohibited" in str(exc.value.detail)
