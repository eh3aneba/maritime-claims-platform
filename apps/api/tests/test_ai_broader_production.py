from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.ai_broader_production.models import AIBroaderProductionAuthorization
from app.modules.ai_broader_production.service import _rollout_bucket, reserve_run_if_broader_production
from app.modules.ai_runtime import require_external_ai_runtime_authorization
from app.modules.ai_scale_up.models import AIScaleUpAuthorization
from app.modules.ai_scale_up_outcomes.models import AIScaleUpOutcomeAssessment
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.organizations.models import Organization
from app.modules.processing.models import DocumentProcessingJob, ProcessingJobStatus, ProcessingJobType
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_ai_scale_up_outcomes import _completed_scale_up
from tests.test_ai_private_pilot import _claim_and_user
from tests.test_claims_api import TEST_PASSWORD, login


def setup_function() -> None:
    reset_database()


def _positive_11h() -> dict:
    authorization, _ = _completed_scale_up()
    with TestingSessionLocal() as db:
        scale_up = db.scalar(select(AIScaleUpAuthorization).where(
            AIScaleUpAuthorization.id == UUID(authorization["id"])))
        manager = db.scalar(select(User).where(User.email == "alpha-manager@example.com"))
        assert scale_up is not None and manager is not None
        assert scale_up.status == "completed" and scale_up.decision_hash
        assessment = AIScaleUpOutcomeAssessment(
            organization_id=scale_up.organization_id,
            scale_up_authorization_id=scale_up.id,
            requested_by_id=manager.id,
            finalized_by_id=manager.id,
            attempt_number=1,
            assessment_key=f"11i-positive-readiness-{uuid4()}",
            assessment_profile="controlled_scale_up_readiness_v1",
            scale_up_decision_hash=scale_up.decision_hash,
            outcome_assessment_hash=scale_up.outcome_assessment_hash,
            outcome_decision_hash=scale_up.outcome_decision_hash,
            model=scale_up.model,
            prompt_bundle_version=scale_up.prompt_bundle_version,
            schema_bundle_version=scale_up.schema_bundle_version,
            rollout_percentage=scale_up.rollout_percentage,
            status="recommended",
            outcome="recommend_broader_production_stage",
            metrics={"overall_pass": True, "run_count": 20},
            failure_reasons=[],
            assessment_note="All Sprint 11H readiness thresholds passed.",
            assessment_hash=uuid4().hex * 2,
            assessed_at=datetime.now(UTC),
            decision_note="Recommend only a separately authorized broader-production cohort.",
            decision_hash=uuid4().hex * 2,
            decided_at=datetime.now(UTC),
        )
        db.add(assessment)
        db.commit()
        db.refresh(assessment)
        return {"id": str(assessment.id), "previous_rollout": scale_up.rollout_percentage}


def _add_governance_reviewer() -> None:
    with TestingSessionLocal() as db:
        alpha = db.scalar(select(Organization).where(Organization.slug == "alpha"))
        assert alpha is not None
        if db.scalar(select(User).where(User.email == "alpha-governance@example.com")) is None:
            db.add(User(
                organization_id=alpha.id,
                email="alpha-governance@example.com",
                full_name="Alpha Claims Governance Reviewer",
                password_hash=hash_password(TEST_PASSWORD),
                role=UserRole.CLAIMS_MANAGER,
                is_active=True,
            ))
            db.commit()


def _payload(readiness_id: str, **overrides) -> dict:
    payload = {
        "readiness_assessment_id": readiness_id,
        "authorization_key": f"broader-production-{uuid4()}",
        "allowed_document_types": ["chief_engineer_report", "engine_log"],
        "rollout_percentage": 50,
        "max_claims": 20,
        "max_documents": 60,
        "max_users": 20,
        "max_provider_runs": 200,
        "starts_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
        "deployment_isolation_reference": "artifact://ai-broader-production/deployment-isolation",
        "provider_project_reference": "artifact://ai-broader-production/provider-project",
        "credential_control_reference": "artifact://ai-broader-production/credential-control",
        "privacy_legal_reference": "artifact://ai-broader-production/privacy-legal",
        "monitoring_reference": "monitor://ai-broader-production/live-controls",
        "incident_response_reference": "runbook://ai-broader-production/incident-response",
        "rollback_reference": "runbook://ai-broader-production/rollback-15-minutes",
        "change_ticket_reference": "ticket://ai-broader-production/change-001",
        "confirm_separate_broader_production": True,
    }
    payload.update(overrides)
    return payload


