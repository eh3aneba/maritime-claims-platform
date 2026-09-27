from __future__ import annotations

import hashlib
import json
from uuid import UUID

import pytest

from app.modules.audit.models import AuditLog
from app.modules.documents.object_storage import ObjectStorageError
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.sftp_change_detection_service import (
    register_external_document_source_sftp_exact_file_metadata_adapter,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    register_external_document_source_sftp_file_content_read_adapter,
)
from app.modules.external_document_sources.sftp_generation3_restaging_models import (
    ExternalDocumentSourceSftpGeneration3Restaging,
    ExternalDocumentSourceSftpGeneration3RestagingReceipt,
)
from app.modules.external_document_sources.sftp_quarantine_staging_service import (
    register_external_document_source_sftp_quarantine_staging_store,
)
from app.modules.external_document_sources.sftp_successor_change_detection_models import (
    ExternalDocumentSourceSftpSuccessorChangeDetection,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_profiles import _headers, _seed_tenant
from tests.test_external_document_source_sftp_change_detection import _StatAdapter
from tests.test_external_document_source_sftp_file_content_proof import (
    _BODY_MARKER,
    _FileReadAdapter,
)
from tests.test_external_document_source_sftp_quarantine_staging import (
    _QuarantineStore,
    _STORAGE_SECRET,
    _STORAGE_URL,
)
from tests.test_external_document_source_sftp_successor_restaging import (
    _MetadataOnlyChangedAdapter,
)
from tests.test_external_document_source_sftp_successor_change_detection import (
    _completed_phase_n,
    _generation_2_baseline,
    _observe as _observe_successor,
    setup_function as _o_setup,
    teardown_function as _o_teardown,
)


_REASON = (
    "Re-read the exact Phase 17.6-O changed SFTP file and stage one immutable "
    "generation-3 candidate without advancing the checkpoint or admitting Evidence."
)


class _FailFirstPutStore(_QuarantineStore):
    def __init__(self):
        super().__init__()
        self._put_failed = False

    def put_bytes_if_absent(self, payload, *, storage_key, expected_sha256=None):
        if not self._put_failed:
            self._put_failed = True
            self.put_calls += 1
            raise ObjectStorageError("simulated pre-write recovery boundary")
        return super().put_bytes_if_absent(
            payload,
            storage_key=storage_key,
            expected_sha256=expected_sha256,
        )


def setup_function() -> None:
    _o_setup()


def teardown_function() -> None:
    _o_teardown()


def _changed_phase_o(seed: str):
    chain = _completed_phase_n(seed)
    baseline = _generation_2_baseline(chain)
    stat_adapter = _StatAdapter(mode="changed", baseline=baseline)
    register_external_document_source_sftp_exact_file_metadata_adapter(stat_adapter)
    response = _observe_successor(chain, key=f"{seed}-o-changed")
    assert response.status_code == 201, response.text
    assert response.json()["result_status"] == "changed"
    chain["successor_change_detection_id"] = response.json()["id"]
    chain["generation2_baseline"] = baseline
    chain["o_stat_adapter"] = stat_adapter
    chain["o_observed_size"] = response.json()["observed_byte_size"]
    return chain


def _restage3(
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
            f"sftp-successor-change-detections/{chain['successor_change_detection_id']}/"
            "generation-3-restaging-executions"
        ),
        headers=_headers(actor_id or chain["requester_id"]),
        json=payload,
    )


