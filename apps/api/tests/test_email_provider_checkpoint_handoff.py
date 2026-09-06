from __future__ import annotations

from hashlib import sha256
from uuid import UUID

from sqlalchemy import select

from app.core.security import hash_password
from app.modules.audit.models import AuditLog
from app.modules.email_ingestion import provider_execution
from app.modules.email_ingestion.models import EmailAdapterRun, EmailProviderAdapter, IngestedEmailMessage
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import TEST_PASSWORD, login
from tests.test_email_provider_execution import _adapter


def setup_function() -> None:
    reset_database()


def _graph_page(connection: dict, checkpoint: str, calls: list[str]):
    def fake_http(url: str, token: str, *, headers=None):
        assert token == "graph-handoff-secret"
        calls.append(url)
        if "/attachments?" in url:
            return {"value": []}
        return {
            "value": [
                {
                    "id": "handoff-message-1",
                    "internetMessageId": "<handoff-message-1@orion.test>",
                    "subject": "Checkpoint custody test",
                    "body": {"contentType": "text", "content": "Provider staging only."},
                    "bodyPreview": "Provider staging only.",
                    "receivedDateTime": "2026-09-06T10:00:00Z",
                    "from": {"emailAddress": {"address": "master@orion.test"}},
                    "toRecipients": [{"emailAddress": {"address": connection["mailbox_address"]}}],
                    "ccRecipients": [],
                    "hasAttachments": False,
                }
            ],
            "@odata.deltaLink": checkpoint,
        }
    return fake_http


def _execute_graph(adapter_id: str, key: str, checkpoint: str | None = None):
    payload = {"idempotency_key": key, "trigger": "manual"}
    if checkpoint is not None:
        payload["provider_checkpoint"] = checkpoint
    return client.post(f"/api/v1/email-ingestion/adapters/{adapter_id}/execute", json=payload)


def test_successful_pull_stays_pending_until_exact_checkpoint_ack(monkeypatch) -> None:
    _, connection, adapter = _adapter("microsoft_graph")
    monkeypatch.setenv("MCRI_PROVIDER_TEST_TOKEN", "graph-handoff-secret")
    next_checkpoint = (
        "https://graph.microsoft.com/v1.0/me/mailFolders/Claims/messages/delta?"
        "$deltatoken=handoff-0001"
    )
    calls: list[str] = []
    monkeypatch.setattr(provider_execution, "_http_json", _graph_page(connection, next_checkpoint, calls))

    first = _execute_graph(adapter["id"], "handoff-run-0001")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["run"]["status"] == "succeeded"
    assert body["run"]["checkpoint_handoff_status"] == "pending"
    assert body["checkpoint_handoff_required"] is True
    assert body["next_checkpoint"] == next_checkpoint

    with TestingSessionLocal() as db:
        db_adapter = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        run = db.get(EmailAdapterRun, UUID(body["run"]["id"]))
        assert db_adapter.checkpoint_hash is None
        assert db_adapter.next_sync_at is None
        assert run.checkpoint_hash == sha256(next_checkpoint.encode()).hexdigest()
        assert run.checkpoint_handoff_status == "pending"

    reconciliation = client.get("/api/v1/email-ingestion/adapter-reconciliation")
    assert reconciliation.status_code == 200
    item = next(value for value in reconciliation.json()["items"] if value["adapter_id"] == adapter["id"])
    assert item["operational_state"] == "checkpoint_handoff_pending"
    assert item["checkpoint_handoff_required"] is True
    assert item["pending_checkpoint_run_id"] == body["run"]["id"]
    assert item["checkpoint_ack_available"] is True
    assert item["checkpoint_abandon_available"] is True
    serialized_reconciliation = str(item)
    assert next_checkpoint not in serialized_reconciliation
    assert "graph-handoff-secret" not in serialized_reconciliation

    wrong = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/runs/{body['run']['id']}/checkpoint-ack",
        json={"confirm_ack": True, "provider_checkpoint": next_checkpoint + "-wrong"},
    )
    assert wrong.status_code == 409
    with TestingSessionLocal() as db:
        assert db.get(EmailProviderAdapter, UUID(adapter["id"])).checkpoint_hash is None

    acknowledged = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/runs/{body['run']['id']}/checkpoint-ack",
        json={"confirm_ack": True, "provider_checkpoint": next_checkpoint},
    )
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["checkpoint_committed"] is True
    assert acknowledged.json()["checkpoint_handoff_status"] == "acknowledged"

    with TestingSessionLocal() as db:
        db_adapter = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        run = db.get(EmailAdapterRun, UUID(body["run"]["id"]))
        assert db_adapter.checkpoint_hash == sha256(next_checkpoint.encode()).hexdigest()
        assert db_adapter.next_sync_at is not None
        assert run.checkpoint_handoff_status == "acknowledged"
        assert run.checkpoint_acknowledged_at is not None
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.entity_id == run.id,
                AuditLog.action == "ACKNOWLEDGE_EMAIL_PROVIDER_CHECKPOINT",
            )
        )
        assert audit is not None
        serialized = str(audit.new_values) + str(audit.details)
        assert next_checkpoint not in serialized
        assert sha256(next_checkpoint.encode()).hexdigest() not in serialized
        assert "graph-handoff-secret" not in serialized


