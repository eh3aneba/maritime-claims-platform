import json
from dataclasses import replace
from uuid import UUID

import pytest

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.change_detection_service import (
    ExactItemMetadataResult,
    register_external_document_source_change_detection_adapter,
)
from app.modules.external_document_sources.generation_3_change_detection_models import (
    ExternalDocumentSourceGeneration3ChangeDetectionExecution,
    ExternalDocumentSourceGeneration3ChangeDetectionReceipt,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_change_detection import (
    _ChangeAdapter,
    _PROVIDER_URL,
    _RAW_RESPONSE,
    _SECRET,
    _TOKEN,
)
from tests.test_external_document_source_checkpoint_generation_3 import (
    _advance,
    _completed_phase_t,
    setup_function as _phase_u_setup,
    teardown_function as _phase_u_teardown,
)
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_successor_change_detection import _generation2_projection
from tests.test_external_document_source_successor_versioned_restaging import (
    _T_BODY,
    _T_MODIFIED,
    _T_VERSION,
)

_OBSERVE_REASON = "Observe the exact provider item once against the immutable generation-3 successor checkpoint using metadata only."


def setup_function() -> None:
    _phase_u_setup()


def teardown_function() -> None:
    _phase_u_teardown()


def _observe(
    profile_id: str,
    u_execution_id: str,
    actor_id: UUID,
    *,
    key: str,
    reason: str = _OBSERVE_REASON,
    extra: dict | None = None,
):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/checkpoint-generation-3-executions/{u_execution_id}/generation-3-successor-change-detection-executions",
        headers=_headers(actor_id),
        json=payload,
    )


def _completed_phase_u():
    (
        requester_id,
        profile_id,
        binding_id,
        checkpoint,
        change,
        q_body,
        r_body,
        s_body,
        t_body,
        metadata_adapter,
        q_adapter,
        phase_m_read_adapter,
        t_adapter,
        store,
    ) = _completed_phase_t()
    response = _advance(
        profile_id,
        t_body["id"],
        requester_id,
        key="phase-v-u-checkpoint",
    )
    assert response.status_code == 201, response.text
    u_body = response.json()
    assert u_body["status"] == "completed"
    assert u_body["result_status"] == "checkpoint_generation_3_advanced"
    return (
        requester_id,
        profile_id,
        binding_id,
        checkpoint,
        change,
        q_body,
        r_body,
        s_body,
        t_body,
        u_body,
        metadata_adapter,
        q_adapter,
        phase_m_read_adapter,
        t_adapter,
        store,
    )


def _upstream_io(metadata_adapter, q_adapter, phase_m_read_adapter, t_adapter, store):
    return (
        metadata_adapter.calls,
        q_adapter.calls,
        phase_m_read_adapter.calls,
        t_adapter.calls,
        store.put_calls,
        store.head_calls,
        store.get_calls,
    )


def _baseline_projection():
    return _generation2_projection(
        size=len(_T_BODY),
        version=_T_VERSION,
        modified=_T_MODIFIED,
    )


