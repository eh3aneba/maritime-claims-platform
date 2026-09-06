from __future__ import annotations

import base64
import json
from uuid import UUID

from app.modules.email_ingestion import provider_attachment_acquisition as acquisition
from app.modules.email_ingestion.models import EmailProviderAdapter, IngestedEmailMessage
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_email_provider_attachment_quarantine import (
    _enable_clean_scan,
    _stage_provider_attachment,
)


def setup_function() -> None:
    reset_database()


def test_suspended_connection_blocks_attachment_acquisition_before_network(monkeypatch) -> None:
    _, adapter, message_id, manifest_id = _stage_provider_attachment(linked=True)
    calls = _enable_clean_scan(monkeypatch)
    suspended = client.post(
        f"/api/v1/email-ingestion/connections/{adapter['connection_id']}/transition",
        json={"action": "suspend", "note": "Mailbox consent authority is temporarily suspended."},
    )
    assert suspended.status_code == 200

    response = client.post(
        f"/api/v1/email-ingestion/messages/{message_id}/attachments/{manifest_id}/acquire"
    )
    assert response.status_code == 409
    assert calls == {"locator": 0, "fetch": 0, "scan": 0}


def test_declared_attachment_size_overflow_fails_before_provider_fetch(monkeypatch) -> None:
    _, _, message_id, manifest_id = _stage_provider_attachment(linked=True)
    calls = _enable_clean_scan(monkeypatch)
    with TestingSessionLocal() as db:
        from app.modules.email_ingestion.models import EmailAttachmentManifest

        manifest = db.get(EmailAttachmentManifest, UUID(manifest_id))
        manifest.file_size_bytes = acquisition.settings.max_upload_bytes + 1
        db.commit()

    response = client.post(
        f"/api/v1/email-ingestion/messages/{message_id}/attachments/{manifest_id}/acquire"
    )
    assert response.status_code == 413
    assert calls == {"locator": 0, "fetch": 0, "scan": 0}


def test_graph_and_gmail_byte_fetches_are_exact_message_attachment_scoped(monkeypatch) -> None:
    _, graph_adapter, graph_message_id, _ = _stage_provider_attachment(
        provider_kind="microsoft_graph",
        linked=True,
    )
    with TestingSessionLocal() as db:
        graph = db.get(EmailProviderAdapter, UUID(graph_adapter["id"]))
        graph_message = db.get(IngestedEmailMessage, UUID(graph_message_id))
        graph_calls: list[str] = []

        def graph_http(url: str, token: str, *, max_bytes: int, accept: str):
            graph_calls.append(url)
            assert token == "graph-token"
            assert accept == "application/octet-stream"
            return b"graph-bytes"

        monkeypatch.setattr(acquisition, "_http_bytes", graph_http)
        assert acquisition._fetch_attachment_bytes(
            graph,
            "graph-token",
            graph_message,
            "graph-attachment-exact",
        ) == b"graph-bytes"
        assert len(graph_calls) == 1
        assert "/messages/microsoft_graph-attachment-message/attachments/graph-attachment-exact/$value" in graph_calls[0]

    reset_database()
    _, gmail_adapter, gmail_message_id, _ = _stage_provider_attachment(
        provider_kind="gmail_api",
        linked=True,
    )
    with TestingSessionLocal() as db:
        gmail = db.get(EmailProviderAdapter, UUID(gmail_adapter["id"]))
        gmail_message = db.get(IngestedEmailMessage, UUID(gmail_message_id))
        gmail_calls: list[str] = []
        encoded = base64.urlsafe_b64encode(b"gmail-bytes").decode().rstrip("=")

        def gmail_http(url: str, token: str, *, max_bytes: int, accept: str):
            gmail_calls.append(url)
            assert token == "gmail-token"
            assert accept == "application/json"
            return json.dumps({"data": encoded}).encode()

        monkeypatch.setattr(acquisition, "_http_bytes", gmail_http)
        assert acquisition._fetch_attachment_bytes(
            gmail,
            "gmail-token",
            gmail_message,
            "gmail-attachment-exact",
        ) == b"gmail-bytes"
        assert len(gmail_calls) == 1
        assert "/messages/gmail_api-attachment-message/attachments/gmail-attachment-exact" in gmail_calls[0]