def test_generation3_restaging_rejects_caller_authority_tenant_and_non_changed() -> None:
    chain = _changed_phase_o("sftp-g3-boundary")
    store = _QuarantineStore()
    register_external_document_source_sftp_quarantine_staging_store(store)

    forbidden = _restage3(
        chain,
        key="deny",
        extra={
            "hostname": "caller.invalid",
            "remote_path": "/caller/path",
            "content": _BODY_MARKER,
            "storage_key": "caller/storage",
            "digest": "0" * 64,
            "generation": 99,
            "credential": "caller-secret",
        },
    )
    assert forbidden.status_code == 422, forbidden.text
    assert store.put_calls == 0

    _, other_requester, _, _ = _seed_tenant("sftp-g3-other")
    wrong_tenant = _restage3(chain, key="tenant", actor_id=other_requester)
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert store.put_calls == 0

    unchanged_chain = _completed_phase_n("sftp-g3-unchanged")
    baseline = _generation_2_baseline(unchanged_chain)
    register_external_document_source_sftp_exact_file_metadata_adapter(
        _StatAdapter(mode="unchanged", baseline=baseline)
    )
    observed = _observe_successor(unchanged_chain, key="unchanged")
    assert observed.status_code == 201, observed.text
    assert observed.json()["result_status"] == "unchanged"
    unchanged_chain["successor_change_detection_id"] = observed.json()["id"]
    register_external_document_source_sftp_quarantine_staging_store(store)

    rejected = _restage3(unchanged_chain, key="ineligible")
    assert rejected.status_code == 409, rejected.text
    assert "changed observation" in rejected.text
    assert store.put_calls == 0

    missing_chain = _completed_phase_n("sftp-g3-missing")
    missing_baseline = _generation_2_baseline(missing_chain)
    register_external_document_source_sftp_exact_file_metadata_adapter(
        _StatAdapter(mode="missing", baseline=missing_baseline)
    )
    missing_observed = _observe_successor(missing_chain, key="missing")
    assert missing_observed.status_code == 201, missing_observed.text
    assert missing_observed.json()["result_status"] == "missing"
    missing_chain["successor_change_detection_id"] = missing_observed.json()["id"]
    register_external_document_source_sftp_quarantine_staging_store(store)
    missing_rejected = _restage3(missing_chain, key="missing-ineligible")
    assert missing_rejected.status_code == 409, missing_rejected.text
    assert "changed observation" in missing_rejected.text
    assert store.put_calls == 0


