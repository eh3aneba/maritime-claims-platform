from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.security import hash_password
from app.modules import ai_runtime
from app.modules.ai_bounded_full_production.models import AIBoundedFullProductionAuthorization
from app.modules.ai_near_universal_outcomes.models import AINearUniversalOutcomeAssessment
from app.modules.ai_near_universal_production.models import AINearUniversalAuthorization
from app.modules.documents.models import Document
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_ai_near_universal_outcomes import _completed_near_universal
from tests.test_claims_api import TEST_PASSWORD, login


def setup_function() -> None:
    reset_database()


REVIEWERS = [
    ("alpha-11r-security@example.com", "security"),
    ("alpha-11r-privacy@example.com", "privacy"),
    ("alpha-11r-product@example.com", "product"),
    ("alpha-11r-operations@example.com", "operations"),
    ("alpha-11r-risk@example.com", "risk"),
    ("alpha-11r-claims-governance@example.com", "claims_governance"),
    ("alpha-11r-ai-quality@example.com", "ai_quality"),
    ("alpha-11r-legal@example.com", "legal_data_governance"),
    ("alpha-11r-business-owner@example.com", "business_owner"),
    ("alpha-11r-sre@example.com", "platform_reliability"),
    ("alpha-11r-assurance@example.com", "independent_production_assurance"),
    ("alpha-11r-data-protection@example.com", "data_protection"),
    ("alpha-11r-executive@example.com", "executive_production_sponsor"),
]
FINAL_ADMIN = "alpha-11r-final-admin@example.com"


def _ensure_11r_users() -> None:
    with TestingSessionLocal() as db:
        alpha = db.scalar(select(Organization).where(Organization.slug == "alpha"))
        assert alpha is not None
        for email, role in REVIEWERS:
            if db.scalar(select(User).where(User.email == email)) is None:
                db.add(User(
                    organization_id=alpha.id,
                    email=email,
                    full_name=f"Sprint 11R {role.replace('_', ' ').title()} Reviewer",
                    password_hash=hash_password(TEST_PASSWORD),
                    role=UserRole.CLAIMS_MANAGER,
                    is_active=True,
                ))
        if db.scalar(select(User).where(User.email == FINAL_ADMIN)) is None:
            db.add(User(
                organization_id=alpha.id,
                email=FINAL_ADMIN,
                full_name="Sprint 11R Separate Final Admin",
                password_hash=hash_password(TEST_PASSWORD),
                role=UserRole.ADMIN,
                is_active=True,
            ))
        db.commit()


def _positive_11q() -> dict:
    near_ref, _, _ = _completed_near_universal()
    _ensure_11r_users()
    with TestingSessionLocal() as db:
        near = db.scalar(select(AINearUniversalAuthorization).where(
            AINearUniversalAuthorization.id == UUID(near_ref["id"])
        ))
        manager = db.scalar(select(User).where(User.email == "alpha-manager@example.com"))
        assert near is not None and manager is not None
        assessment = AINearUniversalOutcomeAssessment(
            organization_id=near.organization_id,
            near_universal_authorization_id=near.id,
            requested_by_id=manager.id,
            finalized_by_id=manager.id,
            attempt_number=1,
            assessment_key=f"11r-positive-11q-{uuid4()}",
            assessment_profile="near_universal_outcome_v1",
            near_universal_decision_hash=near.decision_hash,
            near_universal_completion_hash=near.completion_hash,
            outcome_assessment_hash=near.outcome_assessment_hash,
            outcome_decision_hash=near.outcome_decision_hash,
            final_production_decision_hash=near.final_production_decision_hash,
            final_production_completion_hash=near.final_production_completion_hash,
            final_readiness_assessment_hash=near.final_readiness_assessment_hash,
            final_readiness_decision_hash=near.final_readiness_decision_hash,
            high_coverage_outcome_assessment_hash=near.high_coverage_outcome_assessment_hash,
            high_coverage_outcome_decision_hash=near.high_coverage_outcome_decision_hash,
            high_coverage_decision_hash=near.high_coverage_decision_hash,
            high_coverage_completion_hash=near.high_coverage_completion_hash,
            broader_outcome_assessment_hash=near.broader_outcome_assessment_hash,
            broader_outcome_decision_hash=near.broader_outcome_decision_hash,
            broader_production_decision_hash=near.broader_production_decision_hash,
            scale_readiness_assessment_hash=near.scale_readiness_assessment_hash,
            scale_readiness_decision_hash=near.scale_readiness_decision_hash,
            scale_up_decision_hash=near.scale_up_decision_hash,
            inherited_outcome_assessment_hash=near.inherited_outcome_assessment_hash,
            inherited_outcome_decision_hash=near.inherited_outcome_decision_hash,
            model=near.model,
            prompt_bundle_version=near.prompt_bundle_version,
            schema_bundle_version=near.schema_bundle_version,
            max_input_chars=near.max_input_chars,
            max_output_tokens=near.max_output_tokens,
            allowed_document_types=list(near.allowed_document_types),
            rollout_percentage=near.rollout_percentage,
            max_claims=near.max_claims,
            max_documents=near.max_documents,
            max_users=near.max_users,
            max_provider_runs=near.max_provider_runs,
            status="recommended",
            outcome="recommend_separate_100_percent_authorization_review",
            metrics={"overall_pass": True, "source_ledger_revalidated": True,
                     "business_value": {"overall_pass": True}},
            failure_reasons=[],
            assessment_note="Sprint 11Q technical, safety and business-value controls passed.",
            assessment_hash="c" * 64,
            assessed_at=datetime.now(UTC),
            decision_note="Recommend only a separately authorized bounded 100 percent cohort.",
            decision_hash="d" * 64,
            decided_at=datetime.now(UTC),
        )
        db.add(assessment)
        db.commit()
        db.refresh(assessment)
        return {"id": str(assessment.id), "near_id": str(near.id)}


