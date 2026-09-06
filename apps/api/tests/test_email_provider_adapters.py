from uuid import UUID

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.email_ingestion.models import EmailAdapterRun, EmailProviderAdapter, EmailRetentionRun
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import login
from tests.test_controlled_email_ingestion import _connection


def setup_function() -> None:
    reset_database()


def test_adapter_is_least_privilege_and_pull_runs_require_governed_execution() -> None:
    _, connection, _ = _connection()
    denied = client.post("/api/v1/email-ingestion/adapters", json={
        "connection_id": connection["id"], "provider_kind": "microsoft_graph",
        "display_name": "Graph intake", "credential_reference": "vault://mcri/graph-alpha",
        "allowed_folder": "Claims Intake", "permission_manifest": ["mail.send"], "batch_limit": 50,
    })
    assert denied.status_code == 422
    credential_reference = "vault://mcri/graph-alpha"
    created = client.post("/api/v1/email-ingestion/adapters", json={
        "connection_id": connection["id"], "provider_kind": "microsoft_graph",
        "display_name": "Graph intake", "credential_reference": credential_reference,
        "allowed_folder": "Claims Intake",
        "permission_manifest": ["messages.read.allowed_folder", "attachments.metadata.read"],
        "batch_limit": 25, "retention_schedule_enabled": True,
    })
    assert created.status_code == 201, created.text
    adapter = created.json()
    assert "credential_reference" not in adapter
    assert "checkpoint_hash" not in adapter
    assert adapter["credential_backend"] == "vault"
    assert adapter["credential_reference_configured"] is True
    assert adapter["credential_resolver_available"] is False
    assert adapter["credential_reference_version"] == 1
    assert adapter["checkpoint_present"] is False
    assert "token" not in adapter

    with TestingSessionLocal() as db:
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.action == "CREATE_EMAIL_PROVIDER_ADAPTER",
                AuditLog.entity_id == UUID(adapter["id"]),
            )
        )
        assert audit is not None
        serialized = str(audit.new_values) + str(audit.details)
        assert credential_reference not in serialized
        assert "mcri/graph-alpha" not in serialized

    # Phase 15.3 makes Graph/Gmail execution state authoritative only through
    # the governed /execute path. The historical manual run-reporting endpoint
    # must not manufacture a provider fetch or checkpoint, even idempotently.
    payload = {"idempotency_key": "graph-run-0001", "trigger": "scheduled",
               "messages_seen": 2, "messages_ingested": 2, "provider_checkpoint": "opaque-cursor-77"}
    first = client.post(f"/api/v1/email-ingestion/adapters/{adapter['id']}/runs", json=payload)
    second = client.post(f"/api/v1/email-ingestion/adapters/{adapter['id']}/runs", json=payload)
    assert first.status_code == 409 and second.status_code == 409

    too_large = client.post(f"/api/v1/email-ingestion/adapters/{adapter['id']}/runs", json={
        **payload, "idempotency_key": "graph-run-0002", "messages_seen": 26, "messages_ingested": 26,
    })
    assert too_large.status_code == 409

    retention = client.post("/api/v1/email-ingestion/retention-runs", json={"idempotency_key": "aaaaaaaa"})
    retention_again = client.post("/api/v1/email-ingestion/retention-runs", json={"idempotency_key": "aaaaaaaa"})
    assert retention.status_code == 201 and retention.json()["id"] == retention_again.json()["id"]
    with TestingSessionLocal() as db:
        assert db.query(EmailProviderAdapter).count() == 1
        assert db.query(EmailAdapterRun).count() == 0
        assert db.query(EmailRetentionRun).count() == 1


def test_adapter_lifecycle_and_roles_follow_consented_connection() -> None:
    _, connection, _ = _connection()
    client.cookies.clear(); login("alpha", "alpha-handler@example.com")
    denied = client.post("/api/v1/email-ingestion/adapters", json={
        "connection_id": connection["id"], "provider_kind": "provider_webhook",
        "display_name": "Worker", "credential_reference": "env://WORKER_SECRET",
        "allowed_folder": "Claims", "permission_manifest": ["messages.read.allowed_folder"],
    })
    assert denied.status_code == 403
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    adapter = client.post("/api/v1/email-ingestion/adapters", json={
        "connection_id": connection["id"], "provider_kind": "provider_webhook",
        "display_name": "Worker", "credential_reference": "env://WORKER_SECRET",
        "allowed_folder": "Claims", "permission_manifest": ["messages.read.allowed_folder"],
    }).json()
    assert "credential_reference" not in adapter
    assert adapter["credential_backend"] == "env"
    assert adapter["credential_resolver_available"] is True
    assert client.post(f"/api/v1/email-ingestion/adapters/{adapter['id']}/transition",
                       json={"action": "suspend", "note": "Operational review."}).status_code == 200
    blocked = client.post(f"/api/v1/email-ingestion/adapters/{adapter['id']}/runs", json={
        "idempotency_key": "blocked-run-0001", "messages_seen": 0, "messages_ingested": 0,
    })
    assert blocked.status_code == 409
