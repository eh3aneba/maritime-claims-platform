from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import subprocess
import threading
import time

import paramiko
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
    assert entries["escape-link"].byte_size is None
    assert entries["empty-folder"].entry_kind == "directory"
    assert entries["empty-folder"].byte_size is None
    assert entries["survey.txt"].byte_size == len(b"controlled-real-sftp-evidence\n")
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



def test_real_tcp_peer_abrupt_disconnect_before_ssh_banner_fails_closed() -> None:
    """Accepted real TCP connection then peer closes before SSH negotiation.

    This is a controlled kernel-socket failure injection, NOT a mid-session
    disconnect of the production OpenSSH server or a governed DB mutation.
    """
    host, _port, _user, _password, _root = _settings()
    assert host == "127.0.0.1"
    accepted = threading.Event()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((host, 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        listener.settimeout(4)

        def serve_disconnect() -> None:
            try:
                with listener.accept()[0]:
                    accepted.set()
                    # Closing without a banner forces a real SSH negotiation
                    # error; no username, password, path or file is transmitted.
            except OSError:
                pass

        peer = threading.Thread(target=serve_disconnect, daemon=True)
        peer.start()
        result = _runtime().probe_host_key(
            SftpTransportHostKeyProbeRequest(
                hostname=host, port=port, connect_timeout_seconds=1,
                handshake_timeout_seconds=1, allow_private_destinations=True,
            )
        )
        peer.join(timeout=4)

    assert accepted.is_set()
    assert not peer.is_alive()
    assert result.failure_code == "ssh_negotiation_failed"
    assert result.authentication_performed is False
    assert result.sftp_session_opened is False
    assert result.remote_operation_performed is False


def test_real_tcp_peer_ssh_banner_stall_has_bounded_failure() -> None:
    """A peer that accepts TCP but never responds must never pass handshake.

    This is a controlled TCP black-hole test, not a complete production SSH
    server timeout and NOT an authenticated session disconnect scenario.
    """
    host, _port, _user, _password, _root = _settings()
    assert host == "127.0.0.1"
    accepted = threading.Event()
    release_peer = threading.Event()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((host, 0))
        listener.listen(1)
        listener.settimeout(4)
        port = listener.getsockname()[1]

        def serve_stall() -> None:
            try:
                with listener.accept()[0]:
                    accepted.set()
                    release_peer.wait(timeout=4)
            except OSError:
                pass

        peer = threading.Thread(target=serve_stall, daemon=True)
        peer.start()
        started = time.monotonic()
        try:
            result = _runtime().probe_host_key(
                SftpTransportHostKeyProbeRequest(
                    hostname=host, port=port, connect_timeout_seconds=1,
                    handshake_timeout_seconds=1, allow_private_destinations=True,
                )
            )
        finally:
            release_peer.set()
            peer.join(timeout=4)
        elapsed = time.monotonic() - started

    assert accepted.is_set()
    assert not peer.is_alive()
    # Paramiko's banner timeout commonly maps to ssh_negotiation_failed;
    # socket.timeout may map to connection_timeout. Both are bounded failures.
    assert result.failure_code in {"connection_timeout", "ssh_negotiation_failed"}
    assert elapsed < 8
    assert result.authentication_performed is False
    assert result.sftp_session_opened is False
    assert result.remote_operation_performed is False


def test_real_openssh_authenticated_partial_read_transport_drop_discards_all_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed after real OpenSSH authentication and the first real file chunk.

    An isolated client transport is intentionally dropped after the first
    server-served chunk, before the exact-file read can finish. No server
    process, other session, remote fixture or customer data is modified.
    This proves read interruption handling, not server-originated failure.
    """
    runtime = _runtime()
    fingerprint = _fingerprint(runtime)
    original_session = runtime._open_session
    observation = {
        "session_opened": False,
        "first_chunk_read": False,
        "transport_closed": False,
        "next_read_attempted": False,
    }

    def open_with_single_session_fault(**kwargs):
        session = original_session(**kwargs)
        assert session.transport.is_authenticated()
        observation["session_opened"] = True
        original_open = session.sftp.open

        def open_with_one_chunk(*args, **kwargs):
            handle = original_open(*args, **kwargs)
            actual_read = handle.read

            def read_with_disconnect(size):
                if observation["transport_closed"]:
                    observation["next_read_attempted"] = True
                    # Let the real Paramiko file handle see the closed
                    # transport; never substitute a synthetic successful EOF.
                    return actual_read(size)
                chunk = actual_read(size)
                if chunk:
                    observation["first_chunk_read"] = True
                    # Close only this authenticated client session, not
                    # sshd, the controlled fixture or any other connection.
                    session.transport.close()
                    observation["transport_closed"] = True
                return chunk

            monkeypatch.setattr(handle, "read", read_with_disconnect)
            return handle

        monkeypatch.setattr(session.sftp, "open", open_with_one_chunk)
        return session

    monkeypatch.setattr(runtime, "_open_session", open_with_single_session_fault)
    result = runtime.read_content(
        _read_request(fingerprint, relative="survey.txt", max_content_bytes=1024)
    )

    assert observation == {
        "session_opened": True,
        "first_chunk_read": True,
        "transport_closed": True,
        "next_read_attempted": True,
    }
    assert result.failure_code == "read_failed"
    assert result.content is None
    assert result.content_read_count == 0
    assert result.remote_stat_performed is True
    assert result.remote_read_performed is True
    assert result.remote_write_performed is False
    assert result.remote_rename_performed is False
    assert result.remote_delete_performed is False
    assert result.command_executed is False


def test_real_openssh_same_size_inplace_rewrite_during_read_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detect a genuine OpenSSH opened-file metadata drift during streaming.

    A CI-only local-host fixture write is injected after the FIRST genuine
    server-served chunk. The production SFTP client itself has read-only
    authority and must not return any bytes after the SAME opened handle's
    post-read fstat discovers a changed mtime. This is a reproducible
    controlled server-side change, not a proof against unchanged metadata.
    """
    runtime = _runtime()
    fingerprint = _fingerprint(runtime)
    host, _port, username, _password, root = _settings()
    assert host == "127.0.0.1"
    assert username == "mcri-sftp-ci"
    assert root == "/home/mcri-sftp-ci/evidence"
    fixture_path = root + "/inplace-drift.txt"
    observed = {"opened": False, "first_chunk": False, "fixture_rewritten": False}
    original_open_session = runtime._open_session

    def open_with_fixture_mutation(**kwargs):
        session = original_open_session(**kwargs)
        assert session.transport.is_authenticated()
        original_open = session.sftp.open

        def open_with_first_chunk_mutation(*args, **kwargs):
            handle = original_open(*args, **kwargs)
            observed["opened"] = True
            real_read = handle.read

            def read_and_rewrite(size):
                chunk = real_read(size)
                if chunk and not observed["fixture_rewritten"]:
                    observed["first_chunk"] = True
                    # Root fixture modification occurs ONLY on the disposable
                    # runner host, never via the production SFTP connection.
                    # Preserve inode and byte length; force an unambiguous
                    # mtime difference independent of timestamp granularity.
                    local_mutation = (
                        "import os, sys\n"
                        "p = sys.argv[1]\n"
                        "before = os.stat(p)\n"
                        "assert before.st_size == 64\n"
                        "with open(p, 'r+b') as stream:\n"
                        "    stream.write(b'Z' * 64)\n"
                        "    stream.flush()\n"
                        "    os.fsync(stream.fileno())\n"
                        "os.utime(p, ns=(before.st_atime_ns, before.st_mtime_ns + 120_000_000_000))\n"
                    )
                    subprocess.run(
                        ["sudo", "python3", "-c", local_mutation, fixture_path],
                        check=True, capture_output=True, timeout=10,
                    )
                    observed["fixture_rewritten"] = True
                return chunk

            monkeypatch.setattr(handle, "read", read_and_rewrite)
            return handle

        monkeypatch.setattr(session.sftp, "open", open_with_first_chunk_mutation)
        return session

    monkeypatch.setattr(runtime, "_open_session", open_with_fixture_mutation)
    result = runtime.read_content(
        _read_request(fingerprint, relative="inplace-drift.txt",
                      max_content_bytes=1024)
    )
    assert observed == {
        "opened": True,
        "first_chunk": True,
        "fixture_rewritten": True,
    }
    assert result.failure_code == "opened_file_changed"
    assert result.content is None
    assert result.content_read_count == 0
    assert result.remote_stat_performed is True
    assert result.remote_read_performed is True
    assert result.remote_write_performed is False
    assert result.remote_rename_performed is False
    assert result.remote_delete_performed is False
    assert result.command_executed is False


def test_real_openssh_unavailable_port_fails_closed_without_authentication() -> None:
    """Network outage before the SSH banner is not interpreted as SFTP success."""
    host, _port, _user, _password, _root = _settings()
    runtime = _runtime()

    # Obtain a genuinely unused loopback port. This is a best-effort controlled
    # unavailable-server case, not a simulated mid-session disconnect.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((host, 0))
        unavailable_port = listener.getsockname()[1]

    result = runtime.probe_host_key(
        SftpTransportHostKeyProbeRequest(
            hostname=host,
            port=unavailable_port,
            connect_timeout_seconds=1,
            handshake_timeout_seconds=1,
            allow_private_destinations=True,
        )
    )
    assert result.failure_code == "connection_refused"
    assert result.ssh_transport_performed is False
    assert result.authentication_performed is False
    assert result.sftp_session_opened is False
    assert result.remote_operation_performed is False


def test_real_openssh_permission_denied_read_fails_closed() -> None:
    """An actual OpenSSH SFTP permission error must never release file bytes."""
    runtime = _runtime()
    fingerprint = _fingerprint(runtime)

    # The CI fixture is root-owned with mode 0600; the SFTP account is non-root.
    # Metadata may be visible while content access is forbidden.
    metadata = runtime.stat_metadata(
        _stat_request(fingerprint, relative="denied.txt")
    )
    assert metadata.failure_code is None
    assert metadata.found is True

    read = runtime.read_content(
        _read_request(fingerprint, relative="denied.txt")
    )
    assert read.content is None
    assert read.failure_code == "read_failed"
    assert read.content_read_count == 0
    assert read.remote_read_performed is False
    assert read.remote_write_performed is False
    assert read.remote_delete_performed is False
    assert read.command_executed is False


def test_real_openssh_sftp_principal_cannot_write_rename_delete_or_mkdir() -> None:
    """Actual server-side ACL, not just a client-side read-only flag.

    Against the controlled *ephemeral loopback-only* OpenSSH server, use
    the exact synthetic password identity to request forbidden remote
    mutations. Every mutation must be rejected at the server filesystem
    permission boundary, including in the nested directory. The original
    synthetic content must remain readable and unchanged.
    """
    host, port, username, password, root = _settings()
    assert (host, port, username, root) == (
        "127.0.0.1", 2222, "mcri-sftp-ci", "/home/mcri-sftp-ci/evidence"
    )
    expected_pin = os.environ["MCRI_REAL_SFTP_FINGERPRINT"]
    # The independent test client also validates the exact OpenSSH server key
    # before authenticating. No AutoAddPolicy or disabling host-key checks.
    with paramiko.Transport((host, port)) as transport:
        transport.start_client(timeout=3)
        key = transport.get_remote_server_key()
        assert key.get_name() == "ssh-ed25519"
        observed_pin = "SHA256:" + base64.b64encode(
            hashlib.sha256(key.asbytes()).digest()
        ).decode("ascii").rstrip("=")
        assert observed_pin == expected_pin
        transport.auth_password(username=username, password=password)
        assert transport.is_authenticated()
        sftp = paramiko.SFTPClient.from_transport(transport)
        assert sftp is not None
        try:
            source = f"{root}/survey.txt"
            expected_bytes = b"controlled-real-sftp-evidence\n"
            with sftp.open(source, "rb") as handle:
                assert handle.read() == expected_bytes
            original = sftp.stat(source)
            for mutation in (
                lambda: sftp.open(f"{root}/forbidden-created.txt", "wb"),
                lambda: sftp.open(source, "r+b"),
                lambda: sftp.mkdir(f"{root}/forbidden-directory"),
                lambda: sftp.open(
                    f"{root}/empty-folder/forbidden-created.txt", "wb"
                ),
                lambda: sftp.remove(source),
                lambda: sftp.rename(
                    source, f"{root}/forbidden-renamed.txt"
                ),
            ):
                with pytest.raises(OSError):
                    mutation()
                with sftp.open(source, "rb") as handle:
                    assert handle.read() == expected_bytes
            still_there = sftp.stat(source)
            assert still_there.st_size == original.st_size
            assert still_there.st_mtime == original.st_mtime
            # No failure attempt may create a file in either read-only dir.
            assert "forbidden-created.txt" not in sftp.listdir(root)
            assert "forbidden-directory" not in sftp.listdir(root)
            assert "forbidden-renamed.txt" not in sftp.listdir(root)
            assert "forbidden-created.txt" not in sftp.listdir(
                f"{root}/empty-folder"
            )
        finally:
            sftp.close()
