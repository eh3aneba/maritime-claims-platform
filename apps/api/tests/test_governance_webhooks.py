from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.core.security import hash_password
from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.evidence_search.qa_synthesis_models import ClaimQaSynthesisRun
from app.modules.governance_webhooks.models import (
    GovernanceWebhookDelivery,
    GovernanceWebhookDestination,
)
from app.modules.governance_webhooks.service import (
    claim_next_delivery,
    process_delivery,
    signed_delivery_request,
    sync_content_free_ai_events,
    verify_signature,
)
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
        alpha = Organization(name="Alpha Webhooks", slug="alpha-webhooks")
        beta = Organization(name="Beta Webhooks", slug="beta-webhooks")
        db.add_all([alpha, beta]); db.flush()
        admin = User(
            organization_id=alpha.id,
            email="admin-webhooks@example.com",
            full_name="Webhook Admin",
            password_hash=hash_password(TEST_PASSWORD),
            role=UserRole.ADMIN,
            is_active=True,
        )
        manager = User(
            organization_id=alpha.id,
            email="manager-webhooks@example.com",
            full_name="Webhook Manager",
            password_hash=hash_password(TEST_PASSWORD),
            role=UserRole.CLAIMS_MANAGER,
            is_active=True,
        )
        beta_admin = User(
            organization_id=beta.id,
            email="beta-webhooks@example.com",
            full_name="Beta Webhook Admin",
            password_hash=hash_password(TEST_PASSWORD),
            role=UserRole.ADMIN,
            is_active=True,
        )
        vessel = Vessel(organization_id=alpha.id, name="MT WEBHOOK", imo_number="7000301")
        db.add_all([admin, manager, beta_admin, vessel]); db.flush()
        claim = Claim(
            organization_id=alpha.id,
            vessel_id=vessel.id,
            handler_id=manager.id,
            claim_reference="MCRI-HM-2026-WEBHOOK",
            incident_date=date(2026, 8, 1),
            notification_date=date(2026, 8, 2),
            incident_description="Synthetic webhook claim",
            currency="USD",
        )
        db.add(claim); db.flush()
        synthesis = ClaimQaSynthesisRun(
            organization_id=alpha.id,
            claim_id=claim.id,
            requested_by_id=manager.id,
            retrieval_run_id=None,
            production_authorization_id=None,
            status="verification_failed",
            failure_code="grounding_verification_failed",
            fallback_used=True,
            provider_call_made=True,
            provider="openai",
            model="governed-test-model",
            prompt_bundle_version="prompt-v1",
            schema_bundle_version="schema-v1",
            authorization_hash="a" * 64,
            eligibility_policy_hash="b" * 64,
            question_hash="c" * 64,
            result_set_hash="d" * 64,
            input_hash="e" * 64,
            output_hash="f" * 64,
            answer_hash="1" * 64,
            source_unit_ids=["SUPER_SECRET_SOURCE_UNIT_SHOULD_NOT_EXPORT"],
            source_count=2,
            input_chars=500,
            input_tokens=100,
            output_tokens=20,
            total_tokens=120,
            latency_ms=900,
            provider_response_id_hash="2" * 64,
            completed_at=now,
        )
        db.add(synthesis); db.commit()
        return {
            "alpha_org": str(alpha.id),
            "beta_org": str(beta.id),
            "claim": str(claim.id),
        }


