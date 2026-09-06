from __future__ import annotations

import base64
from hashlib import sha256
from urllib.error import HTTPError
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.modules.audit.models import AuditLog
from app.modules.email_ingestion import provider_gmail_history
from app.modules.email_ingestion.models import EmailAdapterRun, EmailProviderAdapter, IngestedEmailMessage
from app.modules.email_ingestion.provider_execution import ProviderExecutionFailure
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import TEST_PASSWORD, login
from tests.test_email_provider_execution import _adapter


def setup_function() -> None:
    reset_database()


def _gmail_message(message_id: str, mailbox: str, *, subject: str = "Incremental Gmail report") -> dict:
    body = base64.urlsafe_b64encode(f"Body for {message_id}".encode()).decode().rstrip("=")
    return {
        "id": message_id,
        "internalDate": "1788685200000",
        "snippet": f"Body for {message_id}",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "From", "value": "Master <master@orion-shipping.com>"},
                {"name": "To", "value": mailbox},
                {"name": "Subject", "value": subject},
                {"name": "Message-ID", "value": f"<{message_id}@orion.test>"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "filename": "",
                    "body": {"size": len(body), "data": body},
                },
                {
                    "mimeType": "application/pdf",
                    "filename": f"{message_id}.pdf",
                    "body": {"size": 12000, "attachmentId": f"att-{message_id}"},
                },
            ],
        },
    }


def _set_checkpoint(adapter_id: str, checkpoint: str) -> None:
    with TestingSessionLocal() as db:
        adapter = db.get(EmailProviderAdapter, UUID(adapter_id))
        adapter.checkpoint_hash = sha256(checkpoint.encode()).hexdigest()
        db.commit()


def _ack(adapter_id: str, run_id: str, checkpoint: str):
    return client.post(
        f"/api/v1/email-ingestion/adapters/{adapter_id}/runs/{run_id}/checkpoint-ack",
        json={"confirm_ack": True, "provider_checkpoint": checkpoint},
    )


def test_gmail_history_incremental_sync_uses_history_id_and_exact_message_ids(monkeypatch) -> None:
    _, connection, adapter = _adapter("gmail_api", allowed_folder="INBOX")
    monkeypatch.setenv("MCRI_PROVIDER_TEST_TOKEN", "gmail-secret-value")
    start_checkpoint = provider_gmail_history.encode_gmail_checkpoint("history", "9000")
    _set_checkpoint(adapter["id"], start_checkpoint)
    calls: list[str] = []

    def fake_http(url: str, token: str, *, map_history_404=False):
        assert token == "gmail-secret-value"
        calls.append(url)
        assert "/send" not in url and "/attachments/" not in url
        if "/history?" in url:
            assert map_history_404 is True
            assert "startHistoryId=9000" in url
            assert "labelId=INBOX" in url
            assert "historyTypes=messageAdded" in url
            if "pageToken=hist-page-2" in url:
                return {"history": [], "historyId": "9020"}
            return {
                "history": [
                    {
                        "id": "9005",
                        "messagesAdded": [
                            {"message": {"id": "gmail-new-1", "threadId": "thread-1"}},
                            {"message": {"id": "gmail-new-1", "threadId": "thread-1"}},
                        ],
                    }
                ],
                "historyId": "9010",
                "nextPageToken": "hist-page-2",
            }
        if "gmail-new-1?format=full" in url:
            assert map_history_404 is False
            return _gmail_message("gmail-new-1", connection["mailbox_address"])
        raise AssertionError(f"Unexpected Gmail URL: {url}")

    monkeypatch.setattr(provider_gmail_history, "_gmail_http_json", fake_http)
    first = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/execute",
        json={"idempotency_key": "gmail-history-0001", "provider_checkpoint": start_checkpoint},
    )
    assert first.status_code == 200, first.text
    assert first.json()["run"]["status"] == "succeeded"
    assert first.json()["run"]["messages_seen"] == 1
    assert first.json()["run"]["messages_ingested"] == 1
    assert first.json()["run"]["checkpoint_handoff_status"] == "pending"
    page_checkpoint = first.json()["next_checkpoint"]
    page = provider_gmail_history.decode_gmail_checkpoint(page_checkpoint)
    assert page.mode == "history_page"
    assert page.history_id == "9000"
    assert page.page_token == "hist-page-2"

    with TestingSessionLocal() as db:
        assert db.get(EmailProviderAdapter, UUID(adapter["id"])).checkpoint_hash == sha256(
            start_checkpoint.encode()
        ).hexdigest()

    ack_first = _ack(adapter["id"], first.json()["run"]["id"], page_checkpoint)
    assert ack_first.status_code == 200, ack_first.text

    second = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/execute",
        json={"idempotency_key": "gmail-history-0002", "provider_checkpoint": page_checkpoint},
    )
    assert second.status_code == 200, second.text
    assert second.json()["run"]["messages_seen"] == 0
    steady_checkpoint = second.json()["next_checkpoint"]
    steady = provider_gmail_history.decode_gmail_checkpoint(steady_checkpoint)
    assert steady.mode == "history"
    assert steady.history_id == "9020"

    inbox = client.get("/api/v1/email-ingestion/inbox").json()
    staged = [m for m in inbox["messages"] if m["provider_message_id"] == "gmail-new-1"]
    assert len(staged) == 1
    assert staged[0]["linked_claim_id"] is None
    assert staged[0]["correspondence_id"] is None
    assert staged[0]["attachments"][0]["admission_status"] == "blocked_pending_quarantine"
    with TestingSessionLocal() as db:
        assert db.query(IngestedEmailMessage).filter(
            IngestedEmailMessage.provider_message_id == "gmail-new-1"
        ).count() == 1
        assert db.get(EmailProviderAdapter, UUID(adapter["id"])).checkpoint_hash == sha256(
            page_checkpoint.encode()
        ).hexdigest()

    ack_second = _ack(adapter["id"], second.json()["run"]["id"], steady_checkpoint)
    assert ack_second.status_code == 200
    with TestingSessionLocal() as db:
        assert db.get(EmailProviderAdapter, UUID(adapter["id"])).checkpoint_hash == sha256(
            steady_checkpoint.encode()
        ).hexdigest()


