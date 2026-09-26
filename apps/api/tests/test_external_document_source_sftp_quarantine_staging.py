import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

import pytest

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.documents.object_storage import (
    ObjectMetadata,
    ObjectStorageError,
    ObjectStorageIntegrityError,
    ObjectStorageNotFound,
    ObjectStoragePreconditionFailed,
    StoredObject,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    register_external_document_source_sftp_file_content_read_adapter,
)
from app.modules.external_document_sources.sftp_quarantine_staging_models import (
    ExternalDocumentSourceSftpQuarantineStaging,
    ExternalDocumentSourceSftpQuarantineStagingReceipt,
)
from app.modules.external_document_sources.sftp_quarantine_staging_service import (
    clear_external_document_source_sftp_quarantine_staging_store,
    register_external_document_source_sftp_quarantine_staging_store,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_profiles import _headers, _seed_tenant
from tests.test_external_document_source_sftp_file_content_proof import (
    _BODY_MARKER,
    _FILE_BODY,
    _FileReadAdapter,
    _listed_chain,
    _proof,
    setup_function as _i_setup,
    teardown_function as _i_teardown,
)


_STAGE_REASON = (
    "Re-read the exact Phase 17.6-I SFTP file and stage only a digest-matching "
    "copy into governed quarantine custody without Document or Evidence authority."
)
_STORAGE_SECRET = "phase-j-object-store-secret-must-never-persist"
_STORAGE_URL = "https://storage.example.test/phase-j-internal-only"


@dataclass(frozen=True)
class _Health:
    backend: str = "s3-compatible-foundation"
    endpoint_origin: str = "https://storage.example.test"
    bucket_fingerprint: str = "0123456789abcdef"
    region: str = "us-east-1"


class _QuarantineStore:
    def __init__(
        self,
        *,
        fail_first_head_after_put: bool = False,
    ):
        self.objects: dict[str, bytes] = {}
        self.put_calls = 0
        self.head_calls = 0
        self.get_calls = 0
        self.fail_first_head_after_put = fail_first_head_after_put
        self._head_failed = False

    @property
    def sanitized_health_identity(self):
        secret = _STORAGE_SECRET
        url = _STORAGE_URL
        assert secret and url
        return _Health()

    def put_bytes_if_absent(
        self,
        payload: bytes,
        *,
        storage_key: str,
        expected_sha256: str | None = None,
    ):
        self.put_calls += 1
        digest = hashlib.sha256(payload).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise ObjectStorageIntegrityError("hash mismatch")
        if storage_key in self.objects:
            raise ObjectStoragePreconditionFailed("exists")
        self.objects[storage_key] = bytes(payload)
        return StoredObject(
            storage_key=storage_key,
            file_size_bytes=len(payload),
            file_hash=digest,
            etag="phase-j-etag",
        )

    def head_object(self, *, storage_key: str):
        self.head_calls += 1
        if (
            self.fail_first_head_after_put
            and self.objects
            and not self._head_failed
        ):
            self._head_failed = True
            raise ObjectStorageError(
                "simulated bounded storage verification failure"
            )
        payload = self.objects.get(storage_key)
        if payload is None:
            raise ObjectStorageNotFound("missing")
        return ObjectMetadata(
            storage_key=storage_key,
            file_size_bytes=len(payload),
            file_hash=hashlib.sha256(payload).hexdigest(),
            etag="phase-j-etag",
        )

    def get_bytes(
        self,
        *,
        storage_key: str,
        expected_sha256: str | None = None,
    ):
        self.get_calls += 1
        payload = self.objects.get(storage_key)
        if payload is None:
            raise ObjectStorageNotFound("missing")
        digest = hashlib.sha256(payload).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise ObjectStorageIntegrityError("hash mismatch")
        return bytes(payload)


def setup_function() -> None:
    _i_setup()
    clear_external_document_source_sftp_quarantine_staging_store()


def teardown_function() -> None:
    clear_external_document_source_sftp_quarantine_staging_store()
    _i_teardown()


def _completed_phase_i(seed: str):
    chain = _listed_chain(seed)
    adapter = _FileReadAdapter()
    register_external_document_source_sftp_file_content_read_adapter(adapter)
    response = _proof(
        chain,
        key=f"{seed}-proof",
    )
    assert response.status_code == 201, response.text
    assert response.json()["result_status"] == "read_verified"
    chain["proof_id"] = response.json()["id"]
    chain["read_adapter"] = adapter
    return chain


def _stage(
    chain: dict,
    *,
    key: str,
    reason: str = _STAGE_REASON,
    actor_id=None,
    extra: dict | None = None,
):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-file-content-proofs/{chain['proof_id']}/"
            "quarantine-staging-executions"
        ),
        headers=_headers(actor_id or chain["requester_id"]),
        json=payload,
    )


