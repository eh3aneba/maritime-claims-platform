from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.security import hash_password
from app.modules.ai_operations import service as operations
from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.evidence_search.qa_synthesis_models import ClaimQaSynthesisRun
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import TEST_PASSWORD


def setup_function() -> None:
    reset_database()


def _seed() -> dict[str, str]:
    now = datetime.now(UTC)
    with TestingSessionLocal() as db:
        alpha = Organization(name="Alpha Operations", slug="alpha-ops")
        beta = Organization(name="Beta Operations", slug="beta-ops")
        db.add_all([alpha, beta]); db.flush()
        alpha_manager = User(
            organization_id=alpha.id, email="alpha-ops@example.com", full_name="Alpha Ops Manager",
            password_hash=hash_password(TEST_PASSWORD), role=UserRole.CLAIMS_MANAGER, is_active=True,
        )
        beta_manager = User(
            organization_id=beta.id, email="beta-ops@example.com", full_name="Beta Ops Manager",
            password_hash=hash_password(TEST_PASSWORD), role=UserRole.CLAIMS_MANAGER, is_active=True,
        )
        alpha_vessel = Vessel(organization_id=alpha.id, name="MT ALPHA OPS", imo_number="7000201")
        beta_vessel = Vessel(organization_id=beta.id, name="MT BETA OPS", imo_number="7000202")
        db.add_all([alpha_manager, beta_manager, alpha_vessel, beta_vessel]); db.flush()
        alpha_claim = Claim(
            organization_id=alpha.id, vessel_id=alpha_vessel.id, handler_id=alpha_manager.id,
            claim_reference="MCRI-HM-2026-OPS-A", incident_date=date(2026, 8, 1),
            notification_date=date(2026, 8, 2), incident_description="Synthetic alpha operations claim", currency="USD",
        )
        beta_claim = Claim(
            organization_id=beta.id, vessel_id=beta_vessel.id, handler_id=beta_manager.id,
            claim_reference="MCRI-HM-2026-OPS-B", incident_date=date(2026, 8, 3),
            notification_date=date(2026, 8, 4), incident_description="Synthetic beta operations claim", currency="USD",
        )
        db.add_all([alpha_claim, beta_claim]); db.flush()
        rows = [
            ClaimQaSynthesisRun(
                organization_id=alpha.id, claim_id=alpha_claim.id, requested_by_id=alpha_manager.id,
                retrieval_run_id=None, production_authorization_id=None, status="completed", failure_code=None,
                fallback_used=False, provider_call_made=True, provider="openai", model="gpt-test",
                prompt_bundle_version="prompt-v1", schema_bundle_version="schema-v1",
                authorization_hash="a" * 64, eligibility_policy_hash="b" * 64,
                question_hash="c" * 64, result_set_hash="d" * 64, input_hash="e" * 64,
                output_hash="f" * 64, answer_hash="1" * 64, source_unit_ids=[], source_count=2,
                input_chars=500, input_tokens=100, output_tokens=20, total_tokens=120, latency_ms=900,
                provider_response_id_hash="2" * 64, completed_at=now - timedelta(minutes=1),
            ),
            ClaimQaSynthesisRun(
                organization_id=alpha.id, claim_id=alpha_claim.id, requested_by_id=alpha_manager.id,
                retrieval_run_id=None, production_authorization_id=None, status="verification_failed",
                failure_code="grounding_verification_failed", fallback_used=True, provider_call_made=True,
                provider="openai", model="gpt-test", prompt_bundle_version="prompt-v1",
                schema_bundle_version="schema-v1", authorization_hash="a" * 64,
                eligibility_policy_hash="b" * 64, question_hash="3" * 64, result_set_hash="4" * 64,
                input_hash="5" * 64, output_hash="6" * 64, answer_hash="7" * 64,
                source_unit_ids=[], source_count=3, input_chars=700, input_tokens=150,
                output_tokens=30, total_tokens=180, latency_ms=1400,
                provider_response_id_hash="8" * 64, completed_at=now,
            ),
            ClaimQaSynthesisRun(
                organization_id=beta.id, claim_id=beta_claim.id, requested_by_id=beta_manager.id,
                retrieval_run_id=None, production_authorization_id=None, status="completed", failure_code=None,
                fallback_used=False, provider_call_made=True, provider="openai", model="gpt-test",
                prompt_bundle_version="prompt-v1", schema_bundle_version="schema-v1",
                authorization_hash="9" * 64, eligibility_policy_hash="0" * 64,
                question_hash="a" * 64, result_set_hash="b" * 64, input_hash="c" * 64,
                output_hash="d" * 64, answer_hash="e" * 64, source_unit_ids=[], source_count=1,
                input_chars=300, input_tokens=70, output_tokens=10, total_tokens=80, latency_ms=600,
                provider_response_id_hash="f" * 64, completed_at=now,
            ),
        ]
        db.add_all(rows); db.commit()
        return {
            "alpha_claim": str(alpha_claim.id), "beta_claim": str(beta_claim.id),
            "alpha_org": str(alpha.id), "beta_org": str(beta.id),
        }


def _login(slug: str, email: str) -> None:
    client.cookies.clear()
    response = client.post("/api/v1/auth/login", json={
        "organization_slug": slug, "email": email, "password": TEST_PASSWORD,
    })
    assert response.status_code == 200, response.text


