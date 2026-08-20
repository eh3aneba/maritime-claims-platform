from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.ai_governance.service import require_external_ai_runtime_authorization
from app.modules.ai_limited_production.models import AILimitedProductionAuthorization
from app.modules.ai_limited_production.service import (
    _rollout_bucket,
    reserve_run_if_limited_production,
)
from app.modules.ai_pilot_outcomes.models import AIPilotOutcomeAssessment
from app.modules.ai_private_pilot.models import AIPrivatePilotAuthorization
from app.modules.audit.models import AuditLog
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.organizations.models import Organization
from app.modules.processing.models import (
    DocumentProcessingJob,
    ProcessingJobStatus,
    ProcessingJobType,
)
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_ai_pilot_outcomes import _completed_pilot
from tests.test_ai_private_pilot import _claim_and_user
from tests.test_claims_api import TEST_PASSWORD, login


def setup_function() -> None:
    reset_database()


def _recommended_outcome() -> tuple[dict, AIPilotOutcomeAssessment]:
    pilot, _ = _completed_pilot()
    with TestingSessionLocal() as db:
        pilot_row = db.scalar(select(AIPrivatePilotAuthorization).where(
            AIPrivatePilotAuthorization.id == UUID(pilot["id"])))
        manager = db.scalar(select(User).where(User.email == "alpha-manager@example.com"))
        assert pilot_row is not None and manager is not None
        assessment = AIPilotOutcomeAssessment(
            organization_id=pilot_row.organization_id, pilot_id=pilot_row.id,
            requested_by_id=manager.id, finalized_by_id=manager.id,
            attempt_number=1, assessment_key="recommended-limited-production-anchor",
            assessment_profile="private_pilot_exit_v1", status="recommended",
            outcome="recommend_limited_production_evaluation",
            metrics={"overall_pass": True, "run_count": 6}, failure_reasons=[],
            assessment_note="Every Sprint 11D threshold and independent review passed.",
            assessment_hash="a" * 64, assessed_at=datetime.now(UTC),
            decision_note="Recommend a separately authorized limited-production evaluation.",
            decision_hash="b" * 64, decided_at=datetime.now(UTC),
        )
        db.add(assessment); db.commit(); db.refresh(assessment); db.expunge(assessment)
    return pilot, assessment


def _add_operations_reviewer() -> None:
    with TestingSessionLocal() as db:
        alpha = db.scalar(select(Organization).where(Organization.slug == "alpha"))
        assert alpha is not None
        db.add(User(
            organization_id=alpha.id, email="alpha-operations@example.com",
            full_name="Alpha AI Operations Reviewer",
            password_hash=hash_password(TEST_PASSWORD),
            role=UserRole.CLAIMS_MANAGER, is_active=True))
        db.commit()


def _authorization_payload(assessment_id: UUID, **overrides) -> dict:
    payload = {
        "outcome_assessment_id": str(assessment_id),
        "authorization_key": "limited-production-evaluation-attempt-one",
        "allowed_document_types": ["chief_engineer_report", "engine_log"],
        "rollout_percentage": 10, "max_claims": 5, "max_documents": 15,
        "max_users": 5, "max_provider_runs": 50,
        "starts_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
        "deployment_isolation_reference": "artifact://ai-limited-production/deployment-isolation",
        "provider_project_reference": "artifact://ai-limited-production/provider-project",
        "credential_control_reference": "artifact://ai-limited-production/credential-control",
        "data_processing_reference": "artifact://ai-limited-production/data-processing",
        "monitoring_reference": "monitor://ai-limited-production/live-controls",
        "rollback_reference": "runbook://ai-limited-production/rollback",
        "change_ticket_reference": "ticket://ai-limited-production/change-001",
        "confirm_separate_limited_production_evaluation": True,
    }
    payload.update(overrides)
    return payload


