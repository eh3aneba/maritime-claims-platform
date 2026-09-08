import base64
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from app.modules.auth.models import AuthSession, EnterpriseIdentityProvider
from app.modules.auth.oidc_assurance_models import (
    OidcMfaAssuranceBinding,
    OidcMfaAssuranceProfile,
)
from app.modules.auth.service import create_auth_session, create_external_identity_binding
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database

ISSUER = "https://issuer.assurance.example.test"
AUDIENCE = "mcri-assurance-client"


def setup_function() -> None:
    reset_database()


def _seed() -> tuple[UUID, UUID]:
    with TestingSessionLocal() as db:
        org = Organization(name="OIDC Assurance Marine", slug="oidc-assurance-marine")
        db.add(org)
        db.flush()
        admin = User(
            organization_id=org.id,
            email="oidc-assurance-admin@example.com",
            full_name="OIDC Assurance Admin",
            password_hash="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        return org.id, admin.id


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


def _create_stack(headers: dict[str, str]) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/identity-providers",
        headers=headers,
        json={
            "provider_key": "corp-oidc",
            "display_name": "Corporate OIDC",
            "protocol": "oidc",
            "issuer_identifier": ISSUER,
        },
    )
    assert response.status_code == 201
    provider = response.json()
    assert client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/enable",
        headers=headers,
    ).status_code == 200
    trust_response = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/oidc-trust-profiles",
        headers=headers,
        json={
            "audience": AUDIENCE,
            "jwks_uri": f"{ISSUER}/.well-known/jwks.json",
            "allowed_algorithms": ["RS256"],
        },
    )
    assert trust_response.status_code == 201
    runtime_response = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/oidc-runtime-profiles",
        headers=headers,
        json={
            "authorization_endpoint": f"{ISSUER}/authorize",
            "token_endpoint": f"{ISSUER}/token",
            "redirect_uri": "https://mcri.example.test/api/v1/auth/oidc/callback",
            "scopes": ["openid", "profile", "email"],
            "client_auth_method": "none",
        },
    )
    assert runtime_response.status_code == 201
    return {
        "provider": provider,
        "trust": trust_response.json(),
        "runtime": runtime_response.json(),
    }


def _bind(provider_id: str, user_id: UUID, *, subject: str = "assurance-subject") -> None:
    with TestingSessionLocal() as db:
        provider = db.get(EnterpriseIdentityProvider, UUID(provider_id))
        user = db.get(User, user_id)
        assert provider is not None and user is not None
        create_external_identity_binding(
            db,
            provider=provider,
            user=user,
            external_subject=subject,
        )
        db.commit()


def _profile(
    headers: dict[str, str],
    provider_id: str,
    *,
    enabled: bool,
    amr: list[str] | None = None,
    acr: list[str] | None = None,
):
    return client.post(
        f"/api/v1/auth/identity-providers/{provider_id}/oidc-mfa-assurance-profiles",
        headers=headers,
        json={
            "enabled": enabled,
            "accepted_amr_values": amr or [],
            "accepted_acr_values": acr or [],
        },
    )


def _start() -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/oidc/transactions",
        json={
            "organization_slug": "oidc-assurance-marine",
            "provider_key": "corp-oidc",
        },
    )
    assert response.status_code == 201
    return response.json()


def _b64_uint(value: int) -> str:
    size = max(1, (value.bit_length() + 7) // 8)
    return base64.urlsafe_b64encode(value.to_bytes(size, "big")).rstrip(b"=").decode("ascii")


def _rsa_signer():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "kid": "assurance-rsa-key",
        "use": "sig",
        "alg": "RS256",
        "n": _b64_uint(numbers.n),
        "e": _b64_uint(numbers.e),
    }
    return private_key, jwk


def _id_token(private_key, jwk, *, nonce: str, claims: dict[str, object] | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "assurance-subject",
        "nonce": nonce,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        # Deliberately hostile authorization-like claims; DB role remains authoritative.
        "role": "super-admin",
        "groups": ["global-admin"],
    }
    if claims:
        payload.update(claims)
    return jwt.encode(
        payload,
        private_key,
        algorithm="RS256",
        headers={"kid": jwk["kid"]},
    )


