import json
from hashlib import sha256
from uuid import UUID

from app.core.security import create_access_token
from app.modules.auth.models import AuthSession, OidcTrustProfile
from app.modules.auth.service import create_auth_session
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


def _seed() -> tuple[UUID, UUID, UUID, UUID, UUID]:
    with TestingSessionLocal() as db:
        org_a = Organization(name="Alpha Marine", slug="alpha-oidc-trust")
        org_b = Organization(name="Beta Marine", slug="beta-oidc-trust")
        db.add_all([org_a, org_b])
        db.flush()

        admin_a = User(
            organization_id=org_a.id,
            email="alpha-admin-trust@example.com",
            full_name="Alpha Admin",
            password_hash="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        handler_a = User(
            organization_id=org_a.id,
            email="alpha-handler-trust@example.com",
            full_name="Alpha Handler",
            password_hash="",
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        admin_b = User(
            organization_id=org_b.id,
            email="beta-admin-trust@example.com",
            full_name="Beta Admin",
            password_hash="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add_all([admin_a, handler_a, admin_b])
        db.commit()
        return org_a.id, admin_a.id, handler_a.id, org_b.id, admin_b.id


def _headers(user_id: UUID) -> dict[str, str]:
    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        assert user is not None
        auth_session = create_auth_session(db, user=user)
        db.commit()
        token = create_access_token(
            user_id=user.id,
            organization_id=user.organization_id,
            role=user.role.value,
            session_id=auth_session.id,
            identity_source=auth_session.identity_source,
            auth_method=auth_session.auth_method,
        )
    return {"Authorization": f"Bearer {token}"}


def _create_provider(
    headers: dict[str, str],
    *,
    protocol: str = "oidc",
    issuer: str = "https://issuer.alpha.example.test",
    enabled: bool = True,
    provider_key: str = "corp-oidc",
) -> dict[str, object]:
    created = client.post(
        "/api/v1/auth/identity-providers",
        headers=headers,
        json={
            "provider_key": provider_key,
            "display_name": f"Corporate {protocol.upper()}",
            "protocol": protocol,
            "issuer_identifier": issuer,
        },
    )
    assert created.status_code == 201
    provider = created.json()
    if enabled:
        response = client.post(
            f"/api/v1/auth/identity-providers/{provider['id']}/enable",
            headers=headers,
        )
        assert response.status_code == 200
        provider = response.json()
    return provider


def _profile_payload(
    *,
    audience: str = "mcri-enterprise",
    jwks_uri: str = "https://issuer.alpha.example.test/.well-known/jwks.json",
    algorithms: list[str] | None = None,
) -> dict[str, object]:
    return {
        "audience": audience,
        "jwks_uri": jwks_uri,
        "allowed_algorithms": algorithms or ["RS256", "ES256"],
    }


def test_profile_is_source_derived_deterministic_and_has_no_authority_side_effects() -> None:
    org_a_id, admin_a_id, handler_a_id, _, _ = _seed()
    headers = _headers(admin_a_id)
    issuer = "https://issuer.alpha.example.test"
    provider = _create_provider(headers, issuer=issuer)

    with TestingSessionLocal() as db:
        session_count_before = db.query(AuthSession).count()
        user_count_before = db.query(User).count()
        handler = db.get(User, handler_a_id)
        assert handler is not None
        role_before = handler.role

    response = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/oidc-trust-profiles",
        headers=headers,
        json=_profile_payload(),
    )
    assert response.status_code == 201
    profile = response.json()
    assert profile["profile_number"] == 1
    assert profile["issuer_identifier"] == issuer
    assert profile["previous_profile_hash"] is None
    assert profile["allowed_algorithms"] == ["ES256", "RS256"]

    canonical = {
        "organization_id": str(org_a_id),
        "provider_id": str(provider["id"]),
        "issuer_identifier": issuer,
        "audience": "mcri-enterprise",
        "jwks_uri": "https://issuer.alpha.example.test/.well-known/jwks.json",
        "allowed_algorithms": ["ES256", "RS256"],
    }
    expected_hash = sha256(
        json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    assert profile["profile_hash"] == expected_hash

    with TestingSessionLocal() as db:
        assert db.query(OidcTrustProfile).count() == 1
        assert db.query(AuthSession).count() == session_count_before
        assert db.query(User).count() == user_count_before
        handler = db.get(User, handler_a_id)
        assert handler is not None
        assert handler.role == role_before


def test_exact_replay_is_idempotent_and_changed_profile_appends_lineage() -> None:
    _, admin_a_id, _, _, _ = _seed()
    headers = _headers(admin_a_id)
    provider = _create_provider(headers)
    url = f"/api/v1/auth/identity-providers/{provider['id']}/oidc-trust-profiles"

    first = client.post(url, headers=headers, json=_profile_payload())
    assert first.status_code == 201
    replay = client.post(url, headers=headers, json=_profile_payload())
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["profile_hash"] == first.json()["profile_hash"]

    second = client.post(
        url,
        headers=headers,
        json=_profile_payload(audience="mcri-enterprise-v2"),
    )
    assert second.status_code == 201
    assert second.json()["profile_number"] == 2
    assert second.json()["previous_profile_hash"] == first.json()["profile_hash"]

    history = client.get(url, headers=headers)
    assert history.status_code == 200
    rows = history.json()
    assert [row["profile_number"] for row in rows] == [1, 2]

    current = client.get(
        f"/api/v1/auth/identity-providers/{provider['id']}/oidc-trust-profile",
        headers=headers,
    )
    assert current.status_code == 200
    assert current.json()["id"] == second.json()["id"]


def test_client_cannot_override_issuer_or_use_unsafe_algorithms_or_remote_http_jwks() -> None:
    _, admin_a_id, _, _, _ = _seed()
    headers = _headers(admin_a_id)
    provider = _create_provider(headers)
    url = f"/api/v1/auth/identity-providers/{provider['id']}/oidc-trust-profiles"

    issuer_override = _profile_payload()
    issuer_override["issuer_identifier"] = "https://attacker.example.test"
    response = client.post(url, headers=headers, json=issuer_override)
    assert response.status_code == 422

    unsafe_algorithm = client.post(
        url,
        headers=headers,
        json=_profile_payload(algorithms=["HS256"]),
    )
    assert unsafe_algorithm.status_code == 422

    insecure_remote_jwks = client.post(
        url,
        headers=headers,
        json=_profile_payload(jwks_uri="http://remote.example.test/keys"),
    )
    assert insecure_remote_jwks.status_code == 409


def test_profile_creation_fails_closed_for_disabled_or_non_oidc_provider() -> None:
    _, admin_a_id, _, _, _ = _seed()
    headers = _headers(admin_a_id)

    disabled = _create_provider(
        headers,
        enabled=False,
        provider_key="disabled-oidc",
        issuer="https://disabled.example.test",
    )
    response = client.post(
        f"/api/v1/auth/identity-providers/{disabled['id']}/oidc-trust-profiles",
        headers=headers,
        json=_profile_payload(),
    )
    assert response.status_code == 409

    saml = _create_provider(
        headers,
        protocol="saml",
        provider_key="corp-saml",
        issuer="urn:example:saml:tenant-a",
    )
    response = client.post(
        f"/api/v1/auth/identity-providers/{saml['id']}/oidc-trust-profiles",
        headers=headers,
        json=_profile_payload(),
    )
    assert response.status_code == 409


def test_profile_management_is_tenant_scoped_and_admin_only() -> None:
    _, admin_a_id, handler_a_id, _, admin_b_id = _seed()
    alpha_headers = _headers(admin_a_id)
    beta_headers = _headers(admin_b_id)
    handler_headers = _headers(handler_a_id)
    provider = _create_provider(alpha_headers)
    url = f"/api/v1/auth/identity-providers/{provider['id']}/oidc-trust-profiles"

    created = client.post(url, headers=alpha_headers, json=_profile_payload())
    assert created.status_code == 201

    cross_tenant = client.get(url, headers=beta_headers)
    assert cross_tenant.status_code == 404

    non_admin = client.get(url, headers=handler_headers)
    assert non_admin.status_code == 403