def _login(slug: str, email: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/api/v1/auth/login",
        json={"organization_slug": slug, "email": email, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200, response.text


def _create_destination(enabled: bool = True) -> dict:
    response = client.post(
        "/api/v1/governance-webhooks/destinations",
        json={
            "name": "Primary SIEM",
            "endpoint_url": "https://example.com/mcri-governance",
            "event_types": ["ai_operations.claim_qa_synthesis"],
            "enabled": enabled,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_destination_secret_is_one_time_and_private_targets_are_blocked() -> None:
    _seed()
    _login("alpha-webhooks", "admin-webhooks@example.com")
    created = _create_destination()
    assert len(created["signing_secret"]) >= 40
    assert created["destination"]["secret_material_persisted"] is False
    listed = client.get("/api/v1/governance-webhooks/destinations")
    assert listed.status_code == 200
    serialized = listed.text
    assert "signing_secret" not in serialized
    assert "secret_salt" not in serialized
    assert "previous_secret_salt" not in serialized

    for url in ("https://127.0.0.1/hook", "https://localhost/hook", "http://example.com/hook"):
        blocked = client.post(
            "/api/v1/governance-webhooks/destinations",
            json={
                "name": f"blocked-{url}",
                "endpoint_url": url,
                "event_types": ["ai_operations.claim_qa_synthesis"],
                "enabled": False,
            },
        )
        assert blocked.status_code == 422


def test_manager_can_observe_but_cannot_mutate_and_tenants_are_isolated() -> None:
    _seed()
    _login("alpha-webhooks", "admin-webhooks@example.com")
    created = _create_destination()
    destination_id = created["destination"]["id"]

    _login("alpha-webhooks", "manager-webhooks@example.com")
    dashboard = client.get("/api/v1/governance-webhooks")
    assert dashboard.status_code == 200
    assert dashboard.json()["metrics"]["destination_count"] == 1
    denied = client.patch(
        f"/api/v1/governance-webhooks/destinations/{destination_id}",
        json={"enabled": False},
    )
    assert denied.status_code == 403

    _login("beta-webhooks", "beta-webhooks@example.com")
    beta = client.get("/api/v1/governance-webhooks/destinations")
    assert beta.status_code == 200
    assert beta.json() == []


def test_sync_is_idempotent_and_payload_is_content_free() -> None:
    ids = _seed()
    _login("alpha-webhooks", "admin-webhooks@example.com")
    created = _create_destination()
    destination_id = UUID(created["destination"]["id"])
    with TestingSessionLocal() as db:
        first = sync_content_free_ai_events(db)
        assert first["deliveries_created"] == 1
        second = sync_content_free_ai_events(db)
        assert second["deliveries_created"] == 0
        assert second["duplicates_skipped"] >= 1
        delivery = db.scalar(
            select(GovernanceWebhookDelivery).where(
                GovernanceWebhookDelivery.destination_id == destination_id
            )
        )
        assert delivery is not None
        assert delivery.organization_id == UUID(ids["alpha_org"])
        assert delivery.envelope["content_free"] is True
        assert delivery.envelope["raw_claim_or_model_content_included"] is False
        assert delivery.envelope["inbound_command"] is False
        serialized = str(delivery.envelope)
        for forbidden in (
            "SUPER_SECRET_SOURCE_UNIT_SHOULD_NOT_EXPORT",
            "source_unit_ids",
            "raw_provider_response",
            "source_passages",
            "synthesized_answer",
        ):
            assert forbidden not in serialized


def test_signature_tamper_replay_and_delivery_success() -> None:
    _seed()
    _login("alpha-webhooks", "admin-webhooks@example.com")
    created = _create_destination()
    secret = created["signing_secret"]
    with TestingSessionLocal() as db:
        sync_content_free_ai_events(db)
        delivery = claim_next_delivery(db, worker_id="test-worker")
        assert delivery is not None
        destination = db.get(GovernanceWebhookDestination, delivery.destination_id)
        assert destination is not None
        now = datetime.now(UTC)
        body, headers = signed_delivery_request(destination, delivery, now=now)
        timestamp = int(headers["X-MCRI-Webhook-Timestamp"])
        assert verify_signature(
            secret,
            body=body,
            timestamp=timestamp,
            event_id=delivery.id,
            signature_header=headers["X-MCRI-Webhook-Signature"],
            now=now,
        )
        assert not verify_signature(
            secret,
            body=body + b"tampered",
            timestamp=timestamp,
            event_id=delivery.id,
            signature_header=headers["X-MCRI-Webhook-Signature"],
            now=now,
        )
        assert not verify_signature(
            secret,
            body=body,
            timestamp=timestamp,
            event_id=delivery.id,
            signature_header=headers["X-MCRI-Webhook-Signature"],
            now=now + timedelta(minutes=10),
        )
        process_delivery(db, delivery=delivery, transport=lambda url, headers, body, timeout: 204)
        db.refresh(delivery)
        assert delivery.status == "delivered"
        assert delivery.last_http_status == 204


def test_failure_dead_letter_rotation_and_manual_retry_are_audited() -> None:
    _seed()
    _login("alpha-webhooks", "admin-webhooks@example.com")
    created = _create_destination()
    destination_id = created["destination"]["id"]
    with TestingSessionLocal() as db:
        sync_content_free_ai_events(db)
        delivery = claim_next_delivery(db, worker_id="failure-worker")
        assert delivery is not None
        delivery.max_attempts = 1
        db.commit()
        process_delivery(db, delivery=delivery, transport=lambda url, headers, body, timeout: 503)
        db.refresh(delivery)
        assert delivery.status == "dead_letter"
        delivery_id = str(delivery.id)

    rotated = client.post(
        f"/api/v1/governance-webhooks/destinations/{destination_id}/rotate-secret"
    )
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["secret_version"] == 2
    assert rotated.json()["signing_secret"] != created["signing_secret"]

    retry = client.post(f"/api/v1/governance-webhooks/deliveries/{delivery_id}/retry")
    assert retry.status_code == 200, retry.text
    assert retry.json()["delivery"]["status"] == "queued"
    assert retry.json()["delivery"]["secret_version"] == 2

    with TestingSessionLocal() as db:
        actions = set(db.scalars(select(AuditLog.action)))
        assert "CREATE_GOVERNANCE_WEBHOOK_DESTINATION" in actions
        assert "ROTATE_GOVERNANCE_WEBHOOK_SECRET" in actions
        assert "RETRY_GOVERNANCE_WEBHOOK_DELIVERY" in actions
