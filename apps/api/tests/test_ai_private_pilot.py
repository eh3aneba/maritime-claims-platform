from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.ai_governance.service import require_external_ai_runtime_authorization
from app.modules.ai_private_pilot.models import AIPrivatePilotRun
from app.modules.ai_private_pilot.service import reserve_run_if_private_pilot
from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.organizations.models import Organization
from app.modules.processing.models import DocumentProcessingJob, ProcessingJobStatus, ProcessingJobType
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_ai_evaluation_promotion import _authorized_activation, _create_suite, _record_cases
from tests.test_claims_api import TEST_PASSWORD, login


def setup_function() -> None:
    reset_database()


def _promoted_evaluation() -> tuple[dict, dict]:
    activation = _authorized_activation()
    suite = _create_suite(activation["id"])
    _record_cases(suite["id"])
    finalized = client.post(
        f"/api/v1/ai-evaluation/suites/{suite['id']}/finalize",
        json={"confirm_finalize": True,
              "note": "All content-free benchmark observations passed fixed thresholds."},
    )
    assert finalized.status_code == 200, finalized.text
    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    quality = client.post(
        f"/api/v1/ai-evaluation/suites/{suite['id']}/reviews",
        json={"review_role": "quality", "action": "approve",
              "evidence_reference": "artifact://ai-evaluation/quality-private-pilot",
              "note": "Quality reviewer reproduced the measured benchmark evidence."},
    )
    assert quality.status_code == 200, quality.text
    client.cookies.clear(); login("alpha", "alpha-risk@example.com")
    risk = client.post(
        f"/api/v1/ai-evaluation/suites/{suite['id']}/reviews",
        json={"review_role": "risk", "action": "approve",
              "evidence_reference": "artifact://ai-evaluation/risk-private-pilot",
              "note": "Risk reviewer reproduced all fail-closed safety controls."},
    )
    assert risk.status_code == 200, risk.text
    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    promoted = client.post(
        f"/api/v1/ai-evaluation/suites/{suite['id']}/decision",
        json={"outcome": "promote_staging", "confirm_decision": True,
              "note": "Administrator promoted the measured bundle for bounded staging use."},
    )
    assert promoted.status_code == 200, promoted.text
    return activation, promoted.json()


def _pilot_payload(suite_id: str, **overrides) -> dict:
    payload = {
        "evaluation_suite_id": suite_id,
        "pilot_key": "real-document-private-pilot-attempt-one",
        "allowed_document_types": ["chief_engineer_report", "engine_log"],
        "max_claims": 2, "max_documents": 4, "max_users": 3,
        "max_provider_runs": 8,
        "starts_at": datetime.now(UTC).isoformat(),
        "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
        "organization_authorization_reference": "artifact://ai-pilot/organization-authorization",
        "data_owner_authorization_reference": "artifact://ai-pilot/data-owner-authorization",
        "monitoring_reference": "monitor://ai-pilot/private-cohort",
        "incident_runbook_reference": "runbook://ai-pilot/incident-response",
        "rollback_reference": "runbook://ai-pilot/immediate-rollback",
        "confirm_bounded_real_document_pilot": True,
    }
    payload.update(overrides)
    return payload


def _create_and_authorize_pilot(suite_id: str, **overrides) -> dict:
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    created = client.post("/api/v1/ai-private-pilot/pilots",
                          json=_pilot_payload(suite_id, **overrides))
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["status"] == "pending_approvals"
    assert item["summary"]["restricted_documents_authorized"] is False
    assert item["summary"]["production_wide_authorized"] is False
    self_review = client.post(
        f"/api/v1/ai-private-pilot/pilots/{item['id']}/approvals",
        json={"approval_role": "organization_owner", "action": "approve",
              "evidence_reference": "artifact://ai-pilot/self-review",
              "note": "The requester must not approve their own private pilot."},
    )
    assert self_review.status_code == 409

    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    organization = client.post(
        f"/api/v1/ai-private-pilot/pilots/{item['id']}/approvals",
        json={"approval_role": "organization_owner", "action": "approve",
              "evidence_reference": "artifact://ai-pilot/organization-owner-review",
              "note": "Organization owner approved the exact bounded cohort and period."},
    )
    assert organization.status_code == 200, organization.text
    client.cookies.clear(); login("alpha", "alpha-risk@example.com")
    data_owner = client.post(
        f"/api/v1/ai-private-pilot/pilots/{item['id']}/approvals",
        json={"approval_role": "data_owner", "action": "approve",
              "evidence_reference": "artifact://ai-pilot/data-owner-review",
              "note": "Data owner approved only real non-restricted allowlisted documents."},
    )
    assert data_owner.status_code == 200, data_owner.text
    assert data_owner.json()["status"] == "decision_ready"

    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    decision = client.post(
        f"/api/v1/ai-private-pilot/pilots/{item['id']}/decision",
        json={"outcome": "authorize_pilot", "confirm_decision": True,
              "note": "Administrator authorized only this expiring real-document cohort."},
    )
    assert decision.status_code == 200, decision.text
    authorized = decision.json()
    assert authorized["status"] == "authorized"
    assert len(authorized["decision_hash"]) == 64
    return authorized


