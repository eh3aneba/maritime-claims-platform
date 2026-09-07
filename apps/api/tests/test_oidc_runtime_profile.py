import json
from hashlib import sha256
from uuid import UUID

from app.core.security import create_access_token
from app.modules.auth.models import (
    AuthSession,
    ExternalIdentityBinding,
    OidcAuthorizationTransaction,
    OidcRuntimeProfile,
)
from app.modules.auth.oidc_transaction import consume_oidc_authorization_transaction
from app.modules.auth.service import create_auth_session
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


def _seed() -> tuple[UUID, UUID, UUID, UUID, UUID]:
    with TestingSessionLocal() as db:
        org_a = Organization(name="Alpha Marine", slug="alpha-oidc-runtime")
        org_b = Organization(name="Beta Marine", slug="beta-oidc-runtime")
        db.add_all([org_a, org_b])
        db.flush()

        admin_a = User(
            organization_id=org_a.id,
            email="alpha-admin-runtime@example.com",
            full_name="Alpha Admin",
            password_hash="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        handler_a = User(
            organization_id=org_a.id,
            email="alpha-handler-runtime@example.com",
            full_name="Alpha Handler",
            password_hash="",
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        admin_b = User(
            organization_id=org_b.id,
            email="beta-admin-runtime@example.com",
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
    provider_key: str = "corp-oidc",
    issuer: str = "https://issuer.alpha.example.test",
) -> dict[str, object]:
    created = client.post(
        "/api/v1/auth/identity-providers",
        headers=headers,
        json={
            "provider_key": provider_key,
            "display_name": "Corporate OIDC",
            "protocol": "oidc",
            "issuer_identifier": issuer,
        },
    )
    assert created.status_code == 201
    provider = created.json()
    enabled = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/enable",
        headers=headers,
    )
    assert enabled.status_code == 200
    return enabled.json()


def _create_trust_profile(
    headers: dict[str, str],
    provider_id: str,
    *,
    audience: str = "mcri-enterprise",
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/auth/identity-providers/{provider_id}/oidc-trust-profiles",
        headers=headers,
        json={
            "audience": audience,
            "jwks_uri": "https://issuer.alpha.example.test/.well-known/jwks.json",
            "allowed_algorithms": ["RS256", "ES256"],
        },
    )
    assert response.status_code == 201
    return response.json()


def _runtime_payload(
    *,
    authorization_endpoint: str = "https://issuer.alpha.example.test/oauth2/authorize",
    token_endpoint: str = "https://issuer.alpha.example.test/oauth2/token",
    redirect_uri: str = "https://mcri.example.test/api/v1/auth/oidc/callback",
    scopes: list[str] | None = None,
    client_auth_method: str = "none",
) -> dict[str, object]:
    return {
        "authorization_endpoint": authorization_endpoint,
        "token_endpoint": token_endpoint,
        "redirect_uri": redirect_uri,
        "scopes": scopes or ["openid", "profile", "email"],
        "client_auth_method": client_auth_method,
    }


def _runtime_url(provider_id: str) -> str:
    return f"/api/v1/auth/identity-providers/{provider_id}/oidc-runtime-profiles"


