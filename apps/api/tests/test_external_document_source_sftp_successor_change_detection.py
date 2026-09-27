from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.sftp_change_detection_models import (
    ExternalDocumentSourceSftpChangeDetection,
)
from app.modules.external_document_sources.sftp_change_detection_service import (
    clear_external_document_source_sftp_exact_file_metadata_adapter,
    register_external_document_source_sftp_exact_file_metadata_adapter,
)
from app.modules.external_document_sources.sftp_checkpoint_advancement_models import (
    ExternalDocumentSourceSftpCheckpointAdvancement,
)
from app.modules.external_document_sources.sftp_checkpoint_models import (
    ExternalDocumentSourceSftpCheckpoint,
)
from app.modules.external_document_sources.sftp_successor_change_detection_models import (
    ExternalDocumentSourceSftpSuccessorChangeDetection,
    ExternalDocumentSourceSftpSuccessorChangeDetectionReceipt,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_profiles import _headers, _seed_tenant
from tests.test_external_document_source_sftp_change_detection import _StatAdapter
from tests.test_external_document_source_sftp_checkpoint_advancement import (
    _advance,
    _completed_phase_m,
    setup_function as _n_setup,
    teardown_function as _n_teardown,
)


_REASON = (
    "Observe the exact SFTP file once against the generation-2 successor "
    "checkpoint without reading content or touching object storage."
)


def setup_function() -> None:
    _n_setup()
    clear_external_document_source_sftp_exact_file_metadata_adapter()


def teardown_function() -> None:
    clear_external_document_source_sftp_exact_file_metadata_adapter()
    _n_teardown()


def _completed_phase_n(seed: str):
    chain = _completed_phase_m(seed)
    response = _advance(chain, key="n2")
    assert response.status_code == 201, response.text
    assert response.json()["result_status"] == "checkpoint_advanced"
    chain["advancement_id"] = response.json()["id"]
    return chain


def _generation_2_baseline(chain: dict):
    with TestingSessionLocal() as db:
        advancement = db.get(
            ExternalDocumentSourceSftpCheckpointAdvancement,
            UUID(chain["advancement_id"]),
        )
        change = db.get(
            ExternalDocumentSourceSftpChangeDetection,
            UUID(chain["change_detection_id"]),
        )
        predecessor = db.get(
            ExternalDocumentSourceSftpCheckpoint,
            UUID(chain["checkpoint_id"]),
        )
        assert advancement is not None
        assert change is not None
        assert predecessor is not None
        assert change.observed_byte_size == advancement.content_byte_count
        assert advancement.content_byte_count != predecessor.content_byte_count
        return {
            "byte_size": advancement.content_byte_count,
            "modified_at": change.observed_modified_at,
            "metadata_id_hash": change.observed_metadata_id_hash,
            "old_generation_byte_size": predecessor.content_byte_count,
        }


def _observe(
    chain: dict,
    *,
    key: str,
    reason: str = _REASON,
    actor_id=None,
    extra: dict | None = None,
):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-checkpoint-advancements/{chain['advancement_id']}/"
            "successor-change-detections"
        ),
        headers=_headers(actor_id or chain["requester_id"]),
        json=payload,
    )