def test_generation3_restaging_content_proof_is_durable_before_put_and_recovers_without_reread(
    caplog: pytest.LogCaptureFixture,
) -> None:
    chain = _changed_phase_o("sftp-g3-recovery")
    successor_body = b"g" * chain["o_observed_size"]
    assert len(successor_body) == chain["o_observed_size"]

    read_adapter = _FileReadAdapter(content=successor_body)
    register_external_document_source_sftp_file_content_read_adapter(read_adapter)
    store = _QuarantineStore(fail_first_head_after_put=True)
    register_external_document_source_sftp_quarantine_staging_store(store)

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()
        observation = db.get(
            ExternalDocumentSourceSftpSuccessorChangeDetection,
            UUID(chain["successor_change_detection_id"]),
        )
        assert observation is not None
        observation_completion = observation.completion_hash

    first = _restage3(chain, key="p3")
    assert first.status_code == 409, first.text
    assert "verification failed" in first.text
    assert len(read_adapter.calls) == 1
    assert store.put_calls == 1
    assert len(store.objects) == 1

    with TestingSessionLocal() as db:
        row = db.query(ExternalDocumentSourceSftpGeneration3Restaging).one()
        restaging_id = str(row.id)
        internal_key = row.storage_object_key
        expected_digest = hashlib.sha256(successor_body).hexdigest()
        assert row.status == "content_verified"
        assert row.result_status is None
        assert row.candidate_generation == 3
        assert row.content_sha256 == expected_digest
        assert row.content_byte_count == len(successor_body)
        assert row.content_proof_hash
        assert row.completion_hash is None
        receipts = (
            db.query(ExternalDocumentSourceSftpGeneration3RestagingReceipt)
            .order_by(ExternalDocumentSourceSftpGeneration3RestagingReceipt.sequence_number)
            .all()
        )
        assert [r.event_type for r in receipts] == ["requested", "content_verified"]
        assert store.objects[internal_key] == successor_body

    recovered = _restage3(chain, key="p3")
    assert recovered.status_code == 201, recovered.text
    body = recovered.json()
    assert body["id"] == restaging_id
    assert body["status"] == "completed"
    assert body["result_status"] == "generation3_staged_verified"
    assert body["candidate_generation"] == 3
    assert body["content_sha256"] == hashlib.sha256(successor_body).hexdigest()
    assert body["content_byte_count"] == len(successor_body)
    assert body["successor_content_proof_completed"] is True
    assert body["remote_read_performed"] is True
    assert body["storage_write_performed"] is True
    assert body["storage_read_performed"] is True
    assert body["storage_reconciliation_performed"] is True
    assert body["durable_content_staged"] is True
    assert body["generation3_restaging_completed"] is True
    assert body["checkpoint_created"] is False
    assert body["checkpoint_advanced"] is False
    assert body["document_created"] is False
    assert body["evidence_admitted"] is False
    assert body["processing_enqueued"] is False
    assert body["ai_executed"] is False
    assert body["claim_mutated"] is False

    # Recovery used the already-staged verified object: no second SFTP read/PUT.
    assert len(read_adapter.calls) == 1
    assert store.put_calls == 1

    replay = _restage3(chain, key="p3")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == restaging_id
    assert len(read_adapter.calls) == 1
    assert store.put_calls == 1

    second_consumption = _restage3(chain, key="p3-second")
    assert second_consumption.status_code == 409, second_consumption.text
    assert len(read_adapter.calls) == 1
    assert store.put_calls == 1

    changed_replay = _restage3(
        chain,
        key="p3",
        reason="Attempt to alter the immutable generation-3 restaging request.",
    )
    assert changed_replay.status_code == 409, changed_replay.text

    for forbidden_field in (
        "storage_object_key", "stored_etag", "destination_hostname",
        "remote_root_path", "effective_remote_path", "reference_name",
        "content", "file_body", "credential",
    ):
        assert forbidden_field not in body
    for marker in (_BODY_MARKER, _STORAGE_SECRET, _STORAGE_URL):
        assert marker not in recovered.text
        assert marker not in caplog.text

    receipts = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-generation-3-restaging-executions/{restaging_id}/receipts"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert receipts.status_code == 200, receipts.text
    receipt_rows = receipts.json()
    assert [r["event_type"] for r in receipt_rows] == [
        "requested", "content_verified", "completed"
    ]
    assert [r["storage_write_performed"] for r in receipt_rows] == [
        False, False, True
    ]

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        observation = db.get(
            ExternalDocumentSourceSftpSuccessorChangeDetection,
            UUID(chain["successor_change_detection_id"]),
        )
        assert observation.completion_hash == observation_completion

        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "external_document_source_sftp_generation3_restaging",
            AuditLog.entity_id == UUID(restaging_id),
        ).one()
        audit_payload = json.dumps(audit.new_values, sort_keys=True) + (audit.details or "")
        assert internal_key not in audit_payload
        assert _BODY_MARKER not in audit_payload
        assert _STORAGE_SECRET not in audit_payload
        assert _STORAGE_URL not in audit_payload

        row = db.get(ExternalDocumentSourceSftpGeneration3Restaging, UUID(restaging_id))
        original_proof = row.content_proof_hash
        row.content_proof_hash = "0" * 64
        db.commit()

    tampered = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-generation-3-restaging-executions/{restaging_id}"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert tampered.status_code == 409, tampered.text

    with TestingSessionLocal() as db:
        row = db.get(ExternalDocumentSourceSftpGeneration3Restaging, UUID(restaging_id))
        row.content_proof_hash = original_proof
        db.commit()


