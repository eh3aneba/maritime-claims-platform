from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.modules.external_document_sources.credential_reference_health_service import (
    CredentialReferenceLocator,
)
from app.modules.external_document_sources.live_provider_adapters import (
    LiveExternalEvidenceRuntime,
    _ContentReadAdapter,
    _MetadataListAdapter,
    _ProviderHealthAdapter,
    _SecretHealthResolver,
    _SecretResolutionResolver,
    _TokenAcquirer,
)
from app.modules.external_document_sources.provider_client_health_service import (
    ProviderClientHealthPolicy,
)
from app.modules.external_document_sources.remote_file_content_read_service import (
    RemoteFileContentReadPolicy,
)
from app.modules.external_document_sources.remote_metadata_listing_service import (
    RemoteMetadataListingPolicy,
)
from app.modules.external_document_sources.token_acquisition_execution_service import (
    TokenAcquisitionPolicy,
)


def _private_key() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


def test_live_sharepoint_contract_is_read_only_and_version_stable(monkeypatch) -> None:
    secret_marker = "ak-sharepoint-client-secret-never-crosses-boundary"
    access_token = "ak-sharepoint-access-token-never-crosses-boundary"
    secret = json.dumps(
        {
            "tenant_domain": "contoso.onmicrosoft.com",
            "client_id": "11111111-1111-1111-1111-111111111111",
            "client_secret": secret_marker,
        }
    )
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        url = str(request.url)
        if "vault.azure.net/secrets/graph-reader" in url:
            assert request.headers["authorization"] == "Bearer azure-workload-token"
            return httpx.Response(200, json={"value": secret})
        if "login.microsoftonline.com/contoso.onmicrosoft.com/oauth2/v2.0/token" in url:
            body = request.content.decode()
            assert "client_secret=" in body
            return httpx.Response(200, json={"access_token": access_token, "expires_in": 3600})
        if request.url.path == "/v1.0/organization":
            assert request.headers["authorization"] == f"Bearer {access_token}"
            return httpx.Response(200, json={"value": [{"id": "org-1"}]})
        if "/root/children?" in url:
            assert request.method == "GET"
            return httpx.Response(
                200,
                json={
                    "value": [
                        {
                            "id": "item-1",
                            "name": "Chief Engineer Report.pdf",
                            "size": 11,
                            "lastModifiedDateTime": "2026-09-22T07:30:00Z",
                            "file": {"mimeType": "application/pdf"},
                            "parentReference": {"id": "root"},
                            "eTag": '"etag-v7"',
                        }
                    ]
                },
            )
        if url.startswith("https://graph.microsoft.com/v1.0/sites/site-1/drives/lib-1/items/item-1?"):
            return httpx.Response(
                200,
                json={
                    "id": "item-1",
                    "size": 11,
                    "file": {"mimeType": "application/pdf"},
                    "eTag": '"etag-v7"',
                },
            )
        if url == "https://graph.microsoft.com/v1.0/sites/site-1/drives/lib-1/items/item-1/content":
            return httpx.Response(
                302,
                headers={"location": "https://tenant.sharepoint.com/download/file-1"},
            )
        if url == "https://tenant.sharepoint.com/download/file-1":
            assert "authorization" not in request.headers
            return httpx.Response(
                200,
                content=b"hello-world",
                headers={"content-type": "application/pdf", "content-length": "11"},
            )
        raise AssertionError(f"unexpected request: {request.method} {url}")

    monkeypatch.setenv("AZURE_KEY_VAULT_ACCESS_TOKEN", "azure-workload-token")
    runtime = LiveExternalEvidenceRuntime(transport=httpx.MockTransport(handler))
    locator = CredentialReferenceLocator(
        backend="azure_key_vault",
        namespace="mcrivault",
        name="graph-reader",
        version="7",
    )

    assert _SecretHealthResolver(runtime, "azure_key_vault").check(locator).resolvable is True
    assert _SecretResolutionResolver(runtime, "azure_key_vault").resolve(locator).resolved is True

    token_policy = TokenAcquisitionPolicy(
        provider_kind="sharepoint",
        token_flow_kind="client_credentials",
        token_endpoint_url=(
            "https://login.microsoftonline.com/contoso.onmicrosoft.com/oauth2/v2.0/token"
        ),
        audience_kind="microsoft_graph_default",
        tenant_hint="contoso.onmicrosoft.com",
    )
    token_result = _TokenAcquirer(runtime, "sharepoint").acquire(locator, token_policy)
    assert token_result.acquired is True
    assert token_result.expiry_class == "standard"
    assert not hasattr(token_result, "access_token")

    health_policy = ProviderClientHealthPolicy(
        provider_kind="sharepoint",
        token_flow_kind="client_credentials",
        client_kind="microsoft_graph_transient_v1",
        health_operation_kind="graph_organization_health",
        provider_origin="https://graph.microsoft.com",
        health_endpoint_url="https://graph.microsoft.com/v1.0/organization?$select=id",
        audience_kind="microsoft_graph_default",
    )
    health = _ProviderHealthAdapter(runtime, "sharepoint").qualify(locator, health_policy)
    assert health.healthy is True

    list_policy = RemoteMetadataListingPolicy(
        provider_kind="sharepoint",
        client_kind="microsoft_graph_transient_v1",
        listing_operation_kind="graph_drive_children_metadata_v1",
        provider_origin="https://graph.microsoft.com",
        listing_endpoint_url=(
            "https://graph.microsoft.com/v1.0/sites/site-1/drives/lib-1/root/children"
            "?%24select=id%2Cname%2Csize&%24top=100"
        ),
        field_projection="id,name,size",
    )
    listed = _MetadataListAdapter(runtime, "sharepoint").list_metadata(locator, list_policy)
    assert listed.listed is True
    assert len(listed.items) == 1
    item = listed.items[0]
    assert item.provider_item_id == "item-1"
    assert item.item_kind == "file"
    assert item.mime_type_class == "application/pdf"
    assert item.byte_size == 11
    assert item.modified_at == datetime(2026, 9, 22, 7, 30, tzinfo=timezone.utc)
    assert item.version_token_hash is not None

    read_policy = RemoteFileContentReadPolicy(
        provider_kind="sharepoint",
        client_kind="microsoft_graph_transient_v1",
        read_operation_kind="graph_drive_item_content_read_v1",
        provider_origin="https://graph.microsoft.com",
        content_endpoint_url=(
            "https://graph.microsoft.com/v1.0/sites/site-1/drives/lib-1/items/item-1/content"
        ),
        redirect_policy_kind="provider_internal_https_one_hop_v1",
        max_redirects=1,
    )
    read = _ContentReadAdapter(runtime, "sharepoint").read_content(locator, read_policy)
    assert read.read is True
    assert read.content == b"hello-world"
    assert read.media_type_class == "application/pdf"
    assert read.observed_version_token_hash == item.version_token_hash

    rendered = repr((health, listed, read))
    assert secret_marker not in rendered
    assert access_token not in rendered
    assert all(method == "GET" for method, url in calls if "graph.microsoft.com" in url)


