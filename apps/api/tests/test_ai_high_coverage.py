from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.ai_broader_production.models import AIBroaderProductionAuthorization
from app.modules.ai_broader_production_outcomes.models import AIBroaderProductionOutcomeAssessment
from app.modules.ai_high_coverage.models import AIHighCoverageAuthorization
from app.modules.ai_high_coverage.service import _rollout_bucket, reserve_run_if_high_coverage
from app.modules.ai_runtime import require_external_ai_runtime_authorization
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.organizations.models import Organization
from app.modules.processing.models import DocumentProcessingJob, ProcessingJobStatus, ProcessingJobType
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_ai_broader_production_outcomes import _completed_broader_production
from tests.test_ai_private_pilot import _claim_and_user
from tests.test_claims_api import TEST_PASSWORD, login


def setup_function() -> None:
    reset_database()


def _positive_11j() -> dict:
    authorization, _ = _completed_broader_production()
    with TestingSessionLocal() as db:
        broader = db.scalar(select(AIBroaderProductionAuthorization).where(
            AIBroaderProductionAuthorization.id == UUID(authorization["id"])))
        manager = db.scalar(select(User).where(User.email == "alpha-manager@example.com"))
        assert broader is not None and manager is not None
        assessment = AIBroaderProductionOutcomeAssessment(
            organization_id=broader.organization_id, broader_production_authorization_id=broader.id,
            requested_by_id=manager.id, finalized_by_id=manager.id, attempt_number=1,
            assessment_key=f"11k-positive-readiness-{uuid4()}", assessment_profile="broader_production_readiness_v1",
            broader_production_decision_hash=broader.decision_hash,
            readiness_assessment_hash=broader.readiness_assessment_hash, readiness_decision_hash=broader.readiness_decision_hash,
            scale_up_decision_hash=broader.scale_up_decision_hash,
            inherited_outcome_assessment_hash=broader.inherited_outcome_assessment_hash,
            inherited_outcome_decision_hash=broader.inherited_outcome_decision_hash,
            model=broader.model, prompt_bundle_version=broader.prompt_bundle_version,
            schema_bundle_version=broader.schema_bundle_version, rollout_percentage=broader.rollout_percentage,
            status="recommended", outcome="recommend_next_broader_stage", metrics={"overall_pass": True, "run_count": 40},
            failure_reasons=[], assessment_note="All Sprint 11J maturity thresholds passed.",
            assessment_hash=uuid4().hex * 2, assessed_at=datetime.now(UTC),
            decision_note="Recommend only a separately authorized high-coverage stage.",
            decision_hash=uuid4().hex * 2, decided_at=datetime.now(UTC))
        db.add(assessment); db.commit(); db.refresh(assessment)
        return {"id": str(assessment.id), "previous_rollout": broader.rollout_percentage}


def _add_11k_users() -> None:
    with TestingSessionLocal() as db:
        alpha = db.scalar(select(Organization).where(Organization.slug == "alpha")); assert alpha is not None
        for email, name, role in [
            ("alpha-ai-quality@example.com", "Alpha AI Quality Reviewer", UserRole.CLAIMS_MANAGER),
            ("alpha-11k-admin@example.com", "Alpha 11K Final Admin", UserRole.ADMIN),
        ]:
            if db.scalar(select(User).where(User.email == email)) is None:
                db.add(User(organization_id=alpha.id, email=email, full_name=name,
                            password_hash=hash_password(TEST_PASSWORD), role=role, is_active=True))
        db.commit()


def _payload(outcome_id: str, **overrides) -> dict:
    payload = {"outcome_assessment_id": outcome_id, "authorization_key": f"high-coverage-{uuid4()}",
        "allowed_document_types": ["chief_engineer_report", "engine_log"], "rollout_percentage": 75,
        "max_claims": 30, "max_documents": 90, "max_users": 30, "max_provider_runs": 400,
        "starts_at": datetime.now(UTC).isoformat(), "expires_at": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
        "deployment_isolation_reference": "artifact://ai-high-coverage/deployment-isolation",
        "provider_project_reference": "artifact://ai-high-coverage/provider-project",
        "credential_control_reference": "artifact://ai-high-coverage/credential-control",
        "privacy_legal_reference": "artifact://ai-high-coverage/privacy-legal",
        "monitoring_reference": "monitor://ai-high-coverage/live-controls",
        "incident_response_reference": "runbook://ai-high-coverage/incident-response",
        "rollback_reference": "runbook://ai-high-coverage/rollback-15-minutes",
        "change_ticket_reference": "ticket://ai-high-coverage/change-001", "confirm_separate_high_coverage": True}
    payload.update(overrides); return payload


