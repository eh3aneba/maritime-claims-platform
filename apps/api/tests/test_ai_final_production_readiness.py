from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.security import hash_password
from app.modules.ai_final_production_readiness.models import AIFinalProductionReadinessAssessment
from app.modules.ai_high_coverage.models import AIHighCoverageAuthorization
from app.modules.ai_high_coverage_outcomes.models import AIHighCoverageOutcomeAssessment
from app.modules.audit.models import AuditLog
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_ai_high_coverage_outcomes import _completed_high_coverage
from tests.test_ai_private_pilot import _claim_and_user
from tests.test_claims_api import TEST_PASSWORD, login

CONTROL_KEYS = [
    "kill_switch_rehearsal",
    "fail_closed_no_fallback",
    "audit_traceability",
    "model_change_governance",
    "bundle_rollback_target",
    "unit_economics",
    "operations_oncall_ownership",
    "monitoring_retention_sustainability",
    "privacy_access_control",
    "data_retention_legal_basis",
]


def setup_function() -> None:
    reset_database()


def _add_privacy_user() -> None:
    with TestingSessionLocal() as db:
        alpha = db.scalar(select(Organization).where(Organization.slug == "alpha"))
        assert alpha is not None
        if db.scalar(select(User).where(User.email == "alpha-privacy@example.com")) is None:
            db.add(User(
                organization_id=alpha.id,
                email="alpha-privacy@example.com",
                full_name="Alpha Privacy Reviewer",
                password_hash=hash_password(TEST_PASSWORD),
                role=UserRole.CLAIMS_MANAGER,
                is_active=True,
            ))
        db.commit()


def _positive_11l(*, safety_incident: bool = False) -> dict:
    authorization, _ = _completed_high_coverage(safety_incident=safety_incident)
    with TestingSessionLocal() as db:
        auth = db.scalar(select(AIHighCoverageAuthorization).where(
            AIHighCoverageAuthorization.id == UUID(authorization["id"])))
        manager = db.scalar(select(User).where(User.email == "alpha-manager@example.com"))
        assert auth is not None and manager is not None
        metrics = {
            "overall_pass": True,
            "human_reviewed_run_count": 80,
            "different_human_review_rate_bps": 10000,
            "human_reject_rate_bps": 0,
            "human_edit_rate_bps": 1000,
            "mean_usefulness_bps": 10000,
            "unsupported_output_rate_bps": 0,
            "source_grounding_validity_bps": 10000,
            "mean_review_seconds": 160,
            "p95_latency_ms": 2500,
            "mean_observed_provider_cost_microusd": 100000,
            "rollback_recovery": {"recovery_rate_bps": 10000},
            "monitor_history": {"latest_monitor_fresh": True},
            "incident_history": {
                "safety_boundary_incident_count": 0,
                "unresolved_high_or_critical_count": 0,
            },
        }
        outcome = AIHighCoverageOutcomeAssessment(
            organization_id=auth.organization_id,
            high_coverage_authorization_id=auth.id,
            requested_by_id=manager.id,
            finalized_by_id=manager.id,
            attempt_number=1,
            assessment_key=f"11m-positive-11l-{uuid4()}",
            assessment_profile="high_coverage_final_readiness_v1",
            high_coverage_decision_hash=auth.decision_hash,
            high_coverage_completion_hash=auth.completion_hash,
            broader_outcome_assessment_hash=auth.outcome_assessment_hash,
            broader_outcome_decision_hash=auth.outcome_decision_hash,
            broader_production_decision_hash=auth.broader_production_decision_hash,
            readiness_assessment_hash=auth.readiness_assessment_hash,
            readiness_decision_hash=auth.readiness_decision_hash,
            scale_up_decision_hash=auth.scale_up_decision_hash,
            inherited_outcome_assessment_hash=auth.inherited_outcome_assessment_hash,
            inherited_outcome_decision_hash=auth.inherited_outcome_decision_hash,
            model=auth.model,
            prompt_bundle_version=auth.prompt_bundle_version,
            schema_bundle_version=auth.schema_bundle_version,
            rollout_percentage=auth.rollout_percentage,
            status="recommended",
            outcome="recommend_final_production_readiness_review",
            metrics=metrics,
            failure_reasons=[],
            assessment_note="Sprint 11L technical readiness passed.",
            assessment_hash="e" * 64,
            assessed_at=datetime.now(UTC),
            decision_note="Recommend a separate final Production AI readiness review.",
            decision_hash="f" * 64,
            decided_at=datetime.now(UTC),
        )
        db.add(outcome); db.commit(); db.refresh(outcome)
        return {"id": str(outcome.id), "authorization_id": str(auth.id)}


