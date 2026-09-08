import base64
import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.security import create_access_token
from app.modules.auth.mfa_policy_models import MfaPolicy
from app.modules.auth.models import AuthSession
from app.modules.auth.service import create_auth_session
from app.modules.auth.webauthn_models import (
    WebAuthnAuthenticationTransaction,
    WebAuthnCredential,
    WebAuthnRegistrationTransaction,
    WebAuthnRelyingPartyProfile,
)
from app.modules.auth.webauthn_reset_models import WebAuthnCredentialResetRequest
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


def _seed_org(slug: str) -> tuple[UUID, UUID, UUID, UUID]:
    with TestingSessionLocal() as db:
        org = Organization(name=f"Org {slug}", slug=slug)
        db.add(org)
        db.flush()
        admin_a = User(
            organization_id=org.id,
            email=f"admin-a-{slug}@example.com",
            full_name="Admin A",
            password_hash="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        admin_b = User(
            organization_id=org.id,
            email=f"admin-b-{slug}@example.com",
            full_name="Admin B",
            password_hash="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        target = User(
            organization_id=org.id,
            email=f"target-{slug}@example.com",
            full_name="Target Handler",
            password_hash="",
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        db.add_all([admin_a, admin_b, target])
        db.flush()
        profile = WebAuthnRelyingPartyProfile(
            organization_id=org.id,
            profile_number=1,
            rp_id="claims.example.com",
            rp_name="MCRI Claims",
            allowed_origins=["https://claims.example.com"],
            user_verification="required",
            attestation="none",
            profile_hash=sha256(f"profile-{slug}".encode()).hexdigest(),
            previous_profile_hash=None,
            created_by_id=admin_a.id,
        )
        db.add(profile)
        db.add(
            MfaPolicy(
                organization_id=org.id,
                is_enabled=True,
                required_roles=[UserRole.CLAIMS_HANDLER.value],
                updated_by_id=admin_a.id,
            )
        )
        db.commit()
        return org.id, admin_a.id, admin_b.id, target.id


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


def _seed_credential(*, user_id: UUID, session_id: UUID, suffix: str) -> UUID:
    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        session = db.get(AuthSession, session_id)
        assert user is not None and session is not None
        profile = (
            db.query(WebAuthnRelyingPartyProfile)
            .filter(WebAuthnRelyingPartyProfile.organization_id == user.organization_id)
            .one()
        )
        now = datetime.now(timezone.utc)
        transaction = WebAuthnRegistrationTransaction(
            organization_id=user.organization_id,
            user_id=user.id,
            auth_session_id=session.id,
            profile_id=profile.id,
            profile_number=profile.profile_number,
            profile_hash=profile.profile_hash,
            challenge_hash=sha256(f"old-registration-{suffix}".encode()).hexdigest(),
            expires_at=now + timedelta(minutes=5),
            consumed_at=now,
        )
        db.add(transaction)
        db.flush()
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key_pem = private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii")
        credential = WebAuthnCredential(
            organization_id=user.organization_id,
            user_id=user.id,
            profile_id=profile.id,
            profile_number=profile.profile_number,
            profile_hash=profile.profile_hash,
            registration_transaction_id=transaction.id,
            credential_id_hash=sha256(f"credential-{suffix}".encode()).hexdigest(),
            public_key_pem=public_key_pem,
            algorithm=-7,
            sign_count=0,
            aaguid="0" * 32,
            attestation_format="none",
        )
        db.add(credential)
        db.commit()
        return credential.id


def _seed_open_transactions(*, user_id: UUID, session_id: UUID, suffix: str) -> tuple[UUID, UUID]:
    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        session = db.get(AuthSession, session_id)
        assert user is not None and session is not None
        profile = (
            db.query(WebAuthnRelyingPartyProfile)
            .filter(WebAuthnRelyingPartyProfile.organization_id == user.organization_id)
            .one()
        )
        now = datetime.now(timezone.utc)
        registration = WebAuthnRegistrationTransaction(
            organization_id=user.organization_id,
            user_id=user.id,
            auth_session_id=session.id,
            profile_id=profile.id,
            profile_number=profile.profile_number,
            profile_hash=profile.profile_hash,
            challenge_hash=sha256(f"open-registration-{suffix}".encode()).hexdigest(),
            expires_at=now + timedelta(minutes=5),
        )
        authentication = WebAuthnAuthenticationTransaction(
            organization_id=user.organization_id,
            user_id=user.id,
            auth_session_id=session.id,
            profile_id=profile.id,
            profile_number=profile.profile_number,
            profile_hash=profile.profile_hash,
            challenge_hash=sha256(f"open-authentication-{suffix}".encode()).hexdigest(),
            expires_at=now + timedelta(minutes=5),
        )
        db.add_all([registration, authentication])
        db.commit()
        return registration.id, authentication.id


def _registration_payload(challenge: str, *, credential_id: bytes) -> dict[str, str]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_numbers = private_key.public_key().public_numbers()
    cose = {
        1: 2,
        3: -7,
        -1: 1,
        -2: public_numbers.x.to_bytes(32, "big"),
        -3: public_numbers.y.to_bytes(32, "big"),
    }
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
            "origin": "https://claims.example.com",
            "crossOrigin": False,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "credential_id": _b64(credential_id),
        "client_data_json": _b64(client_data),
        "attestation_object": _b64(attestation),
    }


