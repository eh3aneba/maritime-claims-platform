from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import pytest

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.sftp_change_detection_service import (
    SftpExactFileMetadataResult,
    register_external_document_source_sftp_exact_file_metadata_adapter,
)
from app.modules.external_document_sources.sftp_checkpoint_models import (
    ExternalDocumentSourceSftpCheckpoint,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    register_external_document_source_sftp_file_content_read_adapter,
)
from app.modules.external_document_sources.sftp_quarantine_staging_service import (
    register_external_document_source_sftp_quarantine_staging_store,
)
from app.modules.external_document_sources.sftp_successor_restaging_models import (
    ExternalDocumentSourceSftpSuccessorRestaging,
    ExternalDocumentSourceSftpSuccessorRestagingReceipt,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_profiles import _headers, _seed_tenant
from tests.test_external_document_source_sftp_change_detection import (
    _StatAdapter,
    _baseline,
    _completed_phase_k,
    _observe,
    setup_function as _l_setup,
    teardown_function as _l_teardown,
)
from tests.test_external_document_source_sftp_file_content_proof import (
    _BODY_MARKER,
    _FILE_BODY,
    _FileReadAdapter,
)
from tests.test_external_document_source_sftp_quarantine_staging import (
    _QuarantineStore,
    _STORAGE_SECRET,
    _STORAGE_URL,
)


_REASON = (
    "Re-read only the exact Phase 17.6-L changed SFTP file and stage one "
    "immutable candidate successor generation without advancing the checkpoint."
)


def setup_function() -> None:
    _l_setup()


def teardown_function() -> None:
    _l_teardown()


def _changed_phase_l(seed: str):
    chain = _completed_phase_k(seed)
    baseline = _baseline(chain)
    stat_adapter = _StatAdapter(mode="changed", baseline=baseline)
    register_external_document_source_sftp_exact_file_metadata_adapter(
        stat_adapter
    )
    response = _observe(chain, key=f"{seed}-changed")
    assert response.status_code == 201, response.text
    assert response.json()["result_status"] == "changed"
    chain["change_detection_id"] = response.json()["id"]
    chain["baseline"] = baseline
    chain["stat_adapter"] = stat_adapter
    return chain


def _restage(
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
            f"sftp-change-detections/{chain['change_detection_id']}/"
            "successor-restaging-executions"
        ),
        headers=_headers(actor_id or chain["requester_id"]),
        json=payload,
    )


def test_sftp_successor_restaging_rejects_caller_authority_and_non_changed_observations() -> None:
    chain = _changed_phase_l("sftp-successor-boundary")
    store = _QuarantineStore()
    register_external_document_source_sftp_quarantine_staging_store(store)

    forbidden = _restage(
        chain,
        key="forbidden",
        extra={
            "remote_path": "/caller/path",
            "content": _BODY_MARKER,
            "storage_key": "caller/storage",
            "digest": "0" * 64,
            "generation": 99,
            "checkpoint_id": chain["checkpoint_id"],
        },
    )
    assert forbidden.status_code == 422, forbidden.text
    assert store.put_calls == 0

    _, other_requester, _, _ = _seed_tenant("sftp-successor-other")
    wrong_tenant = _restage(
        chain,
        key="wrongtenant",
        actor_id=other_requester,
    )
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert store.put_calls == 0

    unchanged_chain = _completed_phase_k("sftp-successor-unchanged")
    baseline = _baseline(unchanged_chain)
    register_external_document_source_sftp_exact_file_metadata_adapter(
        _StatAdapter(mode="unchanged", baseline=baseline)
    )
    observed = _observe(unchanged_chain, key="unchanged")
    assert observed.status_code == 201, observed.text
    unchanged_chain["change_detection_id"] = observed.json()["id"]
    rejected = _restage(unchanged_chain, key="ineligible")
    assert rejected.status_code == 409, rejected.text
    assert "changed-file observations" in rejected.text
    assert store.put_calls == 0


