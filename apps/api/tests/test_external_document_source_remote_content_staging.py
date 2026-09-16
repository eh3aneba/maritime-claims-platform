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
from app.modules.external_document_sources.credential_reference_health_service import clear_external_document_source_credential_reference_health_resolvers
from app.modules.external_document_sources.credential_resolution_execution_service import clear_external_document_source_credential_resolution_resolvers
from app.modules.external_document_sources.discovery_service import clear_external_document_source_discovery_adapters
from app.modules.external_document_sources.provider_client_health_service import clear_external_document_source_provider_client_health_adapters
from app.modules.external_document_sources.remote_content_staging_models import (
    ExternalDocumentSourceRemoteContentStagingExecution,
    ExternalDocumentSourceRemoteContentStagingReceipt,
)
from app.modules.external_document_sources.remote_content_staging_service import (
    clear_external_document_source_remote_content_staging_store,
    register_external_document_source_remote_content_staging_store,
)
from app.modules.external_document_sources.remote_file_content_read_service import (
    clear_external_document_source_remote_file_content_read_adapters,
    register_external_document_source_remote_file_content_read_adapter,
)
from app.modules.external_document_sources.remote_metadata_listing_service import clear_external_document_source_remote_metadata_list_adapters
from app.modules.external_document_sources.token_acquisition_execution_service import clear_external_document_source_token_acquirers
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_external_document_source_discovery import _headers, _seed_tenant
from tests.test_external_document_source_remote_file_content_read import (
    _FILE_BODY,
    _FILE_BODY_MARKER,
    _ReadAdapter,
    _completed_phase_l,
    _read_content,
)

_STAGE_REASON = "Stage the exact Phase M remote body into governed durable quarantine custody without Document or Evidence authority."
_STORAGE_SECRET = "phase-n-object-store-secret-marker"
_PROVIDER_URL = "https://example.test/phase-n-provider-download-marker"


@dataclass(frozen=True)
class _Health:
    backend: str = "s3-compatible-foundation"
    endpoint_origin: str = "https://storage.example.test"
    bucket_fingerprint: str = "0123456789abcdef"
    region: str = "us-east-1"


class _QuarantineStore:
    def __init__(self, *, fail_first_head_after_put: bool = False):
        self.objects: dict[str, bytes] = {}
        self.put_calls = 0
        self.head_calls = 0
        self.get_calls = 0
        self.fail_first_head_after_put = fail_first_head_after_put
        self._head_failed = False

    @property
    def sanitized_health_identity(self):
        secret = _STORAGE_SECRET
        assert secret
        return _Health()

    def put_bytes_if_absent(self, payload: bytes, *, storage_key: str, expected_sha256: str | None = None):
        self.put_calls += 1
        digest = hashlib.sha256(payload).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise ObjectStorageIntegrityError("hash mismatch")
        if storage_key in self.objects:
            raise ObjectStoragePreconditionFailed("exists")
        self.objects[storage_key] = bytes(payload)
        return StoredObject(storage_key=storage_key, file_size_bytes=len(payload), file_hash=digest, etag="phase-n-etag")

    def head_object(self, *, storage_key: str):
        self.head_calls += 1
        if self.fail_first_head_after_put and self.objects and not self._head_failed:
            self._head_failed = True
            raise ObjectStorageError("simulated bounded storage verification failure")
        payload = self.objects.get(storage_key)
        if payload is None:
            raise ObjectStorageNotFound("missing")
        return ObjectMetadata(
            storage_key=storage_key,
            file_size_bytes=len(payload),
            file_hash=hashlib.sha256(payload).hexdigest(),
            etag="phase-n-etag",
        )

    def get_bytes(self, *, storage_key: str, expected_sha256: str | None = None):
        self.get_calls += 1
        payload = self.objects.get(storage_key)
        if payload is None:
            raise ObjectStorageNotFound("missing")
        if expected_sha256 is not None and hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise ObjectStorageIntegrityError("hash mismatch")
        return bytes(payload)


def setup_function() -> None:
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
    clear_external_document_source_discovery_adapters()
    clear_external_document_source_credential_reference_health_resolvers()
    clear_external_document_source_credential_resolution_resolvers()
    clear_external_document_source_token_acquirers()
    clear_external_document_source_provider_client_health_adapters()
    clear_external_document_source_remote_metadata_list_adapters()
    clear_external_document_source_remote_file_content_read_adapters()
    clear_external_document_source_remote_content_staging_store()


