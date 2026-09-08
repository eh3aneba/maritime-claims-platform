import base64
import json
from hashlib import sha256
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from app.modules.auth.service import create_auth_session
from app.modules.auth.webauthn_models import WebAuthnCredential, WebAuthnRegistrationTransaction
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _cbor_head(major: int, length: int) -> bytes:
    if length < 24:
        return bytes([(major << 5) | length])
    if length <= 0xFF:
        return bytes([(major << 5) | 24, length])
    if length <= 0xFFFF:
        return bytes([(major << 5) | 25]) + length.to_bytes(2, "big")
    if length <= 0xFFFFFFFF:
        return bytes([(major << 5) | 26]) + length.to_bytes(4, "big")
    return bytes([(major << 5) | 27]) + length.to_bytes(8, "big")


def _cbor(value) -> bytes:
    if isinstance(value, bool):
        return b"\xf5" if value else b"\xf4"
    if value is None:
        return b"\xf6"
    if isinstance(value, int):
        if value >= 0:
            return _cbor_head(0, value)
        return _cbor_head(1, -1 - value)
    if isinstance(value, bytes):
        return _cbor_head(2, len(value)) + value
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return _cbor_head(3, len(encoded)) + encoded
    if isinstance(value, list):
        return _cbor_head(4, len(value)) + b"".join(_cbor(item) for item in value)
    if isinstance(value, dict):
        return _cbor_head(5, len(value)) + b"".join(
            _cbor(key) + _cbor(item) for key, item in value.items()
        )
    raise TypeError(type(value))


