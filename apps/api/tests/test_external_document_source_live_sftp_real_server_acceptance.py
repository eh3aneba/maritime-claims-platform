from __future__ import annotations

import json
import os

import pytest

from app.modules.external_document_sources.live_sftp_adapters import LiveSftpRuntime
from app.modules.external_document_sources.sftp_change_detection_service import (
    SftpExactFileMetadataRequest,
)
from app.modules.external_document_sources.sftp_directory_listing_service import (
    SftpDirectoryListingRequest,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    SftpFileContentReadRequest,
)
from app.modules.external_document_sources.sftp_session_activation_service import (
    SftpSessionActivationRequest,
)
from app.modules.external_document_sources.sftp_transport_verification_service import (
    SftpTransportHostKeyProbeRequest,
)


pytestmark = pytest.mark.skipif(
    os.getenv("MCRI_REAL_SFTP_ACCEPTANCE") != "1",
    reason="controlled real-SFTP acceptance is opt-in",
)


class _ControlledSecretRuntime:
    def __init__(self, *, username: str, password: str):
        self._payload = json.dumps(
            {
                "username": username,
                "authentication_kind": "password",
                "password": password,
            }
        )

    def load_secret(self, _locator) -> str:
        return self._payload


def _settings() -> tuple[str, int, str, str, str]:
    host = os.environ["MCRI_REAL_SFTP_HOST"]
    port = int(os.environ["MCRI_REAL_SFTP_PORT"])
    username = os.environ["MCRI_REAL_SFTP_USERNAME"]
    password = os.environ["MCRI_REAL_SFTP_PASSWORD"]
    root = os.environ["MCRI_REAL_SFTP_ROOT"]
    return host, port, username, password, root


def _runtime(password: str | None = None) -> LiveSftpRuntime:
    _host, _port, username, configured_password, _root = _settings()
    return LiveSftpRuntime(
        secret_runtime=_ControlledSecretRuntime(
            username=username,
            password=configured_password if password is None else password,
        )
    )


def _fingerprint(runtime: LiveSftpRuntime) -> str:
    host, port, _username, _password, _root = _settings()
    result = runtime.probe_host_key(
        SftpTransportHostKeyProbeRequest(
            hostname=host,
            port=port,
            connect_timeout_seconds=3,
            handshake_timeout_seconds=3,
            allow_private_destinations=True,
        )
    )
    assert result.failure_code is None
    assert result.provider_network_performed is True
    assert result.ssh_transport_performed is True
    assert result.authentication_performed is False
    assert result.sftp_session_opened is False
    assert result.host_key_algorithm == "ssh-ed25519"
    assert result.observed_host_key_fingerprint is not None
    return result.observed_host_key_fingerprint


def _activation_request(fingerprint: str) -> SftpSessionActivationRequest:
    host, port, _username, _password, _root = _settings()
    return SftpSessionActivationRequest(
        hostname=host,
        port=port,
        pinned_host_key_fingerprint=fingerprint,
        authentication_kind="password",
        reference_backend="azure_key_vault",
        reference_namespace="controlled-ci",
        reference_name="synthetic-sftp-password",
        reference_version=None,
        connect_timeout_seconds=3,
        authentication_timeout_seconds=3,
        subsystem_timeout_seconds=3,
        allow_private_destinations=True,
    )


def _listing_request(fingerprint: str) -> SftpDirectoryListingRequest:
    host, port, username, _password, root = _settings()
    return SftpDirectoryListingRequest(
        hostname=host,
        port=port,
        username=username,
        pinned_host_key_fingerprint=fingerprint,
        authentication_kind="password",
        reference_backend="azure_key_vault",
        reference_namespace="controlled-ci",
        reference_name="synthetic-sftp-password",
        reference_version=None,
        remote_root_path=root,
        relative_path="",
        effective_remote_path=root,
        max_entries=20,
        connect_timeout_seconds=3,
        authentication_timeout_seconds=3,
        listing_timeout_seconds=3,
        total_timeout_seconds=9,
        allow_private_destinations=True,
        recursive=False,
        follow_symlinks=False,
    )


def _stat_request(
    fingerprint: str,
    *,
    relative: str,
    effective: str | None = None,
) -> SftpExactFileMetadataRequest:
    host, port, username, _password, root = _settings()
    return SftpExactFileMetadataRequest(
        hostname=host,
        port=port,
        username=username,
        pinned_host_key_fingerprint=fingerprint,
        authentication_kind="password",
        reference_backend="azure_key_vault",
        reference_namespace="controlled-ci",
        reference_name="synthetic-sftp-password",
        reference_version=None,
        remote_root_path=root,
        entry_relative_path=relative,
        effective_remote_path=effective or f"{root}/{relative}",
        connect_timeout_seconds=3,
        authentication_timeout_seconds=3,
        stat_timeout_seconds=3,
        total_timeout_seconds=9,
        allow_private_destinations=True,
        follow_symlinks=False,
    )