def _authorize(readiness: dict) -> dict:
    _add_11k_users(); client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    created = client.post("/api/v1/ai-high-coverage/authorizations", json=_payload(readiness["id"]))
    assert created.status_code == 201, created.text
    item = created.json(); assert 26 <= item["previous_rollout_percentage"] <= 50; assert item["rollout_percentage"] == 75
    self_review = client.post(f"/api/v1/ai-high-coverage/authorizations/{item['id']}/approvals",
        json={"approval_role": "security", "action": "approve", "evidence_reference": "artifact://ai-high-coverage/self-review",
              "note": "The requester must not approve the high-coverage authorization."})
    assert self_review.status_code == 409
    for email, role in [("alpha-security@example.com", "security"), ("alpha-risk@example.com", "privacy"),
        ("alpha-product@example.com", "product"), ("alpha-operations@example.com", "operations"),
        ("alpha-admin@example.com", "risk"), ("alpha-governance@example.com", "claims_governance"),
        ("alpha-ai-quality@example.com", "ai_quality")]:
        client.cookies.clear(); login("alpha", email)
        approval = client.post(f"/api/v1/ai-high-coverage/authorizations/{item['id']}/approvals",
            json={"approval_role": role, "action": "approve",
                  "evidence_reference": f"artifact://ai-high-coverage/{role}-approval",
                  "note": f"Independent {role} reviewer reproduced the bounded Sprint 11K controls."})
        assert approval.status_code == 200, approval.text
    assert approval.json()["status"] == "decision_ready"
    client.cookies.clear(); login("alpha", "alpha-11k-admin@example.com")
    decided = client.post(f"/api/v1/ai-high-coverage/authorizations/{item['id']}/decision",
        json={"outcome": "authorize_high_coverage_cohort", "confirm_decision": True,
              "note": "Authorize only this exact expiring 75-percent high-coverage cohort."})
    assert decided.status_code == 200, decided.text
    result = decided.json(); assert result["status"] == "authorized"; assert len(result["decision_hash"]) == 64
    assert result["summary"]["production_wide_authorized"] is False; return result


def _eligible_document(*, restricted: bool = False) -> tuple[str, str]:
    claim, manager, alpha = _claim_and_user(); document_id = uuid4()
    while _rollout_bucket(document_id) >= 75: document_id = uuid4()
    with TestingSessionLocal() as db:
        db.add(Document(id=document_id, organization_id=alpha.id, claim_id=claim.id, uploaded_by_id=manager.id,
            document_family_id=uuid4(), filename=f"11k-{document_id}.txt", original_filename=f"11k-{document_id}.txt",
            document_type="chief_engineer_report", mime_type="text/plain", file_size_bytes=512,
            file_hash=uuid4().hex * 2, storage_key=f"tests/11k-{document_id}.txt",
            confidentiality_level=(ConfidentialityLevel.RESTRICTED if restricted else ConfidentialityLevel.CONFIDENTIAL)))
        db.commit()
    return str(claim.id), str(document_id)


def _attest(authorization_id: str, claim_id: str, document_id: str):
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    return client.post(f"/api/v1/ai-high-coverage/authorizations/{authorization_id}/documents",
        json={"claim_id": claim_id, "document_id": document_id,
              "legal_basis_reference": "artifact://ai-high-coverage/document-legal",
              "data_minimization_reference": "artifact://ai-high-coverage/document-minimization",
              "change_ticket_reference": "ticket://ai-high-coverage/document-change",
              "note": "Fresh Sprint 11K eligibility for this current non-restricted document.",
              "confirm_new_high_coverage_eligibility": True})


