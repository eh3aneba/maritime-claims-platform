from __future__ import annotations

import json
import stat
from types import SimpleNamespace

import pytest

from app.modules.external_document_sources.live_sftp_adapters import (
    LiveSftpRuntime,
    _SftpCredentialHealthResolver,
    _normalize_remote_path,
    _observe_sftp_operation,
    _openssh_sha256,
    register_live_sftp_adapters,
)
from app.modules.external_document_sources.sftp_change_detection_service import (
    SftpExactFileMetadataRequest,
)
from app.modules.external_document_sources.sftp_credential_health_service import (
    SftpCredentialReferenceLocator,
)
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    SftpFileContentReadRequest,
)


class _SecretRuntime:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = []

    def load_secret(self, locator):
        self.calls.append(locator)
        return json.dumps(self.payload)


class _ReadHandle:
    def __init__(self, body: bytes):
        self._body = body
        self._offset = 0
        self.timeout = None
        self.read_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def settimeout(self, value):
        self.timeout = value

    def read(self, size):
        self.read_calls += 1
        if self._offset >= len(self._body):
            return b""
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class _FakeSftp:
    def __init__(self, *, body: bytes = b"evidence", symlink: bool = False):
        self.body = body
        self.symlink = symlink
        self.events = []
        self.handle = _ReadHandle(body)

    def normalize(self, path):
        self.events.append(("normalize", path))
        return path

    def lstat(self, path):
        self.events.append(("lstat", path))
        mode = stat.S_IFLNK | 0o777 if self.symlink else stat.S_IFREG | 0o640
        return SimpleNamespace(
            st_mode=mode,
            st_size=len(self.body),
            st_mtime=1_796_000_000,
            st_uid=1000,
            st_gid=1000,
        )

    def open(self, path, mode="rb"):
        self.events.append(("open", path, mode))
        return self.handle


class _FakeSession:
    def __init__(self, sftp: _FakeSftp):
        self.sftp = sftp
        self.authentication_method = "public_key"
        self.closed = False

    def close(self):
        self.closed = True


def _read_request() -> SftpFileContentReadRequest:
    return SftpFileContentReadRequest(
        hostname="files.example.com",
        port=22,
        username="claims-reader",
        pinned_host_key_fingerprint="SHA256:" + "A" * 43,
        authentication_kind="private_key",
        reference_backend="azure_key_vault",
        reference_namespace="claims-kv",
        reference_name="sftp-reader",
        reference_version=None,
        remote_root_path="/evidence",
        entry_relative_path="Survey Report.pdf",
        effective_remote_path="/evidence/Survey Report.pdf",
    )


def _stat_request() -> SftpExactFileMetadataRequest:
    return SftpExactFileMetadataRequest(
        hostname="files.example.com",
        port=22,
        username="claims-reader",
        pinned_host_key_fingerprint="SHA256:" + "A" * 43,
        authentication_kind="private_key",
        reference_backend="azure_key_vault",
        reference_namespace="claims-kv",
        reference_name="sftp-reader",
        reference_version=None,
        remote_root_path="/evidence",
        entry_relative_path="Survey Report.pdf",
        effective_remote_path="/evidence/Survey Report.pdf",
    )


def test_live_sftp_credential_health_resolves_material_without_network() -> None:
    secret_runtime = _SecretRuntime(
        {
            "username": "claims-reader",
            "authentication_kind": "password",
            "password": "transient-secret",
        }
    )
    runtime = LiveSftpRuntime(secret_runtime=secret_runtime)
    resolver = _SftpCredentialHealthResolver(runtime, "azure_key_vault")

    result = resolver.check(
        SftpCredentialReferenceLocator(
            backend="azure_key_vault",
            namespace="claims-kv",
            name="sftp-reader",
            version=None,
            authentication_kind="password",
        )
    )

    assert result.resolved is True
    assert result.material_kind == "password"
    assert result.failure_code is None
    assert len(secret_runtime.calls) == 1


def test_live_sftp_content_read_performs_lstat_before_single_bounded_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = LiveSftpRuntime(
        secret_runtime=_SecretRuntime(
            {
                "username": "claims-reader",
                "authentication_kind": "private_key",
                "private_key": "unused-by-injected-session",
            }
        )
    )
    sftp = _FakeSftp(body=b"verified-evidence")
    session = _FakeSession(sftp)
    monkeypatch.setattr(runtime, "_open_session", lambda **_kwargs: session)

    result = runtime.read_content(_read_request())

    assert result.failure_code is None
    assert result.content == b"verified-evidence"
    assert result.remote_stat_performed is True
    assert result.remote_read_performed is True
    assert result.content_read_count == 1
    assert session.closed is True
    assert sftp.events == [
        ("lstat", "/evidence/Survey Report.pdf"),
        ("open", "/evidence/Survey Report.pdf", "rb"),
    ]


