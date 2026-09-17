import json
from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.remote_content_staging_service import (
    register_external_document_source_remote_content_staging_store,
)
from app.modules.external_document_sources.remote_file_content_read_service import (
    RemoteFileContentReadResult,
    register_external_document_source_remote_file_content_read_adapter,
)
from app.modules.external_document_sources.successor_change_detection_models import (
    ExternalDocumentSourceSuccessorChangeDetectionExecution,
)
from app.modules.external_document_sources.successor_versioned_restaging_models import (
    SUCCESSOR_CANDIDATE_GENERATION,
    ExternalDocumentSourceSuccessorVersionedRestagingExecution,
    ExternalDocumentSourceSuccessorVersionedRestagingReceipt,
)
from app.modules.external_document_sources.versioned_restaging_models import (
    ExternalDocumentSourceVersionedRestagingExecution,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_change_detection import _ChangeAdapter, _PROVIDER_URL, _SECRET, _TOKEN, _RAW_RESPONSE
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_remote_content_staging import (
    _FILE_BODY_MARKER,
    _STORAGE_SECRET,
    _QuarantineStore,
)
from tests.test_external_document_source_successor_change_detection import (
    _completed_phase_r,
    _generation2_projection,
    _observe,
    setup_function as _phase_s_setup,
    teardown_function as _phase_s_teardown,
)
from tests.test_external_document_source_versioned_restaging import (
    _NEW_BODY,
    _Q_RAW,
    _Q_SECRET,
    _Q_TOKEN,
)

_RESTAGE_REASON = "Reread the exact Phase S changed file and stage one immutable generation-3 candidate without advancing the checkpoint."
_T_BODY = b"t" * (len(_NEW_BODY) + 7)
_T_VERSION = "d" * 64
_T_MODIFIED = datetime(2026, 9, 16, 8, 30, tzinfo=timezone.utc)
_T_SECRET = "phase-t-provider-secret-marker"
_T_TOKEN = "phase-t-provider-token-marker"
_T_RAW = "phase-t-raw-provider-response-marker"


class _TReadAdapter:
    adapter_kind = "deterministic_phase_t_content_read_v1"
    provider_kind = "sharepoint"
    client_kind = "microsoft_graph_transient_v1"
    read_operation_kind = "graph_drive_item_content_read_v1"
    provider_origin = "https://graph.microsoft.com"
    redirect_policy_kind = "provider_internal_https_one_hop_v1"

    def __init__(self, *, content: bytes = _T_BODY, version: str | None = _T_VERSION, media: str | None = "application/pdf"):
        self.content = content
        self.version = version
        self.media = media
        self.calls = 0
        self.failure_code: str | None = None
        self.raise_with_secrets = False
        self.last_policy = None

    def read_content(self, locator, policy):
        self.calls += 1
        self.last_policy = policy
        if self.raise_with_secrets:
            raise RuntimeError(f"{_T_SECRET} {_T_TOKEN} {_T_RAW} {_PROVIDER_URL}")
        if self.failure_code is not None:
            return RemoteFileContentReadResult(read=False, failure_code=self.failure_code)
        assert policy.provider_origin == "https://graph.microsoft.com"
        assert "/items/remote-file-m-001/content" in policy.content_endpoint_url
        return RemoteFileContentReadResult(
            read=True,
            content=self.content,
            media_type_class=self.media,
            observed_version_token_hash=self.version,
            latency_class="normal",
        )


def setup_function() -> None:
    _phase_s_setup()


def teardown_function() -> None:
    _phase_s_teardown()


def _restage_successor(
    profile_id: str,
    successor_change_id: str,
    actor_id: UUID,
    *,
    key: str,
    reason: str = _RESTAGE_REASON,
    extra: dict | None = None,
):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/successor-change-detection-executions/{successor_change_id}/successor-versioned-restaging-executions",
        headers=_headers(actor_id),
        json=payload,
    )