def test_gmail_history_batch_overflow_fails_closed() -> None:
    payload = {
        "history": [
            {
                "messagesAdded": [
                    {"message": {"id": "one"}},
                    {"message": {"id": "two"}},
                ]
            }
        ]
    }
    with pytest.raises(ProviderExecutionFailure) as exc:
        provider_gmail_history._history_message_ids(payload, 1)
    assert exc.value.code == "gmail_history_batch_overflow"


def test_legacy_gmail_checkpoint_requires_explicit_resync_without_auto_clear(monkeypatch) -> None:
    _, _, adapter = _adapter("gmail_api", allowed_folder="INBOX")
    monkeypatch.setenv("MCRI_PROVIDER_TEST_TOKEN", "gmail-secret-value")
    legacy_checkpoint = "legacy-list-page-token"
    expected_hash = sha256(legacy_checkpoint.encode()).hexdigest()
    _set_checkpoint(adapter["id"], legacy_checkpoint)

    network_called = {"value": False}

    def should_not_fetch(*args, **kwargs):
        network_called["value"] = True
        raise AssertionError("Legacy checkpoint must fail before Gmail network execution")

    monkeypatch.setattr(provider_gmail_history, "_gmail_http_json", should_not_fetch)
    failed = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/execute",
        json={"idempotency_key": "gmail-legacy-0001", "provider_checkpoint": legacy_checkpoint},
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["run"]["status"] == "failed"
    assert failed.json()["run"]["failure_summary"] == "gmail_checkpoint_resync_required"
    assert network_called["value"] is False

    with TestingSessionLocal() as db:
        db_adapter = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        assert db_adapter.checkpoint_hash == expected_hash

    reconciliation = client.get("/api/v1/email-ingestion/adapter-reconciliation")
    assert reconciliation.status_code == 200
    item = next(i for i in reconciliation.json()["items"] if i["adapter_id"] == adapter["id"])
    assert item["operational_state"] == "reconciliation_required"
    assert item["last_run_failure_code"] == "gmail_checkpoint_resync_required"
    assert item["checkpoint_reset_available"] is True
    serialized = str(item)
    assert legacy_checkpoint not in serialized
    assert expected_hash not in serialized


def test_gmail_checkpoint_reset_is_explicit_manager_only_and_makes_adapter_due(monkeypatch) -> None:
    _, _, adapter = _adapter("gmail_api", allowed_folder="INBOX")
    monkeypatch.setenv("MCRI_PROVIDER_TEST_TOKEN", "gmail-secret-value")
    legacy_checkpoint = "legacy-list-page-token"
    _set_checkpoint(adapter["id"], legacy_checkpoint)
    failed = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/execute",
        json={"idempotency_key": "gmail-reset-seed", "provider_checkpoint": legacy_checkpoint},
    )
    assert failed.status_code == 200
    assert failed.json()["run"]["failure_summary"] == "gmail_checkpoint_resync_required"

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    denied = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/checkpoint-reset",
        json={"confirm_reset": True},
    )
    assert denied.status_code == 403

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    unconfirmed = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/checkpoint-reset",
        json={"confirm_reset": False},
    )
    assert unconfirmed.status_code == 422

    reset = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/checkpoint-reset",
        json={"confirm_reset": True},
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["reset_performed"] is True
    assert reset.json()["last_failure_code"] == "gmail_checkpoint_resync_required"
    with TestingSessionLocal() as db:
        db_adapter = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        assert db_adapter.checkpoint_hash is None
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.entity_id == db_adapter.id,
                AuditLog.action == "RESET_GMAIL_PROVIDER_CHECKPOINT",
            )
        )
        assert audit is not None
        serialized = str(audit.new_values) + str(audit.details)
        assert legacy_checkpoint not in serialized
        assert "gmail-secret-value" not in serialized

    replay_reset = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/checkpoint-reset",
        json={"confirm_reset": True},
    )
    assert replay_reset.status_code == 409

    reconciliation = client.get("/api/v1/email-ingestion/adapter-reconciliation")
    item = next(i for i in reconciliation.json()["items"] if i["adapter_id"] == adapter["id"])
    assert item["operational_state"] == "due"
    assert item["checkpoint_reset_available"] is False
    assert item["checkpoint_handoff_required"] is False


