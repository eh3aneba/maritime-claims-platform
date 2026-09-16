import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.credential_reference_health_service import clear_external_document_source_credential_reference_health_resolvers
from app.modules.external_document_sources.credential_resolution_execution_service import clear_external_document_source_credential_resolution_resolvers
from app.modules.external_document_sources.discovery_service import clear_external_document_source_discovery_adapters
from app.modules.external_document_sources.provider_client_health_service import clear_external_document_source_provider_client_health_adapters
from app.modules.external_document_sources.remote_file_content_read_models import (
    MAX_REMOTE_CONTENT_BYTES,
    ExternalDocumentSourceRemoteFileContentReadExecution,
    ExternalDocumentSourceRemoteFileContentReadReceipt,
)
from app.modules.external_document_sources.remote_file_content_read_service import (
    RemoteFileContentReadResult,
    clear_external_document_source_remote_file_content_read_adapters,
    register_external_document_source_remote_file_content_read_adapter,
)
from app.modules.external_document_sources.remote_metadata_listing_models import ExternalDocumentSourceRemoteMetadataListingItem
from app.modules.external_document_sources.remote_metadata_listing_service import (
    RemoteMetadataItemProjection,
    RemoteMetadataListResult,
    clear_external_document_source_remote_metadata_list_adapters,
    register_external_document_source_remote_metadata_list_adapter,
)
from app.modules.external_document_sources.token_acquisition_execution_service import clear_external_document_source_token_acquirers
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_remote_metadata_listing import (
    _LIST_REASON,
    _completed_phase_k,
    _list_metadata,
)

_READ_REASON = "Read one exact Phase L remote file transiently and persist only bounded non-content proof."
_FILE_BODY_MARKER = "phase-m-file-body-marker"
_FILE_BODY_PREFIX = (_FILE_BODY_MARKER + "|").encode()
_FILE_BODY = _FILE_BODY_PREFIX + (b"x" * (4096 - len(_FILE_BODY_PREFIX)))
_CLIENT_SECRET = "phase-m-client-secret-marker"
_ACCESS_TOKEN = "phase-m-access-token-marker"
_CLIENT_OBJECT = "phase-m-provider-client-marker"
_RAW_RESPONSE = "phase-m-provider-raw-response-marker"
_DOWNLOAD_URL = "https://example.test/phase-m-provider-download-marker"
_VERSION_HASH = "a" * 64


class _MListAdapter:
    adapter_kind = "deterministic_phase_m_metadata_list_v1"
    provider_kind = "sharepoint"
    client_kind = "microsoft_graph_transient_v1"
    listing_operation_kind = "graph_drive_children_metadata_v1"
    provider_origin = "https://graph.microsoft.com"

    def __init__(self, *, file_size: int = len(_FILE_BODY)):
        self.file_size = file_size
        self.calls = 0

    def list_metadata(self, locator, policy):
        self.calls += 1
        assert policy.max_items == 100
        return RemoteMetadataListResult(
            listed=True,
            items=(
                RemoteMetadataItemProjection(
                    provider_item_id="remote-file-m-001",
                    parent_item_id="remote-folder-root",
                    item_kind="file",
                    display_name="Phase M Survey Report.pdf",
                    mime_type_class="application/pdf",
                    byte_size=self.file_size,
                    modified_at=datetime(2026, 9, 16, 5, 20, tzinfo=timezone.utc),
                    version_token_hash=_VERSION_HASH,
                ),
                RemoteMetadataItemProjection(
                    provider_item_id="remote-folder-m-002",
                    parent_item_id="remote-folder-root",
                    item_kind="folder",
                    display_name="Phase M Folder",
                    modified_at=datetime(2026, 9, 16, 5, 21, tzinfo=timezone.utc),
                    version_token_hash="b" * 64,
                ),
            ),
            truncated=False,
            page_count=1,
        )


