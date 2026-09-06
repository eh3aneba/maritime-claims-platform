import base64
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.correspondence.models import ClaimCorrespondence
from app.modules.email_ingestion.models import EmailProviderAdapter, IngestedEmailMessage
from app.modules.email_ingestion import provider_execution, provider_gmail_history
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import login
from tests.test_controlled_email_ingestion import _connection


def setup_function() -> None:
    reset_database()


def _adapter(
    provider_kind: str,
    *,
    credential_reference: str = "env://MCRI_PROVIDER_TEST_TOKEN",
    allowed_folder: str = "Claims",
    permissions: list[str] | None = None,
) -> tuple[str, dict, dict]:
    claim_id, connection, _ = _connection()
    created = client.post(
        "/api/v1/email-ingestion/adapters",
        json={
            "connection_id": connection["id"],
            "provider_kind": provider_kind,
            "display_name": f"{provider_kind} intake",
            "credential_reference": credential_reference,
            "allowed_folder": allowed_folder,
            "permission_manifest": permissions or [
                "messages.read.allowed_folder",
                "attachments.metadata.read",
            ],
            "batch_limit": 10,
            "retention_schedule_enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    return claim_id, connection, created.json()


def test_graph_pull_is_folder_scoped_idempotent_and_stages_only(monkeypatch) -> None:
    claim_id, connection, adapter = _adapter("microsoft_graph")
    monkeypatch.setenv("MCRI_PROVIDER_TEST_TOKEN", "graph-secret-value")
    calls: list[tuple[str, str]] = []
    next_checkpoint = (
        "https://graph.microsoft.com/v1.0/me/mailFolders/Claims/messages/delta?"
        "$skiptoken=opaque-graph-page-2"
    )

    def fake_http(url: str, token: str, *, headers=None):
        assert token == "graph-secret-value"
        calls.append((url, str(headers)))
        if "/attachments?" in url:
            assert "contentBytes" not in url
            return {
                "value": [
                    {
                        "id": "att-1",
                        "name": "chief-engineer-report.pdf",
                        "contentType": "application/pdf",
                        "size": 12000,
                        "isInline": False,
                    }
                ]
            }
        assert "/mailFolders/Claims/messages/delta" in url
        return {
            "value": [
                {
                    "id": "graph-message-1",
                    "internetMessageId": "<graph-message-1@orion.test>",
                    "subject": "MCRI-HM-2026-0001 - Graph provider report",
                    "body": {"contentType": "text", "content": "Chief Engineer report attached."},
                    "bodyPreview": "Chief Engineer report attached.",
                    "receivedDateTime": "2026-09-06T08:30:00Z",
                    "from": {"emailAddress": {"address": "master@orion-shipping.com"}},
                    "toRecipients": [{"emailAddress": {"address": connection["mailbox_address"]}}],
                    "ccRecipients": [],
                    "hasAttachments": True,
                }
            ],
            "@odata.nextLink": next_checkpoint,
        }

    monkeypatch.setattr(provider_execution, "_http_json", fake_http)
    executed = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/execute",
        json={"idempotency_key": "graph-exec-0001", "trigger": "manual"},
    )
    assert executed.status_code == 200, executed.text
    payload = executed.json()
    assert payload["run"]["status"] == "succeeded"
    assert payload["run"]["messages_seen"] == 1
    assert payload["run"]["messages_ingested"] == 1
    assert payload["next_checkpoint"] == next_checkpoint
    assert payload["replayed"] is False

    inbox = client.get("/api/v1/email-ingestion/inbox").json()
    staged = next(message for message in inbox["messages"] if message["provider_message_id"] == "graph-message-1")
    assert staged["adapter_id"] == adapter["id"]
    assert staged["status"] == "pending_review"
    assert staged["linked_claim_id"] is None
    assert staged["correspondence_id"] is None
    assert staged["attachments"][0]["admission_status"] == "blocked_pending_quarantine"

    with TestingSessionLocal() as db:
        db_adapter = db.get(EmailProviderAdapter, UUID(adapter["id"]))
        assert db_adapter.checkpoint_hash == sha256(next_checkpoint.encode()).hexdigest()
        message = db.scalar(
            select(IngestedEmailMessage).where(
                IngestedEmailMessage.provider_message_id == "graph-message-1"
            )
        )
        assert message.adapter_id == UUID(adapter["id"])
        assert db.query(ClaimCorrespondence).count() == 0

    first_call_count = len(calls)
    replay = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/execute",
        json={"idempotency_key": "graph-exec-0001", "trigger": "manual"},
    )
    assert replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert replay.json()["next_checkpoint"] is None
    assert len(calls) == first_call_count

    missing_checkpoint = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/execute",
        json={"idempotency_key": "graph-exec-0002", "trigger": "manual"},
    )
    assert missing_checkpoint.status_code == 409
    assert len(calls) == first_call_count
    assert all("sendMail" not in url and "/$value" not in url for url, _ in calls)


