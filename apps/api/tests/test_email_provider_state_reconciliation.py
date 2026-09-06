from datetime import UTC
from uuid import UUID

from app.core.security import hash_password
from app.modules.email_ingestion import provider_execution
from app.modules.email_ingestion.models import EmailProviderAdapter
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import TEST_PASSWORD, login
from tests.test_email_provider_execution import _adapter


def setup_function() -> None:
    reset_database()


def test_manual_pull_run_cannot_forge_graph_execution_state() -> None:
    _, _, adapter = _adapter("microsoft_graph")
    with TestingSessionLocal() as db:
        before = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        initial_next_sync = before.next_sync_at
        assert before.checkpoint_hash is None
        assert before.last_sync_at is None

    forged = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/runs",
        json={
            "idempotency_key": "forged-run-0001",
            "trigger": "manual",
            "messages_seen": 1,
            "messages_ingested": 1,
            "provider_checkpoint": "forged-provider-checkpoint",
        },
    )
    assert forged.status_code == 409

    with TestingSessionLocal() as db:
        after = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        assert after.checkpoint_hash is None
        assert after.last_sync_at is None
        assert after.next_sync_at == initial_next_sync


def test_provider_webhook_has_no_pull_schedule_or_checkpoint_authority() -> None:
    _, _, adapter = _adapter("provider_webhook")
    with TestingSessionLocal() as db:
        item = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        assert item.next_sync_at is None
        assert item.checkpoint_hash is None

    checkpoint_attempt = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/runs",
        json={
            "idempotency_key": "webhook-run-checkpoint",
            "trigger": "provider_push",
            "provider_checkpoint": "opaque-value",
        },
    )
    assert checkpoint_attempt.status_code == 422

    reported_failure = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/runs",
        json={
            "idempotency_key": "webhook-run-failure",
            "trigger": "provider_push",
            "messages_seen": 1,
            "messages_ingested": 0,
            "failure_summary": "SENSITIVE PROVIDER CONTENT MUST NOT BE STORED",
        },
    )
    assert reported_failure.status_code == 201, reported_failure.text
    assert reported_failure.json()["failure_summary"] == "provider_webhook_reported_failure"

    with TestingSessionLocal() as db:
        item = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        assert item.next_sync_at is None
        assert item.checkpoint_hash is None


def test_pull_lifecycle_controls_due_schedule() -> None:
    _, _, adapter = _adapter("gmail_api")
    reconciliation = client.get("/api/v1/email-ingestion/adapter-reconciliation")
    assert reconciliation.status_code == 200
    current = next(item for item in reconciliation.json()["items"] if item["adapter_id"] == adapter["id"])
    assert current["operational_state"] == "due"
    assert current["operator_driven_execution"] is True
    assert current["checkpoint_handoff_required"] is False

    suspended = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/transition",
        json={"action": "suspend", "note": "Operational pause for provider maintenance."},
    )
    assert suspended.status_code == 200
    assert suspended.json()["next_sync_at"] is None
    state = client.get("/api/v1/email-ingestion/adapter-reconciliation").json()["items"][0]
    assert state["operational_state"] == "suspended"

    reactivated = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/transition",
        json={"action": "reactivate", "note": "Provider maintenance completed."},
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["next_sync_at"] is not None
    state = client.get("/api/v1/email-ingestion/adapter-reconciliation").json()["items"][0]
    assert state["operational_state"] == "due"


def test_failed_pull_uses_bounded_backoff_and_surfaces_reconciliation(monkeypatch) -> None:
    _, _, adapter = _adapter("microsoft_graph")
    monkeypatch.setenv("MCRI_PROVIDER_TEST_TOKEN", "runtime-only-secret")

    def fail_transport(*args, **kwargs):
        raise provider_execution.ProviderExecutionFailure("provider_transport_error")

    monkeypatch.setattr(provider_execution, "_http_json", fail_transport)
    expected_minutes = [15, 30, 60, 120]
    for index, expected in enumerate(expected_minutes, start=1):
        response = client.post(
            f"/api/v1/email-ingestion/adapters/{adapter['id']}/execute",
            json={"idempotency_key": f"failed-pull-{index:04d}", "trigger": "manual"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["run"]["status"] == "failed"
        finished_at = response.json()["run"]["finished_at"]
        with TestingSessionLocal() as db:
            item = db.get(EmailProviderAdapter, UUID(adapter["id"]))
            assert item.next_sync_at is not None
            delta_minutes = (item.next_sync_at - item.last_sync_at).total_seconds() / 60
            assert abs(delta_minutes - expected) < 0.1
        assert finished_at is not None

    reconciliation = client.get("/api/v1/email-ingestion/adapter-reconciliation")
    assert reconciliation.status_code == 200
    payload = reconciliation.json()
    item = next(value for value in payload["items"] if value["adapter_id"] == adapter["id"])
    assert item["operational_state"] == "reconciliation_required"
    assert item["consecutive_failures"] == 4
    assert item["last_run_status"] == "failed"
    serialized = str(payload)
    assert "runtime-only-secret" not in serialized
    assert "credential_reference" not in serialized
    assert "checkpoint_hash" not in serialized


def test_reconciliation_is_manager_only_and_tenant_scoped() -> None:
    _adapter("gmail_api")
    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    denied = client.get("/api/v1/email-ingestion/adapter-reconciliation")
    assert denied.status_code == 403

    with TestingSessionLocal() as db:
        beta = db.query(Organization).filter(Organization.slug == "beta").one()
        beta_admin = User(
            organization_id=beta.id,
            email="beta-admin@example.com",
            full_name="Beta Admin",
            password_hash=hash_password(TEST_PASSWORD),
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(beta_admin)
        db.commit()

    client.cookies.clear()
    login("beta", "beta-admin@example.com")
    scoped = client.get("/api/v1/email-ingestion/adapter-reconciliation")
    assert scoped.status_code == 200
    assert scoped.json()["items"] == []