class _ReadAdapter:
    adapter_kind = "deterministic_remote_content_read_v1"
    provider_kind = "sharepoint"
    client_kind = "microsoft_graph_transient_v1"
    read_operation_kind = "graph_drive_item_content_read_v1"
    provider_origin = "https://graph.microsoft.com"
    redirect_policy_kind = "provider_internal_https_one_hop_v1"

    def __init__(
        self,
        *,
        failure_code: str | None = None,
        raise_with_secrets: bool = False,
        content: bytes = _FILE_BODY,
        invalid_content: bool = False,
        observed_version_token_hash: str = _VERSION_HASH,
        media_type_class: str = "application/pdf",
    ):
        self.failure_code = failure_code
        self.raise_with_secrets = raise_with_secrets
        self.content = content
        self.invalid_content = invalid_content
        self.observed_version_token_hash = observed_version_token_hash
        self.media_type_class = media_type_class
        self.calls = 0
        self.last_locator = None
        self.last_policy = None

    def read_content(self, locator, policy):
        self.calls += 1
        self.last_locator = locator
        self.last_policy = policy
        client_secret = _CLIENT_SECRET
        access_token = _ACCESS_TOKEN
        transient_client = _CLIENT_OBJECT
        raw_response = _RAW_RESPONSE
        download_url = _DOWNLOAD_URL
        file_body_marker = _FILE_BODY_MARKER
        assert client_secret and access_token and transient_client and raw_response and download_url and file_body_marker
        assert policy.provider_origin == "https://graph.microsoft.com"
        assert "/v1.0/sites/" in policy.content_endpoint_url
        assert "/drives/" in policy.content_endpoint_url
        assert "/items/remote-file-m-001/content" in policy.content_endpoint_url
        assert policy.max_content_bytes == MAX_REMOTE_CONTENT_BYTES
        assert policy.max_chunk_bytes == 65536
        assert policy.redirect_policy_kind == "provider_internal_https_one_hop_v1"
        assert policy.max_redirects == 1
        if self.raise_with_secrets:
            raise RuntimeError(
                f"content read failed {client_secret} {access_token} {transient_client} {raw_response} {download_url} {file_body_marker}"
            )
        if self.failure_code is not None:
            return RemoteFileContentReadResult(read=False, failure_code=self.failure_code)
        if self.invalid_content:
            return RemoteFileContentReadResult(  # type: ignore[arg-type]
                read=True,
                content="not-bytes",
                media_type_class=self.media_type_class,
                observed_version_token_hash=self.observed_version_token_hash,
                latency_class="normal",
            )
        return RemoteFileContentReadResult(
            read=True,
            content=self.content,
            media_type_class=self.media_type_class,
            observed_version_token_hash=self.observed_version_token_hash,
            latency_class="normal",
        )


class _WrongOriginReadAdapter(_ReadAdapter):
    provider_origin = "https://evil.example.test"


class _WrongRedirectReadAdapter(_ReadAdapter):
    redirect_policy_kind = "arbitrary_redirects_v1"


def setup_function() -> None:
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()
    clear_external_document_source_credential_resolution_resolvers()
    clear_external_document_source_token_acquirers()
    clear_external_document_source_provider_client_health_adapters()
    clear_external_document_source_remote_metadata_list_adapters()
    clear_external_document_source_remote_file_content_read_adapters()
    reset_database()


def teardown_function() -> None:
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()
    clear_external_document_source_credential_resolution_resolvers()
    clear_external_document_source_token_acquirers()
    clear_external_document_source_provider_client_health_adapters()
    clear_external_document_source_remote_metadata_list_adapters()
    clear_external_document_source_remote_file_content_read_adapters()


def _read_content(
    profile_id: str,
    listing_execution_id: str,
    metadata_item_id: str,
    actor_id: UUID,
    *,
    key: str,
    reason: str = _READ_REASON,
):
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/remote-metadata-listing-executions/{listing_execution_id}/items/{metadata_item_id}/remote-content-read-executions",
        headers=_headers(actor_id),
        json={"request_key": key, "reason": reason},
    )


def _completed_phase_l(*, file_size: int = len(_FILE_BODY)):
    requester_id, profile_id, binding_id, health_execution_id = _completed_phase_k()
    listing_adapter = _MListAdapter(file_size=file_size)
    register_external_document_source_remote_metadata_list_adapter(
        "sharepoint",
        "graph_drive_children_metadata_v1",
        listing_adapter,
    )
    listed = _list_metadata(
        profile_id,
        health_execution_id,
        requester_id,
        key="remote-file-content-read-phase-l",
        reason=_LIST_REASON,
    )
    assert listed.status_code == 201, listed.text
    body = listed.json()
    assert listing_adapter.calls == 1
    file_item = next(item for item in body["items"] if item["item_kind"] == "file")
    folder_item = next(item for item in body["items"] if item["item_kind"] == "folder")
    return requester_id, profile_id, binding_id, body["id"], file_item["id"], folder_item["id"]


