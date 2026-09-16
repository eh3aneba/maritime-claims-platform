from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.modules.external_document_sources.change_detection_models import (
    ExternalDocumentSourceChangeDetectionExecution,
    ExternalDocumentSourceChangeDetectionReceipt,
)
from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    clear_external_document_source_change_detection_adapters,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.credential_reference_health_service import clear_external_document_source_credential_reference_health_resolvers
from app.modules.external_document_sources.credential_resolution_execution_service import clear_external_document_source_credential_resolution_resolvers
from app.modules.external_document_sources.discovery_service import clear_external_document_source_discovery_adapters
from app.modules.external_document_sources.provider_client_health_service import clear_external_document_source_provider_client_health_adapters
from app.modules.external_document_sources.remote_content_staging_service import (
    clear_external_document_source_remote_content_staging_store,
    register_external_document_source_remote_content_staging_store,
)
from app.modules.external_document_sources.remote_file_content_read_service import (
    clear_external_document_source_remote_file_content_read_adapters,
    register_external_document_source_remote_file_content_read_adapter,
)
from app.modules.external_document_sources.remote_metadata_listing_service import (
    RemoteMetadataItemProjection,
    RemoteMetadataListResult,
    clear_external_document_source_remote_metadata_list_adapters,
    register_external_document_source_remote_metadata_list_adapter,
)
from app.modules.external_document_sources.sync_checkpoint_models import ExternalDocumentSourceSyncCheckpointExecution
from app.modules.external_document_sources.token_acquisition_execution_service import clear_external_document_source_token_acquirers
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_change_detection import (
    _CHANGE_REASON,
    _RAW_RESPONSE,
    _SECRET,
    _TOKEN,
    _ChangeAdapter,
    _detect,
)
from tests.test_external_document_source_discovery import _headers
from tests.test_external_document_source_remote_content_staging import (
    _PROVIDER_URL,
    _QuarantineStore,
    _stage,
)
from tests.test_external_document_source_remote_file_content_read import (
    _FILE_BODY,
    _ReadAdapter,
    _read_content,
)
from tests.test_external_document_source_remote_metadata_listing import (
    _LIST_REASON,
    _completed_phase_k,
    _list_metadata,
)
from tests.test_external_document_source_sync_checkpoint import _checkpoint, _completed_phase_n


class _NoVersionListAdapter:
    adapter_kind = "deterministic_phase_p_no_version_metadata_list_v1"
    provider_kind = "sharepoint"
    client_kind = "microsoft_graph_transient_v1"
    listing_operation_kind = "graph_drive_children_metadata_v1"
    provider_origin = "https://graph.microsoft.com"

    def __init__(self):
        self.calls = 0

    def list_metadata(self, locator, policy):
        self.calls += 1
        return RemoteMetadataListResult(
            listed=True,
            items=(
                RemoteMetadataItemProjection(
                    provider_item_id="remote-file-m-001",
                    parent_item_id="remote-folder-root",
                    item_kind="file",
                    display_name="Phase M Survey Report.pdf",
                    mime_type_class="application/pdf",
                    byte_size=len(_FILE_BODY),
                    modified_at=datetime(2026, 9, 16, 5, 20, tzinfo=timezone.utc),
                    version_token_hash=None,
                ),
            ),
            truncated=False,
            page_count=1,
        )


def setup_function() -> None:
    clear_external_document_source_change_detection_adapters()
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()
    clear_external_document_source_credential_resolution_resolvers()
    clear_external_document_source_token_acquirers()
    clear_external_document_source_provider_client_health_adapters()
    clear_external_document_source_remote_metadata_list_adapters()
    clear_external_document_source_remote_file_content_read_adapters()
    clear_external_document_source_remote_content_staging_store()
    reset_database()


def teardown_function() -> None:
    clear_external_document_source_change_detection_adapters()
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()
    clear_external_document_source_credential_resolution_resolvers()
    clear_external_document_source_token_acquirers()
    clear_external_document_source_provider_client_health_adapters()
    clear_external_document_source_remote_metadata_list_adapters()
    clear_external_document_source_remote_file_content_read_adapters()
    clear_external_document_source_remote_content_staging_store()