def _create_and_authorize(assessment_id: UUID) -> dict:
    _add_operations_reviewer()
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    created = client.post(
        "/api/v1/ai-limited-production/authorizations",
        json=_authorization_payload(assessment_id))
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["status"] == "pending_approvals"
    assert item["rollout_percentage"] == 10
    assert item["controls"]["rollback_slo_minutes"] == 15
    assert item["summary"]["production_wide_authorized"] is False
    self_review = client.post(
        f"/api/v1/ai-limited-production/authorizations/{item['id']}/approvals",
        json={"approval_role": "security", "action": "approve",
              "evidence_reference": "artifact://ai-limited-production/self-review",
              "note": "The requester must not approve their own authorization."})
    assert self_review.status_code == 409
    reviewers = [
        ("alpha-admin@example.com", "security"),
        ("alpha-risk@example.com", "privacy"),
        ("alpha-product@example.com", "product"),
        ("alpha-operations@example.com", "operations"),
    ]
    for email, role in reviewers:
        client.cookies.clear(); login("alpha", email)
        response = client.post(
            f"/api/v1/ai-limited-production/authorizations/{item['id']}/approvals",
            json={"approval_role": role, "action": "approve",
                  "evidence_reference": f"artifact://ai-limited-production/{role}-review",
                  "note": f"Independent {role} reviewer approved the exact bounded controls."})
        assert response.status_code == 200, response.text
    assert response.json()["status"] == "decision_ready"
    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    decision = client.post(
        f"/api/v1/ai-limited-production/authorizations/{item['id']}/decision",
        json={"outcome": "authorize_limited_evaluation", "confirm_decision": True,
              "note": "Admin authorized only this expiring limited-production evaluation."})
    assert decision.status_code == 200, decision.text
    result = decision.json()
    assert result["status"] == "authorized"
    assert result["summary"]["limited_production_evaluation_authorized"] is True
    assert result["summary"]["production_wide_authorized"] is False
    assert result["summary"]["restricted_documents_authorized"] is False
    assert len(result["decision_hash"]) == 64
    return result


def _document_for_bucket(*, accepted: bool,
                         confidentiality=ConfidentialityLevel.CONFIDENTIAL) -> tuple[str, str]:
    claim, manager, alpha = _claim_and_user()
    document_id = uuid4()
    while (_rollout_bucket(document_id) < 10) != accepted:
        document_id = uuid4()
    with TestingSessionLocal() as db:
        document = Document(
            id=document_id, organization_id=alpha.id, claim_id=claim.id,
            uploaded_by_id=manager.id, document_family_id=uuid4(),
            filename=f"limited-{document_id}.txt",
            original_filename=f"limited-{document_id}.txt",
            document_type="chief_engineer_report", mime_type="text/plain",
            file_size_bytes=256, file_hash=document_id.hex * 2,
            storage_key=f"tests/limited-{document_id}.txt",
            confidentiality_level=confidentiality,
        )
        db.add(document); db.commit()
    return str(claim.id), str(document_id)


def _attest(authorization_id: str, claim_id: str, document_id: str):
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    return client.post(
        f"/api/v1/ai-limited-production/authorizations/{authorization_id}/documents",
        json={
            "claim_id": claim_id, "document_id": document_id,
            "legal_basis_reference": "artifact://ai-limited-production/document-legal-basis",
            "data_minimization_reference": "artifact://ai-limited-production/document-minimization",
            "change_ticket_reference": "ticket://ai-limited-production/document-change",
            "note": "Manager verified a current non-restricted document inside the rollout bucket.",
            "confirm_non_restricted_rollout_document": True,
        })


