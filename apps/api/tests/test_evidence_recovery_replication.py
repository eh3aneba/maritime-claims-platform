import hashlib
import threading
from contextlib import contextmanager
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.security import create_access_token
from app.modules.auth.mfa_policy_models import MfaPolicy
from app.modules.auth.service import create_auth_session
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.documents import recovery_replication_service
from app.modules.documents.models import Document, DocumentProcessingStatus
from app.modules.documents.recovery_replication_models import (
    EvidenceRecoveryReplica,
    EvidenceRecoveryVerification,
)
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, client, reset_database


class _RecoveryS3Handler(BaseHTTPRequestHandler):
    bucket = "recovery-test-bucket"
    objects: dict[str, tuple[bytes, str]] = {}

    @classmethod
    def reset(cls) -> None:
        cls.objects = {}

    def log_message(self, format, *args):  # noqa: A003
        return

    def _key(self) -> str | None:
        prefix = f"/{type(self).bucket}/"
        if not self.path.startswith(prefix):
            return None
        return self.path[len(prefix) :]

    def do_HEAD(self):  # noqa: N802
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
        key = self._key()
        if key is None:
            self.send_response(400)
            self.end_headers()
            return
        if self.headers.get("If-None-Match") == "*" and key in type(self).objects:
            self.send_response(412)
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
    _RecoveryS3Handler.reset()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RecoveryS3Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def setup_function() -> None:
    reset_database()


def _settings(endpoint: str, storage_root: Path) -> Settings:
    return Settings(
        app_env="development",
        storage_backend="local",
        local_storage_path=str(storage_root),
        s3_foundation_enabled=True,
        s3_endpoint_url=endpoint,
        s3_region="us-east-1",
        s3_bucket="recovery-test-bucket",
        s3_access_key_id="AKIA_RECOVERY_TEST_ONLY",
        s3_secret_access_key="recovery-test-secret",
        s3_request_timeout_seconds=2.0,
        s3_max_attempts=2,
        malware_scan_enabled=False,
        cors_allowed_origins="http://localhost:3000",
    )


def _seed_tenant(*, slug: str, storage_root: Path, payload: bytes = b"survey evidence"):
    with TestingSessionLocal() as db:
        org = Organization(name=f"Recovery {slug}", slug=f"recovery-{slug}")
        db.add(org)
        db.flush()
        admin = User(
            organization_id=org.id,
            email=f"admin-{slug}@example.com",
            full_name=f"Admin {slug}",
            password_hash="local",
            role=UserRole.ADMIN,
            is_active=True,
        )
        manager = User(
            organization_id=org.id,
            email=f"manager-{slug}@example.com",
            full_name=f"Manager {slug}",
            password_hash="local",
            role=UserRole.CLAIMS_MANAGER,
            is_active=True,
        )
        vessel = Vessel(organization_id=org.id, name=f"MT {slug.upper()}")
        db.add_all([admin, manager, vessel])
        db.flush()
        claim = Claim(
            organization_id=org.id,
            vessel_id=vessel.id,
            handler_id=manager.id,
            claim_reference=f"REC-{slug.upper()}-001",
            status=ClaimStatus.CLOSED,
            incident_date=date(2026, 1, 1),
            notification_date=date(2026, 1, 2),
            incident_description="Recovery replication test claim.",
            currency="USD",
        )
        db.add(claim)
        db.flush()
        document_id = uuid4()
        storage_key = f"org/{org.id}/claim/{claim.id}/{document_id}.pdf"
        digest = hashlib.sha256(payload).hexdigest()
        document = Document(
            id=document_id,
            organization_id=org.id,
            claim_id=claim.id,
            uploaded_by_id=admin.id,
            filename="survey.pdf",
            original_filename="survey.pdf",
            mime_type="application/pdf",
            file_size_bytes=len(payload),
            file_hash=digest,
            storage_key=storage_key,
            processing_status=DocumentProcessingStatus.PROCESSED,
        )
        db.add(document)
        db.commit()

    path = storage_root / storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return org.id, admin.id, manager.id, claim.id, document_id, storage_key, path


def _headers(user_id: UUID) -> dict[str, str]:
    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        session = create_auth_session(db, user=user)
        db.commit()
        token = create_access_token(
            user_id=user.id,
            organization_id=user.organization_id,
            role=user.role.value,
            session_id=session.id,
            identity_source=session.identity_source,
            auth_method=session.auth_method,
        )
    return {"Authorization": f"Bearer {token}"}


def _replicate(claim_id: UUID, document_id: UUID, headers: dict[str, str]):
    return client.post(
        f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-replica",
        headers=headers,
        json={"reason": "Create and independently verify the governed recovery replica."},
    )


