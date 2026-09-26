import json
from datetime import datetime, timezone
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.sftp_directory_listing_models import (
    ExternalDocumentSourceSftpDirectoryListing,
    ExternalDocumentSourceSftpDirectoryListingEntry,
    ExternalDocumentSourceSftpDirectoryListingReceipt,
)
from app.modules.external_document_sources.sftp_directory_listing_service import (
    SftpDirectoryListingResult,
    SftpDirectoryMetadataEntry,
    clear_external_document_source_sftp_directory_listing_adapter,
    register_external_document_source_sftp_directory_listing_adapter,
)
from app.modules.external_document_sources.sftp_session_activation_service import (
    register_external_document_source_sftp_session_activation_adapter,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_profiles import _headers, _seed_tenant
from tests.test_external_document_source_sftp_session_activation import (
    _DeterministicSessionActivationAdapter,
    _activate,
    _success_activation_result,
    _verified_transport,
    setup_function as _g_setup,
    teardown_function as _g_teardown,
)


_REASON = (
    "List one bounded page of read-only SFTP directory metadata inside the exact "
    "approved root without reading file content or mutating the remote server."
)
_SECRET_MARKER = "phase-h-raw-secret-must-never-persist"
_RAW_RESPONSE_MARKER = "phase-h-raw-directory-response-must-never-persist"


class _DirectoryListingAdapter:
    adapter_kind = "deterministic_sftp_directory_listing"

    def __init__(
        self,
        result: SftpDirectoryListingResult | None = None,
        *,
        raise_error: bool = False,
    ):
        self.result = result or _success_listing_result()
        self.raise_error = raise_error
        self.calls = []

    def list_metadata(self, request):
        self.calls.append(request)
        assert request.max_entries == 100
        assert request.max_pages == 1
        assert request.max_connection_attempts == 1
        assert request.max_authentication_attempts == 1
        assert request.max_listing_attempts == 1
        assert request.read_only_intent is True
        assert request.recursive is False
        assert request.follow_symlinks is False
        assert request.allow_private_destinations is False
        assert request.allow_redirects is False
        assert request.allow_proxy_retargeting is False
        assert request.remote_root_path.startswith("/")
        assert request.effective_remote_path.startswith(request.remote_root_path.rstrip("/") or "/")
        assert not hasattr(request, "password")
        assert not hasattr(request, "private_key")
        assert not hasattr(request, "passphrase")
        if self.raise_error:
            raise RuntimeError(f"{_SECRET_MARKER} {_RAW_RESPONSE_MARKER}")
        return self.result


def _success_listing_result(*, entries=None) -> SftpDirectoryListingResult:
    if entries is None:
        entries = (
            SftpDirectoryMetadataEntry(
                relative_path="Survey Report.pdf",
                entry_kind="file",
                byte_size=245760,
                modified_at=datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc),
                metadata_id_hash="a" * 64,
            ),
            SftpDirectoryMetadataEntry(
                relative_path="Correspondence",
                entry_kind="directory",
                modified_at=datetime(2026, 9, 26, 8, 1, tzinfo=timezone.utc),
                metadata_id_hash="b" * 64,
            ),
        )
    return SftpDirectoryListingResult(
        authentication_method="public_key",
        latency_class="fast",
        entries=tuple(entries),
        page_count=1,
        secret_resolution_performed=True,
        provider_network_performed=True,
        ssh_transport_performed=True,
        host_key_verification_performed=True,
        host_key_verified=True,
        authentication_performed=True,
        authentication_succeeded=True,
        sftp_session_opened=True,
        remote_list_performed=True,
        sftp_session_closed=True,
    )


def setup_function() -> None:
    _g_setup()
    clear_external_document_source_sftp_directory_listing_adapter()


def teardown_function() -> None:
    clear_external_document_source_sftp_directory_listing_adapter()
    _g_teardown()


def _activated_chain(seed: str):
    chain = _verified_transport(seed)
    activation_adapter = _DeterministicSessionActivationAdapter(_success_activation_result())
    register_external_document_source_sftp_session_activation_adapter(activation_adapter)
    response = _activate(chain, key=f"{seed}-activation")
    assert response.status_code == 201, response.text
    assert response.json()["result_status"] == "activated"
    chain["activation_id"] = response.json()["id"]
    chain["activation_adapter"] = activation_adapter
    return chain


def _list(chain: dict, *, key: str, relative_path: str = "", reason: str = _REASON, actor_id=None):
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-session-activations/{chain['activation_id']}/directory-listings"
        ),
        headers=_headers(actor_id or chain["requester_id"]),
        json={"request_key": key, "reason": reason, "relative_path": relative_path},
    )