def _seed_org(slug: str) -> tuple[UUID, UUID]:
    with TestingSessionLocal() as db:
        org = Organization(name=f"Org {slug}", slug=slug)
        db.add(org)
        db.flush()
        user = User(
            organization_id=org.id,
            email=f"handler-{slug}@example.com",
            full_name="Claims Handler",
            password_hash="",
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        admin = User(
            organization_id=org.id,
            email=f"admin-{slug}@example.com",
            full_name="Identity Admin",
            password_hash="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add_all([user, admin])
        db.commit()
        return user.id, admin.id


def _headers(user_id: UUID) -> tuple[dict[str, str], UUID]:
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
        return {"Authorization": f"Bearer {token}"}, session.id


def _profile(admin_headers: dict[str, str]) -> dict:
    response = client.post(
        "/api/v1/auth/webauthn/rp-profiles",
        headers=admin_headers,
        json={
            "rp_id": "claims.example.com",
            "rp_name": "MCRI Claims",
            "allowed_origins": ["https://claims.example.com"],
            "user_verification": "required",
            "attestation": "none",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _begin(headers: dict[str, str]) -> dict:
    response = client.post("/api/v1/auth/webauthn/registration/begin", headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _registration_payload(
    challenge: str,
    *,
    origin: str = "https://claims.example.com",
    credential_id: bytes = b"credential-id-for-mcri-0000000001",
    algorithm: int = -7,
) -> dict[str, str]:
    if algorithm == -7:
        public_key = ec.generate_private_key(ec.SECP256R1()).public_key().public_numbers()
        cose = {
            1: 2,
            3: -7,
            -1: 1,
            -2: public_key.x.to_bytes(32, "big"),
            -3: public_key.y.to_bytes(32, "big"),
        }
    elif algorithm == -257:
        public_key = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key().public_numbers()
        cose = {
            1: 3,
            3: -257,
            -1: public_key.n.to_bytes((public_key.n.bit_length() + 7) // 8, "big"),
            -2: public_key.e.to_bytes((public_key.e.bit_length() + 7) // 8, "big"),
        }
    else:
        raise AssertionError("unsupported test algorithm")

    auth_data = (
        sha256(b"claims.example.com").digest()
        + bytes([0x45])
        + (0).to_bytes(4, "big")
        + (b"\x00" * 16)
        + len(credential_id).to_bytes(2, "big")
        + credential_id
        + _cbor(cose)
    )
    attestation = _cbor({"fmt": "none", "authData": auth_data, "attStmt": {}})
    client_data = json.dumps(
        {
            "type": "webauthn.create",
            "challenge": challenge,
            "origin": origin,
            "crossOrigin": False,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "credential_id": _b64(credential_id),
        "client_data_json": _b64(client_data),
        "attestation_object": _b64(attestation),
    }


def test_verified_es256_registration_is_one_time_hash_only_and_revocable() -> None:
    user_id, admin_id = _seed_org("webauthn-finish-es")
    admin_headers, _ = _headers(admin_id)
    user_headers, _ = _headers(user_id)
    _profile(admin_headers)
    begun = _begin(user_headers)
    transaction_id = UUID(begun["transaction_id"])
    material = _registration_payload(begun["challenge"])

    finished = client.post(
        f"/api/v1/auth/webauthn/registration/{transaction_id}/finish",
        headers=user_headers,
        json=material,
    )
    assert finished.status_code == 201, finished.text
    credential = finished.json()
    assert credential["algorithm"] == -7
    assert credential["attestation_format"] == "none"
    assert "public_key_pem" not in credential
    assert "credential_id_hash" not in credential

    raw_material = json.dumps(material)
    with TestingSessionLocal() as db:
        transaction = db.get(WebAuthnRegistrationTransaction, transaction_id)
        stored = db.get(WebAuthnCredential, UUID(credential["id"]))
        assert transaction is not None and transaction.consumed_at is not None
        assert stored is not None
        assert stored.credential_id_hash == sha256(
            base64.urlsafe_b64decode(material["credential_id"] + "=" * (-len(material["credential_id"]) % 4))
        ).hexdigest()
        assert "BEGIN PUBLIC KEY" in stored.public_key_pem
        assert material["credential_id"] not in json.dumps(stored.__dict__, default=str)
        audits = db.query(AuditLog).filter(AuditLog.entity_id == stored.id).all()
        assert audits
        audit_dump = json.dumps(
            [{"old": item.old_values, "new": item.new_values, "details": item.details} for item in audits],
            default=str,
        )
        assert material["credential_id"] not in audit_dump
        assert material["client_data_json"] not in audit_dump
        assert material["attestation_object"] not in audit_dump
        assert raw_material not in audit_dump

    replay = client.post(
        f"/api/v1/auth/webauthn/registration/{transaction_id}/finish",
        headers=user_headers,
        json=material,
    )
    assert replay.status_code == 409

    inventory = client.get(
        "/api/v1/auth/webauthn/registration/credentials",
        headers=user_headers,
    )
    assert inventory.status_code == 200
    assert [item["id"] for item in inventory.json()] == [credential["id"]]

    revoked = client.post(
        f"/api/v1/auth/webauthn/registration/credentials/{credential['id']}/revoke",
        headers=user_headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] is not None


def test_failed_origin_verification_does_not_consume_registration_transaction() -> None:
    user_id, admin_id = _seed_org("webauthn-finish-origin")
    admin_headers, _ = _headers(admin_id)
    user_headers, _ = _headers(user_id)
    _profile(admin_headers)
    begun = _begin(user_headers)
    transaction_id = UUID(begun["transaction_id"])

    bad = _registration_payload(begun["challenge"], origin="https://evil.example.com")
    rejected = client.post(
        f"/api/v1/auth/webauthn/registration/{transaction_id}/finish",
        headers=user_headers,
        json=bad,
    )
    assert rejected.status_code == 400
    with TestingSessionLocal() as db:
        transaction = db.get(WebAuthnRegistrationTransaction, transaction_id)
        assert transaction is not None and transaction.consumed_at is None
        assert db.query(WebAuthnCredential).count() == 0

    valid = _registration_payload(begun["challenge"])
    accepted = client.post(
        f"/api/v1/auth/webauthn/registration/{transaction_id}/finish",
        headers=user_headers,
        json=valid,
    )
    assert accepted.status_code == 201, accepted.text


def test_registration_is_exact_session_scoped_and_credential_id_cannot_rebind() -> None:
    user_id, admin_id = _seed_org("webauthn-finish-scope")
    admin_headers, _ = _headers(admin_id)
    first_headers, _ = _headers(user_id)
    second_headers, _ = _headers(user_id)
    _profile(admin_headers)

    first = _begin(first_headers)
    transaction_id = UUID(first["transaction_id"])
    material = _registration_payload(first["challenge"])
    wrong_session = client.post(
        f"/api/v1/auth/webauthn/registration/{transaction_id}/finish",
        headers=second_headers,
        json=material,
    )
    assert wrong_session.status_code == 409

    accepted = client.post(
        f"/api/v1/auth/webauthn/registration/{transaction_id}/finish",
        headers=first_headers,
        json=material,
    )
    assert accepted.status_code == 201

    second = _begin(first_headers)
    duplicate_material = _registration_payload(
        second["challenge"],
        credential_id=b"credential-id-for-mcri-0000000001",
    )
    duplicate = client.post(
        f"/api/v1/auth/webauthn/registration/{second['transaction_id']}/finish",
        headers=first_headers,
        json=duplicate_material,
    )
    assert duplicate.status_code == 409
    with TestingSessionLocal() as db:
        second_tx = db.get(WebAuthnRegistrationTransaction, UUID(second["transaction_id"]))
        assert second_tx is not None and second_tx.consumed_at is None
        assert db.query(WebAuthnCredential).count() == 1


def test_verified_rs256_registration_is_supported_without_mfa_elevation() -> None:
    user_id, admin_id = _seed_org("webauthn-finish-rs")
    admin_headers, _ = _headers(admin_id)
    user_headers, session_id = _headers(user_id)
    _profile(admin_headers)
    begun = _begin(user_headers)
    material = _registration_payload(
        begun["challenge"],
        credential_id=b"credential-id-for-mcri-rs256-00001",
        algorithm=-257,
    )
    finished = client.post(
        f"/api/v1/auth/webauthn/registration/{begun['transaction_id']}/finish",
        headers=user_headers,
        json=material,
    )
    assert finished.status_code == 201, finished.text
    assert finished.json()["algorithm"] == -257

    from app.modules.auth.models import AuthSession

    with TestingSessionLocal() as db:
        session = db.get(AuthSession, session_id)
        assert session is not None
        assert session.mfa_verified_at is None
        assert session.mfa_method is None
