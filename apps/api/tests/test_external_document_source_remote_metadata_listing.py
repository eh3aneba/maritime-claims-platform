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
from app.modules.external_document_sources.provider_client_health_service import (
    clear_external_document_source_provider_client_health_adapters,
    register_external_document_source_provider_client_health_adapter,
)
from app.modules.external_document_sources.remote_metadata_listing_models import (
    ExternalDocumentSourceRemoteMetadataListingExecution,
    ExternalDocumentSourceRemoteMetadataListingItem,
    ExternalDocumentSourceRemoteMetadataListingReceipt,
)
from app.modules.external_document_sources.remote_metadata_listing_service import (
    RemoteMetadataItemProjection,
    RemoteMetadataListResult,
    clear_external_document_source_remote_metadata_list_adapters,
    register_external_document_source_remote_metadata_list_adapter,
)
from app.modules.external_document_sources.token_acquisition_execution_service import clear_external_document_source_token_acquirers
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_provider_client_health import (
    _HEALTH_REASON,
    _HealthAdapter,
    _health,
    _completed_phase_j,
)

_LIST_REASON = "Perform one bounded live metadata-only listing within the governed remote document source boundary."
_CLIENT_SECRET = "phase-l-client-secret-marker"
_ACCESS_TOKEN = "phase-l-access-token-marker"
_CLIENT_OBJECT = "phase-l-provider-client-marker"
_RAW_RESPONSE = "phase-l-provider-raw-response-marker"
_FILE_CONTENT = "phase-l-forbidden-file-content-marker"
_DOWNLOAD_URL = "https://example.test/phase-l-forbidden-download-url"


class _ListAdapter:
    adapter_kind = "deterministic_remote_metadata_list_v1"
    provider_kind = "sharepoint"
    client_kind = "microsoft_graph_transient_v1"
    listing_operation_kind = "graph_drive_children_metadata_v1"
    provider_origin = "https://graph.microsoft.com"

    def __init__(
        self,
        *,
        failure_code: str | None = None,
        raise_with_secrets: bool = False,
        too_many_items: bool = False,
        invalid_projection: bool = False,
    ):
        self.failure_code = failure_code
        self.raise_with_secrets = raise_with_secrets
        self.too_many_items = too_many_items
        self.invalid_projection = invalid_projection
        self.calls = 0
        self.last_locator = None
        self.last_policy = None

    def list_metadata(self, locator, policy):
        self.calls += 1
        self.last_locator = locator
        self.last_policy = policy
        client_secret = _CLIENT_SECRET
        access_token = _ACCESS_TOKEN
        transient_client = _CLIENT_OBJECT
        raw_response = _RAW_RESPONSE
        file_content = _FILE_CONTENT
        download_url = _DOWNLOAD_URL
        assert client_secret and access_token and transient_client and raw_response and file_content and download_url
        assert policy.provider_origin == "https://graph.microsoft.com"
        assert "/v1.0/sites/" in policy.listing_endpoint_url
        assert "/drives/" in policy.listing_endpoint_url
        assert "/root/children?" in policy.listing_endpoint_url
        assert "%24select=" in policy.listing_endpoint_url or "$select=" in policy.listing_endpoint_url
        assert policy.max_items == 100
        assert policy.max_pages == 1
        assert policy.max_response_bytes == 131072
        assert policy.allow_redirects is False
        if self.raise_with_secrets:
            raise RuntimeError(
                f"remote listing failed {client_secret} {access_token} {transient_client} {raw_response} {file_content} {download_url}"
            )
        if self.failure_code is not None:
            return RemoteMetadataListResult(listed=False, failure_code=self.failure_code)
        if self.too_many_items:
            items = tuple(
                RemoteMetadataItemProjection(
                    provider_item_id=f"item-{index}",
                    item_kind="file",
                    display_name=f"Document {index}.pdf",
                    mime_type_class="application/pdf",
                    byte_size=1000 + index,
                    modified_at=datetime(2026, 9, 16, 5, 0, tzinfo=timezone.utc),
                    version_token_hash="a" * 64,
                )
                for index in range(101)
            )
            return RemoteMetadataListResult(listed=True, items=items, truncated=True, page_count=1)
        if self.invalid_projection:
            return RemoteMetadataListResult(
                listed=True,
                items=(
                    RemoteMetadataItemProjection(
                        provider_item_id="bad-item",
                        item_kind="file",
                        display_name="Bad Item.pdf",
                        version_token_hash="raw-etag-must-not-cross-boundary",
                    ),
                ),
                page_count=1,
            )
        return RemoteMetadataListResult(
            listed=True,
            items=(
                RemoteMetadataItemProjection(
                    provider_item_id="remote-file-001",
                    parent_item_id="remote-folder-root",
                    item_kind="file",
                    display_name="Survey Report.pdf",
                    mime_type_class="application/pdf",
                    byte_size=245760,
                    modified_at=datetime(2026, 9, 15, 12, 30, tzinfo=timezone.utc),
                    version_token_hash="a" * 64,
                ),
                RemoteMetadataItemProjection(
                    provider_item_id="remote-folder-002",
                    parent_item_id="remote-folder-root",
                    item_kind="folder",
                    display_name="Correspondence",
                    modified_at=datetime(2026, 9, 15, 13, 0, tzinfo=timezone.utc),
                    version_token_hash="b" * 64,
                ),
            ),
            truncated=False,
            page_count=1,
        )


