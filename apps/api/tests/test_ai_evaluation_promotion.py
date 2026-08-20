from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.ai_evaluation.service import require_active_staging_promotion
from app.modules.audit.models import AuditLog
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_ai_provider_activation import _add_reviewers, _create_and_authorize
from tests.test_claims_api import TEST_PASSWORD, create_orion_claim, login


def setup_function() -> None:
    reset_database()


def _authorized_activation() -> dict:
    create_orion_claim()
    _add_reviewers()
    return _create_and_authorize()


def _create_suite(activation_id: str, key: str = "quality-safety-cost-attempt-one") -> dict:
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    response = client.post("/api/v1/ai-evaluation/suites", json={
        "activation_request_id": activation_id, "suite_key": key,
        "confirm_content_free": True,
    })
    assert response.status_code == 201, response.text
    return response.json()


def _case_payload(index: int, failed_scenario: str | None = None) -> dict:
    boundary = ["prompt_injection", "malformed_input", "cross_tenant", "restricted_data"]
    scenario = boundary[index] if index < len(boundary) else "baseline"
    failing = scenario == failed_scenario
    return {
        "case_key": f"benchmark-case-{index:02d}",
        "document_type": "chief_engineer_report" if index < 6 else "engine_log",
        "scenario_type": scenario, "data_mode": "synthetic",
        "result": "fail" if failing else "pass",
        "field_true_positive": 95, "field_false_positive": 5,
        "field_false_negative": 10, "extracted_claim_count": 100,
        "unsupported_claim_count": 1, "source_quote_checked_count": 100,
        "source_quote_valid_count": 99, "human_approved_count": 9,
        "human_edited_count": 1, "human_rejected_count": 0,
        "latency_ms": 2000 + index * 10, "input_tokens": 1500,
        "output_tokens": 500, "observed_provider_cost_microusd": 150000,
        "boundary_control_passed": not failing,
        "evidence_reference": f"artifact://ai-evaluation/case-{index:02d}",
        "note": "Observed aggregate benchmark metrics independently checked against the artifact.",
        "executed_at": datetime.now(UTC).isoformat(), "confirm_content_free": True,
    }


def _record_cases(suite_id: str, failed_scenario: str | None = None) -> dict:
    current = None
    for index in range(12):
        response = client.post(
            f"/api/v1/ai-evaluation/suites/{suite_id}/cases",
            json=_case_payload(index, failed_scenario),
        )
        assert response.status_code == 201, response.text
        current = response.json()
    assert current is not None
    return current


def test_passing_evaluation_requires_independent_reviews_and_admin_promotion(monkeypatch) -> None:
    activation = _authorized_activation()
    suite = _create_suite(activation["id"])
    assert suite["benchmark_profile"] == "quality_safety_cost_v1"
    assert suite["activation_model"] == activation["model"]
    assert suite["summary"]["raw_content_stored"] is False
    assert suite["summary"]["calculated_provider_billing"] is False
    recorded = _record_cases(suite["id"])
    assert recorded["summary"]["case_count"] == 12

    duplicate = client.post(
        f"/api/v1/ai-evaluation/suites/{suite['id']}/cases", json=_case_payload(0))
    assert duplicate.status_code == 409
    raw_content = _case_payload(20)
    raw_content["prompt_text"] = "This must never enter the evaluation ledger"
    rejected_extra = client.post(
        f"/api/v1/ai-evaluation/suites/{suite['id']}/cases", json=raw_content)
    assert rejected_extra.status_code == 422

    finalized = client.post(
        f"/api/v1/ai-evaluation/suites/{suite['id']}/finalize",
        json={"confirm_finalize": True,
              "note": "All content-free benchmark observations are complete and reproducible."},
    )
    assert finalized.status_code == 200, finalized.text
    result = finalized.json()
    assert result["status"] == "review_ready"
    assert result["metrics"]["overall_pass"] is True
    assert result["metrics"]["precision_bps"] == 9500
    assert result["metrics"]["recall_bps"] == 9047
    assert result["metrics"]["unsupported_claim_rate_bps"] == 100
    assert result["metrics"]["source_quote_validity_bps"] == 9900
    assert result["metrics"]["human_override_rate_bps"] == 1000
    assert len(result["evaluation_hash"]) == 64

    self_review = client.post(
        f"/api/v1/ai-evaluation/suites/{suite['id']}/reviews",
        json={"review_role": "quality", "action": "approve",
              "evidence_reference": "artifact://ai-evaluation/self-review",
              "note": "The requester must not review their own evaluation suite."},
    )
    assert self_review.status_code == 409

    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    quality = client.post(
        f"/api/v1/ai-evaluation/suites/{suite['id']}/reviews",
        json={"review_role": "quality", "action": "approve",
              "evidence_reference": "artifact://ai-evaluation/quality-review",
              "note": "Quality reviewer reproduced metrics and source-grounding evidence."},
    )
    assert quality.status_code == 200, quality.text
    same_person = client.post(
        f"/api/v1/ai-evaluation/suites/{suite['id']}/reviews",
        json={"review_role": "risk", "action": "approve",
              "evidence_reference": "artifact://ai-evaluation/risk-review",
              "note": "A different person must perform the independent Risk review."},
    )
    assert same_person.status_code == 409

    client.cookies.clear(); login("alpha", "alpha-risk@example.com")
    risk = client.post(
        f"/api/v1/ai-evaluation/suites/{suite['id']}/reviews",
        json={"review_role": "risk", "action": "approve",
              "evidence_reference": "artifact://ai-evaluation/risk-review",
              "note": "Risk reviewer reproduced every adversarial fail-closed result."},
    )
    assert risk.status_code == 200, risk.text
    assert risk.json()["status"] == "promotion_ready"
    assert risk.json()["summary"]["independent_reviews_complete"] is True

    client.cookies.clear(); login("alpha", "alpha-product@example.com")
    non_admin = client.post(
        f"/api/v1/ai-evaluation/suites/{suite['id']}/decision",
        json={"outcome": "promote_staging", "confirm_decision": True,
              "note": "Only an Administrator can issue the final staging promotion."},
    )
    assert non_admin.status_code == 403
    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    promoted = client.post(
        f"/api/v1/ai-evaluation/suites/{suite['id']}/decision",
        json={"outcome": "promote_staging", "confirm_decision": True,
              "note": "Administrator promotes only this evaluated synthetic staging bundle."},
    )
    assert promoted.status_code == 200, promoted.text
    promotion = promoted.json()
    assert promotion["status"] == "staging_promoted"
    assert promotion["summary"]["promotion_active"] is True
    assert promotion["summary"]["production_authorized"] is False
    assert promotion["summary"]["real_claim_data_authorized"] is False
    assert promotion["summary"]["human_review_required"] is True
    assert promotion["promotion_expires_at"] == activation["evaluation_expires_at"]
    assert len(promotion["decision_hash"]) == 64

    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "staging")
    monkeypatch.setattr(settings, "ai_model", activation["model"])
    monkeypatch.setattr(settings, "ai_prompt_bundle_version", activation["prompt_bundle_version"])
    monkeypatch.setattr(settings, "ai_schema_bundle_version", activation["schema_bundle_version"])
    with TestingSessionLocal() as db:
        alpha = db.scalar(select(Organization).where(Organization.slug == "alpha"))
        assert alpha is not None
        active = require_active_staging_promotion(db, alpha.id)
        assert str(active.id) == suite["id"]

    killed = client.post(
        f"/api/v1/ai-evaluation/suites/{suite['id']}/revoke",
        json={"confirm_revoke": True,
              "note": "Manager activates the evaluation promotion kill switch immediately."},
    )
    assert killed.status_code == 200 and killed.json()["status"] == "revoked"
    with TestingSessionLocal() as db:
        actions = set(db.scalars(select(AuditLog.action).where(
            AuditLog.entity_id == UUID(suite["id"]))))
        assert {"CREATE_AI_EVALUATION_SUITE", "FINALIZE_AI_EVALUATION_SUITE",
                "PROMOTE_STAGING_AI_EVALUATION",
                "REVOKE_AI_EVALUATION_PROMOTION"}.issubset(actions)


