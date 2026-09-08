import base64
import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from app.modules.auth.mfa_policy_models import MfaPolicy
from app.modules.auth.models import AuthSession
from app.modules.auth.service import create_auth_session
from app.modules.auth.webauthn_models import (
    WebAuthnAuthenticationTransaction,
    WebAuthnCredential,
    WebAuthnRegistrationTransaction,
    WebAuthnRelyingPartyProfile,
)
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _seed_org(slug: str, *, two_users: bool = False) -> tuple[UUID, UUID, UUID | None]:
    with TestingSessionLocal() as db:
        org = Organization(name=f"Org {slug}", slug=slug)
        db.add(org)
        db.flush()
        admin = User(
            organization_id=org.id,
            email=f"admin-{slug}@example.com",
            full_name="Identity Admin",
            password_hash="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin)
        other = None
        if two_users:
            other = User(
                organization_id=org.id,
                email=f"other-{slug}@example.com",
                full_name="Other Admin",
                password_hash="",
                role=UserRole.ADMIN,
                is_active=True,
            )
            db.add(other)
        db.commit()
        return org.id, admin.id, None if other is None else other.id


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


def _create_profile(headers: dict[str, str]) -> dict:
    response = client.post(
        "/api/v1/auth/webauthn/rp-profiles",
        headers=headers,
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


def _seed_credential(
    user_id: UUID,
    session_id: UUID,
    *,
    credential_id: bytes,
    algorithm: int = -7,
    sign_count: int = 0,
):
    if algorithm == -7:
        private_key = ec.generate_private_key(ec.SECP256R1())
    elif algorithm == -257:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    else:
        raise AssertionError("unsupported test algorithm")
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        profile = (
            db.query(WebAuthnRelyingPartyProfile)
            .filter(WebAuthnRelyingPartyProfile.organization_id == user.organization_id)
            .order_by(WebAuthnRelyingPartyProfile.profile_number.desc())
            .first()
        )
        assert profile is not None
        now = datetime.now(timezone.utc)
        registration = WebAuthnRegistrationTransaction(
            organization_id=user.organization_id,
            user_id=user.id,
            auth_session_id=session_id,
            profile_id=profile.id,
            profile_number=profile.profile_number,
            profile_hash=profile.profile_hash,
            challenge_hash=sha256(credential_id + b"-registration").hexdigest(),
            expires_at=now + timedelta(minutes=5),
            consumed_at=now,
        )
        db.add(registration)
        db.flush()
        credential = WebAuthnCredential(
            organization_id=user.organization_id,
            user_id=user.id,
            profile_id=profile.id,
            profile_number=profile.profile_number,
            profile_hash=profile.profile_hash,
            registration_transaction_id=registration.id,
            credential_id_hash=sha256(credential_id).hexdigest(),
            public_key_pem=public_key_pem,
            algorithm=algorithm,
            sign_count=sign_count,
            aaguid="0" * 32,
            attestation_format="none",
        )
        db.add(credential)
        db.commit()
        return credential.id, private_key


def _begin(headers: dict[str, str]) -> dict:
    response = client.post(
        "/api/v1/auth/webauthn/authentication/begin",
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _assertion_payload(
    *,
    challenge: str,
    credential_id: bytes,
    private_key,
    sign_count: int,
    origin: str = "https://claims.example.com",
    rp_id: str = "claims.example.com",
    flags: int = 0x05,
    cross_origin: bool = False,
    tamper_signature: bool = False,
) -> dict[str, str]:
    client_data = json.dumps(
        {
            "type": "webauthn.get",
            "challenge": challenge,
            "origin": origin,
            "crossOrigin": cross_origin,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    authenticator_data = (
        sha256(rp_id.encode("utf-8")).digest()
        + bytes([flags])
        + sign_count.to_bytes(4, "big")
    )
    signed = authenticator_data + sha256(client_data).digest()
    if isinstance(private_key, ec.EllipticCurvePrivateKey):
        signature = private_key.sign(signed, ec.ECDSA(hashes.SHA256()))
    else:
        signature = private_key.sign(signed, padding.PKCS1v15(), hashes.SHA256())
    if tamper_signature:
        signature = signature[:-1] + bytes([signature[-1] ^ 0x01])
    return {
        "credential_id": _b64(credential_id),
        "client_data_json": _b64(client_data),
        "authenticator_data": _b64(authenticator_data),
        "signature": _b64(signature),
    }


def _finish(
    headers: dict[str, str],
    begun: dict,
    *,
    credential_id: bytes,
    private_key,
    sign_count: int,
    **overrides,
):
    payload = _assertion_payload(
        challenge=overrides.pop("challenge", begun["challenge"]),
        credential_id=credential_id,
        private_key=private_key,
        sign_count=sign_count,
        **overrides,
    )
    response = client.post(
        f"/api/v1/auth/webauthn/authentication/{begun['transaction_id']}/finish",
        headers=headers,
        json=payload,
    )
    return response, payload


def test_es256_assertion_elevates_only_exact_session_and_keeps_raw_assertion_out_of_custody() -> None:
    _, user_id, _ = _seed_org("webauthn-auth-es")
    headers, session_id = _headers(user_id)
    _create_profile(headers)
    raw_credential_id = b"webauthn-auth-es256-credential-0001"
    credential_id, private_key = _seed_credential(
        user_id,
        session_id,
        credential_id=raw_credential_id,
    )

    begun = _begin(headers)
    assert begun["rp_id"] == "claims.example.com"
    assert begun["user_verification"] == "required"
    challenge = begun["challenge"]
    transaction_id = UUID(begun["transaction_id"])

    with TestingSessionLocal() as db:
        transaction = db.get(WebAuthnAuthenticationTransaction, transaction_id)
        assert transaction is not None
        assert transaction.challenge_hash == sha256(challenge.encode("ascii")).hexdigest()
        assert challenge not in json.dumps(transaction.__dict__, default=str)
        begin_audits = db.query(AuditLog).filter(AuditLog.entity_id == transaction_id).all()
        assert begin_audits
        assert challenge not in json.dumps(
            [{"old": row.old_values, "new": row.new_values, "details": row.details} for row in begin_audits],
            default=str,
        )

    finished, material = _finish(
        headers,
        begun,
        credential_id=raw_credential_id,
        private_key=private_key,
        sign_count=1,
    )
    assert finished.status_code == 200, finished.text
    verified = finished.json()
    assert verified["auth_session_id"] == str(session_id)
    assert verified["mfa_method"] == "webauthn"
    assert verified["credential_id"] == str(credential_id)
    assert verified["sign_count"] == 1

    with TestingSessionLocal() as db:
        session = db.get(AuthSession, session_id)
        transaction = db.get(WebAuthnAuthenticationTransaction, transaction_id)
        credential = db.get(WebAuthnCredential, credential_id)
        user = db.get(User, user_id)
        assert session is not None and session.mfa_verified_at is not None
        assert session.mfa_method == "webauthn"
        assert session.mfa_factor_id is None
        assert transaction is not None and transaction.consumed_at is not None
        assert transaction.credential_id == credential_id
        assert transaction.consumed_at == session.mfa_verified_at
        assert credential is not None and credential.sign_count == 1
        assert user is not None and user.role == UserRole.ADMIN
        assert _b64(raw_credential_id) not in json.dumps(transaction.__dict__, default=str)
        audit_rows = db.query(AuditLog).filter(AuditLog.action == "WEBAUTHN_MFA_SESSION_VERIFIED").all()
        assert audit_rows
        audit_dump = json.dumps(
            [{"old": row.old_values, "new": row.new_values, "details": row.details} for row in audit_rows],
            default=str,
        )
        for raw_value in material.values():
            assert raw_value not in audit_dump

    replay, _ = _finish(
        headers,
        begun,
        credential_id=raw_credential_id,
        private_key=private_key,
        sign_count=2,
    )
    assert replay.status_code == 409


def test_challenge_origin_rp_uv_and_signature_failures_do_not_consume_assertion() -> None:
    _, user_id, _ = _seed_org("webauthn-auth-fail")
    headers, session_id = _headers(user_id)
    _create_profile(headers)
    raw_credential_id = b"webauthn-auth-failure-credential-0001"
    credential_id, private_key = _seed_credential(
        user_id,
        session_id,
        credential_id=raw_credential_id,
    )

    cases = [
        {"challenge": _b64(b"wrong-challenge-value-32-bytes-xxxx")},
        {"origin": "https://evil.example.com"},
        {"rp_id": "evil.example.com"},
        {"flags": 0x01},
        {"cross_origin": True},
        {"tamper_signature": True},
    ]
    for index, overrides in enumerate(cases, start=1):
        begun = _begin(headers)
        rejected, _ = _finish(
            headers,
            begun,
            credential_id=raw_credential_id,
            private_key=private_key,
            sign_count=index,
            **overrides,
        )
        assert rejected.status_code == 401, (overrides, rejected.text)
        with TestingSessionLocal() as db:
            transaction = db.get(
                WebAuthnAuthenticationTransaction,
                UUID(begun["transaction_id"]),
            )
            credential = db.get(WebAuthnCredential, credential_id)
            assert transaction is not None and transaction.consumed_at is None
            assert transaction.credential_id is None
            assert credential is not None and credential.sign_count == 0


def test_rs256_and_zero_counter_authenticators_are_supported_without_counter_invention() -> None:
    _, user_id, _ = _seed_org("webauthn-auth-rs")
    headers, session_id = _headers(user_id)
    _create_profile(headers)
    raw_credential_id = b"webauthn-auth-rs256-credential-0001"
    credential_id, private_key = _seed_credential(
        user_id,
        session_id,
        credential_id=raw_credential_id,
        algorithm=-257,
        sign_count=0,
    )

    first = _begin(headers)
    accepted, _ = _finish(
        headers,
        first,
        credential_id=raw_credential_id,
        private_key=private_key,
        sign_count=0,
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["sign_count"] == 0

    second = _begin(headers)
    accepted_again, _ = _finish(
        headers,
        second,
        credential_id=raw_credential_id,
        private_key=private_key,
        sign_count=0,
    )
    assert accepted_again.status_code == 200, accepted_again.text
    with TestingSessionLocal() as db:
        credential = db.get(WebAuthnCredential, credential_id)
        assert credential is not None and credential.sign_count == 0


def test_counter_regression_foreign_session_and_foreign_user_credential_fail_closed() -> None:
    _, user_id, other_user_id = _seed_org("webauthn-auth-scope", two_users=True)
    assert other_user_id is not None
    first_headers, first_session = _headers(user_id)
    second_headers, second_session = _headers(user_id)
    other_headers, other_session = _headers(other_user_id)
    _create_profile(first_headers)

    first_raw_id = b"webauthn-auth-scope-first-credential-0001"
    first_credential_id, first_key = _seed_credential(
        user_id,
        first_session,
        credential_id=first_raw_id,
        sign_count=7,
    )
    other_raw_id = b"webauthn-auth-scope-other-credential-0001"
    _, other_key = _seed_credential(
        other_user_id,
        other_session,
        credential_id=other_raw_id,
    )

    begun = _begin(first_headers)
    wrong_session, _ = _finish(
        second_headers,
        begun,
        credential_id=first_raw_id,
        private_key=first_key,
        sign_count=8,
    )
    assert wrong_session.status_code == 409

    counter_replay, _ = _finish(
        first_headers,
        begun,
        credential_id=first_raw_id,
        private_key=first_key,
        sign_count=7,
    )
    assert counter_replay.status_code == 401
    with TestingSessionLocal() as db:
        transaction = db.get(WebAuthnAuthenticationTransaction, UUID(begun["transaction_id"]))
        credential = db.get(WebAuthnCredential, first_credential_id)
        assert transaction is not None and transaction.consumed_at is None
        assert credential is not None and credential.sign_count == 7

    other_begun = _begin(other_headers)
    foreign_credential, _ = _finish(
        other_headers,
        other_begun,
        credential_id=first_raw_id,
        private_key=first_key,
        sign_count=8,
    )
    assert foreign_credential.status_code == 401

    own_accepted, _ = _finish(
        other_headers,
        other_begun,
        credential_id=other_raw_id,
        private_key=other_key,
        sign_count=1,
    )
    assert own_accepted.status_code == 200, own_accepted.text


def test_verified_webauthn_satisfies_tenant_mfa_policy_and_revocation_invalidates_it() -> None:
    org_id, admin_id, _ = _seed_org("webauthn-auth-policy")
    headers, session_id = _headers(admin_id)
    _create_profile(headers)
    raw_credential_id = b"webauthn-auth-policy-credential-0001"
    credential_id, private_key = _seed_credential(
        admin_id,
        session_id,
        credential_id=raw_credential_id,
    )

    with TestingSessionLocal() as db:
        db.add(
            MfaPolicy(
                organization_id=org_id,
                is_enabled=True,
                required_roles=["admin"],
                updated_by_id=admin_id,
            )
        )
        db.commit()

    blocked = client.get("/api/v1/auth/webauthn/rp-profile", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "mfa_verification_required"

    begun = _begin(headers)
    verified, _ = _finish(
        headers,
        begun,
        credential_id=raw_credential_id,
        private_key=private_key,
        sign_count=1,
    )
    assert verified.status_code == 200, verified.text

    allowed = client.get("/api/v1/auth/webauthn/rp-profile", headers=headers)
    assert allowed.status_code == 200, allowed.text

    with TestingSessionLocal() as db:
        credential = db.get(WebAuthnCredential, credential_id)
        assert credential is not None
        credential.revoked_at = datetime.now(timezone.utc)
        db.commit()

    blocked_after_revoke = client.get("/api/v1/auth/webauthn/rp-profile", headers=headers)
    assert blocked_after_revoke.status_code == 403
    assert blocked_after_revoke.json()["detail"]["code"] == "mfa_enrollment_required"