class _WrongOriginAdapter(_ListAdapter):
    provider_origin = "https://evil.example.test"


def setup_function() -> None:
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()
    clear_external_document_source_credential_resolution_resolvers()
    clear_external_document_source_token_acquirers()
    clear_external_document_source_provider_client_health_adapters()
    clear_external_document_source_remote_metadata_list_adapters()
    reset_database()


def teardown_function() -> None:
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()
    clear_external_document_source_credential_resolution_resolvers()
    clear_external_document_source_token_acquirers()
    clear_external_document_source_provider_client_health_adapters()
    clear_external_document_source_remote_metadata_list_adapters()


def _list_metadata(profile_id: str, health_execution_id: str, actor_id: UUID, *, key: str, reason: str = _LIST_REASON):
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/provider-client-health-executions/{health_execution_id}/remote-metadata-listing-executions",
        headers=_headers(actor_id),
        json={"request_key": key, "reason": reason},
    )


def _completed_phase_k():
    requester_id, profile_id, binding_id, token_execution_id = _completed_phase_j()
    register_external_document_source_provider_client_health_adapter(
        "sharepoint",
        "graph_organization_health",
        _HealthAdapter(),
    )
    healthy = _health(
        profile_id,
        token_execution_id,
        requester_id,
        key="remote-metadata-listing-phase-k",
        reason=_HEALTH_REASON,
    )
    assert healthy.status_code == 201, healthy.text
    return requester_id, profile_id, binding_id, healthy.json()["id"]