def test_failed_security_case_blocks_review_and_allows_append_only_retry() -> None:
    activation = _authorized_activation()
    suite = _create_suite(activation["id"])
    _record_cases(suite["id"], failed_scenario="prompt_injection")
    finalized = client.post(
        f"/api/v1/ai-evaluation/suites/{suite['id']}/finalize",
        json={"confirm_finalize": True,
              "note": "Prompt-injection failure must remain visible and block promotion."},
    )
    assert finalized.status_code == 200, finalized.text
    failed = finalized.json()
    assert failed["status"] == "failed"
    assert "failed_case_result" in failed["failure_reasons"]
    assert "boundary_prompt_injection" in failed["failure_reasons"]
    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    blocked = client.post(
        f"/api/v1/ai-evaluation/suites/{suite['id']}/reviews",
        json={"review_role": "quality", "action": "approve",
              "evidence_reference": "artifact://ai-evaluation/quality-review",
              "note": "A failed suite must never be reviewable for promotion."},
    )
    assert blocked.status_code == 409
    retry = _create_suite(activation["id"], key="quality-safety-cost-attempt-two")
    assert retry["attempt_number"] == 2 and retry["status"] == "collecting"


def test_evaluation_is_manager_only_tenant_scoped_and_requires_bounded_evidence() -> None:
    activation = _authorized_activation()
    client.cookies.clear(); login("alpha", "alpha-handler@example.com")
    denied = client.post("/api/v1/ai-evaluation/suites", json={
        "activation_request_id": activation["id"], "suite_key": "handler-evaluation-suite",
        "confirm_content_free": True,
    })
    assert denied.status_code == 403
    suite = _create_suite(activation["id"])
    invalid = _case_payload(0)
    invalid["evidence_reference"] = "https://example.com/raw-provider-response"
    assert client.post(f"/api/v1/ai-evaluation/suites/{suite['id']}/cases",
                       json=invalid).status_code == 422

    with TestingSessionLocal() as db:
        beta = db.scalar(select(Organization).where(Organization.slug == "beta"))
        assert beta is not None
        db.add(User(organization_id=beta.id, email="beta-evaluation@example.com",
                    full_name="Beta Evaluation Manager", password_hash=hash_password(TEST_PASSWORD),
                    role=UserRole.CLAIMS_MANAGER, is_active=True))
        db.commit()
    client.cookies.clear(); login("beta", "beta-evaluation@example.com")
    dashboard = client.get("/api/v1/ai-evaluation")
    assert dashboard.status_code == 200 and dashboard.json() == {"suites": []}
    cross_tenant = client.post(
        f"/api/v1/ai-evaluation/suites/{suite['id']}/finalize",
        json={"confirm_finalize": True,
              "note": "A different tenant must not access this evaluation suite."},
    )
    assert cross_tenant.status_code == 404
