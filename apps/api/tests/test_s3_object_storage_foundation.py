import hashlib
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import Settings
from app.core import preflight
from app.modules.documents.object_storage import (
    ObjectStorageConfigurationError,
    ObjectStorageError,
    ObjectStorageIntegrityError,
    S3CompatibleEvidenceStore,
    S3ObjectStoreConfig,
    make_managed_evidence_object_key,
    validate_managed_evidence_object_key,
)


class _FakeS3Handler(BaseHTTPRequestHandler):
    bucket = "test-bucket"
    objects: dict[str, tuple[bytes, str]] = {}
    seen_headers: list[dict[str, str]] = []
    force_status: int | None = None
    request_count = 0

    @classmethod
    def reset(cls) -> None:
        cls.objects = {}
        cls.seen_headers = []
        cls.force_status = None
        cls.request_count = 0

    def log_message(self, format, *args):  # noqa: A003
        return

    def _record(self) -> None:
        type(self).request_count += 1
        type(self).seen_headers.append({key.lower(): value for key, value in self.headers.items()})

    def _forced(self) -> bool:
        if type(self).force_status is None:
            return False
        self.send_response(type(self).force_status)
        self.end_headers()
        return True

    def _key(self) -> str | None:
        prefix = f"/{type(self).bucket}/"
        if not self.path.startswith(prefix):
            return None
        return self.path[len(prefix) :]

    def do_HEAD(self):  # noqa: N802
        self._record()
        if self._forced():
            return
        if self.path == f"/{type(self).bucket}":
            self.send_response(200)
            self.end_headers()
            return
        key = self._key()
        item = None if key is None else type(self).objects.get(key)
        if item is None:
            self.send_response(404)
            self.end_headers()
            return
        payload, digest = item
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("x-amz-meta-mcri-sha256", digest)
        self.send_header("ETag", f'"{hashlib.md5(payload, usedforsecurity=False).hexdigest()}"')
        self.end_headers()

    def do_PUT(self):  # noqa: N802
        self._record()
        if self._forced():
            return
        key = self._key()
        if key is None:
            self.send_response(400)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length)
        digest = self.headers.get("x-amz-meta-mcri-sha256")
        if digest is None:
            self.send_response(400)
            self.end_headers()
            return
        type(self).objects[key] = (payload, digest)
        self.send_response(200)
        self.send_header("ETag", f'"{hashlib.md5(payload, usedforsecurity=False).hexdigest()}"')
        self.end_headers()

    def do_GET(self):  # noqa: N802
        self._record()
        if self._forced():
            return
        key = self._key()
        item = None if key is None else type(self).objects.get(key)
        if item is None:
            self.send_response(404)
            self.end_headers()
            return
        payload, digest = item
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("x-amz-meta-mcri-sha256", digest)
        self.end_headers()
        self.wfile.write(payload)


@contextmanager
def _fake_s3():
    _FakeS3Handler.reset()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeS3Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _config(endpoint: str, *, max_attempts: int = 3) -> S3ObjectStoreConfig:
    return S3ObjectStoreConfig(
        endpoint_url=endpoint,
        region="us-east-1",
        bucket="test-bucket",
        access_key_id="AKIA_TEST_ONLY",
        secret_access_key="super-secret-test-key",
        request_timeout_seconds=2.0,
        max_attempts=max_attempts,
        tls_verify=True,
    )


def test_managed_object_key_is_tenant_and_claim_scoped() -> None:
    organization_id = uuid4()
    claim_id = uuid4()
    document_id = uuid4()
    key = make_managed_evidence_object_key(
        organization_id=organization_id,
        claim_id=claim_id,
        document_id=document_id,
        suffix=".PDF",
    )
    assert key == f"evidence/{organization_id}/{claim_id}/{document_id}.pdf"
    validate_managed_evidence_object_key(
        key,
        organization_id=organization_id,
        claim_id=claim_id,
    )
    with pytest.raises(ObjectStorageConfigurationError):
        validate_managed_evidence_object_key(
            key,
            organization_id=uuid4(),
            claim_id=claim_id,
        )
    with pytest.raises(ObjectStorageConfigurationError):
        make_managed_evidence_object_key(
            organization_id=organization_id,
            claim_id=claim_id,
            document_id=document_id,
            suffix="../../secret",
        )


