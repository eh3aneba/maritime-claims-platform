from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.ai_limited_production.models import AILimitedProductionAuthorization
from app.modules.ai_limited_production_outcomes.models import AILimitedProductionOutcomeAssessment
from app.modules.ai_runtime import require_external_ai_runtime_authorization
from app.modules.ai_scale_up.models import AIScaleUpAuthorization
from app.modules.ai_scale_up.service import _rollout_bucket, reserve_run_if_scale_up
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.organizations.models import Organization
from app.modules.processing.models import DocumentProcessingJob, ProcessingJobStatus, ProcessingJobType
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_ai_limited_production_outcomes import _completed_limited_production
from tests.test_ai_private_pilot import _claim_and_user
from tests.test_claims_api import TEST_PASSWORD, login


def setup_function() -> None:
    reset_database()


def _positive_11f() -> dict:
    authorization, _ = _completed_limited_production()
    with TestingSessionLocal() as db:
        limited = db.scalar(select(AILimitedProductionAuthorization).where(
            AILimitedProductionAuthorization.id == UUID(authorization["id"])))
        manager = db.scalar(select(User).where(User.email == "alpha-manager@example.com"))
        assert limited is not None and manager is not None
        assert limited.status == "completed" and limited.decision_hash
        assessment = AILimitedProductionOutcomeAssessment(
            organization_id=limited.organization_id,
            authorization_id=limited.id,
            requested_by_id=manager.id,
            finalized_by_id=manager.id,
            attempt_number=1,
            assessment_key=f"scale-up-positive-anchor-{uuid4()}",
            assessment_profile="limited_production_graduation_v1",
            authorization_decision_hash=limited.decision_hash,
            model=limited.model,
            prompt_bundle_version=limited.prompt_bundle_version,
            schema_bundle_version=limited.schema_bundle_version,
            rollout_percentage=limited.rollout_percentage,
            status="recommended",
            outcome="recommend_graduation_stage",
            metrics={"overall_pass": True, "provider_run_count": 6},
            failure_reasons=[],
            assessment_note="Every Sprint 11F threshold passed.",
            assessment_hash=uuid4().hex * 2,
            assessed_at=datetime.now(UTC),
            decision_note="Recommend designing a separately authorized scale-up stage only.",
            decision_hash=uuid4().hex * 2,
            decided_at=datetime.now(UTC),
        )
        db.add(assessment); db.commit(); db.refresh(assessment)
        return {"id": str(assessment.id), "rollout_percentage": assessment.rollout_percentage}


def _add_security_reviewer() -> None:
    with TestingSessionLocal() as db:
        alpha = db.scalar(select(Organization).where(Organization.slug == "alpha"))
        assert alpha is not None
        if db.scalar(select(User).where(User.email == "alpha-security@example.com")) is None:
            db.add(User(
                organization_id=alpha.id,
                email="alpha-security@example.com",
                full_name="Alpha AI Security Reviewer",
                password_hash=hash_password(TEST_PASSWORD),
                role=UserRole.CLAIMS_MANAGER,
                is_active=True,
            ))
            db.commit()


def _payload(assessment_id: str, **overrides) -> dict:
    payload = {
        "outcome_assessment_id": assessment_id,
        "authorization_key": f"controlled-scale-up-{uuid4()}",
        "allowed_document_types": ["chief_engineer_report", "engine_log"],
        "rollout_percentage": 25,
        "max_claims": 10,
        "max_documents": 30,
        "max_users": 10,
        "max_provider_runs": 100,
        "starts_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
        "deployment_isolation_reference": "artifact://ai-scale-up/deployment-isolation",
        "provider_project_reference": "artifact://ai-scale-up/provider-project",
        "credential_control_reference": "artifact://ai-scale-up/credential-boundary",
        "privacy_legal_reference": "artifact://ai-scale-up/privacy-legal-basis",
        "monitoring_reference": "monitor://ai-scale-up/live-quality-grounding",
        "incident_response_reference": "runbook://ai-scale-up/incident-response",
        "rollback_reference": "runbook://ai-scale-up/rollback-15-minutes",
        "change_ticket_reference": "ticket://ai-scale-up/change-001",
        "confirm_separate_controlled_scale_up": True,
    }
    payload.update(overrides)
    return payload