def test_phase_v_generation3_successor_exact_item_observation(caplog: pytest.LogCaptureFixture) -> None:
    (
        requester_id,
        profile_id,
        _binding_id,
        _checkpoint,
        _change,
        _q_body,
        _r_body,
        s_body,
        t_body,
        u_body,
        metadata_adapter,
        q_adapter,
        phase_m_read_adapter,
        t_adapter,
        store,
    ) = _completed_phase_u()

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    upstream_before = _upstream_io(metadata_adapter, q_adapter, phase_m_read_adapter, t_adapter, store)
    adapter = _ChangeAdapter()
    adapter.result = ExactItemMetadataResult(found=True, item=_baseline_projection())
    register_external_document_source_change_detection_adapter(
        "sharepoint", "graph_drive_item_metadata_read_v1", adapter,
    )

    forbidden = _observe(
        profile_id,
        u_body["id"],
        requester_id,
        key="phase-v-forbidden",
        extra={
            "checkpoint_generation": 99,
            "provider_item_id": "caller-controlled",
            "version": "caller-version",
            "cursor": "caller-cursor",
            "url": _PROVIDER_URL,
            "path": "/caller/path",
            "content": "caller-content",
            "storage_key": "caller/storage/key",
            "access_token": "caller-token",
        },
    )
    assert forbidden.status_code == 422, forbidden.text
    assert adapter.calls == 0
    assert _upstream_io(metadata_adapter, q_adapter, phase_m_read_adapter, t_adapter, store) == upstream_before

    _, other_requester, _ = _seed_tenant("phase-v-other-tenant")
    wrong_tenant = _observe(profile_id, u_body["id"], other_requester, key="phase-v-wrong-tenant")
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert adapter.calls == 0

    unchanged = _observe(profile_id, u_body["id"], requester_id, key="phase-v-unchanged")
    assert unchanged.status_code == 201, unchanged.text
    body = unchanged.json()
    execution_id = body["id"]
    assert body["status"] == "completed"
    assert body["result_status"] == "unchanged"
    assert body["baseline_generation"] == 3
    assert body["baseline_projection_hash"] == s_body["observed_projection_hash"]
    assert body["baseline_provider_item_id_hash"] == s_body["observed_provider_item_id_hash"]
    assert body["baseline_version_token_hash"] == _T_VERSION
    assert body["baseline_byte_size"] == len(_T_BODY)
    assert body["candidate_content_proof_hash"] == t_body["content_proof_hash"]
    assert body["candidate_completion_hash"] == t_body["completion_hash"]
    assert body["successor_change_completion_hash"] == s_body["completion_hash"]
    assert body["successor_checkpoint_state_hash"] == u_body["successor_checkpoint_state_hash"]
    assert body["successor_checkpoint_completion_hash"] == u_body["completion_hash"]
    assert body["changed_dimensions"] == ""
    assert body["provider_client_constructed"] is True
    assert body["exact_item_metadata_read_performed"] is True
    assert body["generation_3_successor_change_detection_completed"] is True
    assert body["upstream_checkpoint_generation_3_advance_completed"] is True
    for field in (
        "remote_content_transiently_observed",
        "remote_list_performed",
        "remote_read_performed",
        "remote_write_performed",
        "remote_delete_performed",
        "storage_read_performed",
        "storage_write_performed",
        "storage_delete_performed",
        "durable_content_staged",
        "checkpoint_created",
        "checkpoint_advanced",
        "sync_executed",
        "subscription_created",
        "document_created",
        "evidence_admitted",
        "content_parsed",
        "content_extracted",
        "claim_mutated",
    ):
        assert body[field] is False

    assert adapter.calls == 1
    assert adapter.last_policy is not None
    assert "/items/remote-file-m-001" in adapter.last_policy.metadata_endpoint_url
    assert "/content" not in adapter.last_policy.metadata_endpoint_url
    assert adapter.last_policy.allow_redirects is False
    assert adapter.last_policy.max_response_bytes == 65536
    assert _upstream_io(metadata_adapter, q_adapter, phase_m_read_adapter, t_adapter, store) == upstream_before

    for forbidden_field in (
        "provider_item_id",
        "metadata_endpoint_url",
        "provider_origin",
        "storage_object_key",
        "storage_key",
        "content",
        "access_token",
        "client_secret",
    ):
        assert forbidden_field not in body
    serialized = json.dumps(body, sort_keys=True)
    for marker in (_SECRET, _TOKEN, _RAW_RESPONSE, _PROVIDER_URL):
        assert marker not in serialized

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/generation-3-successor-change-detection-executions/{execution_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "completed"]
    assert rows[0]["prior_receipt_hash"] is None
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]
    assert rows[0]["provider_client_constructed"] is False
    assert rows[1]["provider_client_constructed"] is True
    assert adapter.calls == 1

    fetched = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/generation-3-successor-change-detection-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["completion_hash"] == body["completion_hash"]
    assert adapter.calls == 1

    replay = _observe(profile_id, u_body["id"], requester_id, key="phase-v-unchanged")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id
    assert adapter.calls == 1

    changed_replay = _observe(
        profile_id,
        u_body["id"],
        requester_id,
        key="phase-v-unchanged",
        reason="Attempt to alter the completed Phase V request while retaining its request key.",
    )
    assert changed_replay.status_code == 409, changed_replay.text
    assert adapter.calls == 1

    adapter.result = ExactItemMetadataResult(
        found=True,
        item=replace(_baseline_projection(), byte_size=len(_T_BODY) + 1),
    )
    changed = _observe(profile_id, u_body["id"], requester_id, key="phase-v-changed")
    assert changed.status_code == 201, changed.text
    assert changed.json()["result_status"] == "changed"
    assert changed.json()["changed_dimensions"] == "byte_size"
    assert adapter.calls == 2

    adapter.result = ExactItemMetadataResult(found=False, failure_code="not_found")
    missing = _observe(profile_id, u_body["id"], requester_id, key="phase-v-missing")
    assert missing.status_code == 201, missing.text
    assert missing.json()["result_status"] == "missing"
    assert missing.json()["changed_dimensions"] == "missing"
    assert adapter.calls == 3

    failures = (
        "unauthorized",
        "permission_denied",
        "endpoint_unavailable",
        "timeout",
        "malformed_response",
        "oversized_response",
        "provider_rejected",
    )
    for index, failure in enumerate(failures, start=1):
        adapter.result = ExactItemMetadataResult(found=False, failure_code=failure)
        failed = _observe(profile_id, u_body["id"], requester_id, key=f"phase-v-failure-{index}")
        assert failed.status_code == 409, failed.text

    adapter.result = ExactItemMetadataResult(
        found=True,
        item=replace(_baseline_projection(), provider_item_id="unexpected-item"),
    )
    identity_mismatch = _observe(profile_id, u_body["id"], requester_id, key="phase-v-identity-mismatch")
    assert identity_mismatch.status_code == 409, identity_mismatch.text

    adapter.raise_with_secrets = True
    secret_failure = _observe(profile_id, u_body["id"], requester_id, key="phase-v-secret-adapter-failure")
    assert secret_failure.status_code == 409, secret_failure.text
    adapter.raise_with_secrets = False
    secret_text = secret_failure.text + caplog.text
    for marker in (_SECRET, _TOKEN, _RAW_RESPONSE, _PROVIDER_URL):
        assert marker not in secret_text

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceGeneration3ChangeDetectionExecution).count() == 3
        assert db.query(ExternalDocumentSourceGeneration3ChangeDetectionReceipt).count() == 6
        audits = (
            db.query(AuditLog)
            .filter(AuditLog.action == "EXTERNAL_DOCUMENT_SOURCE_GENERATION_3_EXACT_ITEM_CHANGE_DETECTION_COMPLETED")
            .all()
        )
        assert len(audits) == 3
        audit_text = json.dumps(
            [{"new": row.new_values, "details": row.details} for row in audits],
            sort_keys=True,
        )
        for marker in (_SECRET, _TOKEN, _RAW_RESPONSE, _PROVIDER_URL, "storage_object_key"):
            assert marker not in audit_text

    with TestingSessionLocal() as db:
        row = db.get(ExternalDocumentSourceGeneration3ChangeDetectionExecution, UUID(execution_id))
        assert row is not None
        row.completion_hash = "f" * 64
        db.commit()
    tampered = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/generation-3-successor-change-detection-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert tampered.status_code == 409, tampered.text
    assert adapter.calls == 12
