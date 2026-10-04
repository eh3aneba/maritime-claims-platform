from __future__ import annotations

import stat
from types import SimpleNamespace

import pytest

from app.modules.external_document_sources import sftp_production_hardening as hardening
from app.modules.external_document_sources.sftp_file_content_proof_service import (
    SftpFileContentReadRequest,
)


class _ReadHandle:
    def __init__(self, body: bytes, *, opened_size: int | None = None):
        self.body = body
        self.offset = 0
        self.opened_size = len(body) if opened_size is None else opened_size
        self.read_calls = 0
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def close(self):
        self.closed = True

    def settimeout(self, _value):
        return None

    def stat(self):
        return SimpleNamespace(
            st_mode=stat.S_IFREG | 0o640,
            st_size=self.opened_size,
            st_mtime=1_796_000_000,
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


class _FakeSftp:
    def __init__(self, body: bytes, *, opened_size: int | None = None):
        self.body = body
        self.handle = _ReadHandle(body, opened_size=opened_size)
        self.closed = False

    def normalize(self, path):
        return path

    def lstat(self, _path):
        return SimpleNamespace(
            st_mode=stat.S_IFREG | 0o640,
            st_size=len(self.body),
            st_mtime=1_796_000_000,
            st_uid=1000,
            st_gid=1000,
        )

    def open(self, _path, mode="rb"):
        assert mode == "rb"
        return self.handle

    def close(self):
        self.closed = True


class _FakeSession:
    def __init__(self, sftp):
        self.sftp = sftp
        self.authentication_method = "public_key"
        self.closed = False

    def close(self):
        self.closed = True
        self.sftp.close()


def _request() -> SftpFileContentReadRequest:
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


def test_opened_file_snapshot_drift_fails_before_first_content_byte(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"verified-evidence"
    sftp = _FakeSftp(body, opened_size=len(body) + 1)
    session = _FakeSession(sftp)
    runtime = hardening.HardenedLiveSftpRuntime(secret_runtime=SimpleNamespace())

    monkeypatch.setattr(
        hardening._ORIGINAL_RUNTIME_CLASS,
        "_open_session",
        lambda self, **_kwargs: session,
    )

    result = runtime.read_content(_request())

    assert result.content is None
    assert result.failure_code == "opened_file_snapshot_drift"
    assert result.remote_stat_performed is True
    assert result.remote_read_performed is False
    assert result.content_read_count == 0
    assert sftp.handle.read_calls == 0
    assert sftp.handle.closed is True
    assert session.closed is True


def test_opened_file_snapshot_match_allows_single_bounded_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = b"verified-evidence"
    sftp = _FakeSftp(body)
    session = _FakeSession(sftp)
    runtime = hardening.HardenedLiveSftpRuntime(secret_runtime=SimpleNamespace())

    monkeypatch.setattr(
        hardening._ORIGINAL_RUNTIME_CLASS,
        "_open_session",
        lambda self, **_kwargs: session,
    )

    result = runtime.read_content(_request())

    assert result.failure_code is None
    assert result.content == body
    assert result.remote_stat_performed is True
    assert result.remote_read_performed is True
    assert result.content_read_count == 1
    assert sftp.handle.read_calls >= 1
    assert session.closed is True


def test_registration_state_changes_only_after_final_adapter_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hardening, "_registration_complete", False)
    calls = []
    monkeypatch.setattr(
        hardening,
        "_ORIGINAL_CONTENT_REGISTRAR",
        lambda adapter: calls.append(adapter),
    )

    adapter = object()
    hardening._register_content_adapter_and_mark_complete(adapter)

    assert calls == [adapter]
    assert hardening.sftp_runtime_registration_complete() is True


def test_registration_state_stays_unavailable_when_final_registration_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hardening, "_registration_complete", False)

    def _fail(_adapter):
        raise RuntimeError("registration failed")

    monkeypatch.setattr(hardening, "_ORIGINAL_CONTENT_REGISTRAR", _fail)

    with pytest.raises(RuntimeError, match="registration failed"):
        hardening._register_content_adapter_and_mark_complete(object())

    assert hardening.sftp_runtime_registration_complete() is False
