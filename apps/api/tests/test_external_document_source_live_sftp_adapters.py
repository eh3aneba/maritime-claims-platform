from __future__ import annotations

import json
import stat
from types import SimpleNamespace

import pytest

from app.modules.external_document_sources.live_sftp_adapters import (
    LiveSftpRuntime,
    _CredentialMaterial,
    _SftpCredentialHealthResolver,
    _SftpRuntimeFailure,
    _normalize_remote_path,
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
from app.modules.external_document_sources.sftp_transport_verification_service import (
    SftpTransportHostKeyProbeRequest,
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
        ("normalize", "/evidence"),
        ("normalize", "/evidence"),
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
    assert sftp.events == [
        ("normalize", "/evidence"),
        ("normalize", "/evidence"),
        ("lstat", "/evidence/Survey Report.pdf"),
    ]


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


class _FakeSocket:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakeHostKey:
    def asbytes(self):
        return b"weak-host-key"

    def get_name(self):
        return "ssh-rsa"


class _FakeSecurityOptions:
    def __init__(self):
        self.key_types = (
            "ssh-ed25519",
            "rsa-sha2-512",
            "ssh-rsa",
        )


class _WeakAlgorithmTransport:
    instances = []

    def __init__(self, sock):
        self.sock = sock
        self.banner_timeout = None
        self.host_key_type = "ssh-rsa"
        self.closed = False
        self.options = _FakeSecurityOptions()
        type(self).instances.append(self)

    def get_security_options(self):
        return self.options

    def start_client(self, timeout):
        self.timeout = timeout

    def get_remote_server_key(self):
        return _FakeHostKey()

    def close(self):
        self.closed = True


def test_live_sftp_transport_rejects_weak_negotiated_host_key_algorithm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.external_document_sources.live_sftp_adapters as live

    sock = _FakeSocket()
    _WeakAlgorithmTransport.instances.clear()
    monkeypatch.setattr(
        live,
        "_connect_socket",
        lambda *args, **kwargs: (sock, False),
    )
    monkeypatch.setattr(
        live,
        "_paramiko",
        lambda: SimpleNamespace(Transport=_WeakAlgorithmTransport),
    )

    runtime = LiveSftpRuntime(secret_runtime=_SecretRuntime({}))
    result = runtime.probe_host_key(
        SftpTransportHostKeyProbeRequest(
            hostname="files.example.com",
            port=22,
        )
    )

    assert result.failure_code == "ssh_negotiation_failed"
    assert result.authentication_performed is False
    assert result.sftp_session_opened is False
    assert len(_WeakAlgorithmTransport.instances) == 1
    transport = _WeakAlgorithmTransport.instances[0]
    assert "ssh-rsa" not in transport.options.key_types
    assert transport.closed is True
    assert sock.closed is True


class _ClosingTransport:
    def __init__(self):
        self.closed = False
        self.auth_calls = 0

    def close(self):
        self.closed = True

    def is_authenticated(self):
        return False


def test_live_sftp_host_key_mismatch_fails_before_secret_resolution_or_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.external_document_sources.live_sftp_adapters as live

    runtime = LiveSftpRuntime(secret_runtime=_SecretRuntime({}))
    sock = _FakeSocket()
    transport = _ClosingTransport()
    secret_calls = {"count": 0}

    monkeypatch.setattr(live, "_paramiko", lambda: SimpleNamespace())
    monkeypatch.setattr(
        runtime,
        "_start_transport",
        lambda **_kwargs: (
            sock,
            transport,
            "SHA256:" + "B" * 43,
            "ssh-ed25519",
            False,
        ),
    )

    def _must_not_resolve(**_kwargs):
        secret_calls["count"] += 1
        raise AssertionError("credential resolution must not happen after host-key mismatch")

    monkeypatch.setattr(runtime, "_load_credential", _must_not_resolve)

    with pytest.raises(_SftpRuntimeFailure, match="host_key_revalidation_failed"):
        runtime._open_session(
            hostname="files.example.com",
            port=22,
            pinned_host_key_fingerprint="SHA256:" + "A" * 43,
            authentication_kind="password",
            reference_backend="azure_key_vault",
            reference_namespace="claims-kv",
            reference_name="sftp-reader",
            reference_version=None,
            expected_username="claims-reader",
            connect_timeout_seconds=2.0,
            authentication_timeout_seconds=2.0,
            subsystem_timeout_seconds=2.0,
            allow_private_destinations=False,
        )

    assert secret_calls["count"] == 0
    assert transport.closed is True
    assert sock.closed is True


def test_live_sftp_authentication_failure_closes_transport_and_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.external_document_sources.live_sftp_adapters as live

    class AuthenticationException(Exception):
        pass

    class AuthFailTransport(_ClosingTransport):
        def auth_password(self, username, password, fallback=False):
            self.auth_calls += 1
            assert username == "claims-reader"
            assert password == "transient-secret"
            assert fallback is False
            raise AuthenticationException()

    runtime = LiveSftpRuntime(secret_runtime=_SecretRuntime({}))
    sock = _FakeSocket()
    transport = AuthFailTransport()

    monkeypatch.setattr(
        live,
        "_paramiko",
        lambda: SimpleNamespace(
            AuthenticationException=AuthenticationException,
        ),
    )
    monkeypatch.setattr(
        runtime,
        "_start_transport",
        lambda **_kwargs: (
            sock,
            transport,
            "SHA256:" + "A" * 43,
            "ssh-ed25519",
            False,
        ),
    )
    monkeypatch.setattr(
        runtime,
        "_load_credential",
        lambda **_kwargs: _CredentialMaterial(
            username="claims-reader",
            authentication_kind="password",
            password="transient-secret",
        ),
    )

    with pytest.raises(_SftpRuntimeFailure, match="authentication_failed"):
        runtime._open_session(
            hostname="files.example.com",
            port=22,
            pinned_host_key_fingerprint="SHA256:" + "A" * 43,
            authentication_kind="password",
            reference_backend="azure_key_vault",
            reference_namespace="claims-kv",
            reference_name="sftp-reader",
            reference_version=None,
            expected_username="claims-reader",
            connect_timeout_seconds=2.0,
            authentication_timeout_seconds=2.0,
            subsystem_timeout_seconds=2.0,
            allow_private_destinations=False,
        )

    assert transport.auth_calls == 1
    assert transport.closed is True
    assert sock.closed is True
