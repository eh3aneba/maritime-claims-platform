"""Opt-in real OpenSSH -> governed PostgreSQL initial SFTP custody acceptance.

Activation and profile lineage use deterministic synthetic governance fixtures;
the *listing and two initial content reads* use the production real-SFTP
runtime against a disposable OpenSSH server. The quarantine object store is
a controlled in-memory substitute. This is NOT full canonical v1 admission
and grants no production-source or customer-data permission.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import os
from uuid import UUID

import pytest

from app.modules.documents.models import Document
from app.modules.external_document_sources.live_sftp_adapters import (
    LiveSftpRuntime,
    _SftpListingAdapter,
)
from app.modules.external_document_sources.sftp_checkpoint_models import (
    ExternalDocumentSourceSftpCheckpoint,
    ExternalDocumentSourceSftpCheckpointReceipt,
)
from app.modules.external_document_sources.sftp_directory_listing_models import (
    ExternalDocumentSourceSftpDirectoryListing,
    ExternalDocumentSourceSftpDirectoryListingReceipt,
)
from app.modules.external_document_sources.sftp_directory_listing_service import (
    clear_external_document_source_sftp_directory_listing_adapter,
    register_external_document_source_sftp_directory_listing_adapter,
)
from app.modules.external_document_sources.sftp_file_content_proof_models import (
    ExternalDocumentSourceSftpFileContentProof,
    ExternalDocumentSourceSftpFileContentProofReceipt,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    clear_external_document_source_sftp_file_content_read_adapter,
    register_external_document_source_sftp_file_content_read_adapter,
)
from app.modules.external_document_sources.sftp_quarantine_staging_models import (
    ExternalDocumentSourceSftpQuarantineStaging,
    ExternalDocumentSourceSftpQuarantineStagingReceipt,
)
from app.modules.external_document_sources.sftp_quarantine_staging_service import (
    register_external_document_source_sftp_quarantine_staging_store,
)
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_live_sftp_governed_postgres_acceptance import (
    _ControlledPrivateKeySecretRuntime,
    setup_function as _setup,
    teardown_function as _teardown,
)
from tests.test_external_document_source_live_sftp_nplus1_governed_acceptance import (
    _LocalOnlyRealContentBridge,
)
from tests.test_external_document_source_live_sftp_real_server_acceptance import (
    _fingerprint,
    _settings,
)
from tests.test_external_document_source_sftp_checkpoint import _checkpoint
from tests.test_external_document_source_sftp_directory_listing import (
    _activated_chain,
    _list,
)
from tests.test_external_document_source_sftp_file_content_proof import _proof
from tests.test_external_document_source_sftp_quarantine_staging import (
    _QuarantineStore,
    _stage,
)

pytestmark = pytest.mark.skipif(
    os.getenv("MCRI_REAL_SFTP_ACCEPTANCE") != "1"
    or not os.getenv("MCRI_TEST_DATABASE_URL")
    or not os.getenv("MCRI_REAL_SFTP_PRIVATE_KEY_FILE"),
    reason="opt-in real OpenSSH + PostgreSQL initial custody acceptance only",
)

_BYTES = b"controlled-real-sftp-evidence\n"
_SHA = hashlib.sha256(_BYTES).hexdigest()


class _LocalOnlyDirectoryBridge:
    """Rebind exactly one controlled runner call, without changing DB authority."""

    adapter_kind = "controlled_openssh_postgres_directory_bridge_v1"

    def __init__(self, runtime: LiveSftpRuntime, fingerprint: str):
        self._adapter = _SftpListingAdapter(runtime)
        self._fingerprint = fingerprint
        self.calls = 0

    def list_metadata(self, request):
        self.calls += 1
        host, port, username, _password, root = _settings()
        assert host == "127.0.0.1"
        assert request.authentication_kind == "private_key"
        assert request.allow_private_destinations is False
        assert request.read_only_intent is True
        assert request.recursive is False and request.follow_symlinks is False
        assert request.max_pages == 1 and request.max_listing_attempts == 1
        assert request.max_connection_attempts == 1
        assert request.max_authentication_attempts == 1
        assert request.relative_path == ""
        adapted = replace(
            request,
            hostname=host,
            port=port,
            username=username,
            pinned_host_key_fingerprint=self._fingerprint,
            reference_backend="azure_key_vault",
            reference_namespace="ci-only",
            reference_name="ephemeral-openssh-key",
            reference_version=None,
            remote_root_path=root,
            effective_remote_path=root,
            allow_private_destinations=True,
        )
        result = self._adapter.list_metadata(adapted)
        assert result.remote_read_performed is False
        assert result.remote_write_performed is False
        assert result.command_executed is False
        return result


def setup_function() -> None:
    _setup()


def teardown_function() -> None:
    clear_external_document_source_sftp_directory_listing_adapter()
    clear_external_document_source_sftp_file_content_read_adapter()
    _teardown()


def test_real_openssh_initial_list_content_proof_quarantine_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain = _activated_chain("initial-real-openssh-custody")
    runtime = LiveSftpRuntime(secret_runtime=_ControlledPrivateKeySecretRuntime())
    fingerprint = _fingerprint(runtime)
    assert fingerprint == os.environ["MCRI_REAL_SFTP_FINGERPRINT"]

    listing_bridge = _LocalOnlyDirectoryBridge(runtime, fingerprint)
    register_external_document_source_sftp_directory_listing_adapter(listing_bridge)

    with TestingSessionLocal() as db:
        before_documents = db.query(Document).count()

    listed = _list(chain, key="initial-real-sftp-list")
    assert listed.status_code == 201, listed.text
    listing = listed.json()
    assert listing["result_status"] == "listed"
    assert listing["remote_list_performed"] is True
    entries = {x["relative_path"]: x for x in listing["entries"]}
    assert entries["survey.txt"]["entry_kind"] == "file"
    assert entries["survey.txt"]["byte_size"] == len(_BYTES)
    assert "escape-link" in entries
    chain["listing_id"] = listing["id"]
    chain["file_entry_id"] = entries["survey.txt"]["id"]

    read_bridge = _LocalOnlyRealContentBridge(runtime, fingerprint)
    register_external_document_source_sftp_file_content_read_adapter(read_bridge)
    proof_response = _proof(chain, key="initial-real-sftp-proof")
    assert proof_response.status_code == 201, proof_response.text
    proof = proof_response.json()
    assert proof["result_status"] == "read_verified"
    assert proof["content_sha256"] == _SHA
    assert proof["content_byte_count"] == len(_BYTES)
    assert proof["remote_content_stored"] is False
    assert proof["remote_content_returned"] is False
    assert proof["remote_read_performed"] is True
    chain["proof_id"] = proof["id"]

    store = _QuarantineStore()
    register_external_document_source_sftp_quarantine_staging_store(store)
    staged_response = _stage(chain, key="initial-real-sftp-stage")
    assert staged_response.status_code == 201, staged_response.text
    staged = staged_response.json()
    assert staged["result_status"] == "staged_verified"
    assert staged["content_sha256"] == _SHA
    assert staged["content_byte_count"] == len(_BYTES)
    assert store.put_calls == 1
    assert tuple(store.objects.values()) == (_BYTES,)
    chain["staging_id"] = staged["id"]

    # A checkpoint consumes *committed custody*, never another provider read.
    reads_before = read_bridge.calls
    lists_before = listing_bridge.calls
    puts_before = store.put_calls
    checkpoint_response = _checkpoint(chain, key="initial-real-sftp-checkpoint")
    assert checkpoint_response.status_code == 201, checkpoint_response.text
    checkpoint = checkpoint_response.json()
    assert checkpoint["result_status"] == "checkpoint_recorded"
    assert checkpoint["checkpoint_generation"] == 1
    assert checkpoint["remote_read_performed"] is False
    assert checkpoint["document_created"] is False
    assert checkpoint["evidence_admitted"] is False
    assert read_bridge.calls == reads_before == 2
    assert listing_bridge.calls == lists_before == 1
    assert store.put_calls == puts_before == 1

    # Losing the network adapters must not undermine committed replay.
    clear_external_document_source_sftp_directory_listing_adapter()
    clear_external_document_source_sftp_file_content_read_adapter()
    assert _list(chain, key="initial-real-sftp-list").json()["id"] == listing["id"]
    assert _proof(chain, key="initial-real-sftp-proof").json()["id"] == proof["id"]
    assert _stage(chain, key="initial-real-sftp-stage").json()["id"] == staged["id"]
    assert _checkpoint(chain, key="initial-real-sftp-checkpoint").json()["id"] == checkpoint["id"]
    assert listing_bridge.calls == 1 and read_bridge.calls == 2
    assert store.put_calls == 1

    with TestingSessionLocal() as db:
        assert db.query(Document).count() == before_documents
        for model, receipts in (
            (ExternalDocumentSourceSftpDirectoryListing, ExternalDocumentSourceSftpDirectoryListingReceipt),
            (ExternalDocumentSourceSftpFileContentProof, ExternalDocumentSourceSftpFileContentProofReceipt),
            (ExternalDocumentSourceSftpQuarantineStaging, ExternalDocumentSourceSftpQuarantineStagingReceipt),
            (ExternalDocumentSourceSftpCheckpoint, ExternalDocumentSourceSftpCheckpointReceipt),
        ):
            assert db.query(model).count() == 1
            assert db.query(receipts).count() == 2
        db_checkpoint = db.get(ExternalDocumentSourceSftpCheckpoint, UUID(checkpoint["id"]))
        assert db_checkpoint is not None
        assert db_checkpoint.content_sha256 == _SHA