def test_successor_observation_uses_generation_2_baseline_and_is_metadata_only() -> None:
    chain = _completed_phase_n("sftp-successor-observe")
    baseline = _generation_2_baseline(chain)
    adapter = _StatAdapter(mode="unchanged", baseline=baseline)
    register_external_document_source_sftp_exact_file_metadata_adapter(adapter)

    put_before = chain["store"].put_calls
    head_before = chain["store"].head_calls
    get_before = chain["store"].get_calls
    read_before = len(chain["read_adapter"].calls)

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    forbidden = _observe(
        chain,
        key="deny",
        extra={
            "hostname": "caller.invalid",
            "remote_path": "/caller/path",
            "content": "caller-content",
            "generation": 9,
            "storage_key": "caller/storage",
            "credential": "caller-secret",
        },
    )
    assert forbidden.status_code == 422, forbidden.text
    assert adapter.calls == []

    _, other_requester, _, _ = _seed_tenant("sftp-successor-observe-other")
    wrong_tenant = _observe(chain, key="tenant", actor_id=other_requester)
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert adapter.calls == []

    response = _observe(chain, key="o1")
    assert response.status_code == 201, response.text
    body = response.json()
    execution_id = body["id"]

    assert body["baseline_generation"] == 2
    assert body["baseline_byte_size"] == baseline["byte_size"]
    assert body["baseline_byte_size"] != baseline["old_generation_byte_size"]
    if baseline["modified_at"] is None:
        assert body["baseline_modified_at"] is None
    else:
        expected_modified = baseline["modified_at"]
        if expected_modified.tzinfo is None:
            expected_modified = expected_modified.replace(tzinfo=timezone.utc)
        actual_modified = datetime.fromisoformat(body["baseline_modified_at"])
        assert actual_modified == expected_modified.astimezone(timezone.utc)
    assert body["baseline_metadata_id_hash"] == baseline["metadata_id_hash"]
    assert body["result_status"] == "unchanged"
    assert body["changed_dimensions"] is None
    assert body["observed_byte_size"] == baseline["byte_size"]
    assert body["remote_stat_performed"] is True
    assert body["exact_item_metadata_read_performed"] is True
    assert body["successor_change_detection_completed"] is True
    assert body["remote_list_performed"] is False
    assert body["remote_read_performed"] is False
    assert body["remote_content_transiently_observed"] is False
    assert body["storage_read_performed"] is False
    assert body["storage_write_performed"] is False
    assert body["storage_reconciliation_performed"] is False
    assert body["checkpoint_created"] is False
    assert body["checkpoint_advanced"] is False
    assert body["subscription_created"] is False
    assert body["document_created"] is False
    assert body["evidence_admitted"] is False
    assert body["processing_enqueued"] is False
    assert body["ai_executed"] is False
    assert body["claim_mutated"] is False

    assert len(adapter.calls) == 1
    request = adapter.calls[0]
    assert request.max_stat_attempts == 1
    assert request.read_only_intent is True
    assert request.follow_symlinks is False
    assert request.effective_remote_path.endswith(request.entry_relative_path)

    assert chain["store"].put_calls == put_before
    assert chain["store"].head_calls == head_before
    assert chain["store"].get_calls == get_before
    assert len(chain["read_adapter"].calls) == read_before

    replay = _observe(chain, key="o1")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id
    assert len(adapter.calls) == 1

    second_manual = _observe(chain, key="o2")
    assert second_manual.status_code == 201, second_manual.text
    assert second_manual.json()["id"] != execution_id
    assert len(adapter.calls) == 2

    changed_replay = _observe(
        chain,
        key="o1",
        reason="Attempt to alter the completed successor observation request after completion.",
    )
    assert changed_replay.status_code == 409, changed_replay.text
    assert len(adapter.calls) == 2

    for forbidden_field in (
        "hostname", "effective_remote_path", "entry_relative_path",
        "remote_root_path", "reference_name", "reference_namespace",
        "storage_object_key", "stored_etag", "content", "credential",
    ):
        assert forbidden_field not in body

    receipts = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-successor-change-detections/{execution_id}/receipts"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "completed"]
    assert [row["remote_stat_performed"] for row in rows] == [False, True]

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceSftpSuccessorChangeDetection).count() == 2


