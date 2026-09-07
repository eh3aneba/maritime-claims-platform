import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from app.modules.auth.models import AuthSession, ExternalIdentityBinding
from app.modules.auth.saml_models import SamlTrustRuntimeProfile
from app.modules.auth.service import create_auth_session
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


def _seed_tenants() -> tuple[UUID, UUID, UUID, UUID]:
    with TestingSessionLocal() as db:
        alpha = Organization(name="SAML Alpha Marine", slug="saml-alpha")
        beta = Organization(name="SAML Beta Marine", slug="saml-beta")
        db.add_all([alpha, beta])
        db.flush()
        alpha_admin = User(
            organization_id=alpha.id,
            email="saml-alpha-admin@example.com",
            full_name="SAML Alpha Admin",
            password_hash="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        beta_admin = User(
            organization_id=beta.id,
            email="saml-beta-admin@example.com",
            full_name="SAML Beta Admin",
            password_hash="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add_all([alpha_admin, beta_admin])
        db.commit()
        return alpha.id, alpha_admin.id, beta.id, beta_admin.id


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


def _provider(
    headers: dict[str, str],
    *,
    protocol: str = "saml",
    provider_key: str = "corp-saml",
    issuer: str = "https://idp.saml.example.test/entity",
    enable: bool = True,
) -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/identity-providers",
        headers=headers,
        json={
            "provider_key": provider_key,
            "display_name": f"Corporate {protocol.upper()}",
            "protocol": protocol,
            "issuer_identifier": issuer,
        },
    )
    assert response.status_code == 201
    provider = response.json()
    if enable:
        response = client.post(
            f"/api/v1/auth/identity-providers/{provider['id']}/enable",
            headers=headers,
        )
        assert response.status_code == 200
    return provider


def _certificate_pem(
    *,
    expired: bool = False,
    ec_key: bool = False,
) -> str:
    private_key = (
        ec.generate_private_key(ec.SECP256R1())
        if ec_key
        else rsa.generate_private_key(public_exponent=65537, key_size=2048)
    )
    now = datetime.now(timezone.utc)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "MCRI SAML Test IdP")]
    )
    not_before = now - timedelta(days=10)
    not_after = now - timedelta(days=1) if expired else now + timedelta(days=365)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .sign(private_key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")


def _profile_payload(certificate_pem: str) -> dict[str, object]:
    return {
        "idp_sso_url": "https://idp.saml.example.test/sso",
        "sp_entity_id": "https://mcri.example.test/saml/sp",
        "acs_url": "https://mcri.example.test/api/v1/auth/saml/acs",
        "authn_request_binding": "HTTP-Redirect",
        "response_binding": "HTTP-POST",
        "allowed_signature_algorithms": ["RSA-SHA256"],
        "allowed_digest_algorithms": ["SHA-256"],
        "idp_signing_certificate_pem": certificate_pem,
    }


def test_saml_profile_is_immutable_idempotent_and_has_no_auth_side_effects() -> None:
    _, alpha_admin_id, _, _ = _seed_tenants()
    headers = _headers(alpha_admin_id)
    provider = _provider(headers)
    payload = _profile_payload(_certificate_pem())

    with TestingSessionLocal() as db:
        users_before = db.query(User).count()
        bindings_before = db.query(ExternalIdentityBinding).count()
        sessions_before = db.query(AuthSession).count()

    response = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/saml-trust-runtime-profiles",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 201
    first = response.json()
    assert first["profile_number"] == 1
    assert first["idp_entity_identifier"] == provider["issuer_identifier"]
    assert first["authn_request_binding"] == "HTTP-Redirect"
    assert first["response_binding"] == "HTTP-POST"
    assert first["allowed_signature_algorithms"] == ["RSA-SHA256"]
    assert first["allowed_digest_algorithms"] == ["SHA-256"]
    assert len(first["certificate_sha256"]) == 64
    assert "BEGIN CERTIFICATE" in first["idp_signing_certificate_pem"]
    assert "PRIVATE KEY" not in first["idp_signing_certificate_pem"]

    replay = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/saml-trust-runtime-profiles",
        headers=headers,
        json=payload,
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == first["id"]

    changed = dict(payload)
    changed["idp_sso_url"] = "https://idp.saml.example.test/sso-v2"
    response = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/saml-trust-runtime-profiles",
        headers=headers,
        json=changed,
    )
    assert response.status_code == 201
    second = response.json()
    assert second["profile_number"] == 2
    assert second["previous_profile_hash"] == first["profile_hash"]
    assert second["profile_hash"] != first["profile_hash"]

    current = client.get(
        f"/api/v1/auth/identity-providers/{provider['id']}/saml-trust-runtime-profile",
        headers=headers,
    )
    assert current.status_code == 200
    assert current.json()["id"] == second["id"]

    history = client.get(
        f"/api/v1/auth/identity-providers/{provider['id']}/saml-trust-runtime-profiles",
        headers=headers,
    )
    assert history.status_code == 200
    assert [item["profile_number"] for item in history.json()] == [1, 2]

    with TestingSessionLocal() as db:
        assert db.query(SamlTrustRuntimeProfile).count() == 2
        assert db.query(User).count() == users_before
        assert db.query(ExternalIdentityBinding).count() == bindings_before
        assert db.query(AuthSession).count() == sessions_before
        audits = db.query(AuditLog).filter(
            AuditLog.action == "SAML_TRUST_RUNTIME_PROFILE_PINNED"
        ).all()
        serialized = json.dumps([row.new_values or {} for row in audits], sort_keys=True)
        assert "BEGIN CERTIFICATE" not in serialized
        assert "PRIVATE KEY" not in serialized


