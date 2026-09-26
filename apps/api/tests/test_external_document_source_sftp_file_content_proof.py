import hashlib
import json
from uuid import UUID

from app.modules.audit.models import AuditLog
from app.modules.claims.models import Claim
from app.modules.documents.models import Document
from app.modules.external_document_sources.sftp_directory_listing_service import (
    SftpDirectoryMetadataEntry,
    register_external_document_source_sftp_directory_listing_adapter,
)
from app.modules.external_document_sources.sftp_file_content_proof_models import (
    MAX_SFTP_CONTENT_PROOF_BYTES,
    ExternalDocumentSourceSftpFileContentProof,
    ExternalDocumentSourceSftpFileContentProofReceipt,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    SftpFileContentReadResult,
    clear_external_document_source_sftp_file_content_read_adapter,
    register_external_document_source_sftp_file_content_read_adapter,
)
from tests.db_harness import TestingSessionLocal, client
from tests.test_external_document_source_profiles import _headers, _seed_tenant
from tests.test_external_document_source_sftp_directory_listing import (
    _DirectoryListingAdapter,
    _activated_chain,
    _list,
    _success_listing_result,
    setup_function as _h_setup,
    teardown_function as _h_teardown,
)


_REASON = (
    "Read one exact Phase 17.6-H SFTP file transiently and persist only bounded "
    "SHA-256 and byte-count proof without durable content custody."
)
_BODY_MARKER = "phase-i-file-body-must-never-persist"
_FILE_BODY = (_BODY_MARKER + "|").encode() + b"x" * 4060
_SECRET_MARKER = "phase-i-secret-must-never-persist"
_RAW_MARKER = "phase-i-raw-response-must-never-persist"


class _FileReadAdapter:
    adapter_kind = "deterministic_sftp_file_content_read"

    def __init__(
        self,
        *,
        content: bytes = _FILE_BODY,
        raise_error: bool = False,
        failure_code: str | None = None,
        remote_write_performed: bool = False,
        invalid_content: bool = False,
    ):
        self.content = content
        self.raise_error = raise_error
        self.failure_code = failure_code
        self.remote_write_performed = remote_write_performed
        self.invalid_content = invalid_content
        self.calls = []

    def read_content(self, request):
        self.calls.append(request)
        assert request.max_content_bytes == MAX_SFTP_CONTENT_PROOF_BYTES
        assert request.max_chunk_bytes == 65536
        assert request.max_connection_attempts == 1
        assert request.max_authentication_attempts == 1
        assert request.max_read_attempts == 1
        assert request.allow_private_destinations is False
        assert request.allow_redirects is False
        assert request.allow_proxy_retargeting is False
        assert request.read_only_intent is True
        assert request.exact_file_only is True
        assert request.follow_symlinks is False
        assert request.remote_root_path.startswith("/")
        assert request.effective_remote_path.startswith(request.remote_root_path.rstrip("/") or "/")
        assert not hasattr(request, "password")
        assert not hasattr(request, "private_key")
        assert not hasattr(request, "passphrase")
        if self.raise_error:
            raise RuntimeError(f"{_SECRET_MARKER} {_RAW_MARKER} {_BODY_MARKER}")
        if self.failure_code is not None:
            return SftpFileContentReadResult(failure_code=self.failure_code)
        body = "not-bytes" if self.invalid_content else self.content
        return SftpFileContentReadResult(  # type: ignore[arg-type]
            content=body,
            authentication_method="public_key",
            latency_class="normal",
            secret_resolution_performed=True,
            provider_network_performed=True,
            ssh_transport_performed=True,
            host_key_verification_performed=True,
            host_key_verified=True,
            authentication_performed=True,
            authentication_succeeded=True,
            sftp_session_opened=True,
            remote_read_performed=True,
            content_read_count=1,
            sftp_session_closed=True,
            remote_write_performed=self.remote_write_performed,
        )


def setup_function() -> None:
    _h_setup()
    clear_external_document_source_sftp_file_content_read_adapter()


def teardown_function() -> None:
    clear_external_document_source_sftp_file_content_read_adapter()
    _h_teardown()


def _listed_chain(seed: str, *, file_size: int | None = len(_FILE_BODY)):
    chain = _activated_chain(seed)
    entries = (
        SftpDirectoryMetadataEntry(
            relative_path="Survey Report.pdf",
            entry_kind="file",
            byte_size=file_size,
            metadata_id_hash="d" * 64,
        ),
        SftpDirectoryMetadataEntry(
            relative_path="Correspondence",
            entry_kind="directory",
            metadata_id_hash="e" * 64,
        ),
    )
    listing_adapter = _DirectoryListingAdapter(_success_listing_result(entries=entries))
    register_external_document_source_sftp_directory_listing_adapter(listing_adapter)
    listed = _list(chain, key=f"{seed}-listing")
    assert listed.status_code == 201, listed.text
    body = listed.json()
    assert body["result_status"] == "listed"
    file_entry = next(entry for entry in body["entries"] if entry["entry_kind"] == "file")
    directory_entry = next(entry for entry in body["entries"] if entry["entry_kind"] == "directory")
    chain["listing_id"] = body["id"]
    chain["file_entry_id"] = file_entry["id"]
    chain["directory_entry_id"] = directory_entry["id"]
    chain["listing_adapter"] = listing_adapter
    return chain


