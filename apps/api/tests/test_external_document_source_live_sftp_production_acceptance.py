from __future__ import annotations

import json
import stat
from types import SimpleNamespace

import pytest

from app.modules.external_document_sources.live_sftp_adapters import (
    LiveSftpRuntime,
    _openssh_sha256,
)
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


class _SecretRuntime:
    def __init__(self) -> None:
        self.calls = []

    def load_secret(self, locator):
        self.calls.append(locator)
        return json.dumps(
            {
                "username": "claims-reader",
                "authentication_kind": "password",
                "password": "transient-password",
            }
        )


class _FakeHostKey:
    def asbytes(self):
        return b"mcri-ae-c-production-host-key"

    def get_name(self):
        return "ssh-ed25519"


class _FakeSocket:
    def __init__(self) -> None:
        self.closed = False
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value

    def close(self):
        self.closed = True


class _FakeChannel:
    def __init__(self) -> None:
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value


class _ReadHandle:
    def __init__(self, body: bytes, *, opened_size_delta: int = 0):
        self.body = body
        self.offset = 0
        self.timeout = None
        self.read_calls = 0
        self.opened_size_delta = opened_size_delta

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def settimeout(self, value):
        self.timeout = value

    def stat(self):
        return SimpleNamespace(
            st_mode=stat.S_IFREG | 0o640,
            st_size=len(self.body) + self.opened_size_delta,
            st_mtime=1_796_000_000 + (1 if self.opened_size_delta else 0),
            st_uid=1000,
            st_gid=1000,
        )

    def read(self, size):
        self.read_calls += 1
        if self.offset >= len(self.body):
            return b""
        chunk = self.body[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class _ProductionSftp:
    def __init__(self, body: bytes, *, opened_size_delta: int = 0):
        self.body = body
        self.closed = False
        self.channel = _FakeChannel()
        self.events = []
        self.handles = []
        self.opened_size_delta = opened_size_delta

    def get_channel(self):
        return self.channel

    def normalize(self, path):
        self.events.append(("normalize", path))
        return path

    def close(self):
        self.closed = True

    def listdir_attr(self, path):
        self.events.append(("listdir_attr", path))
        return [
            SimpleNamespace(
                filename="Survey Report.pdf",
                st_mode=stat.S_IFREG | 0o640,
                st_size=len(self.body),
                st_mtime=1_796_000_000,
                st_uid=1000,
                st_gid=1000,
            )
        ]

    def lstat(self, path):
        self.events.append(("lstat", path))
        return SimpleNamespace(
            st_mode=stat.S_IFREG | 0o640,
            st_size=len(self.body),
            st_mtime=1_796_000_000,
            st_uid=1000,
            st_gid=1000,
        )

    def open(self, path, mode="rb"):
        self.events.append(("open", path, mode))
        handle = _ReadHandle(
            self.body,
            opened_size_delta=self.opened_size_delta,
        )
        self.handles.append(handle)
        return handle


class _SecurityOptions:
    def __init__(self) -> None:
        self.key_types = (
            "ssh-ed25519",
            "rsa-sha2-512",
            "ssh-rsa",
        )


class _Transport:
    def __init__(self, sock, sftp):
        self.sock = sock
        self.sftp = sftp
        self.banner_timeout = None
        self.host_key_type = "ssh-ed25519"
        self.authenticated = False
        self.closed = False
        self.events = []
        self.security_options = _SecurityOptions()

    def get_security_options(self):
        return self.security_options

    def start_client(self, timeout=None):
        self.events.append(("start_client", timeout))

    def get_remote_server_key(self):
        return _FakeHostKey()

    def auth_password(self, username, password, fallback=False):
        self.events.append(("auth_password", username, bool(password), fallback))
        if username != "claims-reader" or password != "transient-password":
            raise RuntimeError("authentication failed")
        self.authenticated = True

    def is_authenticated(self):
        return self.authenticated

    def close(self):
        self.closed = True


class _SftpClientFactory:
    @staticmethod
    def from_transport(transport):
        return transport.sftp


class _ParamikoDouble:
    SFTPClient = _SftpClientFactory

    class AuthenticationException(Exception):
        pass

    def __init__(self, sftp):
        self.sftp = sftp
        self.transports = []

    def Transport(self, sock):
        transport = _Transport(sock, self.sftp)
        self.transports.append(transport)
        return transport


def _patch_live_transport(monkeypatch: pytest.MonkeyPatch, sftp: _ProductionSftp):
    import app.modules.external_document_sources.live_sftp_adapters as live

    paramiko = _ParamikoDouble(sftp)
    sockets = []

    def _connect(_hostname, _port, *, timeout_seconds, allow_private_destinations):
        sock = _FakeSocket()
        sock.settimeout(timeout_seconds)
        sockets.append(sock)
        return sock, True

    monkeypatch.setattr(live, "_paramiko", lambda: paramiko)
    monkeypatch.setattr(live, "_connect_socket", _connect)
    return paramiko, sockets


def _read_request(pinned: str) -> SftpFileContentReadRequest:
    return SftpFileContentReadRequest(
        hostname="files.example.com",
        port=22,
        username="claims-reader",
        pinned_host_key_fingerprint=pinned,
        authentication_kind="password",
        reference_backend="azure_key_vault",
        reference_namespace="claims-kv",
        reference_name="sftp-reader",
        reference_version=None,
        remote_root_path="/evidence",
        entry_relative_path="Survey Report.pdf",
        effective_remote_path="/evidence/Survey Report.pdf",
    )


def test_ae_c_live_runtime_production_chain_reaches_opened_handle_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"production-shaped-evidence"
    sftp = _ProductionSftp(body)
    paramiko, sockets = _patch_live_transport(monkeypatch, sftp)
    secret_runtime = _SecretRuntime()
    runtime = LiveSftpRuntime(secret_runtime=secret_runtime)
    pinned = _openssh_sha256(_FakeHostKey().asbytes())

    transport_result = runtime.probe_host_key(
        SftpTransportHostKeyProbeRequest(
            hostname="files.example.com",
            port=22,
        )
    )
    assert transport_result.failure_code is None
    assert transport_result.observed_host_key_fingerprint == pinned
    assert transport_result.host_key_algorithm == "ssh-ed25519"
    assert transport_result.authentication_performed is False

    activation_result = runtime.activate(
        SftpSessionActivationRequest(
            hostname="files.example.com",
            port=22,
            pinned_host_key_fingerprint=pinned,
            authentication_kind="password",
            reference_backend="azure_key_vault",
            reference_namespace="claims-kv",
            reference_name="sftp-reader",
            reference_version=None,
        )
    )
    assert activation_result.failure_code is None
    assert activation_result.authentication_method == "password"
    assert activation_result.sftp_session_opened is True
    assert activation_result.sftp_session_closed is True

    listing_result = runtime.list_metadata(
        SftpDirectoryListingRequest(
            hostname="files.example.com",
            port=22,
            username="claims-reader",
            pinned_host_key_fingerprint=pinned,
            authentication_kind="password",
            reference_backend="azure_key_vault",
            reference_namespace="claims-kv",
            reference_name="sftp-reader",
            reference_version=None,
            remote_root_path="/evidence",
            relative_path=".",
            effective_remote_path="/evidence",
        )
    )
    assert listing_result.failure_code is None
    assert [entry.relative_path for entry in listing_result.entries] == [
        "Survey Report.pdf"
    ]

    stat_result = runtime.stat_metadata(
        SftpExactFileMetadataRequest(
            hostname="files.example.com",
            port=22,
            username="claims-reader",
            pinned_host_key_fingerprint=pinned,
            authentication_kind="password",
            reference_backend="azure_key_vault",
            reference_namespace="claims-kv",
            reference_name="sftp-reader",
            reference_version=None,
            remote_root_path="/evidence",
            entry_relative_path="Survey Report.pdf",
            effective_remote_path="/evidence/Survey Report.pdf",
        )
    )
    assert stat_result.failure_code is None
    assert stat_result.found is True
    assert stat_result.byte_size == len(body)

    read_result = runtime.read_content(_read_request(pinned))
    assert read_result.failure_code is None
    assert read_result.content == body
    assert read_result.remote_stat_performed is True
    assert read_result.remote_read_performed is True
    assert read_result.content_read_count == 1
    assert len(sftp.handles) == 1
    assert sftp.handles[0].read_calls >= 1

    assert len(secret_runtime.calls) == 4
    assert all(sock.closed for sock in sockets)
    assert all(transport.closed for transport in paramiko.transports)
    assert ("listdir_attr", "/evidence") in sftp.events
    assert sftp.events.count(("lstat", "/evidence/Survey Report.pdf")) == 2
    assert sftp.events.count(("open", "/evidence/Survey Report.pdf", "rb")) == 1


def test_ae_c_live_runtime_rejects_opened_file_replacement_before_first_byte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sftp = _ProductionSftp(
        b"authorized-evidence",
        opened_size_delta=7,
    )
    paramiko, sockets = _patch_live_transport(monkeypatch, sftp)
    runtime = LiveSftpRuntime(secret_runtime=_SecretRuntime())
    pinned = _openssh_sha256(_FakeHostKey().asbytes())

    result = runtime.read_content(_read_request(pinned))

    assert result.failure_code == "opened_file_changed"
    assert result.content is None
    assert result.remote_stat_performed is True
    assert result.remote_read_performed is False
    assert result.content_read_count == 0
    assert len(sftp.handles) == 1
    assert sftp.handles[0].read_calls == 0
    assert all(sock.closed for sock in sockets)
    assert all(transport.closed for transport in paramiko.transports)