def _completed_phase_s(*, result: str = "changed"):
    requester_id, profile_id, binding_id, checkpoint, change, q_body, r_body, q_adapter, phase_m_read_adapter, store = _completed_phase_r()
    metadata_adapter = _ChangeAdapter()
    if result == "changed":
        metadata_adapter.result = ExactItemMetadataResult(
            found=True,
            item=_generation2_projection(
                size=len(_T_BODY),
                version=_T_VERSION,
                modified=_T_MODIFIED,
            ),
        )
    elif result == "missing":
        metadata_adapter.result = ExactItemMetadataResult(found=False, failure_code="not_found")
    else:
        metadata_adapter.result = ExactItemMetadataResult(
            found=True,
            item=_generation2_projection(),
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
        key=f"phase-t-s-{result}",
    )
    assert observed.status_code == 201, observed.text
    assert observed.json()["result_status"] == result
    return (
        requester_id,
        profile_id,
        binding_id,
        checkpoint,
        change,
        q_body,
        r_body,
        observed.json(),
        metadata_adapter,
        q_adapter,
        phase_m_read_adapter,
        store,
    )


def test_phase_t_bounded_successor_generation3_restaging(caplog: pytest.LogCaptureFixture) -> None:
    (
        requester_id,
        profile_id,
        binding_id,
        _checkpoint,
        _change,
        q_body,
        r_body,
        s_body,
        metadata_adapter,
        q_adapter,
        phase_m_read_adapter,
        store,
    ) = _completed_phase_s(result="changed")

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()
        q_row = db.get(ExternalDocumentSourceVersionedRestagingExecution, UUID(q_body["id"]))
        s_row = db.get(ExternalDocumentSourceSuccessorChangeDetectionExecution, UUID(s_body["id"]))
        assert q_row is not None and s_row is not None
        q_facts = (
            q_row.content_proof_hash,
            q_row.completion_hash,
            q_row.storage_object_key_hash,
            q_row.storage_object_key,
        )
        s_facts = (s_row.scope_hash, s_row.request_hash, s_row.completion_hash)
        raw_q_key = q_row.storage_object_key

    original_objects = dict(store.objects)
    original_puts = store.put_calls
    upstream_calls = (metadata_adapter.calls, q_adapter.calls, phase_m_read_adapter.calls)

    read_adapter = _TReadAdapter()
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        read_adapter,
    )

    forbidden = _restage_successor(
        profile_id,
        s_body["id"],
        requester_id,
        key="phase-t-forbidden",
        extra={
            "provider_item_id": "caller-controlled",
            "generation": 99,
            "version": "caller-version",
            "cursor": "caller-cursor",
            "url": _PROVIDER_URL,
            "path": "/caller/path",
            "range": "bytes=0-10",
            "content": _FILE_BODY_MARKER,
            "storage_key": "caller/storage/key",
            "access_token": "caller-token",
        },
    )
    assert forbidden.status_code == 422, forbidden.text
    assert read_adapter.calls == 0
    assert store.put_calls == original_puts

    _, other_requester, _ = _seed_tenant("phase-t-other-tenant")
    wrong_tenant = _restage_successor(
        profile_id,
        s_body["id"],
        other_requester,
        key="phase-t-wrong-tenant",
    )
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert read_adapter.calls == 0
    assert store.put_calls == original_puts

    completed = _restage_successor(profile_id, s_body["id"], requester_id, key="phase-t-001")
    assert completed.status_code == 201, completed.text
    body = completed.json()
    execution_id = body["id"]
    assert body["status"] == "completed"
    assert body["result_status"] == "staged_candidate_verified"
    assert body["candidate_generation"] == SUCCESSOR_CANDIDATE_GENERATION == 3
    assert body["successor_change_detection_execution_id"] == s_body["id"]
    assert body["checkpoint_generation_execution_id"] == r_body["id"]
    assert body["versioned_restaging_execution_id"] == q_body["id"]
    assert body["observed_projection_hash"] == s_body["observed_projection_hash"]
    assert body["observed_provider_item_id_hash"] == s_body["observed_provider_item_id_hash"]
    assert body["observed_version_token_hash"] == _T_VERSION
    assert body["observed_byte_size"] == len(_T_BODY)
    assert body["content_byte_count"] == len(_T_BODY)
    assert body["content_version_token_hash"] == _T_VERSION
    assert body["provider_client_constructed"] is True
    assert body["remote_content_transiently_observed"] is True
    assert body["remote_read_performed"] is True
    assert body["storage_read_performed"] is True
    assert body["storage_write_performed"] is True
    assert body["durable_content_staged"] is True
    assert body["remote_content_stored"] is True
    assert body["successor_versioned_restaging_completed"] is True
    assert body["checkpoint_created"] is False
    assert body["checkpoint_advanced"] is False
    assert body["sync_executed"] is False
    assert body["subscription_created"] is False
    assert body["document_created"] is False
    assert body["evidence_admitted"] is False
    assert body["content_parsed"] is False
    assert body["content_extracted"] is False
    assert body["claim_mutated"] is False
    assert "storage_object_key" not in body
    assert read_adapter.calls == 1
    assert read_adapter.last_policy is not None
    assert "/items/remote-file-m-001/content" in read_adapter.last_policy.content_endpoint_url

    assert len(store.objects) == len(original_objects) + 1
    for key, payload in original_objects.items():
        assert store.objects[key] == payload
    new_keys = set(store.objects) - set(original_objects)
    assert len(new_keys) == 1
    internal_t_key = next(iter(new_keys))
    assert internal_t_key != raw_q_key
    assert "/generation-3/" in internal_t_key
    assert store.objects[internal_t_key] == _T_BODY

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/successor-versioned-restaging-executions/{execution_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "content_verified", "completed"]
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]
    assert rows[2]["prior_receipt_hash"] == rows[1]["receipt_hash"]

    calls_before_replay = read_adapter.calls
    puts_before_replay = store.put_calls
    replay = _restage_successor(profile_id, s_body["id"], requester_id, key="phase-t-001")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id
    assert read_adapter.calls == calls_before_replay
    assert store.put_calls == puts_before_replay

    changed_replay = _restage_successor(
        profile_id,
        s_body["id"],
        requester_id,
        key="phase-t-001",
        reason="Attempt to alter the completed Phase T request while retaining the consumed Phase S observation.",
    )
    assert changed_replay.status_code == 409, changed_replay.text
    second_consumption = _restage_successor(
        profile_id,
        s_body["id"],
        requester_id,
        key="phase-t-second",
    )
    assert second_consumption.status_code == 409, second_consumption.text
    assert read_adapter.calls == calls_before_replay
    assert store.put_calls == puts_before_replay

    with TestingSessionLocal() as db:
        q_row = db.get(ExternalDocumentSourceVersionedRestagingExecution, UUID(q_body["id"]))
        s_row = db.get(ExternalDocumentSourceSuccessorChangeDetectionExecution, UUID(s_body["id"]))
        execution = db.get(ExternalDocumentSourceSuccessorVersionedRestagingExecution, UUID(execution_id))
        assert q_row is not None and s_row is not None and execution is not None
        assert (
            q_row.content_proof_hash,
            q_row.completion_hash,
            q_row.storage_object_key_hash,
            q_row.storage_object_key,
        ) == q_facts
        assert (s_row.scope_hash, s_row.request_hash, s_row.completion_hash) == s_facts
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "external_document_source_successor_versioned_restaging_execution",
            AuditLog.entity_id == UUID(execution_id),
        ).one()
        audit_payload = json.dumps(audit.new_values, sort_keys=True, default=str) + (audit.details or "")
        assert execution.storage_object_key not in audit_payload
        assert raw_q_key not in audit_payload
        assert "storage_object_key" not in audit.new_values
        for marker in (
            _FILE_BODY_MARKER,
            _NEW_BODY.decode("ascii"),
            _T_BODY.decode("ascii"),
            _STORAGE_SECRET,
            _PROVIDER_URL,
            _SECRET,
            _TOKEN,
            _RAW_RESPONSE,
            _Q_SECRET,
            _Q_TOKEN,
            _Q_RAW,
            _T_SECRET,
            _T_TOKEN,
            _T_RAW,
        ):
            assert marker not in completed.text
            assert marker not in audit_payload
            assert marker not in caplog.text

        receipt = db.query(ExternalDocumentSourceSuccessorVersionedRestagingReceipt).filter(
            ExternalDocumentSourceSuccessorVersionedRestagingReceipt.execution_id == UUID(execution_id),
            ExternalDocumentSourceSuccessorVersionedRestagingReceipt.sequence_number == 1,
        ).one()
        original_reason = receipt.reason
        receipt.reason = "tampered Phase T receipt reason"
        db.commit()

    tampered_receipt = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/successor-versioned-restaging-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert tampered_receipt.status_code == 409, tampered_receipt.text
    with TestingSessionLocal() as db:
        receipt = db.query(ExternalDocumentSourceSuccessorVersionedRestagingReceipt).filter(
            ExternalDocumentSourceSuccessorVersionedRestagingReceipt.execution_id == UUID(execution_id),
            ExternalDocumentSourceSuccessorVersionedRestagingReceipt.sequence_number == 1,
        ).one()
        receipt.reason = original_reason
        db.commit()

    disabled = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/disable",
        headers=_headers(requester_id),
        json={"reason": "Disable upstream credential lineage so completed Phase T custody fails closed."},
    )
    assert disabled.status_code == 200, disabled.text
    fail_closed = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/successor-versioned-restaging-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert fail_closed.status_code == 409, fail_closed.text
    assert upstream_calls == (metadata_adapter.calls, q_adapter.calls, phase_m_read_adapter.calls)