def test_saml_profile_fails_closed_for_protocol_tenant_and_unsafe_input() -> None:
    _, alpha_admin_id, _, beta_admin_id = _seed_tenants()
    alpha_headers = _headers(alpha_admin_id)
    beta_headers = _headers(beta_admin_id)
    certificate = _certificate_pem()

    disabled = _provider(alpha_headers, provider_key="disabled-saml", enable=False)
    response = client.post(
        f"/api/v1/auth/identity-providers/{disabled['id']}/saml-trust-runtime-profiles",
        headers=alpha_headers,
        json=_profile_payload(certificate),
    )
    assert response.status_code == 409

    saml_provider = _provider(alpha_headers, provider_key="enabled-saml")
    cross_tenant = client.get(
        f"/api/v1/auth/identity-providers/{saml_provider['id']}/saml-trust-runtime-profiles",
        headers=beta_headers,
    )
    assert cross_tenant.status_code == 404

    oidc_provider = _provider(
        alpha_headers,
        protocol="oidc",
        provider_key="wrong-protocol",
        issuer="https://oidc.saml-foundation.example.test",
    )
    response = client.post(
        f"/api/v1/auth/identity-providers/{oidc_provider['id']}/saml-trust-runtime-profiles",
        headers=alpha_headers,
        json=_profile_payload(certificate),
    )
    assert response.status_code == 409

    unsafe_url = _profile_payload(certificate)
    unsafe_url["idp_sso_url"] = "http://idp.saml.example.test/sso"
    response = client.post(
        f"/api/v1/auth/identity-providers/{saml_provider['id']}/saml-trust-runtime-profiles",
        headers=alpha_headers,
        json=unsafe_url,
    )
    assert response.status_code == 409

    unsupported = _profile_payload(certificate)
    unsupported["allowed_signature_algorithms"] = ["RSA-SHA1"]
    response = client.post(
        f"/api/v1/auth/identity-providers/{saml_provider['id']}/saml-trust-runtime-profiles",
        headers=alpha_headers,
        json=unsupported,
    )
    assert response.status_code == 409

    malformed = _profile_payload(
        "-----BEGIN CERTIFICATE-----\n" + "A" * 256 + "\n-----END CERTIFICATE-----\n"
    )
    response = client.post(
        f"/api/v1/auth/identity-providers/{saml_provider['id']}/saml-trust-runtime-profiles",
        headers=alpha_headers,
        json=malformed,
    )
    assert response.status_code == 409


def test_saml_profile_entity_identifier_is_server_derived() -> None:
    _, alpha_admin_id, _, _ = _seed_tenants()
    headers = _headers(alpha_admin_id)
    provider = _provider(
        headers,
        issuer="urn:mcri:test:idp:authoritative-entity",
    )
    payload = _profile_payload(_certificate_pem())
    attempted_override = dict(payload)
    attempted_override["idp_entity_identifier"] = "urn:attacker:override"

    response = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/saml-trust-runtime-profiles",
        headers=headers,
        json=attempted_override,
    )
    assert response.status_code == 422

    response = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/saml-trust-runtime-profiles",
        headers=headers,
        json=payload,
    )
    assert response.status_code == 201
    assert response.json()["idp_entity_identifier"] == provider["issuer_identifier"]


def test_saml_profile_requires_current_rsa_signing_certificate() -> None:
    _, alpha_admin_id, _, _ = _seed_tenants()
    headers = _headers(alpha_admin_id)
    provider = _provider(headers)

    for certificate in (_certificate_pem(expired=True), _certificate_pem(ec_key=True)):
        response = client.post(
            f"/api/v1/auth/identity-providers/{provider['id']}/saml-trust-runtime-profiles",
            headers=headers,
            json=_profile_payload(certificate),
        )
        assert response.status_code == 409

    with TestingSessionLocal() as db:
        assert db.query(SamlTrustRuntimeProfile).count() == 0
