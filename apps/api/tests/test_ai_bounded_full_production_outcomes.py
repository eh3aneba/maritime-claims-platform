from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.security import hash_password
from app.modules.ai_bounded_full_production.models import (
    AIBoundedFullProductionAuthorization,
    AIBoundedFullProductionMonitor,
)
from app.modules.ai_bounded_full_production_outcomes.models import AIBoundedFullProductionOutcomeAssessment
from app.modules.ai_near_universal_outcomes.models import AINearUniversalOutcomeAssessment
from app.modules.ai_near_universal_production.models import AINearUniversalAuthorization
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_ai_bounded_full_production import FINAL_ADMIN, REVIEWERS as REVIEWERS_11R, _positive_11q
from tests.test_claims_api import TEST_PASSWORD, login


def setup_function() -> None:
    reset_database()


REVIEWERS = REVIEWERS_11R + [
    ("alpha-11s-enterprise-architecture@example.com", "enterprise_architecture_resilience"),
]


def _completed_11r() -> dict:
    anchor = _positive_11q()
    with TestingSessionLocal() as db:
        near = db.scalar(select(AINearUniversalAuthorization).where(AINearUniversalAuthorization.id == UUID(anchor["near_id"])))
        outcome = db.scalar(select(AINearUniversalOutcomeAssessment).where(AINearUniversalOutcomeAssessment.id == UUID(anchor["id"])))
        manager = db.scalar(select(User).where(User.email == "alpha-manager@example.com"))
        alpha = db.scalar(select(Organization).where(Organization.slug == "alpha"))
        assert near is not None and outcome is not None and manager is not None and alpha is not None
        if db.scalar(select(User).where(User.email == "alpha-11s-enterprise-architecture@example.com")) is None:
            db.add(User(
                organization_id=alpha.id,
                email="alpha-11s-enterprise-architecture@example.com",
                full_name="Sprint 11S Enterprise Architecture Reviewer",
                password_hash=hash_password(TEST_PASSWORD),
                role=UserRole.CLAIMS_MANAGER,
                is_active=True,
            ))
        authorization = AIBoundedFullProductionAuthorization(
            organization_id=near.organization_id,
            near_universal_outcome_assessment_id=outcome.id,
            near_universal_authorization_id=near.id,
            requested_by_id=manager.id,
            finalized_by_id=manager.id,
            attempt_number=1,
            authorization_key=f"11s-completed-11r-{uuid4()}",
            environment="production",
            authorization_mode="bounded_full_100_percent",
            near_universal_outcome_assessment_hash=outcome.assessment_hash,
            near_universal_outcome_decision_hash=outcome.decision_hash,
            near_universal_decision_hash=near.decision_hash,
            near_universal_completion_hash=near.completion_hash,
            model=near.model,
            prompt_bundle_version=near.prompt_bundle_version,
            schema_bundle_version=near.schema_bundle_version,
            max_input_chars=near.max_input_chars,
            max_output_tokens=near.max_output_tokens,
            allowed_document_types=list(near.allowed_document_types),
            previous_rollout_percentage=near.rollout_percentage,
            rollout_percentage=100,
            previous_max_claims=near.max_claims,
            previous_max_documents=near.max_documents,
            previous_max_users=near.max_users,
            previous_max_provider_runs=near.max_provider_runs,
            max_claims=110,
            max_documents=330,
            max_users=110,
            max_provider_runs=1900,
            starts_at=datetime.now(UTC) - timedelta(days=2),
            expires_at=datetime.now(UTC) + timedelta(days=10),
            rollback_slo_minutes=15,
            monitor_interval_minutes=60,
            max_reject_rate_bps=350,
            max_edit_rate_bps=1600,
            max_unsupported_output_rate_bps=15,
            min_source_grounding_validity_bps=9985,
            max_p95_latency_ms=13000,
            max_mean_cost_microusd=350000,
            max_quality_regression_bps=50,
            max_latency_regression_bps=400,
            max_cost_regression_bps=400,
            deployment_isolation_reference="artifact://11s/deployment",
            provider_project_reference="artifact://11s/provider",
            credential_control_reference="artifact://11s/credential",
            privacy_legal_reference="artifact://11s/privacy",
            monitoring_reference="monitor://11s/live",
            incident_response_reference="runbook://11s/incident",
            rollback_reference="runbook://11s/rollback",
            platform_reliability_reference="artifact://11s/reliability",
            data_protection_reference="artifact://11s/data-protection",
            executive_sponsor_reference="artifact://11s/executive",
            change_ticket_reference="ticket://11s/change",
            status="completed",
            outcome="authorize_bounded_100_percent_cohort",
            decision_note="Bounded 100 percent cohort approved.",
            decision_hash="7" * 64,
            decided_at=datetime.now(UTC) - timedelta(days=1),
            completed_at=datetime.now(UTC) - timedelta(minutes=30),
            completion_note="Bounded 100 percent cohort completed with human review.",
            completion_hash="8" * 64,
        )
        db.add(authorization)
        db.flush()
        db.add(AIBoundedFullProductionMonitor(
            organization_id=near.organization_id,
            authorization_id=authorization.id,
            initiated_by_id=manager.id,
            monitor_key=f"11s-final-pass-{uuid4()}",
            metrics={"overall_pass": True, "provider_run_count": 200},
            failure_reasons=[],
            status="pass",
            monitor_hash="9" * 64,
            note="Fresh final Sprint 11R monitor passed before Sprint 11S.",
            monitored_at=datetime.now(UTC),
        ))
        db.commit()
        return {"id": str(authorization.id)}