def test_11k_requires_positive_11j_seven_approvals_and_fresh_eligibility(monkeypatch) -> None:
    readiness = _positive_11j(); client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    assert client.post("/api/v1/ai-high-coverage/authorizations", json=_payload(readiness["id"], rollout_percentage=76)).status_code == 422
    authorization = _authorize(readiness)
    restricted_claim, restricted_doc = _eligible_document(restricted=True)
    assert _attest(authorization["id"], restricted_claim, restricted_doc).status_code == 409
    claim_id, document_id = _eligible_document(); attested = _attest(authorization["id"], claim_id, document_id)
    assert attested.status_code == 201, attested.text
    settings = get_settings(); monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "ai_model", authorization["model"])
    monkeypatch.setattr(settings, "ai_prompt_bundle_version", authorization["prompt_bundle_version"])
    monkeypatch.setattr(settings, "ai_schema_bundle_version", authorization["schema_bundle_version"])
    monkeypatch.setattr(settings, "ai_max_output_tokens", authorization["max_output_tokens"])
    with TestingSessionLocal() as db:
        document = db.scalar(select(Document).where(Document.id == UUID(document_id)))
        manager = db.scalar(select(User).where(User.email == "alpha-manager@example.com")); assert document and manager
        runtime = require_external_ai_runtime_authorization(db, organization_id=document.organization_id, document=document,
            expected_document_type="chief_engineer_report", input_char_count=2000, requested_by_id=manager.id)
        assert isinstance(runtime, AIHighCoverageAuthorization)
        job = DocumentProcessingJob(organization_id=document.organization_id, claim_id=document.claim_id,
            document_id=document.id, requested_by_id=manager.id, job_type=ProcessingJobType.AI_EXTRACT_CE_REPORT,
            status=ProcessingJobStatus.COMPLETED, available_at=datetime.now(UTC), completed_at=datetime.now(UTC), max_attempts=3)
        db.add(job); db.flush()
        run = reserve_run_if_high_coverage(db, user=manager, document=document,
            expected_document_type="chief_engineer_report", input_char_count=2000, processing_job_id=job.id)
        assert run is not None; db.commit(); run_id = str(run.id)
    monkeypatch.setattr(settings, "app_env", "test")
    payload = {"human_review_action": "approve", "output_candidate_count": 100, "human_edit_count": 0,
        "unsupported_output_count": 0, "source_grounded_output_count": 100, "source_grounding_total_count": 100,
        "latency_ms": 2500, "observed_provider_cost_microusd": 120000,
        "evidence_reference": "artifact://ai-high-coverage/run-review",
        "note": "Different-human review records only content-free observed metrics.", "confirm_human_review": True}
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    assert client.post(f"/api/v1/ai-high-coverage/runs/{run_id}/outcome", json=payload).status_code == 409
    client.cookies.clear(); login("alpha", "alpha-product@example.com")
    assert client.post(f"/api/v1/ai-high-coverage/runs/{run_id}/outcome", json=payload).status_code == 200
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    monitor = client.post(f"/api/v1/ai-high-coverage/authorizations/{authorization['id']}/monitors",
        json={"monitor_key": "11k-monitor-first-pass",
              "note": "Human review, grounding, quality, latency, cost and incident controls pass.",
              "confirm_live_monitor_snapshot": True})
    assert monitor.status_code == 201, monitor.text; assert monitor.json()["monitors"][-1]["metrics"]["overall_pass"] is True
    client.cookies.clear(); login("alpha", "alpha-11k-admin@example.com")
    completed = client.post(f"/api/v1/ai-high-coverage/authorizations/{authorization['id']}/complete",
        json={"confirm": True, "note": "Every bounded provider run is human-reviewed and the final monitor passes."})
    assert completed.status_code == 200, completed.text; result = completed.json()
    assert result["summary"]["production_wide_authorized"] is False; assert len(result["completion_hash"]) == 64


def test_11k_safety_incident_blocks_resume_and_runtime_fallback(monkeypatch) -> None:
    authorization = _authorize(_positive_11j()); claim_id, document_id = _eligible_document()
    assert _attest(authorization["id"], claim_id, document_id).status_code == 201
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    incident = client.post(f"/api/v1/ai-high-coverage/authorizations/{authorization['id']}/incidents",
        json={"severity": "medium", "category": "privacy", "evidence_reference": "ticket://ai-high-coverage/privacy-incident",
              "note": "Privacy-boundary incident immediately pauses and rolls back Sprint 11K.",
              "confirm_pause_and_rollback": True})
    assert incident.status_code == 201; incident_id = incident.json()["incidents"][-1]["id"]
    client.cookies.clear(); login("alpha", "alpha-11k-admin@example.com")
    assert client.post(f"/api/v1/ai-high-coverage/authorizations/{authorization['id']}/incidents/{incident_id}/resolve",
        json={"resolution_reference": "artifact://ai-high-coverage/privacy-resolution",
              "resolution_note": "Incident remediated, but safety history remains a permanent attempt blocker.",
              "confirm_resolution": True}).status_code == 200
    assert client.post(f"/api/v1/ai-high-coverage/authorizations/{authorization['id']}/resume",
        json={"confirm": True, "note": "Safety-boundary history requires a new authorization attempt."}).status_code == 409
    settings = get_settings(); monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "ai_model", authorization["model"])
    monkeypatch.setattr(settings, "ai_prompt_bundle_version", authorization["prompt_bundle_version"])
    monkeypatch.setattr(settings, "ai_schema_bundle_version", authorization["schema_bundle_version"])
    monkeypatch.setattr(settings, "ai_max_output_tokens", authorization["max_output_tokens"])
    with TestingSessionLocal() as db:
        document = db.scalar(select(Document).where(Document.id == UUID(document_id)))
        manager = db.scalar(select(User).where(User.email == "alpha-manager@example.com")); assert document and manager
        try:
            require_external_ai_runtime_authorization(db, organization_id=document.organization_id, document=document,
                expected_document_type="chief_engineer_report", input_char_count=2000, requested_by_id=manager.id)
            assert False, "Paused Sprint 11K must never fall back to Sprint 11I/11G/11E"
        except HTTPException as exc:
            assert exc.status_code == 409