@pytest.mark.parametrize("result", ["unchanged", "missing"])
def test_phase_t_rejects_ineligible_successor_observations_before_content_or_storage_io(result: str) -> None:
    (
        requester_id,
        profile_id,
        _binding_id,
        _checkpoint,
        _change,
        _q_body,
        _r_body,
        s_body,
        _metadata_adapter,
        _q_adapter,
        _phase_m_read_adapter,
        store,
    ) = _completed_phase_s(result=result)
    read_adapter = _TReadAdapter()
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        read_adapter,
    )
    io_before = (read_adapter.calls, store.put_calls, store.head_calls, store.get_calls)
    rejected = _restage_successor(
        profile_id,
        s_body["id"],
        requester_id,
        key=f"phase-t-ineligible-{result}",
    )
    assert rejected.status_code == 409, rejected.text
    assert (read_adapter.calls, store.put_calls, store.head_calls, store.get_calls) == io_before
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceSuccessorVersionedRestagingExecution).count() == 0
        assert db.query(ExternalDocumentSourceSuccessorVersionedRestagingReceipt).count() == 0


@pytest.mark.parametrize(
    "failure_code",
    ["unauthorized", "permission_denied", "endpoint_unavailable", "timeout", "malformed_response", "oversized_response", "provider_rejected"],
)
def test_phase_t_content_failures_remain_failures(failure_code: str) -> None:
    requester_id, profile_id, *_rest = _completed_phase_s(result="changed")
    s_body = _rest[5]
    read_adapter = _TReadAdapter()
    read_adapter.failure_code = failure_code
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        read_adapter,
    )
    failed = _restage_successor(
        profile_id,
        s_body["id"],
        requester_id,
        key=f"phase-t-failure-{failure_code}",
    )
    assert failed.status_code == 409, failed.text
    assert read_adapter.calls == 1
    with TestingSessionLocal() as db:
        rows = db.query(ExternalDocumentSourceSuccessorVersionedRestagingExecution).all()
        assert len(rows) == 1
        assert rows[0].status == "requested"
        assert rows[0].result_status is None
        assert db.query(ExternalDocumentSourceSuccessorVersionedRestagingReceipt).count() == 1