def test_generation3_restaging_absent_object_recovery_requires_committed_proof_match() -> None:
    chain = _changed_phase_o("sftp-g3-absent-recovery")
    successor_body = b"a" * chain["o_observed_size"]
    first_reader = _FileReadAdapter(content=successor_body)
    register_external_document_source_sftp_file_content_read_adapter(first_reader)
    store = _FailFirstPutStore()
    register_external_document_source_sftp_quarantine_staging_store(store)

    first = _restage3(chain, key="recover-absent")
    assert first.status_code == 409, first.text
    assert "storage write failed" in first.text
    assert len(first_reader.calls) == 1
    assert store.put_calls == 1
    assert store.objects == {}

    with TestingSessionLocal() as db:
        row = db.query(ExternalDocumentSourceSftpGeneration3Restaging).one()
        assert row.status == "content_verified"
        committed_proof = row.content_proof_hash
        assert committed_proof is not None

    changed_body = b"b" * chain["o_observed_size"]
    assert hashlib.sha256(changed_body).hexdigest() != hashlib.sha256(successor_body).hexdigest()
    changed_reader = _FileReadAdapter(content=changed_body)
    register_external_document_source_sftp_file_content_read_adapter(changed_reader)
    drifted = _restage3(chain, key="recover-absent")
    assert drifted.status_code == 409, drifted.text
    assert "no longer matches the committed content proof" in drifted.text
    assert len(changed_reader.calls) == 1
    assert store.put_calls == 1
    assert store.objects == {}

    matching_reader = _FileReadAdapter(content=successor_body)
    register_external_document_source_sftp_file_content_read_adapter(matching_reader)
    recovered = _restage3(chain, key="recover-absent")
    assert recovered.status_code == 201, recovered.text
    assert recovered.json()["status"] == "completed"
    assert recovered.json()["content_proof_hash"] == committed_proof
    assert len(matching_reader.calls) == 1
    assert store.put_calls == 2
    assert len(store.objects) == 1


def test_generation3_restaging_upstream_tamper_fails_before_reread() -> None:
    chain = _changed_phase_o("sftp-g3-upstream-tamper")
    read_adapter = _FileReadAdapter(content=b"t" * chain["o_observed_size"])
    register_external_document_source_sftp_file_content_read_adapter(read_adapter)
    store = _QuarantineStore()
    register_external_document_source_sftp_quarantine_staging_store(store)

    with TestingSessionLocal() as db:
        observation = db.get(
            ExternalDocumentSourceSftpSuccessorChangeDetection,
            UUID(chain["successor_change_detection_id"]),
        )
        assert observation is not None
        original_completion = observation.completion_hash
        observation.completion_hash = "0" * 64
        db.commit()

    response = _restage3(chain, key="tampered")
    assert response.status_code == 409, response.text
    assert read_adapter.calls == []
    assert store.put_calls == 0

    with TestingSessionLocal() as db:
        observation = db.get(
            ExternalDocumentSourceSftpSuccessorChangeDetection,
            UUID(chain["successor_change_detection_id"]),
        )
        observation.completion_hash = original_completion
        db.commit()


def test_generation3_restaging_same_generation2_digest_fails_closed() -> None:
    chain = _completed_phase_n("sftp-g3-same-digest")
    baseline = _generation_2_baseline(chain)
    register_external_document_source_sftp_exact_file_metadata_adapter(
        _MetadataOnlyChangedAdapter(baseline)
    )
    observed = _observe_successor(chain, key="metadata-only-change")
    assert observed.status_code == 201, observed.text
    assert observed.json()["result_status"] == "changed"
    assert observed.json()["observed_byte_size"] == baseline["byte_size"]
    chain["successor_change_detection_id"] = observed.json()["id"]

    predecessor_body = chain["successor_body"]
    assert len(predecessor_body) == observed.json()["observed_byte_size"]
    read_adapter = _FileReadAdapter(content=predecessor_body)
    register_external_document_source_sftp_file_content_read_adapter(read_adapter)
    store = _QuarantineStore()
    register_external_document_source_sftp_quarantine_staging_store(store)

    response = _restage3(chain, key="same")
    assert response.status_code == 409, response.text
    assert "no generation-3 content version exists" in response.text
    assert len(read_adapter.calls) == 1
    assert store.put_calls == 0