def _install_provider(monkeypatch, *, token: str, jwk: dict[str, str]) -> None:
    monkeypatch.setattr(
        "app.modules.auth.oidc_callback._post_token_request",
        lambda **_: {"token_type": "Bearer", "access_token": "not-persisted", "id_token": token},
    )
    monkeypatch.setattr(
        "app.modules.auth.oidc_callback._get_jwks",
        lambda **_: {"keys": [jwk]},
    )


def _callback(start: dict[str, object]):
    return client.post(
        "/api/v1/auth/oidc/callback",
        json={
            "transaction_id": start["transaction_id"],
            "state": start["state"],
            "nonce": start["nonce"],
            "code_verifier": start["code_verifier"],
            "authorization_code": "one-time-code",
        },
    )


def test_profile_is_immutable_normalized_and_enabled_requires_evidence() -> None:
    _, admin_id = _seed()
    headers = _headers(admin_id)
    stack = _create_stack(headers)
    provider_id = str(stack["provider"]["id"])

    rejected = _profile(headers, provider_id, enabled=True)
    assert rejected.status_code == 409

    first = _profile(
        headers,
        provider_id,
        enabled=True,
        amr=["MFA", "hwk"],
        acr=["urn:example:loa:2"],
    )
    assert first.status_code == 201
    payload = first.json()
    assert payload["profile_number"] == 1
    assert payload["accepted_amr_values"] == ["hwk", "mfa"]
    assert payload["accepted_acr_values"] == ["urn:example:loa:2"]

    second = _profile(headers, provider_id, enabled=False)
    assert second.status_code == 201
    assert second.json()["profile_number"] == 2
    assert second.json()["previous_profile_hash"] == payload["profile_hash"]

    with TestingSessionLocal() as db:
        assert db.query(OidcMfaAssuranceProfile).count() == 2


def test_transaction_pins_profile_and_midflight_rotation_cannot_change_authority(monkeypatch) -> None:
    _, admin_id = _seed()
    headers = _headers(admin_id)
    stack = _create_stack(headers)
    provider_id = str(stack["provider"]["id"])
    _bind(provider_id, admin_id)

    profile_a = _profile(headers, provider_id, enabled=True, amr=["mfa"])
    assert profile_a.status_code == 201
    start = _start()
    profile_b = _profile(headers, provider_id, enabled=True, amr=["hwk"])
    assert profile_b.status_code == 201

    private_key, jwk = _rsa_signer()
    token = _id_token(private_key, jwk, nonce=str(start["nonce"]), claims={"amr": ["pwd", "MFA"]})
    _install_provider(monkeypatch, token=token, jwk=jwk)
    response = _callback(start)
    assert response.status_code == 200
    assert response.json()["user"]["role"] == UserRole.ADMIN.value

    with TestingSessionLocal() as db:
        binding = db.query(OidcMfaAssuranceBinding).filter(
            OidcMfaAssuranceBinding.transaction_id == UUID(str(start["transaction_id"]))
        ).one()
        assert binding.assurance_profile_id == UUID(profile_a.json()["id"])
        assert binding.assurance_profile_id != UUID(profile_b.json()["id"])
        assert binding.verified_at is not None
        assert binding.evidence_type == "amr"
        assert binding.evidence_hash and binding.evidence_hash != "mfa"
        session = db.query(AuthSession).filter(
            AuthSession.oidc_authorization_transaction_id == UUID(str(start["transaction_id"]))
        ).one()
        assert session.mfa_method == "oidc_external"
        assert session.mfa_verified_at is not None
        assert session.mfa_factor_id is None