def test_sftp_quarantine_staging_fails_closed_without_store_and_rejects_caller_authority() -> None:
    chain = _completed_phase_i("sftp-qstage-boundary")

    missing = _stage(chain, key="qstage-missing-store")
    assert missing.status_code == 409, missing.text
    assert "S3 foundation" in missing.text
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceSftpQuarantineStaging).count() == 0

    store = _QuarantineStore()
    register_external_document_source_sftp_quarantine_staging_store(store)

    forbidden = _stage(
        chain,
        key="qstage-forbidden",
        extra={
            "remote_path": "/escape",
            "content": _BODY_MARKER,
            "range": "bytes=0-10",
            "storage_key": "caller/path",
            "access_token": "forbidden",
            "url": _STORAGE_URL,
        },
    )
    assert forbidden.status_code == 422, forbidden.text
    assert store.put_calls == 0

    _, other_requester, _, _ = _seed_tenant("sftp-qstage-other-tenant")
    wrong_tenant = _stage(
        chain,
        key="qstage-wrong-tenant",
        actor_id=other_requester,
    )
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert store.put_calls == 0


def test_sftp_quarantine_staging_digest_mismatch_leaves_only_recovery_anchor() -> None:
    chain = _completed_phase_i("sftp-qstage-mismatch")
    store = _QuarantineStore()
    register_external_document_source_sftp_quarantine_staging_store(store)

    mismatched_adapter = _FileReadAdapter(
        content=b"y" * len(_FILE_BODY)
    )
    register_external_document_source_sftp_file_content_read_adapter(
        mismatched_adapter
    )

    response = _stage(chain, key="mismatch")
    assert response.status_code == 409, response.text
    assert "does not match the Phase 17.6-I content proof" in response.text
    assert len(mismatched_adapter.calls) == 1
    assert store.put_calls == 0
    assert store.objects == {}

    with TestingSessionLocal() as db:
        row = db.query(ExternalDocumentSourceSftpQuarantineStaging).one()
        assert row.status == "requested"
        assert row.result_status is None
        assert row.completion_hash is None
        assert row.remote_read_performed is False
        assert row.durable_content_staged is False
        assert db.query(
            ExternalDocumentSourceSftpQuarantineStagingReceipt
        ).count() == 1

    changed = _stage(
        chain,
        key="mismatch",
        reason=(
            "Attempt to alter the already anchored Phase 17.6-J request "
            "after a digest mismatch."
        ),
    )
    assert changed.status_code == 409, changed.text
    assert len(mismatched_adapter.calls) == 1