def test_live_sftp_exact_metadata_rejects_symlink_without_following_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = LiveSftpRuntime(secret_runtime=_SecretRuntime({}))
    sftp = _FakeSftp(symlink=True)
    session = _FakeSession(sftp)
    monkeypatch.setattr(runtime, "_open_session", lambda **_kwargs: session)

    result = runtime.stat_metadata(_stat_request())

    assert result.found is False
    assert result.failure_code == "symlink_escape_detected"
    assert result.remote_stat_performed is True
    assert result.symlink_escape_detected is True
    assert session.closed is True
    assert sftp.events == [("lstat", "/evidence/Survey Report.pdf")]


def test_live_sftp_remote_path_policy_blocks_escape() -> None:
    assert _normalize_remote_path("/evidence", "/evidence/report.pdf") == (
        "/evidence/report.pdf"
    )
    with pytest.raises(Exception):
        _normalize_remote_path("/evidence", "/other/report.pdf")
    with pytest.raises(Exception):
        _normalize_remote_path("/evidence", "/evidence/../other/report.pdf")


def test_live_sftp_registration_wires_only_bounded_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.external_document_sources.live_sftp_adapters as live

    registered = []
    monkeypatch.setattr(live, "_paramiko", lambda: object())
    monkeypatch.setattr(
        live,
        "_configured_secret_backends",
        lambda: ("azure_key_vault",),
    )
    monkeypatch.setattr(
        live,
        "register_external_document_source_sftp_credential_health_resolver",
        lambda backend, adapter: registered.append(("health", backend, adapter)),
    )
    monkeypatch.setattr(
        live,
        "register_external_document_source_sftp_transport_adapter",
        lambda adapter: registered.append(("transport", adapter)),
    )
    monkeypatch.setattr(
        live,
        "register_external_document_source_sftp_session_activation_adapter",
        lambda adapter: registered.append(("activation", adapter)),
    )
    monkeypatch.setattr(
        live,
        "register_external_document_source_sftp_directory_listing_adapter",
        lambda adapter: registered.append(("listing", adapter)),
    )
    monkeypatch.setattr(
        live,
        "register_external_document_source_sftp_exact_file_metadata_adapter",
        lambda adapter: registered.append(("metadata", adapter)),
    )
    monkeypatch.setattr(
        live,
        "register_external_document_source_sftp_file_content_read_adapter",
        lambda adapter: registered.append(("content", adapter)),
    )

    runtime = LiveSftpRuntime(secret_runtime=_SecretRuntime({}))
    returned = register_live_sftp_adapters(runtime)

    assert returned is runtime
    assert [item[0] for item in registered] == [
        "health",
        "transport",
        "activation",
        "listing",
        "metadata",
        "content",
    ]



