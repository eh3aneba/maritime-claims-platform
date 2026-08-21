from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.security import hash_password
from app.modules import ai_runtime
from app.modules.ai_final_production.models import AIFinalProductionAuthorization
from app.modules.ai_final_production_outcomes.models import AIFinalProductionOutcomeAssessment
from app.modules.ai_near_universal_production.models import AINearUniversalAuthorization
from app.modules.documents.models import Document
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_ai_final_production_outcomes import _completed_final_production
from tests.test_claims_api import TEST_PASSWORD, login


def setup_function() -> None:
    reset_database()


def _add_11p_sre_user() -> None:
    with TestingSessionLocal() as db:
        alpha = db.scalar(select(Organization).where(Organization.slug == "alpha"))
        assert alpha is not None
        if db.scalar(select(User).where(User.email == "alpha-sre-11p@example.com")) is None:
            db.add(User(
                organization_id=alpha.id,
                email="alpha-sre-11p@example.com",
                full_name="Alpha 11P Platform Reliability Reviewer",
                password_hash=hash_password(TEST_PASSWORD),
                role=UserRole.CLAIMS_MANAGER,
                is_active=True,
            ))
        db.commit()


def _positive_11o() -> dict:
    authorization_ref, _, _ = _completed_final_production()
    _add_11p_sre_user()
    with TestingSessionLocal() as db:
        authorization = db.scalar(select(AIFinalProductionAuthorization).where(
            AIFinalProductionAuthorization.id == UUID(authorization_ref["id"])))
        manager = db.scalar(select(User).where(User.email == "alpha-manager@example.com"))
        assert authorization is not None and manager is not None
        assessment = AIFinalProductionOutcomeAssessment(
            organization_id=authorization.organization_id,
            final_production_authorization_id=authorization.id,
            requested_by_id=manager.id,
            finalized_by_id=manager.id,
            attempt_number=1,
            assessment_key=f"11p-positive-11o-{uuid4()}",
            assessment_profile="final_production_outcome_v1",
            final_production_decision_hash=authorization.decision_hash,
            final_production_completion_hash=authorization.completion_hash,
            final_readiness_assessment_hash=authorization.readiness_assessment_hash,
            final_readiness_decision_hash=authorization.readiness_decision_hash,
            high_coverage_outcome_assessment_hash=authorization.high_coverage_outcome_assessment_hash,
            high_coverage_outcome_decision_hash=authorization.high_coverage_outcome_decision_hash,
            high_coverage_decision_hash=authorization.high_coverage_decision_hash,
            high_coverage_completion_hash=authorization.high_coverage_completion_hash,
            broader_outcome_assessment_hash=authorization.broader_outcome_assessment_hash,
            broader_outcome_decision_hash=authorization.broader_outcome_decision_hash,
            broader_production_decision_hash=authorization.broader_production_decision_hash,
            scale_readiness_assessment_hash=authorization.scale_readiness_assessment_hash,
            scale_readiness_decision_hash=authorization.scale_readiness_decision_hash,
            scale_up_decision_hash=authorization.scale_up_decision_hash,
            inherited_outcome_assessment_hash=authorization.inherited_outcome_assessment_hash,
            inherited_outcome_decision_hash=authorization.inherited_outcome_decision_hash,
            model=authorization.model,
            prompt_bundle_version=authorization.prompt_bundle_version,
            schema_bundle_version=authorization.schema_bundle_version,
            max_input_chars=authorization.max_input_chars,
            max_output_tokens=authorization.max_output_tokens,
            allowed_document_types=authorization.allowed_document_types,
            rollout_percentage=authorization.rollout_percentage,
            max_claims=authorization.max_claims,
            max_documents=authorization.max_documents,
            max_users=authorization.max_users,
            max_provider_runs=authorization.max_provider_runs,
            status="recommended",
            outcome="recommend_separate_91_100_authorization_review",
            metrics={"overall_pass": True, "source_ledger_revalidated": True,
                     "business_value": {"overall_pass": True}},
            failure_reasons=[],
            assessment_note="Sprint 11O source-ledger, business-value and safety controls passed.",
            assessment_hash="6" * 64,
            assessed_at=datetime.now(UTC),
            decision_note="Recommend only a separate bounded 91–99% authorization review.",
            decision_hash="7" * 64,
            decided_at=datetime.now(UTC),
        )
        db.add(assessment)
        db.commit()
        db.refresh(assessment)
        return {"id": str(assessment.id), "final_id": str(authorization.id)}