def _authorize(assessment: dict) -> dict:
    _add_security_reviewer()
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    response = client.post("/api/v1/ai-scale-up/authorizations", json=_payload(assessment["id"]))
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["previous_rollout_percentage"] == assessment["rollout_percentage"]
    assert item["rollout_percentage"] == 25
    assert item["summary"]["production_wide_authorized"] is False
    assert item["summary"]["restricted_documents_authorized"] is False
    assert item["summary"]["new_document_classes_authorized"] is False

    assert client.post(
        f"/api/v1/ai-scale-up/authorizations/{item['id']}/approvals",
        json={"approval_role": "security", "action": "approve",
              "evidence_reference": "artifact://ai-scale-up/self-review",
              "note": "The requester cannot approve their own attempt."},
    ).status_code == 409

    for email, role in [
        ("alpha-security@example.com", "security"),
        ("alpha-risk@example.com", "privacy"),
        ("alpha-product@example.com", "product"),
        ("alpha-operations@example.com", "operations"),
        ("alpha-admin@example.com", "risk"),
    ]:
        client.cookies.clear(); login("alpha", email)
        approved = client.post(
            f"/api/v1/ai-scale-up/authorizations/{item['id']}/approvals",
            json={"approval_role": role, "action": "approve",
                  "evidence_reference": f"artifact://ai-scale-up/{role}-review",
                  "note": f"Independent {role} review reproduced the bounded controls."})
        assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "decision_ready"

    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    decided = client.post(
        f"/api/v1/ai-scale-up/authorizations/{item['id']}/decision",
        json={"outcome": "authorize_scale_up", "confirm_decision": True,
              "note": "Authorize only this exact expiring 25-percent cohort."})
    assert decided.status_code == 200, decided.text
    result = decided.json()
    assert result["status"] == "authorized"
    assert result["summary"]["controlled_scale_up_authorized"] is True
    assert result["summary"]["rollout_above_25_percent_authorized"] is False
    assert len(result["decision_hash"]) == 64
    return result


def _eligible_document(*, restricted: bool = False) -> tuple[str, str]:
    claim, manager, alpha = _claim_and_user()
    document_id = uuid4()
    while _rollout_bucket(document_id) >= 25:
        document_id = uuid4()
    with TestingSessionLocal() as db:
        db.add(Document(
            id=document_id,
            organization_id=alpha.id,
            claim_id=claim.id,
            uploaded_by_id=manager.id,
            document_family_id=uuid4(),
            filename=f"11g-{document_id}.txt",
            original_filename=f"11g-{document_id}.txt",
            document_type="chief_engineer_report",
            mime_type="text/plain",
            file_size_bytes=512,
            file_hash=uuid4().hex * 2,
            storage_key=f"tests/11g-{document_id}.txt",
            confidentiality_level=(ConfidentialityLevel.RESTRICTED if restricted
                                   else ConfidentialityLevel.CONFIDENTIAL),
        ))
        db.commit()
    return str(claim.id), str(document_id)


def _attest(authorization_id: str, claim_id: str, document_id: str):
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    return client.post(
        f"/api/v1/ai-scale-up/authorizations/{authorization_id}/documents",
        json={"claim_id": claim_id, "document_id": document_id,
              "legal_basis_reference": "artifact://ai-scale-up/document-legal-basis",
              "data_minimization_reference": "artifact://ai-scale-up/document-minimization",
              "change_ticket_reference": "ticket://ai-scale-up/document-change",
              "note": "Fresh Sprint 11G eligibility for this current non-restricted document.",
              "confirm_new_scale_up_eligibility": True})