def test_pinned_absence_and_malformed_or_nonmatching_claims_do_not_elevate_login(monkeypatch) -> None:
    _, admin_id = _seed()
    headers = _headers(admin_id)
    stack = _create_stack(headers)
    provider_id = str(stack["provider"]["id"])
    _bind(provider_id, admin_id)

    # The transaction explicitly pins absence because no assurance profile exists yet.
    start_absent = _start()
    assert _profile(headers, provider_id, enabled=True, amr=["mfa"]).status_code == 201
    private_key, jwk = _rsa_signer()
    token = _id_token(private_key, jwk, nonce=str(start_absent["nonce"]), claims={"amr": ["mfa"]})
    _install_provider(monkeypatch, token=token, jwk=jwk)
    response = _callback(start_absent)
    assert response.status_code == 200
    with TestingSessionLocal() as db:
        session = db.query(AuthSession).filter(
            AuthSession.oidc_authorization_transaction_id == UUID(str(start_absent["transaction_id"]))
        ).one()
        assert session.mfa_verified_at is None
        assert session.mfa_method is None

    # A malformed AMR claim must not break otherwise valid OIDC identity authentication.
    start_malformed = _start()
    token = _id_token(
        private_key,
        jwk,
        nonce=str(start_malformed["nonce"]),
        claims={"amr": ["mfa", 7], "acr": 42},
    )
    _install_provider(monkeypatch, token=token, jwk=jwk)
    response = _callback(start_malformed)
    assert response.status_code == 200
    with TestingSessionLocal() as db:
        session = db.query(AuthSession).filter(
            AuthSession.oidc_authorization_transaction_id == UUID(str(start_malformed["transaction_id"]))
        ).one()
        assert session.mfa_verified_at is None
        assert session.mfa_method is None


def test_acr_equivalence_satisfies_mfa_policy_only_for_exact_assured_session(monkeypatch) -> None:
    _, admin_id = _seed()
    headers = _headers(admin_id)
    stack = _create_stack(headers)
    provider_id = str(stack["provider"]["id"])
    _bind(provider_id, admin_id)
    assurance_value = "urn:example:loa:gold-mfa"
    assert _profile(headers, provider_id, enabled=True, acr=[assurance_value]).status_code == 201

    # Enable tenant MFA last, while the current local admin session is still allowed to mutate policy.
    policy = client.put(
        "/api/v1/auth/mfa-policy",
        headers=headers,
        json={"is_enabled": True, "required_roles": ["admin"]},
    )
    assert policy.status_code == 200

    private_key, jwk = _rsa_signer()
    assured_start = _start()
    assured_token = _id_token(
        private_key,
        jwk,
        nonce=str(assured_start["nonce"]),
        claims={"acr": assurance_value},
    )
    _install_provider(monkeypatch, token=assured_token, jwk=jwk)
    assured = _callback(assured_start)
    assert assured.status_code == 200
    assured_headers = {"Authorization": f"Bearer {assured.json()['access_token']}"}
    sensitive = client.get(
        f"/api/v1/auth/identity-providers/{provider_id}/oidc-mfa-assurance-profile",
        headers=assured_headers,
    )
    assert sensitive.status_code == 200

    unassured_start = _start()
    unassured_token = _id_token(
        private_key,
        jwk,
        nonce=str(unassured_start["nonce"]),
        claims={"acr": "urn:example:loa:password-only"},
    )
    _install_provider(monkeypatch, token=unassured_token, jwk=jwk)
    unassured = _callback(unassured_start)
    assert unassured.status_code == 200
    unassured_headers = {"Authorization": f"Bearer {unassured.json()['access_token']}"}
    blocked = client.get(
        f"/api/v1/auth/identity-providers/{provider_id}/oidc-mfa-assurance-profile",
        headers=unassured_headers,
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "mfa_enrollment_required"

    with TestingSessionLocal() as db:
        audits = db.query(AuditLog).filter(
            AuditLog.action.in_(["OIDC_LOGIN_SUCCESS", "OIDC_AUTHORIZATION_TRANSACTION_CREATED"])
        ).all()
        serialized = json.dumps([row.new_values or {} for row in audits], sort_keys=True)
        assert assurance_value not in serialized
        assert "one-time-code" not in serialized
        assert "not-persisted" not in serialized