def test_pending_handoff_blocks_new_network_execution_but_exact_replay_is_safe(monkeypatch) -> None:
    _, connection, adapter = _adapter("microsoft_graph")
    monkeypatch.setenv("MCRI_PROVIDER_TEST_TOKEN", "graph-handoff-secret")
    next_checkpoint = (
        "https://graph.microsoft.com/v1.0/me/mailFolders/Claims/messages/delta?"
        "$deltatoken=handoff-0002"
    )
    calls: list[str] = []
    monkeypatch.setattr(provider_execution, "_http_json", _graph_page(connection, next_checkpoint, calls))

    first = _execute_graph(adapter["id"], "handoff-run-0002")
    assert first.status_code == 200
    call_count = len(calls)

    replay = _execute_graph(adapter["id"], "handoff-run-0002")
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["next_checkpoint"] is None
    assert replay.json()["checkpoint_handoff_required"] is True
    assert len(calls) == call_count

    blocked = _execute_graph(adapter["id"], "handoff-run-0003")
    assert blocked.status_code == 409
    assert len(calls) == call_count


def test_abandon_preserves_previous_cursor_and_allows_idempotent_reexecution(monkeypatch) -> None:
    _, connection, adapter = _adapter("microsoft_graph")
    monkeypatch.setenv("MCRI_PROVIDER_TEST_TOKEN", "graph-handoff-secret")
    next_checkpoint = (
        "https://graph.microsoft.com/v1.0/me/mailFolders/Claims/messages/delta?"
        "$deltatoken=handoff-0004"
    )
    calls: list[str] = []
    monkeypatch.setattr(provider_execution, "_http_json", _graph_page(connection, next_checkpoint, calls))

    first = _execute_graph(adapter["id"], "handoff-run-0004")
    assert first.status_code == 200
    run_id = first.json()["run"]["id"]
    with TestingSessionLocal() as db:
        assert db.get(EmailProviderAdapter, UUID(adapter["id"])).checkpoint_hash is None
        assert db.query(IngestedEmailMessage).filter(
            IngestedEmailMessage.provider_message_id == "handoff-message-1"
        ).count() == 1

    abandoned = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/runs/{run_id}/checkpoint-abandon",
        json={
            "confirm_abandon": True,
            "reason": "The execution response checkpoint was not durably received by the operator.",
        },
    )
    assert abandoned.status_code == 200, abandoned.text
    assert abandoned.json()["checkpoint_handoff_status"] == "abandoned"
    assert abandoned.json()["previous_cursor_preserved"] is True

    with TestingSessionLocal() as db:
        db_adapter = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        assert db_adapter.checkpoint_hash is None
        assert db_adapter.next_sync_at is not None

    second = _execute_graph(adapter["id"], "handoff-run-0005")
    assert second.status_code == 200, second.text
    assert second.json()["run"]["messages_seen"] == 1
    assert second.json()["run"]["messages_ingested"] == 0
    assert second.json()["run"]["checkpoint_handoff_status"] == "pending"
    with TestingSessionLocal() as db:
        assert db.query(IngestedEmailMessage).filter(
            IngestedEmailMessage.provider_message_id == "handoff-message-1"
        ).count() == 1


def test_checkpoint_handoff_actions_are_manager_and_tenant_scoped(monkeypatch) -> None:
    _, connection, adapter = _adapter("microsoft_graph")
    monkeypatch.setenv("MCRI_PROVIDER_TEST_TOKEN", "graph-handoff-secret")
    next_checkpoint = (
        "https://graph.microsoft.com/v1.0/me/mailFolders/Claims/messages/delta?"
        "$deltatoken=handoff-0006"
    )
    monkeypatch.setattr(provider_execution, "_http_json", _graph_page(connection, next_checkpoint, []))
    first = _execute_graph(adapter["id"], "handoff-run-0006")
    assert first.status_code == 200
    run_id = first.json()["run"]["id"]

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    denied = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/runs/{run_id}/checkpoint-ack",
        json={"confirm_ack": True, "provider_checkpoint": next_checkpoint},
    )
    assert denied.status_code == 403

    with TestingSessionLocal() as db:
        beta = db.query(Organization).filter(Organization.slug == "beta").one()
        db.add(
            User(
                organization_id=beta.id,
                email="beta-handoff-admin@example.com",
                full_name="Beta Handoff Admin",
                password_hash=hash_password(TEST_PASSWORD),
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
        db.commit()

    client.cookies.clear()
    login("beta", "beta-handoff-admin@example.com")
    cross_tenant = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/runs/{run_id}/checkpoint-abandon",
        json={
            "confirm_abandon": True,
            "reason": "Cross-tenant checkpoint handoff mutation must never be authorized here.",
        },
    )
    assert cross_tenant.status_code == 404


def test_webhook_runs_never_enter_checkpoint_handoff_state() -> None:
    _, _, adapter = _adapter("provider_webhook")
    created = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/runs",
        json={
            "idempotency_key": "webhook-handoff-none",
            "trigger": "provider_push",
            "messages_seen": 1,
            "messages_ingested": 1,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["checkpoint_handoff_status"] == "not_required"