def test_phase_m_bounded_remote_file_content_read_proof(caplog: pytest.LogCaptureFixture) -> None:
    requester_id, profile_id, binding_id, listing_execution_id, file_item_id, folder_item_id = _completed_phase_l()
    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    missing = _read_content(
        profile_id,
        listing_execution_id,
        file_item_id,
        requester_id,
        key="remote-read-missing",
    )
    assert missing.status_code == 409, missing.text
    assert "adapter is unavailable" in missing.text
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceRemoteFileContentReadExecution).count() == 0
        assert db.query(ExternalDocumentSourceRemoteFileContentReadReceipt).count() == 0

    wrong_origin = _WrongOriginReadAdapter()
    with pytest.raises(ValueError, match="origin"):
        register_external_document_source_remote_file_content_read_adapter(
            "sharepoint",
            "graph_drive_item_content_read_v1",
            wrong_origin,
        )
    assert wrong_origin.calls == 0

    wrong_redirect = _WrongRedirectReadAdapter()
    with pytest.raises(ValueError, match="redirect policy"):
        register_external_document_source_remote_file_content_read_adapter(
            "sharepoint",
            "graph_drive_item_content_read_v1",
            wrong_redirect,
        )
    assert wrong_redirect.calls == 0

    success = _ReadAdapter()
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        success,
    )
    folder = _read_content(
        profile_id,
        listing_execution_id,
        folder_item_id,
        requester_id,
        key="remote-read-folder",
    )
    assert folder.status_code == 409, folder.text
    assert "file metadata items" in folder.text
    assert success.calls == 0

    forbidden = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/remote-metadata-listing-executions/{listing_execution_id}/items/{file_item_id}/remote-content-read-executions",
        headers=_headers(requester_id),
        json={
            "request_key": "remote-read-forbidden",
            "reason": _READ_REASON,
            "provider_item_id": "do-not-accept",
            "url": _DOWNLOAD_URL,
            "range": "bytes=0-10",
            "content": _FILE_BODY_MARKER,
            "access_token": "do-not-accept",
        },
    )
    assert forbidden.status_code == 422, forbidden.text
    assert success.calls == 0

    _, other_requester, _ = _seed_tenant("remote-file-read-other-tenant")
    wrong_tenant = _read_content(
        profile_id,
        listing_execution_id,
        file_item_id,
        other_requester,
        key="remote-read-wrong-tenant",
    )
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert success.calls == 0

    for failure_code in ("provider_rejected", "timeout", "permission_denied"):
        negative = _ReadAdapter(failure_code=failure_code)
        register_external_document_source_remote_file_content_read_adapter(
            "sharepoint",
            "graph_drive_item_content_read_v1",
            negative,
        )
        response = _read_content(
            profile_id,
            listing_execution_id,
            file_item_id,
            requester_id,
            key=f"remote-read-{failure_code}",
        )
        assert response.status_code == 409, response.text
        assert failure_code in response.text
        assert negative.calls == 1
        with TestingSessionLocal() as db:
            assert db.query(ExternalDocumentSourceRemoteFileContentReadExecution).count() == 0
            assert db.query(ExternalDocumentSourceRemoteFileContentReadReceipt).count() == 0

    malformed = _ReadAdapter(invalid_content=True)
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        malformed,
    )
    malformed_response = _read_content(
        profile_id,
        listing_execution_id,
        file_item_id,
        requester_id,
        key="remote-read-malformed",
    )
    assert malformed_response.status_code == 409, malformed_response.text
    assert "invalid content body" in malformed_response.text
    assert malformed.calls == 1

    version_mismatch = _ReadAdapter(observed_version_token_hash="c" * 64)
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        version_mismatch,
    )
    mismatched = _read_content(
        profile_id,
        listing_execution_id,
        file_item_id,
        requester_id,
        key="remote-read-version-mismatch",
    )
    assert mismatched.status_code == 409, mismatched.text
    assert "version no longer matches" in mismatched.text
    assert version_mismatch.calls == 1

    oversized = _ReadAdapter(content=b"z" * (MAX_REMOTE_CONTENT_BYTES + 1))
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        oversized,
    )
    oversized_response = _read_content(
        profile_id,
        listing_execution_id,
        file_item_id,
        requester_id,
        key="remote-read-actual-oversize",
    )
    assert oversized_response.status_code == 409, oversized_response.text
    assert "byte bound" in oversized_response.text
    assert oversized.calls == 1
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceRemoteFileContentReadExecution).count() == 0

    raising = _ReadAdapter(raise_with_secrets=True)
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        raising,
    )
    caplog.clear()
    raised = _read_content(
        profile_id,
        listing_execution_id,
        file_item_id,
        requester_id,
        key="remote-read-exception",
    )
    assert raised.status_code == 409, raised.text
    assert raised.json()["detail"] == "Remote file content read failed"
    for marker in (_CLIENT_SECRET, _ACCESS_TOKEN, _CLIENT_OBJECT, _RAW_RESPONSE, _DOWNLOAD_URL, _FILE_BODY_MARKER):
        assert marker not in raised.text
        assert marker not in caplog.text

    success = _ReadAdapter()
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        success,
    )
    completed = _read_content(
        profile_id,
        listing_execution_id,
        file_item_id,
        requester_id,
        key="remote-read-001",
    )
    assert completed.status_code == 201, completed.text
    body = completed.json()
    execution_id = body["id"]
    assert body["status"] == "completed"
    assert body["result_status"] == "read_verified"
    assert body["content_sha256"] == hashlib.sha256(_FILE_BODY).hexdigest()
    assert body["content_byte_count"] == len(_FILE_BODY)
    assert body["media_type_class"] == "application/pdf"
    assert body["observed_version_token_hash"] == _VERSION_HASH
    assert body["latency_class"] == "normal"
    assert body["provider_client_constructed"] is True
    assert body["remote_content_transiently_observed"] is True
    assert body["remote_read_performed"] is True
    assert body["remote_content_stored"] is False
    assert body["remote_content_returned"] is False
    assert body["remote_content_logged"] is False
    assert body["content_parsed"] is False
    assert body["content_extracted"] is False
    assert body["remote_list_performed"] is False
    assert body["remote_write_performed"] is False
    assert body["remote_delete_performed"] is False
    assert body["checkpoint_created"] is False
    assert body["sync_executed"] is False
    assert body["evidence_admitted"] is False
    assert body["document_created"] is False
    assert body["claim_mutated"] is False
    assert success.calls == 1
    assert success.last_locator.backend == "azure_key_vault"
    for forbidden_field in (
        "content_endpoint_url",
        "provider_origin",
        "provider_item_id",
        "raw_response",
        "content",
        "file_body",
        "download_url",
        "upload_url",
        "access_token",
        "client_secret",
        "provider_client",
    ):
        assert forbidden_field not in body
    for marker in (_CLIENT_SECRET, _ACCESS_TOKEN, _CLIENT_OBJECT, _RAW_RESPONSE, _DOWNLOAD_URL, _FILE_BODY_MARKER):
        assert marker not in completed.text

    replay = _read_content(
        profile_id,
        listing_execution_id,
        file_item_id,
        requester_id,
        key="remote-read-001",
    )
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id
    assert success.calls == 1
    changed = _read_content(
        profile_id,
        listing_execution_id,
        file_item_id,
        requester_id,
        key="remote-read-001",
        reason="Attempt to alter the completed governed Phase M remote file content read request.",
    )
    assert changed.status_code == 409, changed.text
    second = _read_content(
        profile_id,
        listing_execution_id,
        file_item_id,
        requester_id,
        key="remote-read-002",
    )
    assert second.status_code == 409, second.text
    assert success.calls == 1

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/remote-content-read-executions/{execution_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    receipt_rows = receipts.json()
    assert [row["event_type"] for row in receipt_rows] == ["requested", "completed"]
    assert [row["remote_read_performed"] for row in receipt_rows] == [False, True]
    assert [row["remote_content_transiently_observed"] for row in receipt_rows] == [False, True]
    assert receipt_rows[1]["prior_receipt_hash"] == receipt_rows[0]["receipt_hash"]

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        execution = db.get(ExternalDocumentSourceRemoteFileContentReadExecution, UUID(execution_id))
        assert execution is not None
        persisted = [str(getattr(execution, column.name)) for column in execution.__table__.columns]
        stored_receipts = db.query(ExternalDocumentSourceRemoteFileContentReadReceipt).filter(
            ExternalDocumentSourceRemoteFileContentReadReceipt.execution_id == UUID(execution_id)
        ).all()
        for receipt in stored_receipts:
            persisted.extend(str(getattr(receipt, column.name)) for column in receipt.__table__.columns)
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "external_document_source_remote_file_content_read_execution",
            AuditLog.entity_id == UUID(execution_id),
        ).one()
        payload = "\n".join(persisted) + json.dumps(audit.new_values, sort_keys=True) + (audit.details or "")
        for marker in (_CLIENT_SECRET, _ACCESS_TOKEN, _CLIENT_OBJECT, _RAW_RESPONSE, _DOWNLOAD_URL, _FILE_BODY_MARKER):
            assert marker not in payload
        for forbidden_text in (
            "content_endpoint_url",
            "provider_item_id",
            "raw_response",
            "file_body",
            "download_url",
            "upload_url",
        ):
            assert forbidden_text not in payload

    with TestingSessionLocal() as db:
        execution = db.get(ExternalDocumentSourceRemoteFileContentReadExecution, UUID(execution_id))
        original_digest = execution.content_sha256
        execution.content_sha256 = "0" * 64
        db.commit()
    tampered_proof = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/remote-content-read-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert tampered_proof.status_code == 409, tampered_proof.text
    with TestingSessionLocal() as db:
        execution = db.get(ExternalDocumentSourceRemoteFileContentReadExecution, UUID(execution_id))
        execution.content_sha256 = original_digest
        db.commit()

    with TestingSessionLocal() as db:
        receipt = db.query(ExternalDocumentSourceRemoteFileContentReadReceipt).filter(
            ExternalDocumentSourceRemoteFileContentReadReceipt.execution_id == UUID(execution_id),
            ExternalDocumentSourceRemoteFileContentReadReceipt.sequence_number == 1,
        ).one()
        original_reason = receipt.reason
        receipt.reason = "Tampered Phase M receipt reason."
        db.commit()
    tampered_receipt = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/remote-content-read-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert tampered_receipt.status_code == 409, tampered_receipt.text
    with TestingSessionLocal() as db:
        receipt = db.query(ExternalDocumentSourceRemoteFileContentReadReceipt).filter(
            ExternalDocumentSourceRemoteFileContentReadReceipt.execution_id == UUID(execution_id),
            ExternalDocumentSourceRemoteFileContentReadReceipt.sequence_number == 1,
        ).one()
        receipt.reason = original_reason
        db.commit()

    with TestingSessionLocal() as db:
        item = db.get(ExternalDocumentSourceRemoteMetadataListingItem, UUID(file_item_id))
        original_name = item.display_name
        item.display_name = "Tampered Phase M Survey Report.pdf"
        db.commit()
    upstream_tamper = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/remote-content-read-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert upstream_tamper.status_code == 409, upstream_tamper.text
    with TestingSessionLocal() as db:
        item = db.get(ExternalDocumentSourceRemoteMetadataListingItem, UUID(file_item_id))
        item.display_name = original_name
        db.commit()

    disabled = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/disable",
        headers=_headers(requester_id),
        json={"reason": "Disable the upstream credential reference so completed Phase M lineage must fail closed."},
    )
    assert disabled.status_code == 200, disabled.text
    fail_closed = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/remote-content-read-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert fail_closed.status_code == 409, fail_closed.text
    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceRemoteFileContentReadExecution).count() == 1
        assert db.query(ExternalDocumentSourceRemoteFileContentReadReceipt).count() == 2


def test_phase_m_declared_oversize_fails_before_content_adapter() -> None:
    requester_id, profile_id, _binding_id, listing_execution_id, file_item_id, _folder_item_id = _completed_phase_l(
        file_size=MAX_REMOTE_CONTENT_BYTES + 1
    )
    adapter = _ReadAdapter()
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        adapter,
    )
    response = _read_content(
        profile_id,
        listing_execution_id,
        file_item_id,
        requester_id,
        key="remote-read-declared-oversize",
    )
    assert response.status_code == 409, response.text
    assert "declared-size byte bound" in response.text
    assert adapter.calls == 0
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceRemoteFileContentReadExecution).count() == 0
        assert db.query(ExternalDocumentSourceRemoteFileContentReadReceipt).count() == 0