def test_phase_t_crash_after_put_recovers_without_provider_reread_or_second_put() -> None:
    requester_id, profile_id, *_rest = _completed_phase_s(result="changed")
    s_body = _rest[5]
    crash_store = _QuarantineStore(fail_first_head_after_put=True)
    register_external_document_source_remote_content_staging_store(crash_store)
    read_adapter = _TReadAdapter()
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint",
        "graph_drive_item_content_read_v1",
        read_adapter,
    )

    first = _restage_successor(profile_id, s_body["id"], requester_id, key="phase-t-crash")
    assert first.status_code == 409, first.text
    assert read_adapter.calls == 1
    assert crash_store.put_calls == 1
    assert len(crash_store.objects) == 1
    with TestingSessionLocal() as db:
        execution = db.query(ExternalDocumentSourceSuccessorVersionedRestagingExecution).one()
        execution_id = str(execution.id)
        assert execution.status == "content_verified"
        assert execution.content_proof_hash is not None
        assert db.query(ExternalDocumentSourceSuccessorVersionedRestagingReceipt).count() == 2

    replay = _restage_successor(profile_id, s_body["id"], requester_id, key="phase-t-crash")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id
    assert replay.json()["status"] == "completed"
    assert read_adapter.calls == 1
    assert crash_store.put_calls == 1
    with TestingSessionLocal() as db:
        execution = db.get(ExternalDocumentSourceSuccessorVersionedRestagingExecution, UUID(execution_id))
        assert execution is not None and execution.status == "completed"
        assert db.query(ExternalDocumentSourceSuccessorVersionedRestagingReceipt).count() == 3
