import json
from uuid import UUID

import pytest

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.sftp_checkpoint_models import (
    ExternalDocumentSourceSftpCheckpoint,
    ExternalDocumentSourceSftpCheckpointReceipt,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    SftpFileContentReadResult,
    register_external_document_source_sftp_file_content_read_adapter,
)
from app.modules.external_document_sources.sftp_quarantine_staging_service import (
    register_external_document_source_sftp_quarantine_staging_store,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_profiles import _headers, _seed_tenant
from tests.test_external_document_source_sftp_quarantine_staging import (
    _BODY_MARKER,
    _QuarantineStore,
    _STORAGE_SECRET,
    _STORAGE_URL,
    _completed_phase_i,
    _stage,
    setup_function as _j_setup,
    teardown_function as _j_teardown,
)


_REASON = (
    "Record one immutable generation-one checkpoint from exact completed "
    "Phase 17.6-J quarantine custody without any new SFTP or storage I/O."
)


class _BombReadAdapter:
    adapter_kind = "deterministic_sftp_file_content_read"

    def __init__(self):
        self.calls = 0

    def read_content(self, request):
        self.calls += 1
        raise AssertionError("Phase 17.6-K must not invoke the SFTP read adapter")


class _BombStore:
    class _Health:
        backend = "s3-compatible-foundation"

    def __init__(self):
        self.put_calls = 0
        self.head_calls = 0
        self.get_calls = 0

    @property
    def sanitized_health_identity(self):
        return self._Health()

    def put_bytes_if_absent(self, payload, *, storage_key, expected_sha256=None):
        self.put_calls += 1
        raise AssertionError("Phase 17.6-K must not write object storage")

    def head_object(self, *, storage_key):
        self.head_calls += 1
        raise AssertionError("Phase 17.6-K must not HEAD object storage")

    def get_bytes(self, *, storage_key, expected_sha256=None):
        self.get_calls += 1
        raise AssertionError("Phase 17.6-K must not GET object storage")


def setup_function() -> None:
    _j_setup()


def teardown_function() -> None:
    _j_teardown()


def _completed_phase_j(seed: str):
    chain = _completed_phase_i(seed)
    store = _QuarantineStore()
    register_external_document_source_sftp_quarantine_staging_store(store)
    response = _stage(chain, key="stage")
    assert response.status_code == 201, response.text
    assert response.json()["result_status"] == "staged_verified"
    chain["staging_id"] = response.json()["id"]
    chain["stage_store"] = store
    return chain


def _checkpoint(
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
            f"sftp-quarantine-staging-executions/{chain['staging_id']}/checkpoints"
        ),
        headers=_headers(actor_id or chain["requester_id"]),
        json=payload,
    )