def _phase_o():
    requester_id, profile_id, binding_id, staging_execution_id, read_adapter, store = _completed_phase_n()
    checkpoint = _checkpoint(
        profile_id,
        staging_execution_id,
        requester_id,
        key="phase-p-acceptance-checkpoint",
    )
    assert checkpoint.status_code == 201, checkpoint.text
    return requester_id, profile_id, binding_id, checkpoint.json()["id"], read_adapter, store


def test_phase_p_failure_classes_never_become_missing_and_do_not_relist(caplog: pytest.LogCaptureFixture) -> None:
    requester_id, profile_id, _binding_id, checkpoint_id, read_adapter, store = _phase_o()
    io_before = (read_adapter.calls, store.put_calls, store.head_calls, store.get_calls)

    # Prove Phase P does not depend on or invoke the folder-listing adapter after Phase O.
    clear_external_document_source_remote_metadata_list_adapters()
    adapter = _ChangeAdapter()
    register_external_document_source_change_detection_adapter(
        "sharepoint", "graph_drive_item_metadata_read_v1", adapter,
    )

    failures = (
        "unauthorized",
        "permission_denied",
        "endpoint_unavailable",
        "timeout",
        "malformed_response",
        "oversized_response",
        "provider_rejected",
    )
    for index, failure_code in enumerate(failures, start=1):
        adapter.result = ExactItemMetadataResult(found=False, failure_code=failure_code)
        response = _detect(
            profile_id,
            checkpoint_id,
            requester_id,
            key=f"phase-p-failure-{index}",
        )
        assert response.status_code == 409, response.text
        assert failure_code in response.text
        assert "missing" not in response.text.lower()
        assert (read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before

    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceChangeDetectionExecution).count() == 0
        assert db.query(ExternalDocumentSourceChangeDetectionReceipt).count() == 0

    adapter.raise_with_secrets = True
    secret_failure = _detect(
        profile_id,
        checkpoint_id,
        requester_id,
        key="phase-p-secret-exception",
    )
    assert secret_failure.status_code == 409, secret_failure.text
    assert "Exact-item metadata observation failed" in secret_failure.text
    for marker in (_SECRET, _TOKEN, _RAW_RESPONSE, _PROVIDER_URL):
        assert marker not in secret_failure.text
        assert marker not in caplog.text

    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceChangeDetectionExecution).count() == 0
        assert db.query(ExternalDocumentSourceChangeDetectionReceipt).count() == 0