def test_gmail_pull_uses_label_scope_and_never_downloads_attachment_bytes(monkeypatch) -> None:
    _, connection, adapter = _adapter("gmail_api", allowed_folder="INBOX")
    monkeypatch.setenv("MCRI_PROVIDER_TEST_TOKEN", "gmail-secret-value")
    calls: list[str] = []
    body_data = base64.urlsafe_b64encode(b"Provider body from Gmail.").decode().rstrip("=")

    def fake_http(url: str, token: str, *, map_history_404=False):
        assert token == "gmail-secret-value"
        calls.append(url)
        assert "/attachments/" not in url
        assert map_history_404 is False
        if url.endswith("/profile"):
            return {"historyId": "9000"}
        if url.endswith("?format=full"):
            return {
                "id": "gmail-message-1",
                "internalDate": "1788685200000",
                "snippet": "Provider body from Gmail.",
                "payload": {
                    "mimeType": "multipart/mixed",
                    "headers": [
                        {"name": "From", "value": "Master <master@orion-shipping.com>"},
                        {"name": "To", "value": connection["mailbox_address"]},
                        {"name": "Cc", "value": "surveyor@example.com"},
                        {"name": "Subject", "value": "Gmail provider report"},
                        {"name": "Message-ID", "value": "<gmail-message-1@orion.test>"},
                    ],
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "filename": "",
                            "body": {"size": 25, "data": body_data},
                        },
                        {
                            "mimeType": "application/pdf",
                            "filename": "survey-report.pdf",
                            "body": {"size": 24000, "attachmentId": "attachment-byte-id-not-fetched"},
                        },
                    ],
                },
            }
        assert "labelIds=INBOX" in url
        if "pageToken=page-2" in url:
            return {"messages": []}
        return {"messages": [{"id": "gmail-message-1"}], "nextPageToken": "page-2"}

    monkeypatch.setattr(provider_gmail_history, "_gmail_http_json", fake_http)
    first = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/execute",
        json={"idempotency_key": "gmail-exec-0001"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["run"]["status"] == "succeeded"
    bootstrap_checkpoint = first.json()["next_checkpoint"]
    parsed_bootstrap = provider_gmail_history.decode_gmail_checkpoint(bootstrap_checkpoint)
    assert parsed_bootstrap.mode == "bootstrap_page"
    assert parsed_bootstrap.history_id == "9000"
    assert parsed_bootstrap.page_token == "page-2"

    inbox = client.get("/api/v1/email-ingestion/inbox").json()
    staged = next(message for message in inbox["messages"] if message["provider_message_id"] == "gmail-message-1")
    assert staged["adapter_id"] == adapter["id"]
    assert staged["sender"] == "master@orion-shipping.com"
    assert staged["body_text"] == "Provider body from Gmail."
    assert staged["attachments"][0]["filename"] == "survey-report.pdf"
    assert staged["attachments"][0]["admission_status"] == "blocked_pending_quarantine"
    assert staged["correspondence_id"] is None

    second = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/execute",
        json={"idempotency_key": "gmail-exec-0002", "provider_checkpoint": bootstrap_checkpoint},
    )
    assert second.status_code == 200, second.text
    assert second.json()["run"]["messages_seen"] == 0
    history_checkpoint = second.json()["next_checkpoint"]
    parsed_history = provider_gmail_history.decode_gmail_checkpoint(history_checkpoint)
    assert parsed_history.mode == "history"
    assert parsed_history.history_id == "9000"
    with TestingSessionLocal() as db:
        assert db.get(EmailProviderAdapter, UUID(adapter["id"])).checkpoint_hash == sha256(
            history_checkpoint.encode()
        ).hexdigest()
    assert calls[0].endswith("/profile")
    assert all("/attachments/" not in url and "/send" not in url for url in calls)


def test_unsupported_secret_resolver_fails_closed_without_leaking_reference(monkeypatch) -> None:
    _, _, adapter = _adapter(
        "microsoft_graph",
        credential_reference="vault://mcri/provider/graph-production",
    )
    calls: list[str] = []

    def fake_http(url: str, token: str, *, headers=None):
        calls.append(url)
        return {}

    monkeypatch.setattr(provider_execution, "_http_json", fake_http)
    response = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/execute",
        json={"idempotency_key": "graph-vault-0001"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["run"]["status"] == "failed"
    assert response.json()["run"]["failure_summary"] == "credential_resolver_unavailable"
    assert calls == []

    with TestingSessionLocal() as db:
        run_id = UUID(response.json()["run"]["id"])
        audit = db.scalar(
            select(AuditLog).where(
                AuditLog.entity_id == run_id,
                AuditLog.action == "EXECUTE_EMAIL_PROVIDER_PULL",
            )
        )
        assert audit is not None
        serialized = str(audit.new_values) + str(audit.details)
        assert "vault://" not in serialized
        assert "graph-production" not in serialized
        assert db.query(IngestedEmailMessage).count() == 0


def test_pull_execution_rejects_webhook_kind_and_missing_read_permission(monkeypatch) -> None:
    _, _, webhook = _adapter("provider_webhook")
    rejected = client.post(
        f"/api/v1/email-ingestion/adapters/{webhook['id']}/execute",
        json={"idempotency_key": "webhook-exec-0001"},
    )
    assert rejected.status_code == 409

    reset_database()
    _, _, graph = _adapter(
        "microsoft_graph",
        permissions=["attachments.metadata.read"],
    )
    monkeypatch.setenv("MCRI_PROVIDER_TEST_TOKEN", "graph-secret-value")
    denied = client.post(
        f"/api/v1/email-ingestion/adapters/{graph['id']}/execute",
        json={"idempotency_key": "graph-perm-0001"},
    )
    assert denied.status_code == 409


def test_pull_execution_requires_manager_role(monkeypatch) -> None:
    _, _, adapter = _adapter("microsoft_graph")
    monkeypatch.setenv("MCRI_PROVIDER_TEST_TOKEN", "graph-secret-value")
    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    denied = client.post(
        f"/api/v1/email-ingestion/adapters/{adapter['id']}/execute",
        json={"idempotency_key": "graph-role-0001"},
    )
    assert denied.status_code == 403