class _MetadataOnlyChangedAdapter:
    adapter_kind = "deterministic_sftp_exact_file_metadata"

    def __init__(self, baseline: dict):
        self.baseline = baseline
        self.calls = []

    def stat_metadata(self, request):
        self.calls.append(request)
        modified = self.baseline["modified_at"]
        if modified is None:
            modified = __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            )
        else:
            modified = modified + timedelta(seconds=1)
        return SftpExactFileMetadataResult(
            found=True,
            entry_kind="file",
            byte_size=self.baseline["byte_size"],
            modified_at=modified,
            metadata_id_hash=self.baseline["metadata_id_hash"],
            authentication_method=(
                "password"
                if request.authentication_kind == "password"
                else "public_key"
            ),
            latency_class="fast",
            secret_resolution_performed=True,
            provider_network_performed=True,
            ssh_transport_performed=True,
            host_key_verification_performed=True,
            host_key_verified=True,
            authentication_performed=True,
            authentication_succeeded=True,
            sftp_session_opened=True,
            remote_stat_performed=True,
            sftp_session_closed=True,
        )


def test_sftp_successor_restaging_same_digest_fails_closed_as_no_new_version() -> None:
    chain = _completed_phase_k("sftp-successor-same-digest")
    baseline = _baseline(chain)
    register_external_document_source_sftp_exact_file_metadata_adapter(
        _MetadataOnlyChangedAdapter(baseline)
    )
    observed = _observe(chain, key="metadata-changed")
    assert observed.status_code == 201, observed.text
    assert observed.json()["result_status"] == "changed"
    chain["change_detection_id"] = observed.json()["id"]

    read_adapter = _FileReadAdapter(content=_FILE_BODY)
    register_external_document_source_sftp_file_content_read_adapter(
        read_adapter
    )
    store = _QuarantineStore()
    register_external_document_source_sftp_quarantine_staging_store(store)

    response = _restage(chain, key="same-digest")
    assert response.status_code == 409, response.text
    assert "no successor content version exists" in response.text
    assert len(read_adapter.calls) == 1
    assert store.put_calls == 0

    with TestingSessionLocal() as db:
        row = db.query(ExternalDocumentSourceSftpSuccessorRestaging).one()
        assert row.status == "requested"
        assert row.successor_content_sha256 is None
        assert row.checkpoint_advanced is False
        assert db.query(
            ExternalDocumentSourceSftpSuccessorRestagingReceipt
        ).count() == 1