def _create_approve_execute_reset(
    *,
    admin_a_headers: dict[str, str],
    admin_b_headers: dict[str, str],
    target_id: UUID,
    credential_id: UUID,
) -> dict:
    created = client.post(
        "/api/v1/auth/webauthn-resets",
        headers=admin_a_headers,
        json={
            "user_id": str(target_id),
            "credential_id": str(credential_id),
            "reason": "Target user reported loss of the registered WebAuthn authenticator",
        },
    )
    assert created.status_code == 201, created.text
    request_id = created.json()["id"]

    self_approval = client.post(
        f"/api/v1/auth/webauthn-resets/{request_id}/approve",
        headers=admin_a_headers,
    )
    assert self_approval.status_code == 403

    approved = client.post(
        f"/api/v1/auth/webauthn-resets/{request_id}/approve",
        headers=admin_b_headers,
    )
    assert approved.status_code == 200, approved.text

    executed = client.post(
        f"/api/v1/auth/webauthn-resets/{request_id}/execute",
        headers=admin_a_headers,
    )
    assert executed.status_code == 200, executed.text
    return executed.json()


def test_four_eyes_reset_revokes_credential_sessions_and_allows_one_verified_reenrollment() -> None:
    org_id, admin_a_id, admin_b_id, target_id = _seed_org("webauthn-reset-primary")
    admin_a_headers, _ = _headers(admin_a_id)
    admin_b_headers, _ = _headers(admin_b_id)
    old_target_headers, target_session_id = _headers(target_id)
    _, second_target_session_id = _headers(target_id)
    credential_id = _seed_credential(
        user_id=target_id,
        session_id=target_session_id,
        suffix="primary",
    )
    open_registration_id, open_authentication_id = _seed_open_transactions(
        user_id=target_id,
        session_id=target_session_id,
        suffix="primary",
    )

    executed = _create_approve_execute_reset(
        admin_a_headers=admin_a_headers,
        admin_b_headers=admin_b_headers,
        target_id=target_id,
        credential_id=credential_id,
    )
    request = executed["request"]
    request_id = UUID(request["id"])
    assert executed["reenrollment_authorized"] is True
    assert executed["cancelled_registration_transactions"] == 1
    assert executed["cancelled_authentication_transactions"] == 1
    assert executed["revoked_sessions"] == 2
    assert request["reenrollment_expires_at"] is not None

    assert client.get("/api/v1/auth/me", headers=old_target_headers).status_code == 401

    with TestingSessionLocal() as db:
        old_credential = db.get(WebAuthnCredential, credential_id)
        reset = db.get(WebAuthnCredentialResetRequest, request_id)
        open_registration = db.get(WebAuthnRegistrationTransaction, open_registration_id)
        open_authentication = db.get(WebAuthnAuthenticationTransaction, open_authentication_id)
        sessions = (
            db.query(AuthSession)
            .filter(AuthSession.organization_id == org_id, AuthSession.user_id == target_id)
            .all()
        )
        assert old_credential is not None and old_credential.revoked_at is not None
        assert reset is not None and reset.reenrollment_auth_session_id is None
        assert open_registration is not None and open_registration.cancelled_at is not None
        assert open_authentication is not None and open_authentication.cancelled_at is not None
        assert {item.id for item in sessions} >= {target_session_id, second_target_session_id}
        assert all(item.revoked_at is not None for item in sessions)

    fresh_headers, fresh_session_id = _headers(target_id)
    other_headers, _ = _headers(target_id)
    begun = client.post(
        "/api/v1/auth/webauthn/registration/begin",
        headers=fresh_headers,
    )
    assert begun.status_code == 201, begun.text
    transaction_id = UUID(begun.json()["transaction_id"])

    other_session = client.post(
        "/api/v1/auth/webauthn/registration/begin",
        headers=other_headers,
    )
    assert other_session.status_code == 403
    assert other_session.json()["detail"]["code"] == "mfa_enrollment_required"

    with TestingSessionLocal() as db:
        reset = db.get(WebAuthnCredentialResetRequest, request_id)
        transaction = db.get(WebAuthnRegistrationTransaction, transaction_id)
        assert reset is not None
        assert reset.reenrollment_auth_session_id == fresh_session_id
        assert reset.reenrollment_claimed_at is not None
        assert transaction is not None
        assert transaction.reenrollment_reset_request_id == request_id

    material = _registration_payload(
        begun.json()["challenge"],
        credential_id=b"replacement-webauthn-credential-0001",
    )
    finished = client.post(
        f"/api/v1/auth/webauthn/registration/{transaction_id}/finish",
        headers=fresh_headers,
        json=material,
    )
    assert finished.status_code == 201, finished.text
    replacement_id = UUID(finished.json()["id"])
    assert replacement_id != credential_id

    with TestingSessionLocal() as db:
        reset = db.get(WebAuthnCredentialResetRequest, request_id)
        replacement = db.get(WebAuthnCredential, replacement_id)
        assert reset is not None and reset.reenrollment_consumed_at is not None
        assert reset.reenrollment_credential_id == replacement_id
        assert replacement is not None and replacement.revoked_at is None

    replay = client.post(
        "/api/v1/auth/webauthn/registration/begin",
        headers=fresh_headers,
    )
    assert replay.status_code == 403
    assert replay.json()["detail"]["code"] == "mfa_verification_required"