def test_successor_observation_changed_missing_failures_and_tamper() -> None:
    changed_chain = _completed_phase_n("sftp-successor-observe-changed")
    baseline = _generation_2_baseline(changed_chain)
    changed_adapter = _StatAdapter(mode="changed", baseline=baseline)
    register_external_document_source_sftp_exact_file_metadata_adapter(changed_adapter)

    changed = _observe(changed_chain, key="chg")
    assert changed.status_code == 201, changed.text
    changed_body = changed.json()
    assert changed_body["result_status"] == "changed"
    assert "byte_size" in changed_body["changed_dimensions"]

    missing_chain = _completed_phase_n("sftp-successor-observe-missing")
    missing_baseline = _generation_2_baseline(missing_chain)
    missing_adapter = _StatAdapter(mode="missing", baseline=missing_baseline)
    register_external_document_source_sftp_exact_file_metadata_adapter(missing_adapter)

    missing = _observe(missing_chain, key="miss")
    assert missing.status_code == 201, missing.text
    assert missing.json()["result_status"] == "missing"
    assert missing.json()["observed_projection_hash"] is None

    failure_chain = _completed_phase_n("sftp-successor-observe-failure")
    failure_adapter = _StatAdapter(
        mode="permission",
        baseline=_generation_2_baseline(failure_chain),
    )
    register_external_document_source_sftp_exact_file_metadata_adapter(failure_adapter)
    failed = _observe(failure_chain, key="fail")
    assert failed.status_code == 409, failed.text
    assert "missing" not in failed.text.lower()

    with TestingSessionLocal() as db:
        advancement = db.get(
            ExternalDocumentSourceSftpCheckpointAdvancement,
            UUID(failure_chain["advancement_id"]),
        )
        original_state = advancement.successor_checkpoint_state_hash
        advancement.successor_checkpoint_state_hash = "0" * 64
        db.commit()

    calls_before = len(failure_adapter.calls)
    tampered_upstream = _observe(failure_chain, key="bad")
    assert tampered_upstream.status_code == 409, tampered_upstream.text
    assert len(failure_adapter.calls) == calls_before

    with TestingSessionLocal() as db:
        advancement = db.get(
            ExternalDocumentSourceSftpCheckpointAdvancement,
            UUID(failure_chain["advancement_id"]),
        )
        advancement.successor_checkpoint_state_hash = original_state
        db.commit()

    restored_adapter = _StatAdapter(
        mode="unchanged",
        baseline=_generation_2_baseline(failure_chain),
    )
    register_external_document_source_sftp_exact_file_metadata_adapter(restored_adapter)
    created = _observe(failure_chain, key="ok")
    assert created.status_code == 201, created.text
    execution_id = UUID(created.json()["id"])

    with TestingSessionLocal() as db:
        receipt = (
            db.query(ExternalDocumentSourceSftpSuccessorChangeDetectionReceipt)
            .filter(
                ExternalDocumentSourceSftpSuccessorChangeDetectionReceipt.execution_id
                == execution_id,
                ExternalDocumentSourceSftpSuccessorChangeDetectionReceipt.sequence_number
                == 1,
            )
            .one()
        )
        original_receipt_hash = receipt.receipt_hash
        receipt.receipt_hash = "0" * 64
        db.commit()

    tampered_receipt = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{failure_chain['profile_id']}/"
            f"sftp-successor-change-detections/{execution_id}"
        ),
        headers=_headers(failure_chain["requester_id"]),
    )
    assert tampered_receipt.status_code == 409, tampered_receipt.text

    with TestingSessionLocal() as db:
        receipt = (
            db.query(ExternalDocumentSourceSftpSuccessorChangeDetectionReceipt)
            .filter(
                ExternalDocumentSourceSftpSuccessorChangeDetectionReceipt.execution_id
                == execution_id,
                ExternalDocumentSourceSftpSuccessorChangeDetectionReceipt.sequence_number
                == 1,
            )
            .one()
        )
        receipt.receipt_hash = original_receipt_hash
        row = db.get(ExternalDocumentSourceSftpSuccessorChangeDetection, execution_id)
        original_projection = row.observed_projection_hash
        row.observed_projection_hash = "0" * 64
        db.commit()

    tampered_execution = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{failure_chain['profile_id']}/"
            f"sftp-successor-change-detections/{execution_id}"
        ),
        headers=_headers(failure_chain["requester_id"]),
    )
    assert tampered_execution.status_code == 409, tampered_execution.text

    with TestingSessionLocal() as db:
        row = db.get(ExternalDocumentSourceSftpSuccessorChangeDetection, execution_id)
        row.observed_projection_hash = original_projection
        db.commit()