def test_phase_l_bounded_live_remote_metadata_listing(caplog: pytest.LogCaptureFixture) -> None:
    requester_id, profile_id, binding_id, health_execution_id = _completed_phase_k()
    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    missing = _list_metadata(profile_id, health_execution_id, requester_id, key="remote-list-missing")
    assert missing.status_code == 409, missing.text
    assert "adapter is unavailable" in missing.text
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceRemoteMetadataListingExecution).count() == 0
        assert db.query(ExternalDocumentSourceRemoteMetadataListingItem).count() == 0
        assert db.query(ExternalDocumentSourceRemoteMetadataListingReceipt).count() == 0

    wrong_origin = _WrongOriginAdapter()
    with pytest.raises(ValueError, match="origin"):
        register_external_document_source_remote_metadata_list_adapter(
            "sharepoint",
            "graph_drive_children_metadata_v1",
            wrong_origin,
        )
    assert wrong_origin.calls == 0

    for failure_code in ("provider_rejected", "timeout", "malformed_response", "oversized_response"):
        negative = _ListAdapter(failure_code=failure_code)
        register_external_document_source_remote_metadata_list_adapter(
            "sharepoint",
            "graph_drive_children_metadata_v1",
            negative,
        )
        response = _list_metadata(profile_id, health_execution_id, requester_id, key=f"remote-list-{failure_code}")
        assert response.status_code == 409, response.text
        assert failure_code in response.text
        assert negative.calls == 1
        with TestingSessionLocal() as db:
            assert db.query(ExternalDocumentSourceRemoteMetadataListingExecution).count() == 0
            assert db.query(ExternalDocumentSourceRemoteMetadataListingItem).count() == 0
            assert db.query(ExternalDocumentSourceRemoteMetadataListingReceipt).count() == 0

    too_many = _ListAdapter(too_many_items=True)
    register_external_document_source_remote_metadata_list_adapter(
        "sharepoint",
        "graph_drive_children_metadata_v1",
        too_many,
    )
    bounded = _list_metadata(profile_id, health_execution_id, requester_id, key="remote-list-too-many")
    assert bounded.status_code == 409, bounded.text
    assert "item bound" in bounded.text
    assert too_many.calls == 1
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceRemoteMetadataListingExecution).count() == 0
        assert db.query(ExternalDocumentSourceRemoteMetadataListingItem).count() == 0

    invalid = _ListAdapter(invalid_projection=True)
    register_external_document_source_remote_metadata_list_adapter(
        "sharepoint",
        "graph_drive_children_metadata_v1",
        invalid,
    )
    invalid_result = _list_metadata(profile_id, health_execution_id, requester_id, key="remote-list-invalid-projection")
    assert invalid_result.status_code == 409, invalid_result.text
    assert "version-token hash" in invalid_result.text
    assert invalid.calls == 1

    raising = _ListAdapter(raise_with_secrets=True)
    register_external_document_source_remote_metadata_list_adapter(
        "sharepoint",
        "graph_drive_children_metadata_v1",
        raising,
    )
    caplog.clear()
    raised = _list_metadata(profile_id, health_execution_id, requester_id, key="remote-list-exception")
    assert raised.status_code == 409, raised.text
    assert raised.json()["detail"] == "Remote metadata listing failed"
    for marker in (_CLIENT_SECRET, _ACCESS_TOKEN, _CLIENT_OBJECT, _RAW_RESPONSE, _FILE_CONTENT, _DOWNLOAD_URL):
        assert marker not in raised.text
        assert marker not in caplog.text

    success = _ListAdapter()
    register_external_document_source_remote_metadata_list_adapter(
        "sharepoint",
        "graph_drive_children_metadata_v1",
        success,
    )
    forbidden = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/provider-client-health-executions/{health_execution_id}/remote-metadata-listing-executions",
        headers=_headers(requester_id),
        json={"request_key": "remote-list-forbidden", "reason": _LIST_REASON, "content": _FILE_CONTENT},
    )
    assert forbidden.status_code == 422, forbidden.text

    _, other_requester, _ = _seed_tenant("remote-metadata-list-other-tenant")
    wrong_tenant = _list_metadata(profile_id, health_execution_id, other_requester, key="remote-list-wrong-tenant")
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert success.calls == 0

    listed = _list_metadata(profile_id, health_execution_id, requester_id, key="remote-list-001")
    assert listed.status_code == 201, listed.text
    body = listed.json()
    execution_id = body["id"]
    assert body["status"] == "completed"
    assert body["result_status"] == "listed"
    assert body["item_count"] == 2
    assert body["page_count"] == 1
    assert body["truncated"] is False
    assert body["provider_client_constructed"] is True
    assert body["remote_list_performed"] is True
    assert body["provider_client_stored"] is False
    assert body["provider_response_body_stored"] is False
    assert body["remote_read_performed"] is False
    assert body["remote_write_performed"] is False
    assert body["remote_delete_performed"] is False
    assert body["checkpoint_created"] is False
    assert body["sync_executed"] is False
    assert body["evidence_admitted"] is False
    assert body["document_created"] is False
    assert body["claim_mutated"] is False
    assert [item["display_name"] for item in body["items"]] == ["Survey Report.pdf", "Correspondence"]
    assert [item["item_kind"] for item in body["items"]] == ["file", "folder"]
    assert success.calls == 1
    assert success.last_locator.backend == "azure_key_vault"
    assert success.last_policy.max_items == 100
    for forbidden_field in (
        "listing_endpoint_url",
        "provider_origin",
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
    for marker in (_CLIENT_SECRET, _ACCESS_TOKEN, _CLIENT_OBJECT, _RAW_RESPONSE, _FILE_CONTENT, _DOWNLOAD_URL):
        assert marker not in listed.text

    replay = _list_metadata(profile_id, health_execution_id, requester_id, key="remote-list-001")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id
    assert success.calls == 1
    changed = _list_metadata(
        profile_id,
        health_execution_id,
        requester_id,
        key="remote-list-001",
        reason="Attempt to alter the completed governed Phase L remote metadata listing request.",
    )
    assert changed.status_code == 409, changed.text
    second = _list_metadata(profile_id, health_execution_id, requester_id, key="remote-list-002")
    assert second.status_code == 409, second.text
    assert success.calls == 1

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/remote-metadata-listing-executions/{execution_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "completed"]
    assert [row["remote_list_performed"] for row in rows] == [False, True]
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        execution = db.get(ExternalDocumentSourceRemoteMetadataListingExecution, UUID(execution_id))
        assert execution is not None
        persisted = [str(getattr(execution, column.name)) for column in execution.__table__.columns]
        item_rows = db.query(ExternalDocumentSourceRemoteMetadataListingItem).filter(
            ExternalDocumentSourceRemoteMetadataListingItem.execution_id == UUID(execution_id)
        ).order_by(ExternalDocumentSourceRemoteMetadataListingItem.item_index.asc()).all()
        for item in item_rows:
            persisted.extend(str(getattr(item, column.name)) for column in item.__table__.columns)
        receipt_rows = db.query(ExternalDocumentSourceRemoteMetadataListingReceipt).filter(
            ExternalDocumentSourceRemoteMetadataListingReceipt.execution_id == UUID(execution_id)
        ).all()
        for receipt in receipt_rows:
            persisted.extend(str(getattr(receipt, column.name)) for column in receipt.__table__.columns)
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "external_document_source_remote_metadata_listing_execution",
            AuditLog.entity_id == UUID(execution_id),
        ).one()
        payload = "\n".join(persisted) + json.dumps(audit.new_values, sort_keys=True) + (audit.details or "")
        for marker in (_CLIENT_SECRET, _ACCESS_TOKEN, _CLIENT_OBJECT, _RAW_RESPONSE, _FILE_CONTENT, _DOWNLOAD_URL):
            assert marker not in payload
        for forbidden_text in ("listing_endpoint_url", "raw_response", "file_body", "download_url", "upload_url"):
            assert forbidden_text not in payload

    with TestingSessionLocal() as db:
        item = db.query(ExternalDocumentSourceRemoteMetadataListingItem).filter(
            ExternalDocumentSourceRemoteMetadataListingItem.execution_id == UUID(execution_id),
            ExternalDocumentSourceRemoteMetadataListingItem.item_index == 0,
        ).one()
        original_name = item.display_name
        item.display_name = "Tampered Survey Report.pdf"
        db.commit()
    tampered_item = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/remote-metadata-listing-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert tampered_item.status_code == 409, tampered_item.text
    with TestingSessionLocal() as db:
        item = db.query(ExternalDocumentSourceRemoteMetadataListingItem).filter(
            ExternalDocumentSourceRemoteMetadataListingItem.execution_id == UUID(execution_id),
            ExternalDocumentSourceRemoteMetadataListingItem.item_index == 0,
        ).one()
        item.display_name = original_name
        db.commit()

    with TestingSessionLocal() as db:
        receipt = db.query(ExternalDocumentSourceRemoteMetadataListingReceipt).filter(
            ExternalDocumentSourceRemoteMetadataListingReceipt.execution_id == UUID(execution_id),
            ExternalDocumentSourceRemoteMetadataListingReceipt.sequence_number == 1,
        ).one()
        original_reason = receipt.reason
        receipt.reason = "Tampered Phase L receipt reason."
        db.commit()
    tampered_receipt = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/remote-metadata-listing-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert tampered_receipt.status_code == 409, tampered_receipt.text
    with TestingSessionLocal() as db:
        receipt = db.query(ExternalDocumentSourceRemoteMetadataListingReceipt).filter(
            ExternalDocumentSourceRemoteMetadataListingReceipt.execution_id == UUID(execution_id),
            ExternalDocumentSourceRemoteMetadataListingReceipt.sequence_number == 1,
        ).one()
        receipt.reason = original_reason
        db.commit()

    disabled = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/disable",
        headers=_headers(requester_id),
        json={"reason": "Disable the upstream credential reference so completed Phase L lineage must fail closed."},
    )
    assert disabled.status_code == 200, disabled.text
    fail_closed = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/remote-metadata-listing-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert fail_closed.status_code == 409, fail_closed.text
    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceRemoteMetadataListingExecution).count() == 1
        assert db.query(ExternalDocumentSourceRemoteMetadataListingItem).count() == 2
        assert db.query(ExternalDocumentSourceRemoteMetadataListingReceipt).count() == 2