def _authorize(readiness: dict) -> dict:
    _add_governance_reviewer()
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    created = client.post("/api/v1/ai-broader-production/authorizations", json=_payload(readiness["id"]))
    assert created.status_code == 201, created.text
    item = created.json()
    assert 11 <= item["previous_rollout_percentage"] <= 25
    assert item["rollout_percentage"] == 50
    assert item["summary"]["production_wide_authorized"] is False
    assert item["summary"]["rollout_above_50_percent_authorized"] is False

    self_review = client.post(
        f"/api/v1/ai-broader-production/authorizations/{item['id']}/approvals",
        json={"approval_role": "security", "action": "approve",
              "evidence_reference": "artifact://ai-broader-production/self-review",
              "note": "The requester must not approve the broader-production attempt."},
    )
    assert self_review.status_code == 409

    for email, role in [
        ("alpha-security@example.com", "security"),
        ("alpha-risk@example.com", "privacy"),
        ("alpha-product@example.com", "product"),
        ("alpha-operations@example.com", "operations"),
        ("alpha-admin@example.com", "risk"),
        ("alpha-governance@example.com", "claims_governance"),
    ]:
        client.cookies.clear()
        login("alpha", email)
        approval = client.post(
            f"/api/v1/ai-broader-production/authorizations/{item['id']}/approvals",
            json={"approval_role": role, "action": "approve",
                  "evidence_reference": f"artifact://ai-broader-production/{role}-approval",
                  "note": f"Independent {role} reviewer reproduced the bounded Sprint 11I controls."},
        )
        assert approval.status_code == 200, approval.text
    assert approval.json()["status"] == "decision_ready"

    client.cookies.clear()
    login("alpha", "alpha-admin@example.com")
    decided = client.post(
        f"/api/v1/ai-broader-production/authorizations/{item['id']}/decision",
        json={"outcome": "authorize_broader_production", "confirm_decision": True,
              "note": "Authorize only this exact expiring 50-percent broader-production cohort."},
    )
    assert decided.status_code == 200, decided.text
    result = decided.json()
    assert result["status"] == "authorized"
    assert result["summary"]["broader_production_cohort_authorized"] is True
    assert result["summary"]["production_wide_authorized"] is False
    assert len(result["decision_hash"]) == 64
    return result


def _eligible_document(*, restricted: bool = False) -> tuple[str, str]:
    claim, manager, alpha = _claim_and_user()
    document_id = uuid4()
    while _rollout_bucket(document_id) >= 50:
        document_id = uuid4()
    with TestingSessionLocal() as db:
        db.add(Document(
            id=document_id,
            organization_id=alpha.id,
            claim_id=claim.id,
            uploaded_by_id=manager.id,
            document_family_id=uuid4(),
            filename=f"11i-{document_id}.txt",
            original_filename=f"11i-{document_id}.txt",
            document_type="chief_engineer_report",
            mime_type="text/plain",
            file_size_bytes=512,
            file_hash=uuid4().hex * 2,
            storage_key=f"tests/11i-{document_id}.txt",
            confidentiality_level=(ConfidentialityLevel.RESTRICTED if restricted
                                   else ConfidentialityLevel.CONFIDENTIAL),
        ))
        db.commit()
    return str(claim.id), str(document_id)


def _attest(authorization_id: str, claim_id: str, document_id: str):
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    return client.post(
        f"/api/v1/ai-broader-production/authorizations/{authorization_id}/documents",
        json={"claim_id": claim_id, "document_id": document_id,
              "legal_basis_reference": "artifact://ai-broader-production/document-legal",
              "data_minimization_reference": "artifact://ai-broader-production/document-minimization",
              "change_ticket_reference": "ticket://ai-broader-production/document-change",
              "note": "Fresh Sprint 11I eligibility for this current non-restricted document.",
              "confirm_new_broader_production_eligibility": True},
    )