def test_recovery_replication_is_verified_idempotent_and_non_destructive(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        org_id, admin_id, manager_id, claim_id, document_id, storage_key, local_path = _seed_tenant(
            slug="happy", storage_root=tmp_path
        )
        settings = _settings(endpoint, tmp_path)
        monkeypatch.setattr(recovery_replication_service, "get_settings", lambda: settings)
        admin_headers = _headers(admin_id)
        manager_headers = _headers(manager_id)

        first = _replicate(claim_id, document_id, admin_headers)
        assert first.status_code == 201, first.text
        body = first.json()
        assert body["created"] is True
        replica_id = body["replica"]["id"]
        remote_key = body["replica"]["recovery_storage_key"]
        assert remote_key.startswith(f"recovery/evidence/{org_id}/{claim_id}/")
        assert body["replica"]["source_file_hash"] == hashlib.sha256(local_path.read_bytes()).hexdigest()
        assert body["replica"]["source_storage_key_fingerprint"] != storage_key
        assert remote_key in _RecoveryS3Handler.objects

        second = _replicate(claim_id, document_id, admin_headers)
        assert second.status_code == 201, second.text
        assert second.json()["created"] is False
        assert second.json()["replica"]["id"] == replica_id
        assert second.json()["verification"]["id"] != body["verification"]["id"]

        manager_read = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-replica",
            headers=manager_headers,
        )
        assert manager_read.status_code == 200
        verifications = client.get(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-replica/verifications",
            headers=manager_headers,
        )
        assert verifications.status_code == 200
        assert len(verifications.json()) == 2

        with TestingSessionLocal() as db:
            document = db.get(Document, document_id)
            assert document is not None
            assert document.deleted_at is None
            assert document.storage_key == storage_key
            assert db.query(EvidenceRecoveryReplica).count() == 1
            assert db.query(EvidenceRecoveryVerification).count() == 2
        assert local_path.exists()


def test_remote_conflict_fails_closed_without_overwrite(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        org_id, admin_id, _manager_id, claim_id, document_id, _storage_key, local_path = _seed_tenant(
            slug="remote-conflict", storage_root=tmp_path
        )
        settings = _settings(endpoint, tmp_path)
        monkeypatch.setattr(recovery_replication_service, "get_settings", lambda: settings)
        remote_key = f"recovery/evidence/{org_id}/{claim_id}/{document_id}.pdf"
        conflicting = b"different remote object"
        conflicting_hash = hashlib.sha256(conflicting).hexdigest()
        _RecoveryS3Handler.objects[remote_key] = (conflicting, conflicting_hash)

        response = _replicate(claim_id, document_id, _headers(admin_id))
        assert response.status_code == 409
        assert _RecoveryS3Handler.objects[remote_key] == (conflicting, conflicting_hash)
        with TestingSessionLocal() as db:
            assert db.query(EvidenceRecoveryReplica).count() == 0
        assert local_path.exists()


def test_remote_tamper_and_local_source_drift_fail_closed(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        _org_id, admin_id, _manager_id, claim_id, document_id, _storage_key, local_path = _seed_tenant(
            slug="drift", storage_root=tmp_path
        )
        settings = _settings(endpoint, tmp_path)
        monkeypatch.setattr(recovery_replication_service, "get_settings", lambda: settings)
        headers = _headers(admin_id)
        created = _replicate(claim_id, document_id, headers)
        assert created.status_code == 201, created.text
        remote_key = created.json()["replica"]["recovery_storage_key"]
        original_remote = _RecoveryS3Handler.objects[remote_key]

        _RecoveryS3Handler.objects[remote_key] = (b"tampered", original_remote[1])
        remote_check = client.post(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-replica/verify",
            headers=headers,
            json={"reason": "Reverify remote recovery integrity after replication."},
        )
        assert remote_check.status_code == 409

        _RecoveryS3Handler.objects[remote_key] = original_remote
        local_path.write_bytes(b"tampered local source")
        local_check = client.post(
            f"/api/v1/claims/{claim_id}/documents/{document_id}/recovery-replica/verify",
            headers=headers,
            json={"reason": "Reverify recovery replica against authoritative local evidence."},
        )
        assert local_check.status_code == 409
        assert _RecoveryS3Handler.objects[remote_key] == original_remote


def test_recovery_replication_rbac_cross_tenant_and_mfa(monkeypatch, tmp_path: Path) -> None:
    with _fake_s3() as endpoint:
        org_a, admin_a, manager_a, claim_a, document_a, _key_a, _path_a = _seed_tenant(
            slug="tenant-a", storage_root=tmp_path / "a"
        )
        _org_b, admin_b, manager_b, _claim_b, _document_b, _key_b, _path_b = _seed_tenant(
            slug="tenant-b", storage_root=tmp_path / "b"
        )
        settings = _settings(endpoint, tmp_path / "a")
        monkeypatch.setattr(recovery_replication_service, "get_settings", lambda: settings)

        manager_mutation = _replicate(claim_a, document_a, _headers(manager_a))
        assert manager_mutation.status_code == 403

        created = _replicate(claim_a, document_a, _headers(admin_a))
        assert created.status_code == 201, created.text

        cross_tenant = client.get(
            f"/api/v1/claims/{claim_a}/documents/{document_a}/recovery-replica",
            headers=_headers(manager_b),
        )
        assert cross_tenant.status_code == 404

        with TestingSessionLocal() as db:
            policy = MfaPolicy(
                organization_id=org_a,
                is_enabled=True,
                required_roles=[UserRole.ADMIN.value],
                updated_by_id=admin_a,
            )
            db.add(policy)
            db.commit()

        blocked = client.post(
            f"/api/v1/claims/{claim_a}/documents/{document_a}/recovery-replica/verify",
            headers=_headers(admin_a),
            json={"reason": "Tenant MFA policy should gate recovery mutations."},
        )
        assert blocked.status_code == 403
        assert admin_b != admin_a