def test_reset_does_not_create_bypass_when_another_active_webauthn_factor_remains() -> None:
    _, admin_a_id, admin_b_id, target_id = _seed_org("webauthn-reset-multiple")
    admin_a_headers, _ = _headers(admin_a_id)
    admin_b_headers, _ = _headers(admin_b_id)
    _, target_session_id = _headers(target_id)
    first_id = _seed_credential(
        user_id=target_id,
        session_id=target_session_id,
        suffix="first",
    )
    second_id = _seed_credential(
        user_id=target_id,
        session_id=target_session_id,
        suffix="second",
    )

    executed = _create_approve_execute_reset(
        admin_a_headers=admin_a_headers,
        admin_b_headers=admin_b_headers,
        target_id=target_id,
        credential_id=first_id,
    )
    assert executed["reenrollment_authorized"] is False
    assert executed["request"]["reenrollment_expires_at"] is None

    with TestingSessionLocal() as db:
        first = db.get(WebAuthnCredential, first_id)
        second = db.get(WebAuthnCredential, second_id)
        assert first is not None and first.revoked_at is not None
        assert second is not None and second.revoked_at is None

    fresh_headers, _ = _headers(target_id)
    blocked = client.post(
        "/api/v1/auth/webauthn/registration/begin",
        headers=fresh_headers,
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "mfa_verification_required"


def test_expired_reenrollment_grant_and_tenant_crossing_fail_closed() -> None:
    _, admin_a_id, admin_b_id, target_id = _seed_org("webauthn-reset-expiry")
    _, foreign_admin_id, _, _ = _seed_org("webauthn-reset-foreign")
    admin_a_headers, _ = _headers(admin_a_id)
    admin_b_headers, _ = _headers(admin_b_id)
    foreign_headers, _ = _headers(foreign_admin_id)
    _, target_session_id = _headers(target_id)
    credential_id = _seed_credential(
        user_id=target_id,
        session_id=target_session_id,
        suffix="expiry",
    )

    created = client.post(
        "/api/v1/auth/webauthn-resets",
        headers=admin_a_headers,
        json={
            "user_id": str(target_id),
            "credential_id": str(credential_id),
            "reason": "Credential reset requested after verified loss of authenticator",
        },
    )
    assert created.status_code == 201
    request_id = UUID(created.json()["id"])

    foreign = client.post(
        f"/api/v1/auth/webauthn-resets/{request_id}/approve",
        headers=foreign_headers,
    )
    assert foreign.status_code == 404

    approved = client.post(
        f"/api/v1/auth/webauthn-resets/{request_id}/approve",
        headers=admin_b_headers,
    )
    assert approved.status_code == 200
    executed = client.post(
        f"/api/v1/auth/webauthn-resets/{request_id}/execute",
        headers=admin_a_headers,
    )
    assert executed.status_code == 200
    assert executed.json()["reenrollment_authorized"] is True

    with TestingSessionLocal() as db:
        reset = db.get(WebAuthnCredentialResetRequest, request_id)
        assert reset is not None
        reset.reenrollment_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    fresh_headers, _ = _headers(target_id)
    expired = client.post(
        "/api/v1/auth/webauthn/registration/begin",
        headers=fresh_headers,
    )
    assert expired.status_code == 403
    assert expired.json()["detail"]["code"] == "mfa_enrollment_required"


def test_webauthn_reset_admin_surface_obeys_enabled_admin_mfa_policy() -> None:
    org_id, admin_a_id, _, _ = _seed_org("webauthn-reset-admin-policy")
    admin_headers, _ = _headers(admin_a_id)
    with TestingSessionLocal() as db:
        policy = (
            db.query(MfaPolicy)
            .filter(MfaPolicy.organization_id == org_id)
            .one()
        )
        policy.required_roles = [UserRole.ADMIN.value]
        db.commit()

    blocked = client.get("/api/v1/auth/webauthn-resets", headers=admin_headers)
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "mfa_enrollment_required"