def test_11g_authorizes_only_new_bounded_runtime_and_requires_different_human(monkeypatch) -> None:
    assessment = _positive_11f()
    authorization = _authorize(assessment)

    restricted_claim, restricted_document = _eligible_document(restricted=True)
    assert _attest(authorization["id"], restricted_claim, restricted_document).status_code == 409

    claim_id, document_id = _eligible_document()
    attested = _attest(authorization["id"], claim_id, document_id)
    assert attested.status_code == 201, attested.text
    assert attested.json()["summary"]["previous_document_eligibility_carried_forward"] is False

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
        assert isinstance(allowed, AIScaleUpAuthorization)
        job = DocumentProcessingJob(
            organization_id=document.organization_id, claim_id=document.claim_id,
            document_id=document.id, requested_by_id=manager.id,
            job_type=ProcessingJobType.AI_EXTRACT_CE_REPORT,
            status=ProcessingJobStatus.COMPLETED, available_at=datetime.now(UTC),
            completed_at=datetime.now(UTC), max_attempts=3)
        db.add(job); db.flush()
        run = reserve_run_if_scale_up(
            db, user=manager, document=document,
            expected_document_type="chief_engineer_report", input_char_count=2000,
            processing_job_id=job.id)
        assert run is not None; db.commit(); run_id = str(run.id)

    monkeypatch.setattr(settings, "app_env", "test")
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    payload = {
        "human_review_action": "approve", "output_candidate_count": 100,
        "human_edit_count": 0, "unsupported_output_count": 0,
        "source_grounded_output_count": 100, "source_grounding_total_count": 100,
        "latency_ms": 2500, "observed_provider_cost_microusd": 120000,
        "evidence_reference": "artifact://ai-scale-up/run-review",
        "note": "Different-human review records only content-free observed metrics.",
        "confirm_human_review": True,
    }
    assert client.post(f"/api/v1/ai-scale-up/runs/{run_id}/outcome", json=payload).status_code == 409

    client.cookies.clear(); login("alpha", "alpha-product@example.com")
    reviewed = client.post(f"/api/v1/ai-scale-up/runs/{run_id}/outcome", json=payload)
    assert reviewed.status_code == 200, reviewed.text

    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    monitor = client.post(
        f"/api/v1/ai-scale-up/authorizations/{authorization['id']}/monitors",
        json={"monitor_key": "scale-up-monitor-first-pass",
              "note": "Review, grounding, quality, latency, cost and incident controls pass.",
              "confirm_live_monitor_snapshot": True})
    assert monitor.status_code == 201, monitor.text
    metrics = monitor.json()["monitors"][-1]["metrics"]
    assert metrics["overall_pass"] is True
    assert metrics["source_grounding_validity_bps"] == 10000
    assert metrics["unsupported_output_rate_bps"] == 0

    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    completed = client.post(
        f"/api/v1/ai-scale-up/authorizations/{authorization['id']}/complete",
        json={"confirm_complete": True,
              "note": "Every bounded run is reviewed and the final monitor passes."})
    assert completed.status_code == 200, completed.text
    assert completed.json()["summary"]["production_wide_authorized"] is False


def test_11g_fails_closed_on_rollout_and_safety_incident() -> None:
    assessment = _positive_11f()
    _add_security_reviewer()
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    assert client.post(
        "/api/v1/ai-scale-up/authorizations",
        json=_payload(assessment["id"], rollout_percentage=26)).status_code == 422

    authorization = _authorize(assessment)
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    incident = client.post(
        f"/api/v1/ai-scale-up/authorizations/{authorization['id']}/incidents",
        json={"severity": "medium", "category": "privacy",
              "evidence_reference": "ticket://ai-scale-up/privacy-incident",
              "note": "Privacy-boundary incident immediately pauses and rolls back the cohort.",
              "confirm_pause_and_rollback": True})
    assert incident.status_code == 201, incident.text
    assert incident.json()["status"] == "paused"

    incident_id = incident.json()["incidents"][-1]["id"]
    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    resolved = client.post(
        f"/api/v1/ai-scale-up/authorizations/{authorization['id']}/incidents/{incident_id}/resolve",
        json={"resolution_reference": "artifact://ai-scale-up/privacy-resolution",
              "resolution_note": "Remediated, but safety history requires a new authorization attempt.",
              "confirm_resolution": True})
    assert resolved.status_code == 200, resolved.text
    resume = client.post(
        f"/api/v1/ai-scale-up/authorizations/{authorization['id']}/resume",
        json={"confirm_resume": True,
              "note": "Safety-boundary history must prevent same-attempt resume."})
    assert resume.status_code == 409
    assert resolved.json()["summary"]["production_wide_authorized"] is False
    assert resolved.json()["summary"]["new_document_classes_authorized"] is False