def _completed_phase_m():
    requester_id, profile_id, binding_id, listing_execution_id, file_item_id, _folder_item_id = _completed_phase_l()
    adapter = _ReadAdapter()
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint", "graph_drive_item_content_read_v1", adapter,
    )
    completed = _read_content(
        profile_id, listing_execution_id, file_item_id, requester_id,
        key="remote-content-staging-phase-m",
    )
    assert completed.status_code == 201, completed.text
    return requester_id, profile_id, binding_id, completed.json()["id"], adapter


def _stage(profile_id: str, read_execution_id: str, actor_id: UUID, *, key: str, reason: str = _STAGE_REASON, extra: dict | None = None):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/remote-content-read-executions/{read_execution_id}/remote-content-staging-executions",
        headers=_headers(actor_id),
        json=payload,
    )


def test_phase_n_governed_durable_remote_content_staging(caplog: pytest.LogCaptureFixture) -> None:
    requester_id, profile_id, binding_id, read_execution_id, read_adapter = _completed_phase_m()
    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    # Production path fails closed when the Phase 17.3 S3 foundation is not explicitly enabled/configured.
    missing_store = _stage(profile_id, read_execution_id, requester_id, key="stage-missing-store")
    assert missing_store.status_code == 409, missing_store.text
    assert "S3 foundation" in missing_store.text
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceRemoteContentStagingExecution).count() == 0

    store = _QuarantineStore()
    register_external_document_source_remote_content_staging_store(store)

    forbidden = _stage(
        profile_id, read_execution_id, requester_id, key="stage-forbidden",
        extra={
            "provider_item_id": "forbidden", "url": _PROVIDER_URL, "content": _FILE_BODY_MARKER,
            "range": "bytes=0-10", "storage_key": "caller/path", "access_token": "forbidden",
        },
    )
    assert forbidden.status_code == 422, forbidden.text
    assert store.put_calls == 0

    _, other_requester, _ = _seed_tenant("phase-n-other-tenant")
    wrong_tenant = _stage(profile_id, read_execution_id, other_requester, key="stage-wrong-tenant")
    assert wrong_tenant.status_code == 404, wrong_tenant.text
    assert store.put_calls == 0

    # Same-size different bytes pass Phase L size checks but must fail the exact Phase M digest reconciliation.
    mismatched_adapter = _ReadAdapter(content=b"y" * len(_FILE_BODY))
    register_external_document_source_remote_file_content_read_adapter(
        "sharepoint", "graph_drive_item_content_read_v1", mismatched_adapter,
    )
    mismatched = _stage(profile_id, read_execution_id, requester_id, key="stage-digest-mismatch")
    assert mismatched.status_code == 409, mismatched.text
    assert "does not match the Phase M content proof" in mismatched.text
    assert store.put_calls == 0
    with TestingSessionLocal() as db:
        anchor = db.query(ExternalDocumentSourceRemoteContentStagingExecution).one()
        assert anchor.status == "requested"
        assert db.query(ExternalDocumentSourceRemoteContentStagingReceipt).count() == 1

    # A changed replay cannot repurpose the durable recovery anchor.
    changed = _stage(
        profile_id, read_execution_id, requester_id, key="stage-digest-mismatch",
        reason="Attempt to alter the anchored Phase N durable staging request after a failed digest reconciliation.",
    )
    assert changed.status_code == 409, changed.text

    # Reset the DB so the crash-recovery path is exercised on a clean exact Phase M lineage.
    clear_external_document_source_remote_content_staging_store()
    reset_database()
    clear_external_document_source_remote_metadata_list_adapters()
    clear_external_document_source_remote_file_content_read_adapters()
    requester_id, profile_id, binding_id, read_execution_id, read_adapter = _completed_phase_m()
    crash_store = _QuarantineStore(fail_first_head_after_put=True)
    register_external_document_source_remote_content_staging_store(crash_store)

    before_n_calls = read_adapter.calls
    first = _stage(profile_id, read_execution_id, requester_id, key="stage-001")
    assert first.status_code == 409, first.text
    assert first.json()["detail"] == "Governed quarantine storage verification failed"
    assert crash_store.put_calls == 1
    assert len(crash_store.objects) == 1
    assert read_adapter.calls == before_n_calls + 1
    with TestingSessionLocal() as db:
        anchor = db.query(ExternalDocumentSourceRemoteContentStagingExecution).one()
        execution_id = str(anchor.id)
        internal_key = anchor.storage_object_key
        assert anchor.status == "requested"
        assert anchor.completion_hash is None
        assert db.query(ExternalDocumentSourceRemoteContentStagingReceipt).count() == 1
        assert crash_store.objects[internal_key] == _FILE_BODY

    # Exact retry reconciles the already-written deterministic object: no second provider read and no second PUT.
    recovered = _stage(profile_id, read_execution_id, requester_id, key="stage-001")
    assert recovered.status_code == 201, recovered.text
    body = recovered.json()
    assert body["id"] == execution_id
    assert body["status"] == "completed"
    assert body["result_status"] == "staged_verified"
    assert body["expected_content_sha256"] == hashlib.sha256(_FILE_BODY).hexdigest()
    assert body["expected_content_byte_count"] == len(_FILE_BODY)
    assert body["durable_content_staged"] is True
    assert body["remote_content_stored"] is True
    assert body["remote_read_performed"] is True
    assert body["storage_delete_performed"] is False
    assert body["checkpoint_created"] is False
    assert body["sync_executed"] is False
    assert body["document_created"] is False
    assert body["evidence_admitted"] is False
    assert body["claim_mutated"] is False
    assert crash_store.put_calls == 1
    assert len(crash_store.objects) == 1
    assert read_adapter.calls == before_n_calls + 1
    assert crash_store.objects[internal_key] == _FILE_BODY
    for forbidden_field in ("storage_object_key", "stored_etag", "endpoint_origin", "bucket", "url", "content", "file_body", "download_url", "access_token", "client_secret"):
        assert forbidden_field not in body
    for marker in (_FILE_BODY_MARKER, _STORAGE_SECRET, _PROVIDER_URL):
        assert marker not in recovered.text
        assert marker not in caplog.text

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/remote-content-staging-executions/{execution_id}/receipts",
        headers=_headers(requester_id),
    )
    assert receipts.status_code == 200, receipts.text
    rows = receipts.json()
    assert [row["event_type"] for row in rows] == ["requested", "completed"]
    assert [row["durable_content_staged"] for row in rows] == [False, True]
    assert rows[1]["prior_receipt_hash"] == rows[0]["receipt_hash"]

    # Completed exact replay verifies custody but does not re-read provider content or write a second object.
    replay = _stage(profile_id, read_execution_id, requester_id, key="stage-001")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == execution_id
    assert crash_store.put_calls == 1
    assert read_adapter.calls == before_n_calls + 1

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        execution = db.get(ExternalDocumentSourceRemoteContentStagingExecution, UUID(execution_id))
        persisted = [str(getattr(execution, column.name)) for column in execution.__table__.columns]
        receipt_rows = db.query(ExternalDocumentSourceRemoteContentStagingReceipt).filter(
            ExternalDocumentSourceRemoteContentStagingReceipt.execution_id == UUID(execution_id)
        ).all()
        for receipt in receipt_rows:
            persisted.extend(str(getattr(receipt, column.name)) for column in receipt.__table__.columns)
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "external_document_source_remote_content_staging_execution",
            AuditLog.entity_id == UUID(execution_id),
        ).one()
        payload = "\n".join(persisted) + json.dumps(audit.new_values, sort_keys=True) + (audit.details or "")
        for marker in (_FILE_BODY_MARKER, _STORAGE_SECRET, _PROVIDER_URL):
            assert marker not in payload
        assert internal_key not in json.dumps(audit.new_values, sort_keys=True)
        original_key_hash = execution.storage_object_key_hash
        execution.storage_object_key_hash = "0" * 64
        db.commit()

    tampered = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/remote-content-staging-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert tampered.status_code == 409, tampered.text
    with TestingSessionLocal() as db:
        execution = db.get(ExternalDocumentSourceRemoteContentStagingExecution, UUID(execution_id))
        execution.storage_object_key_hash = original_key_hash
        db.commit()

    disabled = client.post(
        f"/api/v1/external-document-sources/profiles/{profile_id}/credential-reference-bindings/{binding_id}/disable",
        headers=_headers(requester_id),
        json={"reason": "Disable the upstream credential reference so completed Phase N lineage must fail closed."},
    )
    assert disabled.status_code == 200, disabled.text
    fail_closed = client.get(
        f"/api/v1/external-document-sources/profiles/{profile_id}/remote-content-staging-executions/{execution_id}",
        headers=_headers(requester_id),
    )
    assert fail_closed.status_code == 409, fail_closed.text
    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceRemoteContentStagingExecution).count() == 1
        assert db.query(ExternalDocumentSourceRemoteContentStagingReceipt).count() == 2