def _read_request(
    fingerprint: str,
    *,
    relative: str,
    effective: str | None = None,
    max_content_bytes: int = 1024,
) -> SftpFileContentReadRequest:
    host, port, username, _password, root = _settings()
    return SftpFileContentReadRequest(
        hostname=host,
        port=port,
        username=username,
        pinned_host_key_fingerprint=fingerprint,
        authentication_kind="password",
        reference_backend="azure_key_vault",
        reference_namespace="controlled-ci",
        reference_name="synthetic-sftp-password",
        reference_version=None,
        remote_root_path=root,
        entry_relative_path=relative,
        effective_remote_path=effective or f"{root}/{relative}",
        max_content_bytes=max_content_bytes,
        max_chunk_bytes=16,
        connect_timeout_seconds=3,
        authentication_timeout_seconds=3,
        read_timeout_seconds=3,
        total_timeout_seconds=9,
        allow_private_destinations=True,
        exact_file_only=True,
        follow_symlinks=False,
    )


def test_real_openssh_positive_path_uses_production_runtime() -> None:
    runtime = _runtime()
    fingerprint = _fingerprint(runtime)
    expected_fingerprint = os.environ["MCRI_REAL_SFTP_FINGERPRINT"]
    assert fingerprint == expected_fingerprint

    activated = runtime.activate(_activation_request(fingerprint))
    assert activated.failure_code is None
    assert activated.authentication_method == "password"
    assert activated.host_key_verified is True
    assert activated.authentication_succeeded is True
    assert activated.sftp_session_opened is True
    assert activated.sftp_session_closed is True
    assert activated.remote_operation_performed is False
    assert activated.command_executed is False

    listed = runtime.list_metadata(_listing_request(fingerprint))
    assert listed.failure_code is None
    entries = {entry.relative_path: entry for entry in listed.entries}
    assert entries["survey.txt"].entry_kind == "file"
    assert entries["oversized.bin"].entry_kind == "file"
    assert entries["escape-link"].entry_kind == "symlink"
    assert listed.remote_list_performed is True
    assert listed.remote_read_performed is False
    assert listed.remote_write_performed is False
    assert listed.command_executed is False

    stat_result = runtime.stat_metadata(
        _stat_request(fingerprint, relative="survey.txt")
    )
    assert stat_result.failure_code is None
    assert stat_result.found is True
    assert stat_result.entry_kind == "file"
    assert stat_result.remote_stat_performed is True
    assert stat_result.remote_read_performed is False
    assert stat_result.remote_write_performed is False

    read_result = runtime.read_content(
        _read_request(fingerprint, relative="survey.txt")
    )
    assert read_result.failure_code is None
    assert read_result.content == b"controlled-real-sftp-evidence\n"
    assert read_result.remote_stat_performed is True
    assert read_result.remote_read_performed is True
    assert read_result.content_read_count == 1
    assert read_result.remote_write_performed is False
    assert read_result.remote_rename_performed is False
    assert read_result.remote_delete_performed is False
    assert read_result.command_executed is False


def test_real_openssh_wrong_pin_and_bad_password_fail_closed() -> None:
    runtime = _runtime()
    fingerprint = _fingerprint(runtime)

    wrong_pin = "SHA256:" + ("A" * 43)
    assert wrong_pin != fingerprint
    wrong_pin_result = runtime.activate(_activation_request(wrong_pin))
    assert wrong_pin_result.failure_code == "host_key_revalidation_failed"
    assert wrong_pin_result.authentication_performed is False
    assert wrong_pin_result.sftp_session_opened is False
    assert wrong_pin_result.command_executed is False

    bad_password_runtime = _runtime(password="definitely-wrong-ci-password")
    bad_auth = bad_password_runtime.activate(_activation_request(fingerprint))
    assert bad_auth.failure_code == "authentication_failed"
    assert bad_auth.authentication_performed is True
    assert bad_auth.authentication_succeeded is False
    assert bad_auth.sftp_session_opened is False
    assert bad_auth.command_executed is False


def test_real_openssh_missing_traversal_symlink_and_oversize_are_rejected() -> None:
    runtime = _runtime()
    fingerprint = _fingerprint(runtime)
    _host, _port, _username, _password, root = _settings()

    missing = runtime.stat_metadata(
        _stat_request(fingerprint, relative="missing.txt")
    )
    assert missing.found is False
    assert missing.failure_code == "not_found"

    traversal = runtime.read_content(
        _read_request(
            fingerprint,
            relative="../outside.txt",
            effective=f"{root}/../outside.txt",
        )
    )
    assert traversal.failure_code == "path_policy_violation"
    assert traversal.remote_stat_performed is False
    assert traversal.remote_read_performed is False

    symlink = runtime.stat_metadata(
        _stat_request(fingerprint, relative="escape-link")
    )
    assert symlink.found is False
    assert symlink.failure_code == "symlink_escape_detected"
    assert symlink.symlink_escape_detected is True

    oversized = runtime.read_content(
        _read_request(
            fingerprint,
            relative="oversized.bin",
            max_content_bytes=32,
        )
    )
    assert oversized.content is None
    assert oversized.failure_code == "content_too_large"
    assert oversized.remote_stat_performed is True
    assert oversized.remote_read_performed is True
    assert oversized.content_read_count == 0