def test_sftp_directory_listing_is_bounded_metadata_only_and_replay_safe() -> None:
    chain = _activated_chain("sftp-dir-list")
    adapter = _DirectoryListingAdapter()
    register_external_document_source_sftp_directory_listing_adapter(adapter)

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    response = _list(chain, key="sftp-dir-list-001")
    assert response.status_code == 201, response.text
    body = response.json()
    listing_id = body["id"]

    assert body["result_status"] == "listed"
    assert body["failure_code"] is None
    assert body["authentication_method"] == "public_key"
    assert body["entry_count"] == 2
    assert body["page_count"] == 1
    assert body["truncated"] is False
    assert body["remote_list_performed"] is True
    assert body["remote_stat_performed"] is False
    assert body["remote_read_performed"] is False
    assert body["remote_write_performed"] is False
    assert body["remote_rename_performed"] is False
    assert body["remote_delete_performed"] is False
    assert body["command_executed"] is False
    assert body["checkpoint_created"] is False
    assert body["evidence_admitted"] is False
    assert body["document_created"] is False
    assert body["processing_enqueued"] is False
    assert body["ai_executed"] is False
    assert body["claim_mutated"] is False
    assert [entry["entry_name"] for entry in body["entries"]] == ["Survey Report.pdf", "Correspondence"]
    assert [entry["entry_kind"] for entry in body["entries"]] == ["file", "directory"]
    assert len(adapter.calls) == 1

    request = adapter.calls[0]
    assert request.relative_path == ""
    assert request.effective_remote_path == request.remote_root_path
    assert request.username
    assert request.reference_backend
    assert request.reference_namespace
    assert request.reference_name

    replay = _list(chain, key="sftp-dir-list-001")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == listing_id
    assert len(adapter.calls) == 1

    changed = _list(
        chain,
        key="sftp-dir-list-001",
        reason="Try to mutate the already completed Phase 17.6-H listing request.",
    )
    assert changed.status_code == 409, changed.text
    second = _list(chain, key="sftp-dir-list-002")
    assert second.status_code == 409, second.text
    assert len(adapter.calls) == 1

    fetched = client.get(
        f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/sftp-directory-listings/{listing_id}",
        headers=_headers(chain["requester_id"]),
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["items_hash"] == body["items_hash"]

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/sftp-directory-listings/{listing_id}/receipts",
        headers=_headers(chain["requester_id"]),
    )
    assert receipts.status_code == 200, receipts.text
    receipt_rows = receipts.json()
    assert [row["event_type"] for row in receipt_rows] == ["requested", "completed"]
    assert [row["remote_list_performed"] for row in receipt_rows] == [False, True]
    assert receipt_rows[1]["prior_receipt_hash"] == receipt_rows[0]["receipt_hash"]

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceSftpDirectoryListing).count() == 1
        assert db.query(ExternalDocumentSourceSftpDirectoryListingEntry).count() == 2
        assert db.query(ExternalDocumentSourceSftpDirectoryListingReceipt).count() == 2

        listing = db.get(ExternalDocumentSourceSftpDirectoryListing, UUID(listing_id))
        assert listing is not None
        persisted = [str(getattr(listing, column.name)) for column in listing.__table__.columns]
        for entry in db.query(ExternalDocumentSourceSftpDirectoryListingEntry).all():
            persisted.extend(str(getattr(entry, column.name)) for column in entry.__table__.columns)
        for receipt in db.query(ExternalDocumentSourceSftpDirectoryListingReceipt).all():
            persisted.extend(str(getattr(receipt, column.name)) for column in receipt.__table__.columns)
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "external_document_source_sftp_directory_listing",
            AuditLog.entity_id == UUID(listing_id),
        ).one()
        payload = "\n".join(persisted) + json.dumps(audit.new_values, sort_keys=True) + (audit.details or "")
        assert _SECRET_MARKER not in payload
        assert _RAW_RESPONSE_MARKER not in payload
        for forbidden in ("password", "private_key_material", "passphrase", "raw_response", "file_content"):
            assert forbidden not in payload