def _payload(outcome_id: str, **overrides) -> dict:
    payload = {
        "outcome_assessment_id": outcome_id,
        "authorization_key": f"near-universal-{uuid4()}",
        "allowed_document_types": ["chief_engineer_report", "engine_log"],
        "rollout_percentage": 95,
        "max_claims": 75,
        "max_documents": 225,
        "max_users": 75,
        "max_provider_runs": 1200,
        "starts_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
        "deployment_isolation_reference": "artifact://ai-near-universal/deployment-isolation",
        "provider_project_reference": "artifact://ai-near-universal/provider-project",
        "credential_control_reference": "artifact://ai-near-universal/credential-control",
        "privacy_legal_reference": "artifact://ai-near-universal/privacy-legal",
        "monitoring_reference": "monitor://ai-near-universal/live-controls",
        "incident_response_reference": "runbook://ai-near-universal/incident-response",
        "rollback_reference": "runbook://ai-near-universal/rollback-15-minutes",
        "platform_reliability_reference": "artifact://ai-near-universal/platform-reliability",
        "change_ticket_reference": "ticket://ai-near-universal/change-001",
        "confirm_separate_near_universal": True,
    }
    payload.update(overrides)
    return payload


def _create_authorization(outcome_id: str) -> dict:
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    response = client.post("/api/v1/ai-near-universal-production/authorizations", json=_payload(outcome_id))
    assert response.status_code == 201, response.text
    return response.json()


def test_11p_requires_positive_11o_eleven_reviewers_and_never_authorizes_100_percent() -> None:
    outcome = _positive_11o()
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")

    hundred = client.post(
        "/api/v1/ai-near-universal-production/authorizations",
        json=_payload(outcome["id"], rollout_percentage=100),
    )
    assert hundred.status_code == 422

    too_long = client.post(
        "/api/v1/ai-near-universal-production/authorizations",
        json=_payload(outcome["id"], expires_at=(datetime.now(UTC) + timedelta(days=22)).isoformat()),
    )
    assert too_long.status_code == 422

    item = _create_authorization(outcome["id"])
    assert item["previous_rollout_percentage"] == 80
    assert item["rollout_percentage"] == 95
    assert item["summary"]["rollout_above_90_authorized"] is False
    assert item["summary"]["rollout_100_percent_authorized"] is False
    assert item["summary"]["production_wide_authorized"] is False
    assert item["summary"]["different_human_review_required"] is True

    self_review = client.post(
        f"/api/v1/ai-near-universal-production/authorizations/{item['id']}/approvals",
        json={"approval_role": "security", "action": "approve",
              "evidence_reference": "artifact://ai-near-universal/self-review",
              "note": "The requester must not approve the Sprint 11P authorization."},
    )
    assert self_review.status_code == 409

    reviewers = [
        ("alpha-security@example.com", "security"),
        ("alpha-privacy-11n@example.com", "privacy"),
        ("alpha-product@example.com", "product"),
        ("alpha-admin@example.com", "quality"),
        ("alpha-operations@example.com", "operations"),
        ("alpha-risk@example.com", "risk"),
        ("alpha-governance@example.com", "claims_governance"),
        ("alpha-ai-quality@example.com", "ai_quality"),
        ("alpha-legal-11n@example.com", "legal_data_governance"),
        ("alpha-business-owner-11n@example.com", "business_owner"),
        ("alpha-sre-11p@example.com", "platform_reliability"),
    ]
    for email, role in reviewers:
        client.cookies.clear()
        login("alpha", email)
        approval = client.post(
            f"/api/v1/ai-near-universal-production/authorizations/{item['id']}/approvals",
            json={"approval_role": role, "action": "approve",
                  "evidence_reference": f"artifact://ai-near-universal/{role}-approval",
                  "note": f"Independent {role} reviewer verified the bounded Sprint 11P controls."},
        )
        assert approval.status_code == 200, approval.text
    assert approval.json()["status"] == "decision_ready"

    client.cookies.clear()
    login("alpha", "alpha-11k-admin@example.com")
    decided = client.post(
        f"/api/v1/ai-near-universal-production/authorizations/{item['id']}/decision",
        json={"outcome": "authorize_near_universal_91_99_cohort",
              "confirm_decision": True,
              "note": "Authorize only this exact expiring 95-percent Sprint 11P cohort."},
    )
    assert decided.status_code == 200, decided.text
    result = decided.json()
    assert result["status"] == "authorized"
    assert len(result["decision_hash"]) == 64
    assert result["summary"]["rollout_above_90_authorized"] is True
    assert result["summary"]["rollout_100_percent_authorized"] is False
    assert result["summary"]["production_wide_authorized"] is False
    assert result["summary"]["restricted_documents_authorized"] is False
    assert result["summary"]["new_document_classes_authorized"] is False
    assert result["summary"]["autonomous_claim_decisions_authorized"] is False
    assert result["summary"]["authoritative_facts_auto_updated"] is False


def test_11p_attempt_blocks_runtime_fallback_to_11n_when_inactive(monkeypatch) -> None:
    outcome = _positive_11o()
    item = _create_authorization(outcome["id"])
    assert item["status"] == "pending_approvals"

    monkeypatch.setattr(ai_runtime, "get_settings", lambda: SimpleNamespace(app_env="production"))
    with TestingSessionLocal() as db:
        authorization = db.scalar(select(AINearUniversalAuthorization).where(
            AINearUniversalAuthorization.id == UUID(item["id"])))
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