def _claim_and_user() -> tuple[Claim, User, Organization]:
    with TestingSessionLocal() as db:
        alpha = db.scalar(select(Organization).where(Organization.slug == "alpha"))
        manager = db.scalar(select(User).where(User.email == "alpha-manager@example.com"))
        claim = db.scalar(select(Claim).where(Claim.organization_id == alpha.id))
        assert alpha is not None and manager is not None and claim is not None
        db.expunge(claim); db.expunge(manager); db.expunge(alpha)
        return claim, manager, alpha


def _document(confidentiality=ConfidentialityLevel.CONFIDENTIAL,
              suffix: str = "a") -> tuple[str, str]:
    claim, manager, alpha = _claim_and_user()
    with TestingSessionLocal() as db:
        document = Document(
            organization_id=alpha.id, claim_id=claim.id, uploaded_by_id=manager.id,
            document_family_id=uuid4(), filename=f"pilot-ce-{suffix}.txt",
            original_filename=f"pilot-ce-{suffix}.txt",
            document_type="chief_engineer_report", mime_type="text/plain",
            file_size_bytes=256, file_hash=suffix * 64,
            storage_key=f"tests/pilot-ce-{suffix}.txt",
            confidentiality_level=confidentiality,
        )
        db.add(document); db.commit(); db.refresh(document)
        return str(claim.id), str(document.id)


def _configure_staging(monkeypatch, activation: dict) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "staging")
    monkeypatch.setattr(settings, "ai_model", activation["model"])
    monkeypatch.setattr(settings, "ai_prompt_bundle_version", activation["prompt_bundle_version"])
    monkeypatch.setattr(settings, "ai_schema_bundle_version", activation["schema_bundle_version"])
    monkeypatch.setattr(settings, "ai_max_output_tokens", activation["max_output_tokens"])


def test_real_document_pilot_requires_two_approvals_runtime_quota_and_human_review(monkeypatch) -> None:
    activation, suite = _promoted_evaluation()
    pilot = _create_and_authorize_pilot(suite["id"])
    claim_id, document_id = _document()
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    attested = client.post(
        f"/api/v1/ai-private-pilot/pilots/{pilot['id']}/documents",
        json={"claim_id": claim_id, "document_id": document_id,
              "authorization_basis": "organization_and_data_owner",
              "authorization_reference": "artifact://ai-pilot/document-authorization",
              "data_minimization_reference": "artifact://ai-pilot/document-minimization",
              "note": "Manager confirmed the current document is real, non-restricted and minimized.",
              "confirm_real_non_restricted": True},
    )
    assert attested.status_code == 201, attested.text
    eligibility = attested.json()["document_eligibility"][0]
    assert eligibility["status"] == "eligible" and len(eligibility["snapshot_hash"]) == 64

    _configure_staging(monkeypatch, activation)
    with TestingSessionLocal() as db:
        document = db.scalar(select(Document).where(Document.id == UUID(document_id)))
        manager = db.scalar(select(User).where(User.email == "alpha-manager@example.com"))
        assert document is not None and manager is not None
        allowed = require_external_ai_runtime_authorization(
            db, organization_id=document.organization_id, document=document,
            expected_document_type="chief_engineer_report", input_char_count=2000,
            requested_by_id=manager.id,
        )
        assert str(allowed.id) == activation["id"]
        job = DocumentProcessingJob(
            organization_id=document.organization_id, claim_id=document.claim_id,
            document_id=document.id, requested_by_id=manager.id,
            job_type=ProcessingJobType.AI_EXTRACT_CE_REPORT,
            status=ProcessingJobStatus.COMPLETED, available_at=datetime.now(UTC),
            completed_at=datetime.now(UTC), max_attempts=3,
        )
        db.add(job); db.flush()
        run = reserve_run_if_private_pilot(
            db, user=manager, document=document,
            expected_document_type="chief_engineer_report", input_char_count=2000,
            processing_job_id=job.id,
        )
        assert run is not None; db.commit(); run_id = str(run.id)

    # TestClient uses secure cookies in staging mode; return only the HTTP test
    # client to its normal environment while preserving the pinned AI bundle.
    monkeypatch.setattr(get_settings(), "app_env", "test")
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    self_review = client.post(
        f"/api/v1/ai-private-pilot/runs/{run_id}/outcome",
        json={"human_review_action": "approve", "output_candidate_count": 5,
              "human_edit_count": 0, "latency_ms": 2500,
              "observed_provider_cost_microusd": 120000,
              "evidence_reference": "artifact://ai-pilot/run-human-review",
              "note": "A different human must review every candidate before any use.",
              "confirm_human_review": True},
    )
    assert self_review.status_code == 409
    client.cookies.clear(); login("alpha", "alpha-product@example.com")
    reviewed = client.post(
        f"/api/v1/ai-private-pilot/runs/{run_id}/outcome",
        json={"human_review_action": "edit", "output_candidate_count": 5,
              "human_edit_count": 1, "latency_ms": 2500,
              "observed_provider_cost_microusd": 120000,
              "evidence_reference": "artifact://ai-pilot/run-human-review",
              "note": "Independent human reviewed and edited candidate fields before acceptance.",
              "confirm_human_review": True},
    )
    assert reviewed.status_code == 200, reviewed.text
    result = reviewed.json()
    assert result["summary"]["provider_run_count"] == 1
    assert result["summary"]["human_reviewed_run_count"] == 1
    assert result["runs"][0]["outcome_hash"]
    assert result["summary"]["authoritative_facts_auto_updated"] is False

    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    paused = client.post(
        f"/api/v1/ai-private-pilot/pilots/{pilot['id']}/incidents",
        json={"severity": "high", "category": "quality",
              "evidence_reference": "ticket://ai-pilot/incident-001",
              "note": "Quality monitor triggered an immediate fail-closed pilot pause.",
              "confirm_pause": True},
    )
    assert paused.status_code == 201 and paused.json()["status"] == "paused"
    incident_id = paused.json()["incidents"][0]["id"]
    monkeypatch.setattr(get_settings(), "app_env", "staging")
    with TestingSessionLocal() as db:
        document = db.scalar(select(Document).where(Document.id == UUID(document_id)))
        with pytest.raises(HTTPException, match="No active bounded"):
            require_external_ai_runtime_authorization(
                db, organization_id=document.organization_id, document=document,
                expected_document_type="chief_engineer_report", input_char_count=2000)

    monkeypatch.setattr(get_settings(), "app_env", "test")
    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    resolved = client.post(
        f"/api/v1/ai-private-pilot/pilots/{pilot['id']}/incidents/{incident_id}/resolve",
        json={"resolution_reference": "artifact://ai-pilot/incident-resolution",
              "resolution_note": "Administrator verified remediation and monitoring recovery.",
              "resume_pilot": True, "confirm_resolution": True},
    )
    assert resolved.status_code == 200 and resolved.json()["status"] == "authorized"
    completed = client.post(
        f"/api/v1/ai-private-pilot/pilots/{pilot['id']}/complete",
        json={"confirm_complete": True,
              "note": "All bounded provider runs received human review and incidents are resolved."},
    )
    assert completed.status_code == 200 and completed.json()["status"] == "completed"

    with TestingSessionLocal() as db:
        actions = set(db.scalars(select(AuditLog.action).where(
            AuditLog.entity_id == UUID(pilot["id"]))))
        assert {"CREATE_AI_PRIVATE_PILOT", "AUTHORIZE_PILOT_AI_PRIVATE_PILOT",
                "PAUSE_AI_PRIVATE_PILOT_INCIDENT", "COMPLETE_AI_PRIVATE_PILOT"}.issubset(actions)