def test_sftp_observability_is_low_cardinality_and_locator_free(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO", logger="mcri.sftp"):
        _observe_sftp_operation(
            operation="content_read",
            result="success",
            latency_class="normal",
        )

    message = caplog.records[-1].getMessage()
    payload = json.loads(message)
    assert payload == {
        "event": "sftp_operation",
        "latency_class": "normal",
        "operation": "content_read",
        "result": "success",
    }
    for forbidden in (
        "hostname",
        "path",
        "username",
        "reference_name",
        "password",
        "private_key",
        "passphrase",
        "content",
    ):
        assert forbidden not in payload
        assert forbidden not in message



class _FakeHostKey:
    def asbytes(self):
        return b"mcri-production-shaped-host-key"

    def get_name(self):
        return "ssh-ed25519"


class _FakeSocket:
    def __init__(self):
        self.closed = False
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value

    def close(self):
        self.closed = True


class _FakeChannel:
    def __init__(self):
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value


class _ProductionShapeSftp:
    def __init__(self, body: bytes):
        self.body = body
        self.closed = False
        self.channel = _FakeChannel()
        self.events = []

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
        return _ReadHandle(self.body)


class _FakeTransport:
    def __init__(self, sock, *, sftp):
        self.sock = sock
        self.sftp = sftp
        self.banner_timeout = None
        self.host_key_type = "ssh-ed25519"
        self.authenticated = False
        self.closed = False
        self.events = []

    def start_client(self, timeout=None):
        self.events.append(("start_client", timeout))

    def get_remote_server_key(self):
        return _FakeHostKey()

    def auth_password(self, username, password, fallback=False):
        self.events.append(("auth_password", username, bool(password), fallback))
        if username != "claims-reader" or password != "transient-password":
            raise RuntimeError("auth failed")
        self.authenticated = True

    def auth_publickey(self, username, pkey):
        self.events.append(("auth_publickey", username))
        self.authenticated = True

    def is_authenticated(self):
        return self.authenticated

    def close(self):
        self.closed = True


class _FakeSftpClientFactory:
    current_transport = None

    @classmethod
    def from_transport(cls, transport):
        cls.current_transport = transport
        return transport.sftp


class _FakeParamikoModule:
    SFTPClient = _FakeSftpClientFactory

    def __init__(self, sftp):
        self.sftp = sftp
        self.transports = []

    def Transport(self, sock):
        transport = _FakeTransport(sock, sftp=self.sftp)
        self.transports.append(transport)
        return transport


def test_live_sftp_runtime_production_shaped_transport_auth_list_stat_and_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.external_document_sources.live_sftp_adapters as live
    from app.modules.external_document_sources.sftp_directory_listing_service import (
        SftpDirectoryListingRequest,
    )
    from app.modules.external_document_sources.sftp_session_activation_service import (
        SftpSessionActivationRequest,
    )
    from app.modules.external_document_sources.sftp_transport_verification_service import (
        SftpTransportHostKeyProbeRequest,
    )

    body = b"production-shaped-evidence"
    fake_sftp = _ProductionShapeSftp(body)
    fake_paramiko = _FakeParamikoModule(fake_sftp)
    sockets = []

    def fake_connect_socket(_hostname, _port, *, timeout_seconds, allow_private_destinations):
        sock = _FakeSocket()
        sock.settimeout(timeout_seconds)
        sockets.append(sock)
        return sock, True

    monkeypatch.setattr(live, "_paramiko", lambda: fake_paramiko)
    monkeypatch.setattr(live, "_connect_socket", fake_connect_socket)

    secret_runtime = _SecretRuntime(
        {
            "username": "claims-reader",
            "authentication_kind": "password",
            "password": "transient-password",
        }
    )
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
    assert transport_result.sftp_session_opened is False

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
    assert listing_result.remote_list_performed is True

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
    assert stat_result.entry_kind == "file"
    assert stat_result.byte_size == len(body)
    assert stat_result.remote_stat_performed is True

    read_result = runtime.read_content(
        SftpFileContentReadRequest(
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
    assert read_result.failure_code is None
    assert read_result.content == body
    assert read_result.remote_stat_performed is True
    assert read_result.remote_read_performed is True
    assert read_result.content_read_count == 1

    assert len(secret_runtime.calls) == 4
    assert all(sock.closed for sock in sockets)
    assert all(transport.closed for transport in fake_paramiko.transports)
    assert ("listdir_attr", "/evidence") in fake_sftp.events
    assert fake_sftp.events.count(("lstat", "/evidence/Survey Report.pdf")) == 2
    assert fake_sftp.events.count(("open", "/evidence/Survey Report.pdf", "rb")) == 1



def test_live_sftp_runtime_host_key_mismatch_fails_before_secret_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.external_document_sources.live_sftp_adapters as live
    from app.modules.external_document_sources.sftp_session_activation_service import (
        SftpSessionActivationRequest,
    )

    fake_sftp = _ProductionShapeSftp(b"unused")
    fake_paramiko = _FakeParamikoModule(fake_sftp)
    sockets = []

    def fake_connect_socket(_hostname, _port, *, timeout_seconds, allow_private_destinations):
        sock = _FakeSocket()
        sockets.append(sock)
        return sock, True

    monkeypatch.setattr(live, "_paramiko", lambda: fake_paramiko)
    monkeypatch.setattr(live, "_connect_socket", fake_connect_socket)

    secret_runtime = _SecretRuntime(
        {
            "username": "claims-reader",
            "authentication_kind": "password",
            "password": "must-not-be-read",
        }
    )
    runtime = LiveSftpRuntime(secret_runtime=secret_runtime)

    result = runtime.activate(
        SftpSessionActivationRequest(
            hostname="files.example.com",
            port=22,
            pinned_host_key_fingerprint="SHA256:" + "Z" * 43,
            authentication_kind="password",
            reference_backend="azure_key_vault",
            reference_namespace="claims-kv",
            reference_name="sftp-reader",
            reference_version=None,
        )
    )

    assert result.failure_code == "host_key_revalidation_failed"
    assert result.authentication_performed is False
    assert result.authentication_succeeded is False
    assert result.sftp_session_opened is False
    assert secret_runtime.calls == []
    assert all(sock.closed for sock in sockets)
    assert all(transport.closed for transport in fake_paramiko.transports)


def test_live_sftp_runtime_symlink_content_target_is_rejected_before_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = LiveSftpRuntime(secret_runtime=_SecretRuntime({}))
    sftp = _FakeSftp(body=b"must-not-be-read", symlink=True)
    session = _FakeSession(sftp)
    monkeypatch.setattr(runtime, "_open_session", lambda **_kwargs: session)

    result = runtime.read_content(_read_request())

    assert result.failure_code == "symlink_escape_detected"
    assert result.content is None
    assert result.remote_stat_performed is True
    assert result.remote_read_performed is False
    assert session.closed is True
    assert sftp.events == [("lstat", "/evidence/Survey Report.pdf")]