def test_11i_requires_six_approvals_fresh_eligibility_and_different_human(monkeypatch) -> None:
    readiness = _positive_11h()
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    assert client.post(
        "/api/v1/ai-broader-production/authorizations",
        json=_payload(readiness["id"], rollout_percentage=51),
    ).status_code == 422

    authorization = _authorize(readiness)
    restricted_claim, restricted_doc = _eligible_document(restricted=True)
    assert _attest(authorization["id"], restricted_claim, restricted_doc).status_code == 409

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
        runtime = require_external_ai_runtime_authorization(
            db, organization_id=document.organization_id, document=document,
            expected_document_type="chief_engineer_report", input_char_count=2000,
            requested_by_id=manager.id,
        )
        assert isinstance(runtime, AIBroaderProductionAuthorization)
        job = DocumentProcessingJob(
            organization_id=document.organization_id,
            claim_id=document.claim_id,
            document_id=document.id,
            requested_by_id=manager.id,
            job_type=ProcessingJobType.AI_EXTRACT_CE_REPORT,
            status=ProcessingJobStatus.COMPLETED,
            available_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            max_attempts=3,
        )
        db.add(job)
        db.flush()
        run = reserve_run_if_broader_production(
            db, user=manager, document=document,
            expected_document_type="chief_engineer_report", input_char_count=2000,
            processing_job_id=job.id,
        )
        assert run is not None
        db.commit()
        run_id = str(run.id)

    monkeypatch.setattr(settings, "app_env", "test")
    payload = {
        "human_review_action": "approve", "output_candidate_count": 100,
        "human_edit_count": 0, "unsupported_output_count": 0,
        "source_grounded_output_count": 100, "source_grounding_total_count": 100,
        "latency_ms": 2500, "observed_provider_cost_microusd": 120000,
        "evidence_reference": "artifact://ai-broader-production/run-review",
        "note": "Different-human review records only content-free observed metrics.",
        "confirm_human_review": True,
    }
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    assert client.post(f"/api/v1/ai-broader-production/runs/{run_id}/outcome", json=payload).status_code == 409

    client.cookies.clear()
    login("alpha", "alpha-product@example.com")
    reviewed = client.post(f"/api/v1/ai-broader-production/runs/{run_id}/outcome", json=payload)
    assert reviewed.status_code == 200, reviewed.text

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    monitor = client.post(
        f"/api/v1/ai-broader-production/authorizations/{authorization['id']}/monitors",
        json={"monitor_key": "11i-monitor-first-pass",
              "note": "Human review, grounding, quality, latency, cost and incident controls pass.",
              "confirm_live_monitor_snapshot": True},
    )
    assert monitor.status_code == 201, monitor.text
    assert monitor.json()["monitors"][-1]["metrics"]["overall_pass"] is True

    client.cookies.clear()
    login("alpha", "alpha-admin@example.com")
    completed = client.post(
        f"/api/v1/ai-broader-production/authorizations/{authorization['id']}/complete",
        json={"confirm": True, "note": "Every bounded provider run is human-reviewed and the final monitor passes."},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["summary"]["production_wide_authorized"] is False
    assert completed.json()["summary"]["rollout_above_50_percent_authorized"] is False


def test_11i_safety_incident_blocks_resume_and_runtime_fallback(monkeypatch) -> None:
    readiness = _positive_11h()
    authorization = _authorize(readiness)
    claim_id, document_id = _eligible_document()
    assert _attest(authorization["id"], claim_id, document_id).status_code == 201

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    incident = client.post(
        f"/api/v1/ai-broader-production/authorizations/{authorization['id']}/incidents",
        json={"severity": "medium", "category": "privacy",
              "evidence_reference": "ticket://ai-broader-production/privacy-incident",
              "note": "Privacy-boundary incident immediately pauses and rolls back Sprint 11I.",
              "confirm_pause_and_rollback": True},
    )
    assert incident.status_code == 201, incident.text
    assert incident.json()["status"] == "paused"

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
        try:
            require_external_ai_runtime_authorization(
                db, organization_id=document.organization_id, document=document,
                expected_document_type="chief_engineer_report", input_char_count=2000,
                requested_by_id=manager.id,
            )
            assert False, "Paused Sprint 11I must not fall back to Sprint 11G"
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 409

    monkeypatch.setattr(settings, "app_env", "test")
    incident_id = incident.json()["incidents"][-1]["id"]
    client.cookies.clear()
    login("alpha", "alpha-admin@example.com")
    resolved = client.post(
        f"/api/v1/ai-broader-production/authorizations/{authorization['id']}/incidents/{incident_id}/resolve",
        json={"resolution_reference": "artifact://ai-broader-production/privacy-resolution",
              "resolution_note": "Remediated, but immutable safety history requires a new authorization attempt.",
              "confirm_resolution": True},
    )
    assert resolved.status_code == 200, resolved.text
    resume = client.post(
        f"/api/v1/ai-broader-production/authorizations/{authorization['id']}/resume",
        json={"confirm": True, "note": "Safety-boundary history must prevent same-attempt recovery."},
    )
    assert resume.status_code == 409
    assert resolved.json()["summary"]["production_wide_authorized"] is False