def test_limited_production_requires_separate_approvals_runtime_monitor_and_rollback(
        monkeypatch) -> None:
    _, assessment = _recommended_outcome()
    authorization = _create_and_authorize(assessment.id)

    outside_claim, outside_document = _document_for_bucket(accepted=False)
    assert _attest(authorization["id"], outside_claim, outside_document).status_code == 409
    restricted_claim, restricted_document = _document_for_bucket(
        accepted=True, confidentiality=ConfidentialityLevel.RESTRICTED)
    assert _attest(authorization["id"], restricted_claim, restricted_document).status_code == 409

    claim_id, document_id = _document_for_bucket(accepted=True)
    attested = _attest(authorization["id"], claim_id, document_id)
    assert attested.status_code == 201, attested.text
    eligibility = attested.json()["document_eligibility"][0]
    assert eligibility["rollout_bucket"] < authorization["rollout_percentage"]
    assert eligibility["status"] == "eligible"

    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "ai_model", authorization["model"])
    monkeypatch.setattr(settings, "ai_prompt_bundle_version", authorization["prompt_bundle_version"])
    monkeypatch.setattr(settings, "ai_schema_bundle_version", authorization["schema_bundle_version"])
    monkeypatch.setattr(settings, "ai_max_output_tokens", authorization["max_output_tokens"])
    with TestingSessionLocal() as db:
        document = db.scalar(select(Document).where(Document.id == UUID(document_id)))
        manager = db.scalar(select(User).where(User.email == "alpha-manager@example.com"))
        assert document is not None and manager is not None
        allowed = require_external_ai_runtime_authorization(
            db, organization_id=document.organization_id, document=document,
            expected_document_type="chief_engineer_report", input_char_count=2000,
            requested_by_id=manager.id)
        assert str(allowed.id) == authorization["id"]
        job = DocumentProcessingJob(
            organization_id=document.organization_id, claim_id=document.claim_id,
            document_id=document.id, requested_by_id=manager.id,
            job_type=ProcessingJobType.AI_EXTRACT_CE_REPORT,
            status=ProcessingJobStatus.COMPLETED, available_at=datetime.now(UTC),
            completed_at=datetime.now(UTC), max_attempts=3)
        db.add(job); db.flush()
        run = reserve_run_if_limited_production(
            db, user=manager, document=document,
            expected_document_type="chief_engineer_report", input_char_count=2000,
            processing_job_id=job.id)
        assert run is not None; db.commit(); run_id = str(run.id)

    monkeypatch.setattr(settings, "app_env", "test")
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    self_review = client.post(
        f"/api/v1/ai-limited-production/runs/{run_id}/outcome",
        json={"human_review_action": "approve", "output_candidate_count": 5,
              "human_edit_count": 0, "latency_ms": 2500,
              "observed_provider_cost_microusd": 120000,
              "evidence_reference": "artifact://ai-limited-production/run-review",
              "note": "A different human must review every Production candidate.",
              "confirm_human_review": True})
    assert self_review.status_code == 409
    client.cookies.clear(); login("alpha", "alpha-product@example.com")
    reviewed = client.post(
        f"/api/v1/ai-limited-production/runs/{run_id}/outcome",
        json={"human_review_action": "approve", "output_candidate_count": 5,
              "human_edit_count": 0, "latency_ms": 2500,
              "observed_provider_cost_microusd": 120000,
              "evidence_reference": "artifact://ai-limited-production/run-review",
              "note": "Different human approved the candidates before any downstream use.",
              "confirm_human_review": True})
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["summary"]["human_reviewed_run_count"] == 1

    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    monitor = client.post(
        f"/api/v1/ai-limited-production/authorizations/{authorization['id']}/monitors",
        json={"monitor_key": "live-monitor-first-pass",
              "note": "Human review, latency, cost and incident thresholds are passing.",
              "confirm_live_monitor_snapshot": True})
    assert monitor.status_code == 201, monitor.text
    assert monitor.json()["monitors"][0]["status"] == "pass"
    incident = client.post(
        f"/api/v1/ai-limited-production/authorizations/{authorization['id']}/incidents",
        json={"severity": "high", "category": "quality",
              "evidence_reference": "ticket://ai-limited-production/incident-001",
              "note": "Live quality control triggered immediate pause and rollback.",
              "confirm_pause_and_rollback": True})
    assert incident.status_code == 201 and incident.json()["status"] == "paused"
    incident_id = incident.json()["incidents"][0]["id"]
    monkeypatch.setattr(settings, "app_env", "production")
    with TestingSessionLocal() as db:
        document = db.scalar(select(Document).where(Document.id == UUID(document_id)))
        with pytest.raises(HTTPException, match="No active limited-production"):
            require_external_ai_runtime_authorization(
                db, organization_id=document.organization_id, document=document,
                expected_document_type="chief_engineer_report", input_char_count=2000)

    monkeypatch.setattr(settings, "app_env", "test")
    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    unsafe_resume = client.post(
        f"/api/v1/ai-limited-production/authorizations/{authorization['id']}/incidents/{incident_id}/resolve",
        json={"resolution_reference": "artifact://ai-limited-production/incident-resolution",
              "resolution_note": "Resolution and resume must remain separate operations.",
              "resume_authorization": True, "confirm_resolution": True})
    assert unsafe_resume.status_code == 422
    resolved = client.post(
        f"/api/v1/ai-limited-production/authorizations/{authorization['id']}/incidents/{incident_id}/resolve",
        json={"resolution_reference": "artifact://ai-limited-production/incident-resolution",
              "resolution_note": "Administrator verified remediation before a new monitor.",
              "resume_authorization": False, "confirm_resolution": True})
    assert resolved.status_code == 200 and resolved.json()["status"] == "paused"
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    recovery_monitor = client.post(
        f"/api/v1/ai-limited-production/authorizations/{authorization['id']}/monitors",
        json={"monitor_key": "live-monitor-recovery-pass",
              "note": "Post-remediation human review, latency, cost and incident controls pass.",
              "confirm_live_monitor_snapshot": True})
    assert recovery_monitor.status_code == 201
    assert recovery_monitor.json()["monitors"][-1]["status"] == "pass"
    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    resumed = client.post(
        f"/api/v1/ai-limited-production/authorizations/{authorization['id']}/resume",
        json={"confirm_resume": True,
              "note": "Admin verified resolved incidents and a fresh passing monitor."})
    assert resumed.status_code == 200 and resumed.json()["status"] == "authorized"
    completed = client.post(
        f"/api/v1/ai-limited-production/authorizations/{authorization['id']}/complete",
        json={"confirm_complete": True,
              "note": "All bounded runs were reviewed and the recovery monitor passes."})
    assert completed.status_code == 200, completed.text
    result = completed.json()
    assert result["status"] == "completed"
    assert result["summary"]["production_wide_authorized"] is False
    assert result["summary"]["restricted_documents_authorized"] is False
    assert result["summary"]["authoritative_facts_auto_updated"] is False

    with TestingSessionLocal() as db:
        actions = set(db.scalars(select(AuditLog.action).where(
            AuditLog.organization_id == UUID(str(assessment.organization_id)))))
        assert {"CREATE_AI_LIMITED_PRODUCTION_AUTHORIZATION",
                "AUTHORIZE_LIMITED_EVALUATION_AI_LIMITED_PRODUCTION",
                "PAUSE_AI_LIMITED_PRODUCTION_INCIDENT",
                "COMPLETE_AI_LIMITED_PRODUCTION"}.issubset(actions)