def test_sftp_quarantine_staging_crash_recovery_reconciles_same_object_without_second_reread(
    caplog: pytest.LogCaptureFixture,
) -> None:
    chain = _completed_phase_i("sftp-qstage-recovery")
    read_adapter = chain["read_adapter"]
    before_j_calls = len(read_adapter.calls)

    store = _QuarantineStore(fail_first_head_after_put=True)
    register_external_document_source_sftp_quarantine_staging_store(store)

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    first = _stage(chain, key="qstage-001")
    assert first.status_code == 409, first.text
    assert (
        first.json()["detail"]
        == "Governed SFTP quarantine storage verification failed"
    )
    assert store.put_calls == 1
    assert len(store.objects) == 1
    assert len(read_adapter.calls) == before_j_calls + 1

    with TestingSessionLocal() as db:
        row = db.query(ExternalDocumentSourceSftpQuarantineStaging).one()
        staging_id = str(row.id)
        internal_key = row.storage_object_key
        assert row.status == "requested"
        assert row.completion_hash is None
        assert db.query(
            ExternalDocumentSourceSftpQuarantineStagingReceipt
        ).count() == 1
        assert store.objects[internal_key] == _FILE_BODY

    recovered = _stage(chain, key="qstage-001")
    assert recovered.status_code == 201, recovered.text
    body = recovered.json()
    assert body["id"] == staging_id
    assert body["status"] == "completed"
    assert body["result_status"] == "staged_verified"
    assert body["expected_content_sha256"] == hashlib.sha256(
        _FILE_BODY
    ).hexdigest()
    assert body["expected_content_byte_count"] == len(_FILE_BODY)
    assert body["remote_read_performed"] is True
    assert body["storage_reconciliation_performed"] is True
    assert body["durable_content_staged"] is True
    assert body["remote_content_stored"] is True
    assert body["storage_delete_performed"] is False
    assert body["storage_copy_performed"] is False
    assert body["checkpoint_created"] is False
    assert body["document_created"] is False
    assert body["evidence_admitted"] is False
    assert body["processing_enqueued"] is False
    assert body["ai_executed"] is False
    assert body["claim_mutated"] is False

    assert store.put_calls == 1
    assert len(store.objects) == 1
    assert len(read_adapter.calls) == before_j_calls + 1
    assert store.objects[internal_key] == _FILE_BODY

    for forbidden_field in (
        "storage_object_key",
        "stored_etag",
        "endpoint_origin",
        "bucket",
        "url",
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
            f"sftp-quarantine-staging-executions/{staging_id}/receipts"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert receipts.status_code == 200, receipts.text
    receipt_rows = receipts.json()
    assert [row["event_type"] for row in receipt_rows] == [
        "requested",
        "completed",
    ]
    assert [
        row["durable_content_staged"] for row in receipt_rows
    ] == [False, True]
    assert (
        receipt_rows[1]["prior_receipt_hash"]
        == receipt_rows[0]["receipt_hash"]
    )

    replay = _stage(chain, key="qstage-001")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == staging_id
    assert store.put_calls == 1
    assert len(read_adapter.calls) == before_j_calls + 1

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        row = db.get(
            ExternalDocumentSourceSftpQuarantineStaging,
            UUID(staging_id),
        )
        assert row is not None
        persisted = [
            str(getattr(row, column.name))
            for column in row.__table__.columns
        ]
        receipts_db = db.query(
            ExternalDocumentSourceSftpQuarantineStagingReceipt
        ).filter(
            ExternalDocumentSourceSftpQuarantineStagingReceipt.staging_id
            == UUID(staging_id)
        ).all()
        for receipt in receipts_db:
            persisted.extend(
                str(getattr(receipt, column.name))
                for column in receipt.__table__.columns
            )
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type
            == "external_document_source_sftp_quarantine_staging",
            AuditLog.entity_id == UUID(staging_id),
        ).one()
        audit_payload = (
            json.dumps(audit.new_values, sort_keys=True)
            + (audit.details or "")
        )
        durable_metadata = "\n".join(persisted) + audit_payload

        assert _BODY_MARKER not in durable_metadata
        assert _STORAGE_SECRET not in durable_metadata
        assert _STORAGE_URL not in durable_metadata
        assert internal_key not in audit_payload

        original_key_hash = row.storage_object_key_hash
        row.storage_object_key_hash = "0" * 64
        db.commit()

    tampered = client.get(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-quarantine-staging-executions/{staging_id}"
        ),
        headers=_headers(chain["requester_id"]),
    )
    assert tampered.status_code == 409, tampered.text
    assert "lineage drifted" in tampered.text or "integrity" in tampered.text

    with TestingSessionLocal() as db:
        row = db.get(
            ExternalDocumentSourceSftpQuarantineStaging,
            UUID(staging_id),
        )
        row.storage_object_key_hash = original_key_hash
        db.commit()