def test_private_pilot_is_tenant_scoped_rejects_raw_fields_and_restricted_documents() -> None:
    _, suite = _promoted_evaluation()
    client.cookies.clear(); login("alpha", "alpha-handler@example.com")
    assert client.post("/api/v1/ai-private-pilot/pilots",
                       json=_pilot_payload(suite["id"])).status_code == 403

    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    raw = _pilot_payload(suite["id"], pilot_key="raw-content-pilot-attempt")
    raw["document_text"] = "Raw claim content must never enter the control ledger"
    assert client.post("/api/v1/ai-private-pilot/pilots", json=raw).status_code == 422
    unbounded = _pilot_payload(suite["id"], pilot_key="unbounded-reference-pilot",
                               monitoring_reference="https://example.com/raw-monitor")
    assert client.post("/api/v1/ai-private-pilot/pilots", json=unbounded).status_code == 422

    pilot = _create_and_authorize_pilot(suite["id"])
    claim_id, restricted_id = _document(ConfidentialityLevel.RESTRICTED, "r")
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    restricted = client.post(
        f"/api/v1/ai-private-pilot/pilots/{pilot['id']}/documents",
        json={"claim_id": claim_id, "document_id": restricted_id,
              "authorization_basis": "organization_and_data_owner",
              "authorization_reference": "artifact://ai-pilot/restricted-document",
              "data_minimization_reference": "artifact://ai-pilot/restricted-minimization",
              "note": "Restricted documents must remain prohibited even with a pilot authorization.",
              "confirm_real_non_restricted": True},
    )
    assert restricted.status_code == 409

    with TestingSessionLocal() as db:
        beta = db.scalar(select(Organization).where(Organization.slug == "beta"))
        assert beta is not None
        db.add(User(organization_id=beta.id, email="beta-pilot@example.com",
                    full_name="Beta Pilot Manager", password_hash=hash_password(TEST_PASSWORD),
                    role=UserRole.CLAIMS_MANAGER, is_active=True))
        db.commit()
    client.cookies.clear(); login("beta", "beta-pilot@example.com")
    dashboard = client.get("/api/v1/ai-private-pilot")
    assert dashboard.status_code == 200 and dashboard.json() == {"pilots": []}
    cross_tenant = client.post(
        f"/api/v1/ai-private-pilot/pilots/{pilot['id']}/revoke",
        json={"confirm_revoke": True,
              "note": "A different tenant must not access or revoke this private pilot."},
    )
    assert cross_tenant.status_code == 404
