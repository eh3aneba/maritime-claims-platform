from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.ai_governance.service import require_external_ai_runtime_authorization
from app.modules.audit.models import AuditLog
from app.modules.documents.models import ConfidentialityLevel, Document
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import TEST_PASSWORD, create_orion_claim, login


def setup_function() -> None:
    reset_database()


def _activation_payload(key: str = "openai-staging-evaluation-one") -> dict:
    return {
        "request_key": key,
        "environment": "staging",
        "provider": "openai",
        "provider_project_label": "MCRI bounded staging evaluation",
        "model": "pinned-evaluation-model",
        "prompt_bundle_version": "2026-08-20.1",
        "schema_bundle_version": "2026-08-20.1",
        "data_mode": "synthetic_deidentified",
        "allowed_document_types": [
            "chief_engineer_report", "engine_log", "running_hours_record",
            "pms_record", "workshop_report", "quotation", "invoice",
        ],
        "restricted_documents_allowed": False,
        "credential_storage_mode": "secret_manager",
        "max_input_chars": 60000,
        "max_output_tokens": 2000,
        "requests_per_minute": 10,
        "tokens_per_minute": 50000,
        "monthly_spend_limit_cents": 10000,
        "spend_alert_thresholds": [50, 80],
        "retention_mode": "approved_standard",
        "data_residency_region": "Approved staging region",
        "security_owner_label": "Security Owner",
        "privacy_owner_label": "Privacy Owner",
        "product_owner_label": "Product Owner",
        "incident_owner_label": "Incident Commander",
        "kill_switch_owner_label": "AI Operations Owner",
        "credential_control_reference": "artifact://ai-governance/staging-secret-control",
        "spend_limit_reference": "monitor://ai-governance/staging-spend-cap",
        "data_processing_reference": "artifact://ai-governance/dpa-review",
        "kill_switch_reference": "runbook://ai-governance/kill-switch",
        "evaluation_expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
    }


def _add_reviewers() -> None:
    with TestingSessionLocal() as db:
        alpha = db.scalar(select(Organization).where(Organization.slug == "alpha"))
        assert alpha is not None
        db.add_all([
            User(organization_id=alpha.id, email="alpha-risk@example.com",
                 full_name="Alpha Privacy Reviewer", password_hash=hash_password(TEST_PASSWORD),
                 role=UserRole.CLAIMS_MANAGER, is_active=True),
            User(organization_id=alpha.id, email="alpha-product@example.com",
                 full_name="Alpha Product Reviewer", password_hash=hash_password(TEST_PASSWORD),
                 role=UserRole.CLAIMS_MANAGER, is_active=True),
        ])
        db.commit()


def _create_and_authorize() -> dict:
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    created = client.post("/api/v1/ai-governance/activations", json=_activation_payload())
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["status"] == "pending_approvals"
    assert item["summary"]["key_material_stored"] is False
    assert item["summary"]["production_authorized"] is False
    self_review = client.post(
        f"/api/v1/ai-governance/activations/{item['id']}/approvals",
        json={"approval_role": "security", "action": "approve",
              "evidence_reference": "artifact://ai-governance/self-review",
              "note": "The requester must not approve this activation attempt."},
    )
    assert self_review.status_code == 409

    reviews = [
        ("alpha-admin@example.com", "security"),
        ("alpha-risk@example.com", "privacy"),
        ("alpha-product@example.com", "product"),
    ]
    current = item
    for email, role in reviews:
        client.cookies.clear(); login("alpha", email)
        response = client.post(
            f"/api/v1/ai-governance/activations/{item['id']}/approvals",
            json={"approval_role": role, "action": "approve",
                  "evidence_reference": f"artifact://ai-governance/{role}-review",
                  "note": f"Independent {role} reviewer approved the bounded staging evaluation."},
        )
        assert response.status_code == 200, response.text
        current = response.json()
    assert current["status"] == "decision_ready"
    assert current["summary"]["independent_approvals_complete"] is True

    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    decision = client.post(
        f"/api/v1/ai-governance/activations/{item['id']}/decision",
        json={"outcome": "authorize_staging", "confirm_decision": True,
              "note": "Administrator authorizes only this bounded staging evaluation."},
    )
    assert decision.status_code == 200, decision.text
    authorized = decision.json()
    assert authorized["status"] == "staging_authorized"
    assert len(authorized["decision_hash"]) == 64
    assert authorized["summary"]["authorization_active"] is True
    assert authorized["summary"]["restricted_documents_authorized"] is False
    assert authorized["summary"]["real_claim_data_authorized"] is False
    assert authorized["summary"]["human_review_required"] is True
    return authorized