def _payload(assessment_id: str, **overrides) -> dict:
    payload = {
        "near_universal_outcome_assessment_id": assessment_id,
        "authorization_key": f"bounded-full-{uuid4()}",
        "allowed_document_types": ["chief_engineer_report", "engine_log"],
        "rollout_percentage": 100,
        "max_claims": 110,
        "max_documents": 330,
        "max_users": 110,
        "max_provider_runs": 1900,
        "starts_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(days=20)).isoformat(),
        "deployment_isolation_reference": "artifact://ai-bounded-full/deployment-isolation",
        "provider_project_reference": "artifact://ai-bounded-full/provider-project",
        "credential_control_reference": "artifact://ai-bounded-full/credential-control",
        "privacy_legal_reference": "artifact://ai-bounded-full/privacy-legal",
        "monitoring_reference": "monitor://ai-bounded-full/live-controls",
        "incident_response_reference": "runbook://ai-bounded-full/incidents",
        "rollback_reference": "runbook://ai-bounded-full/rollback",
        "platform_reliability_reference": "artifact://ai-bounded-full/platform-reliability",
        "data_protection_reference": "artifact://ai-bounded-full/data-protection",
        "executive_sponsor_reference": "artifact://ai-bounded-full/executive-sponsor",
        "change_ticket_reference": "ticket://ai-bounded-full/authorization",
        "confirm_separate_bounded_full_production": True,
    }
    payload.update(overrides)
    return payload


def _create(assessment_id: str) -> dict:
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    response = client.post("/api/v1/ai-bounded-full-production/authorizations", json=_payload(assessment_id))
    assert response.status_code == 201, response.text
    return response.json()


def test_11r_requires_positive_11q_thirteen_reviewers_and_never_authorizes_unbounded_production() -> None:
    anchor = _positive_11q()
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")

    below_full = client.post(
        "/api/v1/ai-bounded-full-production/authorizations",
        json=_payload(anchor["id"], rollout_percentage=99),
    )
    assert below_full.status_code == 422

    too_long = client.post(
        "/api/v1/ai-bounded-full-production/authorizations",
        json=_payload(anchor["id"], expires_at=(datetime.now(UTC) + timedelta(days=31)).isoformat()),
    )
    assert too_long.status_code == 422

    item = _create(anchor["id"])
    assert 91 <= item["previous_rollout_percentage"] <= 99
    assert item["rollout_percentage"] == 100
    assert item["summary"]["rollout_100_percent_authorized"] is False
    assert item["summary"]["production_wide_unbounded_authorized"] is False
    assert item["summary"]["different_human_review_required"] is True

    self_review = client.post(
        f"/api/v1/ai-bounded-full-production/authorizations/{item['id']}/approvals",
        json={"approval_role": "security", "action": "approve",
              "evidence_reference": "artifact://ai-bounded-full/self-review",
              "note": "The requester must not approve the Sprint 11R authorization."},
    )
    assert self_review.status_code == 409

    for email, role in REVIEWERS:
        client.cookies.clear()
        login("alpha", email)
        approval = client.post(
            f"/api/v1/ai-bounded-full-production/authorizations/{item['id']}/approvals",
            json={"approval_role": role, "action": "approve",
                  "evidence_reference": f"artifact://ai-bounded-full/{role}-approval",
                  "note": f"Independent {role} reviewer verified the bounded Sprint 11R controls."},
        )
        assert approval.status_code == 200, approval.text
    assert approval.json()["status"] == "decision_ready"

    client.cookies.clear()
    login("alpha", FINAL_ADMIN)
    decided = client.post(
        f"/api/v1/ai-bounded-full-production/authorizations/{item['id']}/decision",
        json={"outcome": "authorize_bounded_100_percent_cohort",
              "confirm_decision": True,
              "note": "Authorize only this exact expiring bounded 100 percent Sprint 11R cohort."},
    )
    assert decided.status_code == 200, decided.text
    result = decided.json()
    assert result["status"] == "authorized"
    assert len(result["decision_hash"]) == 64
    assert result["summary"]["bounded_100_percent_cohort_authorized"] is True
    assert result["summary"]["rollout_100_percent_authorized"] is True
    assert result["summary"]["production_wide_unbounded_authorized"] is False
    assert result["summary"]["restricted_documents_authorized"] is False
    assert result["summary"]["new_document_classes_authorized"] is False
    assert result["summary"]["autonomous_claim_decisions_authorized"] is False
    assert result["summary"]["authoritative_facts_auto_updated"] is False


def test_11r_attempt_blocks_runtime_fallback_to_11p_when_inactive(monkeypatch) -> None:
    anchor = _positive_11q()
    item = _create(anchor["id"])
    assert item["status"] == "pending_approvals"

    monkeypatch.setattr(ai_runtime, "get_settings", lambda: SimpleNamespace(app_env="production"))
    with TestingSessionLocal() as db:
        authorization = db.scalar(select(AIBoundedFullProductionAuthorization).where(
            AIBoundedFullProductionAuthorization.id == UUID(item["id"])
        ))
        document = db.scalar(select(Document).where(
            Document.organization_id == authorization.organization_id,
            Document.document_type.in_(["chief_engineer_report", "engine_log"]),
        )) if authorization else None
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