def test_limited_production_requires_positive_anchor_rejects_raw_fields_and_is_tenant_scoped() -> None:
    _, assessment = _recommended_outcome()
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    raw = _authorization_payload(assessment.id)
    raw["provider_secret"] = "must-not-enter-ledger"
    assert client.post(
        "/api/v1/ai-limited-production/authorizations", json=raw).status_code == 422
    created = client.post(
        "/api/v1/ai-limited-production/authorizations",
        json=_authorization_payload(
            assessment.id, authorization_key="tenant-scope-anchor"))
    assert created.status_code == 201, created.text
    with TestingSessionLocal() as db:
        stored = db.scalar(select(AIPilotOutcomeAssessment).where(
            AIPilotOutcomeAssessment.id == assessment.id))
        stored.status = "failed"; stored.outcome = "thresholds_failed"
        db.commit()
    rejected = client.post(
        "/api/v1/ai-limited-production/authorizations",
        json=_authorization_payload(assessment.id, authorization_key="failed-anchor-attempt"))
    assert rejected.status_code == 409

    with TestingSessionLocal() as db:
        beta = db.scalar(select(Organization).where(Organization.slug == "beta"))
        assert beta is not None
        beta_id = beta.id
        db.add(User(
            organization_id=beta.id, email="beta-limited@example.com",
            full_name="Beta Limited Production Manager",
            password_hash=hash_password(TEST_PASSWORD),
            role=UserRole.CLAIMS_MANAGER, is_active=True))
        db.commit()
    client.cookies.clear(); login("beta", "beta-limited@example.com")
    dashboard = client.get("/api/v1/ai-limited-production")
    assert dashboard.status_code == 200 and dashboard.json() == {"authorizations": []}

    with TestingSessionLocal() as db:
        stored = list(db.scalars(select(AILimitedProductionAuthorization)))
        assert len(stored) == 1
        assert stored[0].organization_id != beta_id