def test_sftp_directory_listing_path_policy_and_nonrecursive_boundary() -> None:
    for index, unsafe in enumerate(("../escape", "/absolute", "folder\\escape", "folder/../../escape")):
        chain = _activated_chain(f"sftp-dir-unsafe-{index}")
        adapter = _DirectoryListingAdapter()
        register_external_document_source_sftp_directory_listing_adapter(adapter)
        response = _list(chain, key=f"unsafe-{index}", relative_path=unsafe)
        assert response.status_code == 422, response.text
        assert adapter.calls == []

    chain = _activated_chain("sftp-dir-normalized")
    child_entries = (
        SftpDirectoryMetadataEntry(
            relative_path="Correspondence/Email.msg",
            entry_kind="file",
            byte_size=1024,
            metadata_id_hash="c" * 64,
        ),
    )
    adapter = _DirectoryListingAdapter(_success_listing_result(entries=child_entries))
    register_external_document_source_sftp_directory_listing_adapter(adapter)
    normalized = _list(chain, key="normalized-child", relative_path="Correspondence//./")
    assert normalized.status_code == 201, normalized.text
    assert normalized.json()["request_relative_path"] == "Correspondence"
    assert normalized.json()["entries"][0]["relative_path"] == "Correspondence/Email.msg"
    assert adapter.calls[0].relative_path == "Correspondence"

    chain = _activated_chain("sftp-dir-recursive-escape")
    recursive_entry = SftpDirectoryMetadataEntry(
        relative_path="Correspondence/nested/file.pdf",
        entry_kind="file",
        byte_size=10,
    )
    violating = _DirectoryListingAdapter(_success_listing_result(entries=(recursive_entry,)))
    register_external_document_source_sftp_directory_listing_adapter(violating)
    escaped = _list(chain, key="recursive-escape", relative_path="Correspondence")
    assert escaped.status_code == 409, escaped.text
    with TestingSessionLocal() as db:
        rows = db.query(ExternalDocumentSourceSftpDirectoryListing).filter(
            ExternalDocumentSourceSftpDirectoryListing.session_activation_id == UUID(chain["activation_id"])
        ).count()
        assert rows == 0


def test_sftp_directory_listing_fails_closed_on_symlink_bounds_and_forbidden_remote_actions() -> None:
    chain = _activated_chain("sftp-dir-symlink")
    symlink = _DirectoryListingAdapter(SftpDirectoryListingResult(
        failure_code=None,
        authentication_method="public_key",
        latency_class="fast",
        page_count=1,
        secret_resolution_performed=True,
        provider_network_performed=True,
        ssh_transport_performed=True,
        host_key_verification_performed=True,
        host_key_verified=True,
        authentication_performed=True,
        authentication_succeeded=True,
        sftp_session_opened=True,
        remote_list_performed=True,
        sftp_session_closed=True,
        symlink_escape_detected=True,
    ))
    register_external_document_source_sftp_directory_listing_adapter(symlink)
    response = _list(chain, key="symlink-escape")
    assert response.status_code == 201, response.text
    assert response.json()["result_status"] == "failed"
    assert response.json()["failure_code"] == "symlink_escape_detected"
    assert response.json()["entries"] == []

    chain = _activated_chain("sftp-dir-too-many")
    too_many_entries = tuple(
        SftpDirectoryMetadataEntry(
            relative_path=f"file-{index:03d}.pdf",
            entry_kind="file",
            byte_size=index,
        )
        for index in range(101)
    )
    bounded = _DirectoryListingAdapter(_success_listing_result(entries=too_many_entries))
    register_external_document_source_sftp_directory_listing_adapter(bounded)
    response = _list(chain, key="too-many")
    assert response.status_code == 201, response.text
    assert response.json()["result_status"] == "failed"
    assert response.json()["failure_code"] == "too_many_entries"
    assert response.json()["entry_count"] == 0

    chain = _activated_chain("sftp-dir-read-violation")
    violating_result = _success_listing_result()
    violating_result = SftpDirectoryListingResult(
        **{**violating_result.__dict__, "remote_read_performed": True}
    )
    violating = _DirectoryListingAdapter(violating_result)
    register_external_document_source_sftp_directory_listing_adapter(violating)
    response = _list(chain, key="read-violation")
    assert response.status_code == 409, response.text
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceSftpDirectoryListing).filter(
            ExternalDocumentSourceSftpDirectoryListing.session_activation_id == UUID(chain["activation_id"])
        ).count() == 0


def test_sftp_directory_listing_sanitizes_adapter_errors_and_is_tenant_isolated() -> None:
    chain = _activated_chain("sftp-dir-error")
    adapter = _DirectoryListingAdapter(raise_error=True)
    register_external_document_source_sftp_directory_listing_adapter(adapter)

    _, other_requester, _ = _seed_tenant("sftp-dir-other-tenant")
    wrong_tenant = _list(chain, key="wrong-tenant", actor_id=other_requester)
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert adapter.calls == []

    response = _list(chain, key="adapter-error")
    assert response.status_code == 201, response.text
    assert response.json()["result_status"] == "failed"
    assert response.json()["failure_code"] == "adapter_error"
    assert _SECRET_MARKER not in response.text
    assert _RAW_RESPONSE_MARKER not in response.text

    listing_id = UUID(response.json()["id"])
    with TestingSessionLocal() as db:
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "external_document_source_sftp_directory_listing",
            AuditLog.entity_id == listing_id,
        ).one()
        payload = json.dumps(audit.new_values, sort_keys=True) + (audit.details or "")
        assert _SECRET_MARKER not in payload
        assert _RAW_RESPONSE_MARKER not in payload