def _create_assessment(outcome_id: str) -> dict:
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    response = client.post(
        "/api/v1/ai-final-production-readiness/assessments",
        json={
            "high_coverage_outcome_assessment_id": outcome_id,
            "assessment_key": f"final-prod-readiness-{uuid4()}",
            "confirm_recommendation_only_review": True,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _record_business_value(assessment_id: str) -> None:
    claim, _, _ = _claim_and_user()
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    for index in range(10):
        workflow = "chief_engineer_report" if index < 5 else "engine_log"
        response = client.post(
            f"/api/v1/ai-final-production-readiness/assessments/{assessment_id}/claims",
            json={
                "claim_id": str(claim.id),
                "evidence_key": f"11m-claim-workflow-{index}",
                "workflow_type": workflow,
                "baseline_tfta_seconds": 1000,
                "assisted_tfta_seconds": 600,
                "baseline_triage_seconds": 1000,
                "assisted_triage_seconds": 500,
                "baseline_handler_effort_seconds": 1000,
                "assisted_handler_effort_seconds": 700,
                "baseline_rework_count": 1,
                "assisted_rework_count": 1,
                "handler_usefulness_rating": 5,
                "final_claim_decision_human_owned": True,
                "evidence_reference": f"artifact://11m/productivity-{index}",
                "note": "Content-free baseline-versus-assisted design-partner claim workflow measurement.",
                "confirm_content_free_productivity_evidence": True,
            },
        )
        assert response.status_code == 201, response.text


def _record_controls(assessment_id: str) -> None:
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    for key in CONTROL_KEYS:
        response = client.post(
            f"/api/v1/ai-final-production-readiness/assessments/{assessment_id}/controls",
            json={
                "control_key": key,
                "passed": True,
                "evidence_reference": f"artifact://11m/{key}",
                "note": f"Independent bounded evidence confirms the Sprint 11M {key} control is operational.",
                "confirm_control_evidence": True,
            },
        )
        assert response.status_code == 201, response.text


def test_11m_requires_business_value_enterprise_controls_eight_reviews_and_never_authorizes_production_wide() -> None:
    anchor = _positive_11l()
    _add_privacy_user()
    assessment = _create_assessment(anchor["id"])
    assert assessment["assessment_profile"] == "final_production_ai_readiness_v1"
    assert assessment["summary"]["production_wide_authorized"] is False
    assert assessment["summary"]["rollout_above_75_authorized"] is False

    claim, _, _ = _claim_and_user()
    forbidden = client.post(
        f"/api/v1/ai-final-production-readiness/assessments/{assessment['id']}/claims",
        json={
            "claim_id": str(claim.id), "evidence_key": "forbidden-raw-provider-output",
            "workflow_type": "chief_engineer_report",
            "baseline_tfta_seconds": 1000, "assisted_tfta_seconds": 600,
            "baseline_triage_seconds": 1000, "assisted_triage_seconds": 500,
            "baseline_handler_effort_seconds": 1000, "assisted_handler_effort_seconds": 700,
            "baseline_rework_count": 1, "assisted_rework_count": 1,
            "handler_usefulness_rating": 5, "final_claim_decision_human_owned": True,
            "evidence_reference": "artifact://11m/forbidden",
            "note": "Raw provider output must never enter the final readiness ledger.",
            "confirm_content_free_productivity_evidence": True,
            "provider_response": "forbidden",
        },
    )
    assert forbidden.status_code == 422

    _record_business_value(assessment["id"])
    _record_controls(assessment["id"])
    finalized = client.post(
        f"/api/v1/ai-final-production-readiness/assessments/{assessment['id']}/finalize",
        json={"confirm_finalize": True,
              "note": "Freeze technical, claim-productivity, safety, resilience, auditability and governance evidence."},
    )
    assert finalized.status_code == 200, finalized.text
    scorecard = finalized.json()
    assert scorecard["status"] == "review_ready"
    assert scorecard["metrics"]["overall_pass"] is True
    assert scorecard["metrics"]["business_value"]["claim_workflow_count"] == 10
    assert scorecard["metrics"]["business_value"]["median_tfta_improvement_bps"] == 4000
    assert scorecard["metrics"]["business_value"]["median_triage_improvement_bps"] == 5000
    assert scorecard["metrics"]["business_value"]["median_handler_effort_improvement_bps"] == 3000
    assert scorecard["metrics"]["business_value"]["human_final_decision_ownership_rate_bps"] == 10000
    assert scorecard["metrics"]["enterprise_controls"]["pass_rate_bps"] == 10000
    assert len(scorecard["assessment_hash"]) == 64

    self_review = client.post(
        f"/api/v1/ai-final-production-readiness/assessments/{assessment['id']}/reviews",
        json={"review_role": "product", "action": "approve",
              "evidence_reference": "artifact://11m/self-review",
              "note": "The requester must remain outside the eight-party final review."},
    )
    assert self_review.status_code == 409

    for email, role in [
        ("alpha-product@example.com", "product"),
        ("alpha-admin@example.com", "quality"),
        ("alpha-risk@example.com", "risk"),
        ("alpha-operations@example.com", "operations"),
        ("alpha-security@example.com", "security"),
        ("alpha-privacy@example.com", "privacy"),
        ("alpha-governance@example.com", "claims_governance"),
        ("alpha-ai-quality@example.com", "ai_quality"),
    ]:
        client.cookies.clear(); login("alpha", email)
        review = client.post(
            f"/api/v1/ai-final-production-readiness/assessments/{assessment['id']}/reviews",
            json={"review_role": role, "action": "approve",
                  "evidence_reference": f"artifact://11m/{role}-review",
                  "note": f"Independent {role} reviewer reproduced the combined Sprint 11M scorecard."},
        )
        assert review.status_code == 200, review.text
    assert review.json()["status"] == "decision_ready"

    client.cookies.clear(); login("alpha", "alpha-11k-admin@example.com")
    decided = client.post(
        f"/api/v1/ai-final-production-readiness/assessments/{assessment['id']}/decision",
        json={"outcome": "recommend_separate_final_production_authorization",
              "confirm_recommendation_only": True,
              "note": "Recommend only a separately authorized final Production stage; no rollout change occurs here."},
    )
    assert decided.status_code == 200, decided.text
    result = decided.json()
    assert result["status"] == "recommended"
    assert result["summary"]["separate_final_production_authorization_recommended"] is True
    assert result["summary"]["production_wide_authorized"] is False
    assert result["summary"]["rollout_above_75_authorized"] is False
    assert result["summary"]["restricted_documents_authorized"] is False
    assert result["summary"]["new_document_classes_authorized"] is False
    assert result["summary"]["autonomous_claim_decisions_authorized"] is False
    assert len(result["decision_hash"]) == 64

    with TestingSessionLocal() as db:
        actions = set(db.scalars(select(AuditLog.action).where(
            AuditLog.entity_id == UUID(assessment["id"]))))
        assert {"CREATE_AI_FINAL_PRODUCTION_READINESS_ASSESSMENT",
                "FINALIZE_AI_FINAL_PRODUCTION_READINESS_ASSESSMENT",
                "DECIDE_AI_FINAL_PRODUCTION_READINESS_RECOMMENDATION"}.issubset(actions)


def test_11m_rechecks_actual_safety_history_even_if_11l_metrics_are_tampered_positive() -> None:
    anchor = _positive_11l(safety_incident=True)
    _add_privacy_user()
    assessment = _create_assessment(anchor["id"])
    _record_business_value(assessment["id"])
    _record_controls(assessment["id"])
    finalized = client.post(
        f"/api/v1/ai-final-production-readiness/assessments/{assessment['id']}/finalize",
        json={"confirm_finalize": True,
              "note": "Actual persisted safety history must override a misleading positive upstream metrics object."},
    )
    assert finalized.status_code == 200, finalized.text
    result = finalized.json()
    assert result["metrics"]["overall_pass"] is False
    assert "privacy_security_or_cross_tenant_incident_history" in result["failure_reasons"]
    assert result["summary"]["production_wide_authorized"] is False
    assert result["summary"]["rollout_above_75_authorized"] is False