def _create_assessment(authorization_id: str) -> dict:
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    response = client.post(
        "/api/v1/ai-bounded-full-production-outcomes/assessments",
        json={
            "bounded_full_authorization_id": authorization_id,
            "assessment_key": f"11s-outcome-{uuid4()}",
            "confirm_content_free_assessment": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_11s_is_recommendation_only_and_forbids_raw_provider_content() -> None:
    authorization = _completed_11r()
    assessment = _create_assessment(authorization["id"])
    assert assessment["assessment_profile"] == "bounded_full_outcome_v1"
    assert assessment["rollout_percentage"] == 100
    assert assessment["thresholds"]["minimum_human_reviewed_provider_runs"] == 200
    assert assessment["thresholds"]["minimum_business_workflows"] == 15
    assert len(assessment["thresholds"]["required_enterprise_control_categories"]) == 10
    assert assessment["summary"]["production_wide_unbounded_authorized"] is False
    assert assessment["summary"]["different_human_review_required"] is True

    forbidden = client.post(
        f"/api/v1/ai-bounded-full-production-outcomes/assessments/{assessment['id']}/enterprise-evidence",
        json={
            "control_category": "tenant_isolation",
            "evidence_key": "tenant-isolation-evidence",
            "passed": True,
            "evidence_reference": "artifact://11s/tenant-isolation",
            "note": "Content-free tenant-isolation evidence only.",
            "confirm_content_free_enterprise_evidence": True,
            "provider_response": "forbidden raw content",
        },
    )
    assert forbidden.status_code == 422


def test_11s_requires_fourteen_distinct_reviews_and_positive_outcome_never_authorizes_production_wide() -> None:
    authorization = _completed_11r()
    assessment = _create_assessment(authorization["id"])
    with TestingSessionLocal() as db:
        item = db.scalar(select(AIBoundedFullProductionOutcomeAssessment).where(
            AIBoundedFullProductionOutcomeAssessment.id == UUID(assessment["id"])
        ))
        assert item is not None
        item.status = "review_ready"
        item.metrics = {
            "overall_pass": True,
            "source_ledger_revalidated": True,
            "enterprise_readiness": {"all_required_categories_present": True, "all_controls_passing": True},
            "business_value": {"workflow_count": 15},
        }
        item.failure_reasons = []
        item.assessment_hash = "e" * 64
        item.assessed_at = datetime.now(UTC)
        db.commit()

    for email, role in REVIEWERS:
        client.cookies.clear()
        login("alpha", email)
        response = client.post(
            f"/api/v1/ai-bounded-full-production-outcomes/assessments/{assessment['id']}/reviews",
            json={
                "review_role": role,
                "action": "approve",
                "evidence_reference": f"artifact://11s/{role}-review",
                "note": f"Independent {role} reviewer approved the recommendation-only Sprint 11S gate.",
            },
        )
        assert response.status_code == 200, response.text
    assert response.json()["status"] == "decision_ready"
    assert len(response.json()["reviews"]) == 14

    client.cookies.clear()
    login("alpha", FINAL_ADMIN)
    decided = client.post(
        f"/api/v1/ai-bounded-full-production-outcomes/assessments/{assessment['id']}/decision",
        json={
            "outcome": "recommend_separate_production_wide_authorization_review",
            "confirm_recommendation_only": True,
            "note": "Recommend only a separate Production-wide authorization design and review.",
        },
    )
    assert decided.status_code == 200, decided.text
    result = decided.json()
    assert result["status"] == "recommended"
    assert result["outcome"] == "recommend_separate_production_wide_authorization_review"
    assert len(result["decision_hash"]) == 64
    assert result["summary"]["production_wide_unbounded_authorized"] is False
    assert result["summary"]["restricted_documents_authorized"] is False
    assert result["summary"]["new_document_classes_authorized"] is False
    assert result["summary"]["autonomous_claim_decisions_authorized"] is False
    assert result["summary"]["authoritative_facts_auto_updated"] is False