def test_sftp_checkpoint_is_control_plane_only_replay_safe_and_tenant_scoped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    chain = _completed_phase_j("sftp-checkpoint-main")

    bomb_read = _BombReadAdapter()
    bomb_store = _BombStore()
    register_external_document_source_sftp_file_content_read_adapter(bomb_read)
    register_external_document_source_sftp_quarantine_staging_store(bomb_store)

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    forbidden = _checkpoint(
        chain,
        key="forbidden",
        extra={
            "remote_path": "/forbidden",
            "content": _BODY_MARKER,
            "storage_key": "caller/path",
            "etag": "caller-etag",
            "cursor": "caller-cursor",
            "version": "caller-version",
        },
    )
    assert forbidden.status_code == 422, forbidden.text
    assert bomb_read.calls == 0
    assert bomb_store.put_calls == 0
    assert bomb_store.head_calls == 0
    assert bomb_store.get_calls == 0

    _, other_requester, _, _ = _seed_tenant("sftp-checkpoint-other")
    wrong_tenant = _checkpoint(
        chain,
        key="wrongtenant",
        actor_id=other_requester,
    )
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert bomb_read.calls == 0
    assert bomb_store.put_calls == 0
    assert bomb_store.head_calls == 0
    assert bomb_store.get_calls == 0

    response = _checkpoint(chain, key="checkpoint")
    assert response.status_code == 201, response.text
    body = response.json()
    checkpoint_id = body["id"]

    assert body["status"] == "completed"
    assert body["result_status"] == "checkpoint_recorded"
    assert body["checkpoint_kind"] == "initial_sftp_quarantine_snapshot_v1"
    assert body["checkpoint_generation"] == 1
    assert body["checkpoint_created"] is True
    assert body["provider_network_performed"] is False
    assert body["remote_read_performed"] is False
    assert body["remote_list_performed"] is False
    assert body["storage_read_performed"] is False
    assert body["storage_write_performed"] is False
    assert body["storage_delete_performed"] is False
    assert body["storage_copy_performed"] is False
    assert body["document_created"] is False
    assert body["evidence_admitted"] is False
    assert body["processing_enqueued"] is False
    assert body["ai_executed"] is False
    assert body["claim_mutated"] is False

    assert bomb_read.calls == 0
    assert bomb_store.put_calls == 0
    assert bomb_store.head_calls == 0
    assert bomb_store.get_calls == 0

    for forbidden_field in (
        "storage_object_key",
        "stored_etag",
        "endpoint_origin",
        "bucket",
        "content",
        "file_body",
        "password",
        "private_key",
        "passphrase",
    ):
        assert forbidden_field not in body
    for marker in (_BODY_MARKER, _STORAGE_SECRET, _STORAGE_URL):
        assert marker not in response.text
        assert marker not in caplog.text

    receipts = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-checkpoints/{checkpoint_id}/receipts"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "completed"]
    assert [row["checkpoint_created"] for row in rows] == [False, True]
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]
    assert bomb_read.calls == 0
    assert bomb_store.head_calls == 0
    assert bomb_store.get_calls == 0

    replay = _checkpoint(chain, key="checkpoint")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == checkpoint_id
    assert bomb_read.calls == 0
    assert bomb_store.put_calls == 0
    assert bomb_store.head_calls == 0
    assert bomb_store.get_calls == 0

    changed = _checkpoint(
        chain,
        key="checkpoint",
        reason=(
            "Attempt to alter the immutable Phase 17.6-K checkpoint request "
            "after the exact checkpoint was already recorded."
        ),
    )
    assert changed.status_code == 409, changed.text

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        row = db.get(ExternalDocumentSourceSftpCheckpoint, UUID(checkpoint_id))
        assert row is not None
        assert db.query(ExternalDocumentSourceSftpCheckpoint).count() == 1
        assert db.query(ExternalDocumentSourceSftpCheckpointReceipt).count() == 2
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "external_document_source_sftp_checkpoint",
            AuditLog.entity_id == UUID(checkpoint_id),
        ).one()
        audit_payload = json.dumps(audit.new_values, sort_keys=True) + (audit.details or "")
        assert row.storage_object_key_hash in audit_payload
        for marker in (_BODY_MARKER, _STORAGE_SECRET, _STORAGE_URL):
            assert marker not in audit_payload

        original = row.checkpoint_state_hash
        row.checkpoint_state_hash = "0" * 64
        db.commit()

    tampered = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-checkpoints/{checkpoint_id}"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert tampered.status_code == 409, tampered.text

    with TestingSessionLocal() as db:
        row = db.get(ExternalDocumentSourceSftpCheckpoint, UUID(checkpoint_id))
        row.checkpoint_state_hash = original
        db.commit()


def test_sftp_checkpoint_rejects_tampered_or_incomplete_phase_j_lineage() -> None:
    chain = _completed_phase_j("sftp-checkpoint-lineage")
    with TestingSessionLocal() as db:
        from app.modules.external_document_sources.sftp_quarantine_staging_models import (
            ExternalDocumentSourceSftpQuarantineStaging,
        )

        staging = db.get(
            ExternalDocumentSourceSftpQuarantineStaging,
            UUID(chain["staging_id"]),
        )
        staging.storage_object_key_hash = "0" * 64
        db.commit()

    response = _checkpoint(chain, key="lineage")
    assert response.status_code == 409, response.text
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceSftpCheckpoint).count() == 0