def test_sftp_successor_restaging_crash_recovery_is_versioned_and_does_not_advance_checkpoint(
    caplog: pytest.LogCaptureFixture,
) -> None:
    chain = _changed_phase_l("sftp-successor-recovery")
    successor_body = b"n" * chain["baseline"]["byte_size"] + b"x"
    assert len(successor_body) == chain["baseline"]["byte_size"] + 1

    read_adapter = _FileReadAdapter(content=successor_body)
    register_external_document_source_sftp_file_content_read_adapter(
        read_adapter
    )
    store = _QuarantineStore(fail_first_head_after_put=True)
    register_external_document_source_sftp_quarantine_staging_store(store)

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()
        checkpoint = db.get(
            ExternalDocumentSourceSftpCheckpoint,
            UUID(chain["checkpoint_id"]),
        )
        original_checkpoint_hash = checkpoint.content_sha256
        original_checkpoint_completion = checkpoint.completion_hash

    first = _restage(chain, key="successor")
    assert first.status_code == 409, first.text
    assert "verification failed" in first.text
    assert len(read_adapter.calls) == 1
    assert store.put_calls == 1
    assert len(store.objects) == 1

    with TestingSessionLocal() as db:
        row = db.query(ExternalDocumentSourceSftpSuccessorRestaging).one()
        restaging_id = str(row.id)
        internal_key = row.storage_object_key
        assert row.status == "requested"
        assert row.successor_content_sha256 is None
        assert row.completion_hash is None
        assert row.checkpoint_advanced is False
        assert store.objects[internal_key] == successor_body

    recovered = _restage(chain, key="successor")
    assert recovered.status_code == 201, recovered.text
    body = recovered.json()
    expected_digest = hashlib.sha256(successor_body).hexdigest()
    assert body["id"] == restaging_id
    assert body["status"] == "completed"
    assert body["result_status"] == "successor_staged_verified"
    assert body["successor_generation"] == 2
    assert body["successor_content_sha256"] == expected_digest
    assert body["successor_content_byte_count"] == len(successor_body)
    assert body["successor_content_proof_hash"]
    assert len(body["successor_content_proof_hash"]) == 64
    assert body["successor_content_proof_completed"] is True
    assert body["remote_read_performed"] is True
    assert body["storage_write_performed"] is True
    assert body["storage_read_performed"] is True
    assert body["storage_reconciliation_performed"] is True
    assert body["durable_content_staged"] is True
    assert body["checkpoint_advanced"] is False
    assert body["storage_delete_performed"] is False
    assert body["storage_copy_performed"] is False
    assert body["document_created"] is False
    assert body["evidence_admitted"] is False
    assert body["processing_enqueued"] is False
    assert body["ai_executed"] is False
    assert body["claim_mutated"] is False

    assert len(read_adapter.calls) == 1
    assert store.put_calls == 1
    assert len(store.objects) == 1

    replay = _restage(chain, key="successor")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == restaging_id
    assert len(read_adapter.calls) == 1
    assert store.put_calls == 1

    for forbidden_field in (
        "storage_object_key",
        "stored_etag",
        "effective_remote_path",
        "remote_root_path",
        "content",
        "file_body",
        "access_token",
        "client_secret",
    ):
        assert forbidden_field not in body
    for marker in (_BODY_MARKER, _STORAGE_SECRET, _STORAGE_URL):
        assert marker not in recovered.text
        assert marker not in caplog.text

    receipts = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-successor-restaging-executions/{restaging_id}/receipts"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert receipts.status_code == 200, receipts.text
    receipt_rows = receipts.json()
    assert [row["event_type"] for row in receipt_rows] == [
        "requested",
        "completed",
    ]
    assert [row["storage_write_performed"] for row in receipt_rows] == [
        False,
        True,
    ]
    assert [row["storage_read_performed"] for row in receipt_rows] == [
        False,
        True,
    ]

    with TestingSessionLocal() as db:
        checkpoint = db.get(
            ExternalDocumentSourceSftpCheckpoint,
            UUID(chain["checkpoint_id"]),
        )
        assert checkpoint.content_sha256 == original_checkpoint_hash
        assert checkpoint.completion_hash == original_checkpoint_completion
        assert checkpoint.checkpoint_generation == 1
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before

        row = db.get(
            ExternalDocumentSourceSftpSuccessorRestaging,
            UUID(restaging_id),
        )
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type
            == "external_document_source_sftp_successor_restaging",
            AuditLog.entity_id == UUID(restaging_id),
        ).one()
        audit_payload = (
            json.dumps(audit.new_values, sort_keys=True)
            + (audit.details or "")
        )
        assert internal_key not in audit_payload
        assert _BODY_MARKER not in audit_payload
        assert _STORAGE_SECRET not in audit_payload
        assert _STORAGE_URL not in audit_payload

        original_hash = row.storage_object_key_hash
        row.storage_object_key_hash = "0" * 64
        db.commit()

    tampered = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-successor-restaging-executions/{restaging_id}"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert tampered.status_code == 409, tampered.text

    with TestingSessionLocal() as db:
        row = db.get(
            ExternalDocumentSourceSftpSuccessorRestaging,
            UUID(restaging_id),
        )
        row.storage_object_key_hash = original_hash
        db.commit()