def test_runtime_profile_is_deterministic_normalized_and_has_no_authority_side_effects() -> None:
    org_id, admin_id, handler_id, _, _ = _seed()
    headers = _headers(admin_id)
    provider = _create_provider(headers)
    trust = _create_trust_profile(headers, str(provider["id"]))

    with TestingSessionLocal() as db:
        session_count_before = db.query(AuthSession).count()
        user_count_before = db.query(User).count()
        binding_count_before = db.query(ExternalIdentityBinding).count()
        handler = db.get(User, handler_id)
        assert handler is not None
        role_before = handler.role

    response = client.post(
        _runtime_url(str(provider["id"])),
        headers=headers,
        json=_runtime_payload(scopes=["email", "openid", "profile"]),
    )
    assert response.status_code == 201
    runtime = response.json()
    assert runtime["runtime_profile_number"] == 1
    assert runtime["trust_profile_id"] == trust["id"]
    assert runtime["trust_profile_hash"] == trust["profile_hash"]
    assert runtime["scopes"] == ["email", "openid", "profile"]
    assert runtime["previous_runtime_profile_hash"] is None

    canonical = {
        "organization_id": str(org_id),
        "provider_id": str(provider["id"]),
        "trust_profile_id": trust["id"],
        "trust_profile_number": trust["profile_number"],
        "trust_profile_hash": trust["profile_hash"],
        "authorization_endpoint": "https://issuer.alpha.example.test/oauth2/authorize",
        "token_endpoint": "https://issuer.alpha.example.test/oauth2/token",
        "redirect_uri": "https://mcri.example.test/api/v1/auth/oidc/callback",
        "scopes": ["email", "openid", "profile"],
        "client_auth_method": "none",
    }
    expected_hash = sha256(
        json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    assert runtime["runtime_profile_hash"] == expected_hash

    with TestingSessionLocal() as db:
        assert db.query(OidcRuntimeProfile).count() == 1
        assert db.query(AuthSession).count() == session_count_before
        assert db.query(User).count() == user_count_before
        assert db.query(ExternalIdentityBinding).count() == binding_count_before
        handler = db.get(User, handler_id)
        assert handler is not None
        assert handler.role == role_before


def test_exact_replay_is_idempotent_and_changed_runtime_appends_lineage() -> None:
    _, admin_id, _, _, _ = _seed()
    headers = _headers(admin_id)
    provider = _create_provider(headers)
    _create_trust_profile(headers, str(provider["id"]))
    url = _runtime_url(str(provider["id"]))

    first = client.post(url, headers=headers, json=_runtime_payload())
    assert first.status_code == 201
    replay = client.post(
        url,
        headers=headers,
        json=_runtime_payload(scopes=["email", "profile", "openid"]),
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["runtime_profile_hash"] == first.json()["runtime_profile_hash"]

    second = client.post(
        url,
        headers=headers,
        json=_runtime_payload(
            authorization_endpoint="https://issuer.alpha.example.test/oauth2/v2/authorize"
        ),
    )
    assert second.status_code == 201
    assert second.json()["runtime_profile_number"] == 2
    assert second.json()["previous_runtime_profile_hash"] == first.json()[
        "runtime_profile_hash"
    ]

    history = client.get(url, headers=headers)
    assert history.status_code == 200
    assert [row["runtime_profile_number"] for row in history.json()] == [1, 2]

    current = client.get(
        f"/api/v1/auth/identity-providers/{provider['id']}/oidc-runtime-profile",
        headers=headers,
    )
    assert current.status_code == 200
    assert current.json()["id"] == second.json()["id"]


def test_runtime_profile_rejects_unsafe_endpoints_scopes_and_client_auth() -> None:
    _, admin_id, _, _, _ = _seed()
    headers = _headers(admin_id)
    provider = _create_provider(headers)
    _create_trust_profile(headers, str(provider["id"]))
    url = _runtime_url(str(provider["id"]))

    insecure = client.post(
        url,
        headers=headers,
        json=_runtime_payload(
            token_endpoint="http://remote.example.test/oauth2/token"
        ),
    )
    assert insecure.status_code == 409

    credentials = client.post(
        url,
        headers=headers,
        json=_runtime_payload(
            authorization_endpoint="https://user:pass@issuer.alpha.example.test/authorize"
        ),
    )
    assert credentials.status_code == 409

    fragment = client.post(
        url,
        headers=headers,
        json=_runtime_payload(
            redirect_uri="https://mcri.example.test/callback#fragment"
        ),
    )
    assert fragment.status_code == 409

    missing_openid = client.post(
        url,
        headers=headers,
        json=_runtime_payload(scopes=["profile", "email"]),
    )
    assert missing_openid.status_code == 422

    offline_access = _runtime_payload()
    offline_access["scopes"] = ["openid", "offline_access"]
    response = client.post(url, headers=headers, json=offline_access)
    assert response.status_code == 422

    unsupported_auth = _runtime_payload()
    unsupported_auth["client_auth_method"] = "private_key_jwt"
    response = client.post(url, headers=headers, json=unsupported_auth)
    assert response.status_code == 422


def test_runtime_profile_management_is_tenant_scoped_and_admin_only() -> None:
    _, admin_a_id, handler_a_id, _, admin_b_id = _seed()
    alpha_headers = _headers(admin_a_id)
    beta_headers = _headers(admin_b_id)
    handler_headers = _headers(handler_a_id)
    provider = _create_provider(alpha_headers)
    _create_trust_profile(alpha_headers, str(provider["id"]))
    url = _runtime_url(str(provider["id"]))

    created = client.post(url, headers=alpha_headers, json=_runtime_payload())
    assert created.status_code == 201

    cross_tenant = client.get(url, headers=beta_headers)
    assert cross_tenant.status_code == 404

    non_admin = client.get(url, headers=handler_headers)
    assert non_admin.status_code == 403


def test_trust_rotation_requires_compatible_runtime_before_new_transaction() -> None:
    _, admin_id, _, _, _ = _seed()
    headers = _headers(admin_id)
    provider = _create_provider(headers)
    trust_v1 = _create_trust_profile(headers, str(provider["id"]))
    runtime_v1 = client.post(
        _runtime_url(str(provider["id"])),
        headers=headers,
        json=_runtime_payload(),
    )
    assert runtime_v1.status_code == 201

    start_v1 = client.post(
        "/api/v1/auth/oidc/transactions",
        json={
            "organization_slug": "alpha-oidc-runtime",
            "provider_key": "corp-oidc",
        },
    )
    assert start_v1.status_code == 201
    txn_v1 = start_v1.json()
    assert txn_v1["trust_profile_id"] == trust_v1["id"]
    assert txn_v1["runtime_profile_id"] == runtime_v1.json()["id"]

    trust_v2 = _create_trust_profile(
        headers,
        str(provider["id"]),
        audience="mcri-enterprise-v2",
    )
    assert trust_v2["profile_number"] == 2

    current_runtime = client.get(
        f"/api/v1/auth/identity-providers/{provider['id']}/oidc-runtime-profile",
        headers=headers,
    )
    assert current_runtime.status_code == 404

    blocked_start = client.post(
        "/api/v1/auth/oidc/transactions",
        json={
            "organization_slug": "alpha-oidc-runtime",
            "provider_key": "corp-oidc",
        },
    )
    assert blocked_start.status_code == 404

    runtime_v2 = client.post(
        _runtime_url(str(provider["id"])),
        headers=headers,
        json=_runtime_payload(
            authorization_endpoint="https://issuer.alpha.example.test/oauth2/v2/authorize"
        ),
    )
    assert runtime_v2.status_code == 201
    assert runtime_v2.json()["trust_profile_id"] == trust_v2["id"]

    start_v2 = client.post(
        "/api/v1/auth/oidc/transactions",
        json={
            "organization_slug": "alpha-oidc-runtime",
            "provider_key": "corp-oidc",
        },
    )
    assert start_v2.status_code == 201
    txn_v2 = start_v2.json()
    assert txn_v2["trust_profile_id"] == trust_v2["id"]
    assert txn_v2["runtime_profile_id"] == runtime_v2.json()["id"]

    with TestingSessionLocal() as db:
        persisted_v1 = db.get(OidcAuthorizationTransaction, UUID(txn_v1["transaction_id"]))
        persisted_v2 = db.get(OidcAuthorizationTransaction, UUID(txn_v2["transaction_id"]))
        assert persisted_v1 is not None
        assert persisted_v2 is not None
        assert persisted_v1.trust_profile_id == UUID(trust_v1["id"])
        assert persisted_v1.runtime_profile_id == UUID(runtime_v1.json()["id"])
        assert persisted_v2.trust_profile_id == UUID(trust_v2["id"])
        assert persisted_v2.runtime_profile_id == UUID(runtime_v2.json()["id"])


def test_runtime_rotation_preserves_inflight_snapshot_and_consume_uses_exact_source() -> None:
    _, admin_id, _, _, _ = _seed()
    headers = _headers(admin_id)
    provider = _create_provider(headers)
    _create_trust_profile(headers, str(provider["id"]))

    runtime_v1 = client.post(
        _runtime_url(str(provider["id"])),
        headers=headers,
        json=_runtime_payload(),
    )
    assert runtime_v1.status_code == 201

    started = client.post(
        "/api/v1/auth/oidc/transactions",
        json={
            "organization_slug": "alpha-oidc-runtime",
            "provider_key": "corp-oidc",
        },
    )
    assert started.status_code == 201
    txn = started.json()

    runtime_v2 = client.post(
        _runtime_url(str(provider["id"])),
        headers=headers,
        json=_runtime_payload(
            token_endpoint="https://issuer.alpha.example.test/oauth2/v2/token"
        ),
    )
    assert runtime_v2.status_code == 201
    assert runtime_v2.json()["id"] != runtime_v1.json()["id"]

    with TestingSessionLocal() as db:
        consumed = consume_oidc_authorization_transaction(
            db,
            transaction_id=UUID(txn["transaction_id"]),
            state=txn["state"],
            nonce=txn["nonce"],
            code_verifier=txn["code_verifier"],
        )
        assert consumed.runtime_profile_id == UUID(runtime_v1.json()["id"])
        assert consumed.runtime_profile_hash == runtime_v1.json()["runtime_profile_hash"]
        db.commit()

    with TestingSessionLocal() as db:
        persisted = db.get(OidcAuthorizationTransaction, UUID(txn["transaction_id"]))
        assert persisted is not None
        assert persisted.consumed_at is not None
        assert persisted.runtime_profile_id == UUID(runtime_v1.json()["id"])