def test_activation_requires_four_people_and_document_runtime_gate(monkeypatch) -> None:
    claim = create_orion_claim()
    _add_reviewers()
    authorized = _create_and_authorize()
    with TestingSessionLocal() as db:
        alpha = db.scalar(select(Organization).where(Organization.slug == "alpha"))
        admin = db.scalar(select(User).where(User.email == "alpha-admin@example.com"))
        assert alpha is not None and admin is not None
        document = Document(
            organization_id=alpha.id, claim_id=UUID(claim["claim"]["id"]),
            uploaded_by_id=admin.id, document_family_id=uuid4(),
            filename="synthetic-ce-report.txt", original_filename="synthetic-ce-report.txt",
            document_type="chief_engineer_report", mime_type="text/plain",
            file_size_bytes=128, file_hash="a" * 64,
            storage_key="tests/synthetic-ce-report.txt",
            confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
        )
        db.add(document); db.commit(); db.refresh(document); document_id = str(document.id)

    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    attested = client.post("/api/v1/ai-governance/document-eligibility", json={
        "activation_request_id": authorized["id"], "claim_id": claim["claim"]["id"],
        "document_id": document_id, "data_mode": "synthetic",
        "evidence_reference": "artifact://ai-governance/synthetic-document-review",
        "confirm_eligible": True,
        "note": "Manager confirmed this document is synthetic staging evidence only.",
    })
    assert attested.status_code == 201, attested.text
    eligibility = attested.json()
    assert eligibility["status"] == "eligible" and len(eligibility["snapshot_hash"]) == 64

    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "staging")
    monkeypatch.setattr(settings, "ai_model", "pinned-evaluation-model")
    monkeypatch.setattr(settings, "ai_prompt_bundle_version", "2026-08-20.1")
    monkeypatch.setattr(settings, "ai_schema_bundle_version", "2026-08-20.1")
    monkeypatch.setattr(settings, "ai_max_output_tokens", 2000)
    with TestingSessionLocal() as db:
        document = db.scalar(select(Document).where(Document.id == UUID(document_id)))
        assert document is not None
        allowed = require_external_ai_runtime_authorization(
            db, organization_id=document.organization_id, document=document,
            expected_document_type="chief_engineer_report", input_char_count=2000,
        )
        assert str(allowed.id) == authorized["id"]
        monkeypatch.setattr(settings, "ai_model", "different-model")
        with pytest.raises(HTTPException, match="pinned model"):
            require_external_ai_runtime_authorization(
                db, organization_id=document.organization_id, document=document,
                expected_document_type="chief_engineer_report", input_char_count=2000,
            )

    monkeypatch.setattr(settings, "ai_model", "pinned-evaluation-model")
    revoked = client.post(
        f"/api/v1/ai-governance/document-eligibility/{eligibility['id']}/revoke",
        json={"confirm_revoke": True,
              "note": "Manager removed this document from the external AI evaluation."},
    )
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    with TestingSessionLocal() as db:
        document = db.scalar(select(Document).where(Document.id == UUID(document_id)))
        with pytest.raises(HTTPException, match="eligibility attestation"):
            require_external_ai_runtime_authorization(
                db, organization_id=document.organization_id, document=document,
                expected_document_type="chief_engineer_report", input_char_count=2000,
            )

    killed = client.post(
        f"/api/v1/ai-governance/activations/{authorized['id']}/revoke",
        json={"confirm_revoke": True,
              "note": "Manager activated the AI kill switch for this staging attempt."},
    )
    assert killed.status_code == 200 and killed.json()["status"] == "revoked"
    with TestingSessionLocal() as db:
        actions = set(db.scalars(select(AuditLog.action).where(
            AuditLog.entity_id == UUID(authorized["id"]))))
        assert {"CREATE_AI_PROVIDER_ACTIVATION_REQUEST",
                "AUTHORIZE_STAGING_AI_PROVIDER_ACTIVATION",
                "REVOKE_AI_PROVIDER_ACTIVATION"}.issubset(actions)


def test_activation_validation_attempt_history_and_tenant_scope() -> None:
    create_orion_claim(); _add_reviewers()
    client.cookies.clear(); login("alpha", "alpha-handler@example.com")
    assert client.post("/api/v1/ai-governance/activations",
                       json=_activation_payload()).status_code == 403

    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    invalid = _activation_payload("invalid-staging-attempt")
    invalid["spend_alert_thresholds"] = [80, 50]
    assert client.post("/api/v1/ai-governance/activations", json=invalid).status_code == 422
    unbounded = _activation_payload("unbounded-staging-attempt")
    unbounded["spend_limit_reference"] = "https://example.com/spend-secret"
    assert client.post("/api/v1/ai-governance/activations", json=unbounded).status_code == 422

    created = client.post("/api/v1/ai-governance/activations", json=_activation_payload())
    assert created.status_code == 201, created.text
    duplicate = client.post("/api/v1/ai-governance/activations",
                            json=_activation_payload("openai-staging-evaluation-two"))
    assert duplicate.status_code == 409

    with TestingSessionLocal() as db:
        beta = db.scalar(select(Organization).where(Organization.slug == "beta"))
        assert beta is not None
        db.add(User(organization_id=beta.id, email="beta-ai-manager@example.com",
                    full_name="Beta AI Manager", password_hash=hash_password(TEST_PASSWORD),
                    role=UserRole.CLAIMS_MANAGER, is_active=True))
        db.commit()
    client.cookies.clear(); login("beta", "beta-ai-manager@example.com")
    dashboard = client.get("/api/v1/ai-governance")
    assert dashboard.status_code == 200
    assert dashboard.json() == {"activation_requests": [], "document_eligibility": []}
    cross_tenant = client.post(
        f"/api/v1/ai-governance/activations/{created.json()['id']}/approvals",
        json={"approval_role": "security", "action": "reject",
              "note": "A different tenant must not access this activation attempt."},
    )
    assert cross_tenant.status_code == 404