def _proof(chain: dict, *, entry_id: str | None = None, key: str, reason: str = _REASON, actor_id=None, extra=None):
    payload = {"request_key": key, "reason": reason}
    if extra:
        payload.update(extra)
    return client.post(
        (
            f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/"
            f"sftp-directory-listings/{chain['listing_id']}/entries/"
            f"{entry_id or chain['file_entry_id']}/file-content-proofs"
        ),
        headers=_headers(actor_id or chain["requester_id"]),
        json=payload,
    )


def test_sftp_file_content_proof_observes_bytes_once_without_persisting_body() -> None:
    chain = _listed_chain("sftp-content-proof")

    missing = _proof(chain, key="missing-adapter")
    assert missing.status_code == 409, missing.text
    assert "adapter is unavailable" in missing.text

    adapter = _FileReadAdapter()
    register_external_document_source_sftp_file_content_read_adapter(adapter)

    with TestingSessionLocal() as db:
        claims_before = db.query(Claim).count()
        documents_before = db.query(Document).count()

    response = _proof(chain, key="content-proof-001")
    assert response.status_code == 201, response.text
    body = response.json()
    proof_id = body["id"]

    assert body["result_status"] == "read_verified"
    assert body["content_sha256"] == hashlib.sha256(_FILE_BODY).hexdigest()
    assert body["content_byte_count"] == len(_FILE_BODY)
    assert body["declared_byte_size"] == len(_FILE_BODY)
    assert body["authentication_method"] == "public_key"
    assert body["remote_content_transiently_observed"] is True
    assert body["remote_read_performed"] is True
    assert body["remote_content_stored"] is False
    assert body["remote_content_returned"] is False
    assert body["remote_content_logged"] is False
    assert body["content_parsed"] is False
    assert body["content_extracted"] is False
    assert body["remote_list_performed"] is False
    assert body["remote_stat_performed"] is False
    assert body["remote_write_performed"] is False
    assert body["remote_rename_performed"] is False
    assert body["remote_delete_performed"] is False
    assert body["remote_mkdir_performed"] is False
    assert body["remote_chmod_performed"] is False
    assert body["remote_chown_performed"] is False
    assert body["remote_touch_performed"] is False
    assert body["command_executed"] is False
    assert body["checkpoint_created"] is False
    assert body["evidence_admitted"] is False
    assert body["document_created"] is False
    assert body["processing_enqueued"] is False
    assert body["ai_executed"] is False
    assert body["claim_mutated"] is False
    assert _BODY_MARKER not in response.text
    assert len(adapter.calls) == 1

    req = adapter.calls[0]
    assert req.entry_relative_path == "Survey Report.pdf"
    assert req.effective_remote_path.endswith("/Survey Report.pdf")
    assert req.reference_backend
    assert req.reference_namespace
    assert req.reference_name

    replay = _proof(chain, key="content-proof-001")
    assert replay.status_code == 201, replay.text
    assert replay.json()["id"] == proof_id
    assert len(adapter.calls) == 1

    changed = _proof(
        chain,
        key="content-proof-001",
        reason="Attempt to alter the already verified Phase 17.6-I content proof request.",
    )
    assert changed.status_code == 409, changed.text
    second = _proof(chain, key="content-proof-002")
    assert second.status_code == 409, second.text
    assert len(adapter.calls) == 1

    fetched = client.get(
        f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/sftp-file-content-proofs/{proof_id}",
        headers=_headers(chain["requester_id"]),
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["content_sha256"] == body["content_sha256"]

    receipts = client.get(
        f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/sftp-file-content-proofs/{proof_id}/receipts",
        headers=_headers(chain["requester_id"]),
    )
    assert receipts.status_code == 200, receipts.text
    receipt_rows = receipts.json()
    assert [row["event_type"] for row in receipt_rows] == ["requested", "completed"]
    assert [row["remote_read_performed"] for row in receipt_rows] == [False, True]
    assert receipt_rows[1]["prior_receipt_hash"] == receipt_rows[0]["receipt_hash"]

    with TestingSessionLocal() as db:
        assert db.query(Claim).count() == claims_before
        assert db.query(Document).count() == documents_before
        assert db.query(ExternalDocumentSourceSftpFileContentProof).count() == 1
        assert db.query(ExternalDocumentSourceSftpFileContentProofReceipt).count() == 2
        proof = db.get(ExternalDocumentSourceSftpFileContentProof, UUID(proof_id))
        assert proof is not None
        persisted = "\n".join(str(getattr(proof, col.name)) for col in proof.__table__.columns)
        for receipt in db.query(ExternalDocumentSourceSftpFileContentProofReceipt).all():
            persisted += "\n" + "\n".join(str(getattr(receipt, col.name)) for col in receipt.__table__.columns)
        audit = db.query(AuditLog).filter(
            AuditLog.entity_type == "external_document_source_sftp_file_content_proof",
            AuditLog.entity_id == UUID(proof_id),
        ).one()
        persisted += json.dumps(audit.new_values, sort_keys=True) + (audit.details or "")
        assert _BODY_MARKER not in persisted
        assert _SECRET_MARKER not in persisted
        assert _RAW_MARKER not in persisted


def test_sftp_file_content_proof_rejects_folder_arbitrary_fields_and_wrong_tenant_before_read() -> None:
    chain = _listed_chain("sftp-content-policy")
    adapter = _FileReadAdapter()
    register_external_document_source_sftp_file_content_read_adapter(adapter)

    folder = _proof(chain, entry_id=chain["directory_entry_id"], key="folder-read")
    assert folder.status_code == 409, folder.text
    assert adapter.calls == []

    extra = _proof(chain, key="arbitrary-path", extra={"remote_path": "/escape", "range": "0-100"})
    assert extra.status_code == 422, extra.text
    assert adapter.calls == []

    _, other_requester, _, _ = _seed_tenant("sftp-content-other-tenant")
    wrong = _proof(chain, key="wrong-tenant", actor_id=other_requester)
    assert wrong.status_code == 404, wrong.text
    assert adapter.calls == []


def test_sftp_file_content_proof_enforces_declared_and_actual_8mib_bounds() -> None:
    declared = _listed_chain(
        "sftp-content-declared-oversize",
        file_size=MAX_SFTP_CONTENT_PROOF_BYTES + 1,
    )
    adapter = _FileReadAdapter()
    register_external_document_source_sftp_file_content_read_adapter(adapter)
    response = _proof(declared, key="declared-oversize")
    assert response.status_code == 409, response.text
    assert "declared-size byte bound" in response.text
    assert adapter.calls == []

    actual = _listed_chain("sftp-content-actual-oversize", file_size=None)
    oversized_adapter = _FileReadAdapter(content=b"x" * (MAX_SFTP_CONTENT_PROOF_BYTES + 1))
    register_external_document_source_sftp_file_content_read_adapter(oversized_adapter)
    response = _proof(actual, key="actual-oversize")
    assert response.status_code == 409, response.text
    assert "byte bound" in response.text
    assert len(oversized_adapter.calls) == 1
    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceSftpFileContentProof).filter(
            ExternalDocumentSourceSftpFileContentProof.directory_listing_id == UUID(actual["listing_id"])
        ).count() == 0


