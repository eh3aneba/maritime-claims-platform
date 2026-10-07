from __future__ import annotations

import pytest

from app.modules.external_document_sources.live_sftp_adapters import (
    register_live_sftp_adapters,
)
from app.modules.external_document_sources.sftp_directory_listing_service import (
    SftpDirectoryMetadataEntry,
)
from app.modules.external_document_sources.sftp_file_content_proof_models import (
    ExternalDocumentSourceSftpFileContentProof,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    SftpFileContentReadResult,
)
from tests.db_harness import TestingSessionLocal
from tests.test_external_document_source_sftp_directory_listing import (
    _list,
    _success_listing_result,
)
from tests.test_external_document_source_sftp_file_content_proof import (
    _FILE_BODY,
    _proof,
    setup_function as _proof_setup,
    teardown_function as _proof_teardown,
)
from tests.test_external_document_source_sftp_session_activation import (
    _activate,
    _success_activation_result,
)
from tests.test_external_document_source_sftp_transport_verification import (
    _completed_execution,
    _success_result,
    _verify,
)


class _ProductionShapedRuntime:
    def __init__(self, fingerprint: str):
        self.fingerprint = fingerprint
        self.calls: list[tuple[str, object]] = []

    def probe_host_key(self, request):
        self.calls.append(("probe", request))
        return _success_result(self.fingerprint)

    def activate(self, request):
        self.calls.append(("activate", request))
        return _success_activation_result()

    def list_metadata(self, request):
        self.calls.append(("list", request))
        return _success_listing_result(
            entries=(
                SftpDirectoryMetadataEntry(
                    relative_path="Survey Report.pdf",
                    entry_kind="file",
                    byte_size=len(_FILE_BODY),
                    metadata_id_hash="d" * 64,
                ),
            )
        )

    def stat_metadata(self, request):
        raise AssertionError("Exact stat is not part of the initial content-proof slice")

    def read_content(self, request):
        self.calls.append(("read", request))
        return SftpFileContentReadResult(
            content=_FILE_BODY,
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
            remote_stat_performed=True,
            remote_read_performed=True,
            content_read_count=1,
            sftp_session_closed=True,
        )

    def _load_credential(self, **_kwargs):
        raise AssertionError(
            "Credential health resolution is already qualified before this integration slice"
        )


class _OpenedFileDriftRuntime(_ProductionShapedRuntime):
    def read_content(self, request):
        self.calls.append(("read", request))
        return SftpFileContentReadResult(
            content=None,
            failure_code="opened_file_changed",
            latency_class="normal",
            remote_stat_performed=True,
            remote_read_performed=False,
            content_read_count=0,
        )


def setup_function() -> None:
    _proof_setup()


def teardown_function() -> None:
    _proof_teardown()


def _register_runtime(monkeypatch: pytest.MonkeyPatch, runtime) -> None:
    import app.modules.external_document_sources.live_sftp_adapters as live

    monkeypatch.setattr(live, "_paramiko", lambda: object())
    monkeypatch.setattr(
        live,
        "_configured_secret_backends",
        lambda: ("azure_key_vault",),
    )
    register_live_sftp_adapters(runtime)  # type: ignore[arg-type]


def _prepare_governed_slice(monkeypatch: pytest.MonkeyPatch, suffix: str, runtime_type):
    chain = _completed_execution(f"ae-c-production-adapter-{suffix}")
    runtime = runtime_type(chain["fingerprint"])
    _register_runtime(monkeypatch, runtime)

    verified = _verify(chain, key=f"ae-c-{suffix}-transport")
    assert verified.status_code == 201, verified.text
    assert verified.json()["result_status"] == "verified"
    chain["verification_id"] = verified.json()["id"]

    activated = _activate(chain, key=f"ae-c-{suffix}-activation")
    assert activated.status_code == 201, activated.text
    assert activated.json()["result_status"] == "activated"
    chain["activation_id"] = activated.json()["id"]

    listed = _list(chain, key=f"ae-c-{suffix}-list")
    assert listed.status_code == 201, listed.text
    listing = listed.json()
    assert listing["result_status"] == "listed"
    chain["listing_id"] = listing["id"]
    chain["file_entry_id"] = listing["entries"][0]["id"]
    return chain, runtime


def test_ae_c_production_adapter_registration_drives_real_governed_sftp_api_slice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, runtime = _prepare_governed_slice(
        monkeypatch,
        "live",
        _ProductionShapedRuntime,
    )

    proof = _proof(chain, key="ae-c-live-content-proof")
    assert proof.status_code == 201, proof.text
    assert proof.json()["result_status"] == "read_verified"
    assert proof.json()["remote_stat_performed"] is True
    assert proof.json()["remote_read_performed"] is True

    assert [name for name, _request in runtime.calls] == [
        "probe",
        "activate",
        "list",
        "read",
    ]

    transport_request = runtime.calls[0][1]
    activation_request = runtime.calls[1][1]
    listing_request = runtime.calls[2][1]
    read_request = runtime.calls[3][1]

    assert transport_request.max_connection_attempts == 1
    assert activation_request.max_authentication_attempts == 1
    assert listing_request.recursive is False
    assert read_request.exact_file_only is True
    assert read_request.follow_symlinks is False
    assert read_request.max_read_attempts == 1


def test_ae_c_opened_file_drift_is_rejected_without_persisting_content_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chain, runtime = _prepare_governed_slice(
        monkeypatch,
        "opened-drift",
        _OpenedFileDriftRuntime,
    )

    with TestingSessionLocal() as db:
        proofs_before = db.query(ExternalDocumentSourceSftpFileContentProof).count()

    proof = _proof(chain, key="ae-c-opened-drift-content-proof")
    assert proof.status_code == 409, proof.text
    assert [name for name, _request in runtime.calls][-1] == "read"

    with TestingSessionLocal() as db:
        assert db.query(ExternalDocumentSourceSftpFileContentProof).count() == proofs_before