def test_phase_p_checkpoint_and_receipt_tamper_fail_before_new_authority() -> None:
    requester_id, profile_id, _binding_id, checkpoint_id, read_adapter, store = _phase_o()
    io_before = (read_adapter.calls, store.put_calls, store.head_calls, store.get_calls)
    adapter = _ChangeAdapter()
    register_external_document_source_change_detection_adapter(
        "sharepoint", "graph_drive_item_metadata_read_v1", adapter,
    )

    with TestingSessionLocal() as db:
        checkpoint = db.get(ExternalDocumentSourceSyncCheckpointExecution, UUID(checkpoint_id))
        assert checkpoint is not None
        original_state_hash = checkpoint.checkpoint_state_hash
        checkpoint.checkpoint_state_hash = "0" * 64
        db.commit()

    blocked = _detect(
        profile_id,
        checkpoint_id,
        requester_id,
        key="phase-p-upstream-tamper",
    )
    assert blocked.status_code == 409, blocked.text
    assert adapter.calls == 0
    assert (read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before

    with TestingSessionLocal() as db:
        checkpoint = db.get(ExternalDocumentSourceSyncCheckpointExecution, UUID(checkpoint_id))
        assert checkpoint is not None
        checkpoint.checkpoint_state_hash = original_state_hash
        db.commit()

    completed = _detect(
        profile_id,
        checkpoint_id,
        requester_id,
        key="phase-p-receipt-tamper",
    )
    assert completed.status_code == 201, completed.text
    execution_id = completed.json()["id"]
    assert adapter.calls == 1

    with TestingSessionLocal() as db:
        receipt = db.query(ExternalDocumentSourceChangeDetectionReceipt).filter(
            ExternalDocumentSourceChangeDetectionReceipt.execution_id == UUID(execution_id),
            ExternalDocumentSourceChangeDetectionReceipt.sequence_number == 1,
        ).one()
        original_reason = receipt.reason
        receipt.reason = "Tampered Phase P receipt reason."
        db.commit()

    tampered = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/change-detection-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert tampered.status_code == 409, tampered.text

    with TestingSessionLocal() as db:
        receipt = db.query(ExternalDocumentSourceChangeDetectionReceipt).filter(
            ExternalDocumentSourceChangeDetectionReceipt.execution_id == UUID(execution_id),
            ExternalDocumentSourceChangeDetectionReceipt.sequence_number == 1,
        ).one()
        receipt.reason = original_reason
        db.commit()

    restored = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/change-detection-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert restored.status_code == 200, restored.text


def test_phase_p_without_version_token_uses_bounded_projection_fallback() -> None:
    requester_id, profile_id, _binding_id, health_execution_id = _completed_phase_k()
    listing_adapter = _NoVersionListAdapter()
    register_external_document_source_remote_metadata_list_adapter(
        "sharepoint", "graph_drive_children_metadata_v1", listing_adapter,
    )
    listed = _list_metadata(
        profile_id,
        health_execution_id,
        requester_id,
        key="phase-p-no-version-list",
        reason=_LIST_REASON,
    )
    assert listed.status_code == 201, listed.text
    listing_body = listed.json()
    file_item = listing_body["items"][0]
    assert file_item["version_token_hash"] is None
    assert listing_adapter.calls == 1

    read_adapter = _ReadAdapter(observed_version_token_hash=None)  # type: ignore[arg-type]
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint", "graph_drive_item_content_read_v1", read_adapter,
    )
    read = _read_content(
        profile_id,
        listing_body["id"],
        file_item["id"],
        requester_id,
        key="phase-p-no-version-read",
    )
    assert read.status_code == 201, read.text

    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)
    staged = _stage(
        profile_id,
        read.json()["id"],
        requester_id,
        key="phase-p-no-version-stage",
    )
    assert staged.status_code == 201, staged.text

    checkpoint = _checkpoint(
        profile_id,
        staged.json()["id"],
        requester_id,
        key="phase-p-no-version-checkpoint",
    )
    assert checkpoint.status_code == 201, checkpoint.text

    # Listing is no longer available: the observation must use only the exact-item adapter.
    clear_external_document_source_remote_metadata_list_adapters()
    adapter = _ChangeAdapter()
    adapter.result = ExactItemMetadataResult(
        found=True,
        item=RemoteMetadataItemProjection(
            provider_item_id="remote-file-m-001",
            parent_item_id="remote-folder-root",
            item_kind="file",
            display_name="Phase M Survey Report.pdf",
            mime_type_class="application/pdf",
            byte_size=len(_FILE_BODY) + 1,
            modified_at=datetime(2026, 9, 16, 5, 20, tzinfo=timezone.utc),
            version_token_hash=None,
        ),
    )
    register_external_document_source_change_detection_adapter(
        "sharepoint", "graph_drive_item_metadata_read_v1", adapter,
    )
    detected = _detect(
        profile_id,
        checkpoint.json()["id"],
        requester_id,
        key="phase-p-no-version-detect",
        reason=_CHANGE_REASON,
    )
    assert detected.status_code == 201, detected.text
    body = detected.json()
    assert body["result_status"] == "changed"
    assert body["baseline_version_token_hash"] is None
    assert body["observed_version_token_hash"] is None
    assert body["changed_dimensions"] == "byte_size"
    assert adapter.calls == 1