def test_live_google_drive_contract_is_read_only_and_version_stable(monkeypatch) -> None:
    private_key = _private_key()
    secret_marker = "ak-google-private-key-marker"
    service_account = json.dumps(
        {
            "client_email": "mcri-reader@example-project.iam.gserviceaccount.com",
            "private_key": private_key,
            "private_key_id": secret_marker,
        }
    )
    encoded_secret = base64.b64encode(service_account.encode()).decode()
    access_token = "ak-google-access-token-never-crosses-boundary"
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        url = str(request.url)
        if "secretmanager.googleapis.com" in url:
            assert request.headers["authorization"] == "Bearer gcp-workload-token"
            return httpx.Response(200, json={"payload": {"data": encoded_secret}})
        if url == "https://oauth2.googleapis.com/token":
            body = request.content.decode()
            assert "assertion=" in body
            return httpx.Response(200, json={"access_token": access_token, "expires_in": 3600})
        if request.url.path == "/drive/v3/about":
            assert request.headers["authorization"] == f"Bearer {access_token}"
            return httpx.Response(200, json={"user": {"permissionId": "permission-1"}})
        if url.startswith("https://www.googleapis.com/drive/v3/files?"):
            return httpx.Response(
                200,
                json={
                    "files": [
                        {
                            "id": "drive-item-1",
                            "name": "Engine Log.pdf",
                            "mimeType": "application/pdf",
                            "size": "12",
                            "modifiedTime": "2026-09-22T08:00:00Z",
                            "parents": ["folder-1"],
                            "md5Checksum": "abc123",
                            "version": "42",
                        }
                    ]
                },
            )
        if url.startswith("https://www.googleapis.com/drive/v3/files/drive-item-1?fields="):
            return httpx.Response(
                200,
                json={
                    "id": "drive-item-1",
                    "mimeType": "application/pdf",
                    "size": "12",
                    "modifiedTime": "2026-09-22T08:00:00Z",
                    "md5Checksum": "abc123",
                    "version": "42",
                },
            )
        if url.startswith("https://www.googleapis.com/drive/v3/files/drive-item-1?alt=media"):
            return httpx.Response(
                200,
                content=b"google-bytes",
                headers={"content-type": "application/pdf", "content-length": "12"},
            )
        raise AssertionError(f"unexpected request: {request.method} {url}")

    monkeypatch.setenv("GOOGLE_CLOUD_ACCESS_TOKEN", "gcp-workload-token")
    runtime = LiveExternalEvidenceRuntime(transport=httpx.MockTransport(handler))
    locator = CredentialReferenceLocator(
        backend="gcp_secret_manager",
        namespace="example-project",
        name="drive-reader",
        version="3",
    )

    assert _SecretHealthResolver(runtime, "gcp_secret_manager").check(locator).resolvable is True
    assert _SecretResolutionResolver(runtime, "gcp_secret_manager").resolve(locator).resolved is True

    token_policy = TokenAcquisitionPolicy(
        provider_kind="google_drive",
        token_flow_kind="jwt_bearer",
        token_endpoint_url="https://oauth2.googleapis.com/token",
        audience_kind="google_drive_readonly",
        tenant_hint=None,
    )
    token_result = _TokenAcquirer(runtime, "google_drive").acquire(locator, token_policy)
    assert token_result.acquired is True
    assert not hasattr(token_result, "access_token")

    health_policy = ProviderClientHealthPolicy(
        provider_kind="google_drive",
        token_flow_kind="jwt_bearer",
        client_kind="google_drive_transient_v3",
        health_operation_kind="drive_about_health",
        provider_origin="https://www.googleapis.com",
        health_endpoint_url="https://www.googleapis.com/drive/v3/about?fields=user(permissionId)",
        audience_kind="google_drive_readonly",
    )
    assert _ProviderHealthAdapter(runtime, "google_drive").qualify(locator, health_policy).healthy is True

    list_policy = RemoteMetadataListingPolicy(
        provider_kind="google_drive",
        client_kind="google_drive_transient_v3",
        listing_operation_kind="drive_files_list_metadata_v1",
        provider_origin="https://www.googleapis.com",
        listing_endpoint_url=(
            "https://www.googleapis.com/drive/v3/files?"
            "q=%27folder-1%27+in+parents&fields=files"
        ),
        field_projection="files(id,name,mimeType,size,modifiedTime,parents,md5Checksum,version)",
    )
    listed = _MetadataListAdapter(runtime, "google_drive").list_metadata(locator, list_policy)
    assert listed.listed is True
    item = listed.items[0]
    assert item.provider_item_id == "drive-item-1"
    assert item.byte_size == 12
    assert item.version_token_hash is not None

    read_policy = RemoteFileContentReadPolicy(
        provider_kind="google_drive",
        client_kind="google_drive_transient_v3",
        read_operation_kind="drive_file_media_read_v1",
        provider_origin="https://www.googleapis.com",
        content_endpoint_url=(
            "https://www.googleapis.com/drive/v3/files/drive-item-1"
            "?alt=media&supportsAllDrives=true"
        ),
        redirect_policy_kind="no_redirects_v1",
        max_redirects=0,
    )
    read = _ContentReadAdapter(runtime, "google_drive").read_content(locator, read_policy)
    assert read.read is True
    assert read.content == b"google-bytes"
    assert read.observed_version_token_hash == item.version_token_hash

    rendered = repr((listed, read))
    assert private_key not in rendered
    assert secret_marker not in rendered
    assert access_token not in rendered
    assert all(method == "GET" for method, url in calls if "www.googleapis.com/drive/" in url)