def test_s3_put_get_head_round_trip_verifies_hash_and_signs_requests() -> None:
    with _fake_s3() as endpoint:
        store = S3CompatibleEvidenceStore(_config(endpoint))
        payload = b"marine evidence bytes"
        digest = hashlib.sha256(payload).hexdigest()
        key = make_managed_evidence_object_key(
            organization_id=uuid4(),
            claim_id=uuid4(),
            document_id=uuid4(),
            suffix=".pdf",
        )

        stored = store.put_bytes(payload, storage_key=key, expected_sha256=digest)
        assert stored.file_hash == digest
        assert stored.file_size_bytes == len(payload)
        assert store.get_bytes(storage_key=key, expected_sha256=digest) == payload
        metadata = store.head_object(storage_key=key)
        assert metadata.file_hash == digest
        assert metadata.file_size_bytes == len(payload)

        assert _FakeS3Handler.seen_headers
        authorization = _FakeS3Handler.seen_headers[0]["authorization"]
        assert authorization.startswith("AWS4-HMAC-SHA256 Credential=AKIA_TEST_ONLY/")
        assert "super-secret-test-key" not in authorization
        assert "super-secret-test-key" not in repr(store.sanitized_health_identity)
        assert not hasattr(store, "delete")
        assert not hasattr(store, "delete_object")
        assert not hasattr(store, "copy_object")


def test_s3_integrity_drift_fails_closed() -> None:
    with _fake_s3() as endpoint:
        store = S3CompatibleEvidenceStore(_config(endpoint))
        key = "evidence/tenant/claim/document.pdf"
        original = b"original"
        store.put_bytes(original, storage_key=key)
        stored_payload, stored_hash = _FakeS3Handler.objects[key]
        assert stored_payload == original
        _FakeS3Handler.objects[key] = (b"tampered", stored_hash)

        with pytest.raises(ObjectStorageIntegrityError):
            store.get_bytes(storage_key=key)


def test_s3_retry_is_bounded_and_error_is_sanitized() -> None:
    with _fake_s3() as endpoint:
        _FakeS3Handler.force_status = 503
        store = S3CompatibleEvidenceStore(_config(endpoint, max_attempts=2))
        with pytest.raises(ObjectStorageError) as exc_info:
            store.probe_bucket()
        assert _FakeS3Handler.request_count == 2
        message = str(exc_info.value)
        assert "503" in message
        assert "super-secret-test-key" not in message
        assert "AKIA_TEST_ONLY" not in message
        assert endpoint not in message


def test_s3_config_requires_https_when_strict() -> None:
    config = _config("http://127.0.0.1:9000")
    with pytest.raises(ObjectStorageConfigurationError, match="HTTPS"):
        config.validate(require_https=True)


def test_s3_health_identity_contains_no_credentials() -> None:
    store = S3CompatibleEvidenceStore(_config("https://objects.example.test"))
    health = store.sanitized_health_identity
    rendered = repr(health)
    assert health.backend == "s3-compatible-foundation"
    assert health.endpoint_origin == "https://objects.example.test"
    assert len(health.bucket_fingerprint) == 16
    assert "test-bucket" not in rendered
    assert "AKIA_TEST_ONLY" not in rendered
    assert "super-secret-test-key" not in rendered


def test_preflight_can_probe_foundation_target_without_activating_it(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        settings = Settings(
            app_env="development",
            storage_backend="local",
            local_storage_path=str(tmp_path / "documents"),
            s3_foundation_enabled=True,
            s3_endpoint_url=endpoint,
            s3_region="us-east-1",
            s3_bucket="test-bucket",
            s3_access_key_id="AKIA_TEST_ONLY",
            s3_secret_access_key="super-secret-test-key",
            s3_request_timeout_seconds=2.0,
            s3_max_attempts=2,
            malware_scan_enabled=False,
            cors_allowed_origins="http://localhost:3000",
        )
        monkeypatch.setattr(preflight, "get_settings", lambda: settings)
        errors, warnings = preflight.run_preflight(require_db=False)
        assert errors == []
        assert any("foundation target is reachable" in item for item in warnings)
        rendered = "\n".join(errors + warnings)
        assert "super-secret-test-key" not in rendered
        assert "AKIA_TEST_ONLY" not in rendered


def test_active_s3_backend_selection_is_blocked_in_foundation_phase(monkeypatch, tmp_path: Path) -> None:
    settings = Settings(
        app_env="development",
        storage_backend="s3",
        local_storage_path=str(tmp_path / "documents"),
        s3_foundation_enabled=False,
        malware_scan_enabled=False,
        cors_allowed_origins="http://localhost:3000",
    )
    monkeypatch.setattr(preflight, "get_settings", lambda: settings)
    errors, _warnings = preflight.run_preflight(require_db=False)
    assert any("foundation-only" in item for item in errors)
