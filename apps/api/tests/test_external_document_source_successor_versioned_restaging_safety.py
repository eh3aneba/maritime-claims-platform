from uuid import UUID

import pytest

from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.remote_file_content_read_service import (
    register_external_document_source_remote_file_content_read_adapter,
)
from app.modules.external_document_sources.successor_change_detection_models import (
    ExternalDocumentSourceSuccessorChangeDetectionExecution,
)
from app.modules.external_document_sources.successor_versioned_restaging_models import (
    MAX_SUCCESSOR_VERSIONED_RESTAGING_BYTES,
    ExternalDocumentSourceSuccessorVersionedRestagingExecution,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_change_detection import (
    _ChangeAdapter,
    _PROVIDER_URL,
)
from tests.test_external_document_source_discovery import _headers
from tests.test_external_document_source_successor_change_detection import (
    _completed_phase_r,
    _generation2_projection,
    _observe,
)
from tests.test_external_document_source_successor_versioned_restaging import (
    _T_BODY,
    _T_MODIFIED,
    _T_RAW,
    _T_SECRET,
    _T_TOKEN,
    _T_VERSION,
    _TReadAdapter,
    _completed_phase_s,
    _restage_successor,
    setup_function as _phase_t_setup,
    teardown_function as _phase_t_teardown,
)


def setup_function() -> None:
    _phase_t_setup()


def teardown_function() -> None:
    _phase_t_teardown()


@pytest.mark.parametrize(
    ("adapter", "key", "expected_fragment"),
    [
        (_TReadAdapter(media="application/octet-stream"), "phase-t-mime-drift", "media type"),
        (_TReadAdapter(version="e" * 64), "phase-t-version-drift", "version"),
    ],
)
def test_phase_t_rejects_content_metadata_drift(adapter: _TReadAdapter, key: str, expected_fragment: str) -> None:
    requester_id, profile_id, *_rest = _completed_phase_s(result="changed")
    s_body = _rest[5]
    store = _rest[9]
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        adapter,
    )
    io_before = (store.put_calls, store.head_calls, store.get_calls)

    rejected = _restage_successor(profile_id, s_body["id"], requester_id, key=key)
    assert rejected.status_code == 409, rejected.text
    assert expected_fragment in rejected.text.lower()
    assert adapter.calls == 1
    assert (store.put_calls, store.head_calls, store.get_calls) == io_before
    with TestingSessionLocal() as db:
        execution = db.query(ExternalDocumentSourceSuccessorVersionedRestagingExecution).one()
        assert execution.status == "requested"
        assert execution.content_proof_hash is None


def test_phase_t_rejects_actual_oversized_content_before_storage_write() -> None:
    requester_id, profile_id, *_prefix, r_body, _q_adapter, _phase_m_read_adapter, store = _completed_phase_r()
    metadata_adapter = _ChangeAdapter()
    oversized_size = MAX_SUCCESSOR_VERSIONED_RESTAGING_BYTES + 1
    metadata_adapter.result = ExactItemMetadataResult(
        found=True,
        item=_generation2_projection(
            size=oversized_size,
            version=_T_VERSION,
            modified=_T_MODIFIED,
        ),
    )
    register_external_document_source_change_detection_adapter(
        "sharepoint",
        "graph_drive_item_metadata_read_v1",
        metadata_adapter,
    )
    observed = _observe(
        profile_id,
        r_body["id"],
        requester_id,
        key="phase-t-s-oversized",
    )
    assert observed.status_code == 201, observed.text
    assert observed.json()["result_status"] == "changed"

    oversized_adapter = _TReadAdapter(content=b"x" * oversized_size, version=_T_VERSION)
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        oversized_adapter,
    )
    puts_before = store.put_calls
    rejected = _restage_successor(
        profile_id,
        observed.json()["id"],
        requester_id,
        key="phase-t-oversized-content",
    )
    assert rejected.status_code == 409, rejected.text
    assert "byte bound" in rejected.text.lower()
    assert oversized_adapter.calls == 1
    assert store.put_calls == puts_before


def test_phase_t_redacts_secret_bearing_provider_exception(caplog: pytest.LogCaptureFixture) -> None:
    requester_id, profile_id, *_rest = _completed_phase_s(result="changed")
    s_body = _rest[5]
    store = _rest[9]
    adapter = _TReadAdapter()
    adapter.raise_with_secrets = True
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        adapter,
    )
    puts_before = store.put_calls

    rejected = _restage_successor(
        profile_id,
        s_body["id"],
        requester_id,
        key="phase-t-secret-exception",
    )
    assert rejected.status_code == 409, rejected.text
    assert "remote content reread failed" in rejected.text.lower()
    assert adapter.calls == 1
    assert store.put_calls == puts_before
    for marker in (_T_SECRET, _T_TOKEN, _T_RAW, _PROVIDER_URL):
        assert marker not in rejected.text
        assert marker not in caplog.text


def _completed_t():
    requester_id, profile_id, *_rest = _completed_phase_s(result="changed")
    s_body = _rest[5]
    store = _rest[9]
    adapter = _TReadAdapter()
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        adapter,
    )
    completed = _restage_successor(
        profile_id,
        s_body["id"],
        requester_id,
        key="phase-t-safety-completed",
    )
    assert completed.status_code == 201, completed.text
    assert completed.json()["status"] == "completed"
    return requester_id, profile_id, s_body, completed.json(), adapter, store


def test_phase_t_detects_content_proof_tamper() -> None:
    requester_id, profile_id, _s_body, t_body, adapter, _store = _completed_t()
    with TestingSessionLocal() as db:
        execution = db.get(ExternalDocumentSourceSuccessorVersionedRestagingExecution, UUID(t_body["id"]))
        assert execution is not None
        execution.content_proof_hash = "0" * 64
        db.commit()
    calls_before = adapter.calls

    tampered = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/successor-versioned-restaging-executions/{t_body['id']}",
        headers=_headers(requester_id),
    )
    assert tampered.status_code == 409, tampered.text
    assert adapter.calls == calls_before


def test_phase_t_detects_stored_object_tamper() -> None:
    requester_id, profile_id, _s_body, t_body, adapter, store = _completed_t()
    with TestingSessionLocal() as db:
        execution = db.get(ExternalDocumentSourceSuccessorVersionedRestagingExecution, UUID(t_body["id"]))
        assert execution is not None
        storage_key = execution.storage_object_key
        original = store.objects[storage_key]
    store.objects[storage_key] = b"z" * len(original)
    calls_before = adapter.calls

    tampered = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/successor-versioned-restaging-executions/{t_body['id']}",
        headers=_headers(requester_id),
    )
    assert tampered.status_code == 409, tampered.text
    assert adapter.calls == calls_before


def test_phase_t_rejects_upstream_phase_s_tamper_before_new_content_or_storage_authority() -> None:
    requester_id, profile_id, *_rest = _completed_phase_s(result="changed")
    s_body = _rest[5]
    store = _rest[9]
    adapter = _TReadAdapter()
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        adapter,
    )
    with TestingSessionLocal() as db:
        s_row = db.get(ExternalDocumentSourceSuccessorChangeDetectionExecution, UUID(s_body["id"]))
        assert s_row is not None
        s_row.completion_hash = "0" * 64
        db.commit()
    io_before = (adapter.calls, store.put_calls, store.head_calls, store.get_calls)

    rejected = _restage_successor(
        profile_id,
        s_body["id"],
        requester_id,
        key="phase-t-upstream-s-tamper",
    )
    assert rejected.status_code == 409, rejected.text
    assert (adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceSuccessorVersionedRestagingExecution).count() == 0