def test_gmail_checkpoint_reset_is_tenant_source_and_status_gated(monkeypatch) -> None:
    _, _, gmail = _adapter("gmail_api", allowed_folder="INBOX")
    monkeypatch.setenv("MCRI_PROVIDER_TEST_TOKEN", "gmail-secret-value")
    legacy = "legacy-page-token"
    _set_checkpoint(gmail["id"], legacy)
    failed = client.post(
        f"/api/v1/email-ingestion/adapters/{gmail['id']}/execute",
        json={"idempotency_key": "gmail-gates-seed", "provider_checkpoint": legacy},
    )
    assert failed.status_code == 200

    with TestingSessionLocal() as db:
        beta = db.query(Organization).filter(Organization.slug == "beta").one()
        db.add(
            User(
                organization_id=beta.id,
                email="beta-gmail-reset-admin@example.com",
                full_name="Beta Gmail Reset Admin",
                password_hash=hash_password(TEST_PASSWORD),
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
        db.commit()

    client.cookies.clear()
    login("beta", "beta-gmail-reset-admin@example.com")
    cross_tenant = client.post(
        f"/api/v1/email-ingestion/adapters/{gmail['id']}/checkpoint-reset",
        json={"confirm_reset": True},
    )
    assert cross_tenant.status_code == 404

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    suspended = client.post(
        f"/api/v1/email-ingestion/adapters/{gmail['id']}/transition",
        json={"action": "suspend", "note": "Suspend Gmail source before reset test."},
    )
    assert suspended.status_code == 200
    inactive = client.post(
        f"/api/v1/email-ingestion/adapters/{gmail['id']}/checkpoint-reset",
        json={"confirm_reset": True},
    )
    assert inactive.status_code == 409

    reset_database()
    _, _, graph = _adapter("microsoft_graph")
    graph_reset = client.post(
        f"/api/v1/email-ingestion/adapters/{graph['id']}/checkpoint-reset",
        json={"confirm_reset": True},
    )
    assert graph_reset.status_code == 409


def test_gmail_history_http_404_maps_to_resync_required(monkeypatch) -> None:
    def missing(*args, **kwargs):
        raise HTTPError(
            url="https://gmail.googleapis.com/gmail/v1/users/me/history",
            code=404,
            msg="History id too old",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(provider_gmail_history, "urlopen", missing)
    with pytest.raises(ProviderExecutionFailure) as exc:
        provider_gmail_history._gmail_http_json(
            "https://gmail.googleapis.com/gmail/v1/users/me/history?startHistoryId=1",
            "secret-never-logged",
            map_history_404=True,
        )
    assert exc.value.code == "gmail_history_resync_required"


def test_gmail_stale_history_failure_does_not_mutate_checkpoint(monkeypatch) -> None:
    _, _, adapter = _adapter("gmail_api", allowed_folder="INBOX")
    monkeypatch.setenv("MCRI_PROVIDER_TEST_TOKEN", "gmail-secret-value")
    checkpoint = provider_gmail_history.encode_gmail_checkpoint("history", "9000")
    expected_hash = sha256(checkpoint.encode()).hexdigest()
    _set_checkpoint(adapter["id"], checkpoint)

    def stale(*args, **kwargs):
        raise ProviderExecutionFailure("gmail_history_resync_required")

    monkeypatch.setattr(provider_gmail_history, "fetch_gmail_provider_page", stale)
    response = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/execute",
        json={"idempotency_key": "gmail-stale-history", "provider_checkpoint": checkpoint},
    )
    assert response.status_code == 200
    assert response.json()["run"]["status"] == "failed"
    assert response.json()["run"]["failure_summary"] == "gmail_history_resync_required"
    with TestingSessionLocal() as db:
        db_adapter = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        assert db_adapter.checkpoint_hash == expected_hash
        last_run = db.scalar(
            select(EmailAdapterRun)
            .where(EmailAdapterRun.adapter_id == db_adapter.id)
            .order_by(EmailAdapterRun.started_at.desc())
            .limit(1)
        )
        assert last_run.failure_summary == "gmail_history_resync_required"