def test_sftp_file_content_proof_fails_closed_on_adapter_error_invalid_body_and_mutation_signal() -> None:
    chain = _listed_chain("sftp-content-error")
    exploding = _FileReadAdapter(raise_error=True)
    register_external_document_source_sftp_file_content_read_adapter(exploding)
    response = _proof(chain, key="adapter-error")
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "SFTP file content read failed"
    assert _SECRET_MARKER not in response.text
    assert _RAW_MARKER not in response.text
    assert _BODY_MARKER not in response.text

    chain = _listed_chain("sftp-content-invalid")
    invalid = _FileReadAdapter(invalid_content=True)
    register_external_document_source_sftp_file_content_read_adapter(invalid)
    response = _proof(chain, key="invalid-content")
    assert response.status_code == 409, response.text
    assert "invalid content" in response.text

    chain = _listed_chain("sftp-content-mutation")
    mutation = _FileReadAdapter(remote_write_performed=True)
    register_external_document_source_sftp_file_content_read_adapter(mutation)
    response = _proof(chain, key="mutation-signal")
    assert response.status_code == 409, response.text
    assert "bounded read-only boundary" in response.text

    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceSftpFileContentProof).count() == 0


def test_sftp_file_content_proof_detects_persisted_tampering() -> None:
    chain = _listed_chain("sftp-content-tamper")
    adapter = _FileReadAdapter()
    register_external_document_source_sftp_file_content_read_adapter(adapter)
    response = _proof(chain, key="tamper-proof")
    assert response.status_code == 201, response.text
    proof_id = UUID(response.json()["id"])

    with TestingSessionLocal() as db:
        proof = db.get(ExternalDocumentSourceSftpFileContentProof, proof_id)
        assert proof is not None
        proof.content_sha256 = "f" * 64
        db.commit()

    fetched = client.get(
        f"/api/v1/external-document-sources/profiles/{chain['profile_id']}/sftp-file-content-proofs/{proof_id}",
        headers=_headers(chain["requester_id"]),
    )
    assert fetched.status_code == 409, fetched.text
    assert "hash integrity failed" in fetched.text or "result integrity failed" in fetched.text