def test_ai_operations_is_tenant_scoped_paginated_and_content_free() -> None:
    ids = _seed()
    _login("alpha-ops", "alpha-ops@example.com")
    first = client.get("/api/v1/ai-operations/events?page=1&page_size=1")
    assert first.status_code == 200, first.text
    payload = first.json()
    assert payload["total"] == 2
    assert payload["has_more"] is True
    assert len(payload["events"]) == 1
    event = payload["events"][0]
    assert event["claim_id"] == ids["alpha_claim"]
    assert event["content_free"] is True
    forbidden = {"question", "answer", "source_unit_ids", "raw_provider_response", "source_passages", "prompt"}
    assert forbidden.isdisjoint(event.keys())

    second = client.get("/api/v1/ai-operations/events?page=2&page_size=1")
    assert second.status_code == 200
    assert second.json()["events"][0]["id"] != event["id"]

    filtered = client.get("/api/v1/ai-operations/events?failure_code=grounding_verification_failed")
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["events"][0]["requires_attention"] is True

    dashboard = client.get("/api/v1/ai-operations")
    assert dashboard.status_code == 200
    metrics = dashboard.json()["metrics"]
    assert metrics["event_count"] == 2
    assert metrics["claim_qa_synthesis_count"] == 2
    assert metrics["verification_failure_count"] == 1
    assert metrics["total_tokens"] == 300
    assert dashboard.json()["raw_claim_or_model_content_exposed"] is False

    _login("beta-ops", "beta-ops@example.com")
    beta = client.get("/api/v1/ai-operations/events")
    assert beta.status_code == 200
    assert beta.json()["total"] == 1
    assert beta.json()["events"][0]["claim_id"] == ids["beta_claim"]


def test_ai_operations_export_is_allowlisted_and_audited() -> None:
    ids = _seed()
    _login("alpha-ops", "alpha-ops@example.com")
    response = client.post("/api/v1/ai-operations/export", json={"format": "json", "filters": {}, "max_rows": 100})
    assert response.status_code == 200, response.text
    assert response.headers["x-ai-operations-content-free"] == "true"
    rows = response.json()
    assert len(rows) == 2
    assert all(row["claim_id"] == ids["alpha_claim"] for row in rows)
    serialized = response.text
    for forbidden in ('"question":', '"answer":', '"source_unit_ids":', '"source_passages":', '"raw_provider_response":'):
        assert forbidden not in serialized
    with TestingSessionLocal() as db:
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "EXPORT_AI_OPERATIONS_GOVERNANCE"))
        assert audit is not None
        assert audit.organization_id == UUID(ids["alpha_org"])
        assert audit.new_values["raw_claim_or_model_content_included"] is False


def test_document_decision_log_normalization_preserves_review_attention_and_metrics(monkeypatch) -> None:
    now = datetime.now(UTC)
    row = SimpleNamespace(
        id=uuid4(), status="queued", human_review_action=None, unsupported_output_count=None,
        source_grounding_total_count=None, source_grounded_output_count=None, reviewed_at=None, queued_at=now,
        claim_id=uuid4(), document_id=uuid4(), task_type="chief_engineer_report", authorization_id=uuid4(),
        authorization_hash="a" * 64, eligibility_decision_id=uuid4(), eligibility_policy_hash="b" * 64,
        eligibility_decision_hash="c" * 64, model="gpt-test", prompt_bundle_version="prompt-v1",
        schema_bundle_version="schema-v1", requested_by_id=uuid4(), reviewed_by_id=None, run_hash="d" * 64,
        review_hash=None, output_candidate_count=None, human_edit_count=None, latency_ms=None,
        observed_provider_cost_microusd=None,
    )
    document_event = operations._doc_event(row)
    assert document_event["human_review_state"] == "pending"
    assert document_event["requires_attention"] is True
    assert "pending_different_human_review" in document_event["attention_reasons"]

    completed_doc = dict(document_event)
    completed_doc.update({
        "human_review_state": "completed", "human_review_action": "edit", "provider_call_made": True,
        "unsupported_output_count": 1, "source_grounded_output_count": 9, "source_grounding_total_count": 10,
        "latency_ms": 1000, "observed_provider_cost_microusd": 250000, "requires_attention": True,
    })
    qa_event = {
        **document_event,
        "id": uuid4(), "workflow_type": "claim_qa_synthesis", "document_id": None, "document_type": None,
        "human_review_state": "not_applicable", "human_review_action": None, "provider_call_made": True,
        "provider": "openai", "status": "verification_failed", "failure_code": "grounding_verification_failed",
        "fallback_used": True, "total_tokens": 120, "latency_ms": 2000,
        "observed_provider_cost_microusd": None, "unsupported_output_count": None,
        "source_grounded_output_count": None, "source_grounding_total_count": None,
    }
    monkeypatch.setattr(operations, "_filtered_events", lambda db, organization_id, filters: [completed_doc, qa_event])
    result = operations.metrics(None, uuid4())
    assert result["event_count"] == 2
    assert result["document_processing_count"] == 1
    assert result["claim_qa_synthesis_count"] == 1
    assert result["edit_count"] == 1
    assert result["unsupported_output_count"] == 1
    assert result["source_grounding_validity_bps"] == 9000
    assert result["verification_failure_count"] == 1
    assert result["total_tokens"] == 120
    assert result["total_observed_provider_cost_microusd"] == 250000
