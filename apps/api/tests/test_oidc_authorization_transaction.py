import base64
import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID

import pytest

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from app.modules.auth.models import (
    AuthSession,
    ExternalIdentityBinding,
    OidcAuthorizationTransaction,
)
from app.modules.auth.oidc_transaction import (
    cancel_oidc_authorization_transaction,
    consume_oidc_authorization_transaction,
)
from app.modules.auth.service import create_auth_session
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


def _seed() -> tuple[UUID, UUID, UUID, UUID]:
    with TestingSessionLocal() as db:
        org_a = Organization(name="Alpha Marine", slug="alpha-oidc-transaction")
        org_b = Organization(name="Beta Marine", slug="beta-oidc-transaction")
        db.add_all([org_a, org_b])
        db.flush()
        admin_a = User(
            organization_id=org_a.id,
            email="alpha-admin-transaction@example.com",
            full_name="Alpha Admin",
            password_hash="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        admin_b = User(
            organization_id=org_b.id,
            email="beta-admin-transaction@example.com",
            full_name="Beta Admin",
            password_hash="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        db.add_all([admin_a, admin_b])
        db.commit()
        return org_a.id, admin_a.id, org_b.id, admin_b.id


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
    protocol: str = "oidc",
    issuer: str = "https://issuer.alpha.example.test",
    enabled: bool = True,
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
    if enabled:
        response = client.post(
            f"/api/v1/auth/identity-providers/{provider['id']}/enable",
            headers=headers,
        )
        assert response.status_code == 200
        provider = response.json()
    return provider


def _create_profile(
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


def _create_runtime_profile(
    headers: dict[str, str],
    provider_id: str,
    *,
    issuer: str = "https://issuer.alpha.example.test",
    suffix: str = "v1",
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/auth/identity-providers/{provider_id}/oidc-runtime-profiles",
        headers=headers,
        json={
            "authorization_endpoint": f"{issuer}/oauth2/{suffix}/authorize",
            "token_endpoint": f"{issuer}/oauth2/{suffix}/token",
            "redirect_uri": "https://mcri.example.test/api/v1/auth/oidc/callback",
            "scopes": ["openid", "profile", "email"],
            "client_auth_method": "none",
        },
    )
    assert response.status_code == 201
    return response.json()


def _start(*, organization_slug: str, provider_key: str = "corp-oidc"):
    return client.post(
        "/api/v1/auth/oidc/transactions",
        json={
            "organization_slug": organization_slug,
            "provider_key": provider_key,
        },
    )


def _expected_challenge(verifier: str) -> str:
    digest = sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def test_start_binds_exact_profile_and_persists_no_raw_secrets_or_authority_side_effects() -> None:
    _, admin_a_id, _, _ = _seed()
    headers = _headers(admin_a_id)
    provider = _create_provider(headers)
    profile = _create_profile(headers, str(provider["id"]))
    runtime = _create_runtime_profile(headers, str(provider["id"]))

    with TestingSessionLocal() as db:
        sessions_before = db.query(AuthSession).count()
        users_before = db.query(User).count()
        bindings_before = db.query(ExternalIdentityBinding).count()

    response = _start(organization_slug="alpha-oidc-transaction")
    assert response.status_code == 201
    payload = response.json()
    assert payload["provider_key"] == "corp-oidc"
    assert payload["trust_profile_id"] == profile["id"]
    assert payload["trust_profile_number"] == 1
    assert payload["trust_profile_hash"] == profile["profile_hash"]
    assert payload["runtime_profile_id"] == runtime["id"]
    assert payload["runtime_profile_number"] == 1
    assert payload["runtime_profile_hash"] == runtime["runtime_profile_hash"]
    assert payload["authorization_endpoint"] == runtime["authorization_endpoint"]
    assert payload["token_endpoint"] == runtime["token_endpoint"]
    assert payload["redirect_uri"] == runtime["redirect_uri"]
    assert payload["scopes"] == runtime["scopes"]
    assert payload["client_auth_method"] == runtime["client_auth_method"]
    assert payload["code_challenge_method"] == "S256"
    assert len(payload["state"]) >= 43
    assert len(payload["nonce"]) >= 43
    assert 43 <= len(payload["code_verifier"]) <= 128
    assert payload["code_challenge"] == _expected_challenge(payload["code_verifier"])

    with TestingSessionLocal() as db:
        row = db.get(OidcAuthorizationTransaction, UUID(payload["transaction_id"]))
        assert row is not None
        assert row.trust_profile_id == UUID(profile["id"])
        assert row.trust_profile_number == 1
        assert row.trust_profile_hash == profile["profile_hash"]
        assert row.runtime_profile_id == UUID(runtime["id"])
        assert row.runtime_profile_number == 1
        assert row.runtime_profile_hash == runtime["runtime_profile_hash"]
        assert row.state_hash == sha256(payload["state"].encode("utf-8")).hexdigest()
        assert row.nonce_hash == sha256(payload["nonce"].encode("utf-8")).hexdigest()
        assert row.pkce_code_challenge == payload["code_challenge"]
        assert row.state_hash != payload["state"]
        assert row.nonce_hash != payload["nonce"]
        assert row.consumed_at is None
        assert row.cancelled_at is None
        delta = row.expires_at - row.created_at
        assert timedelta(minutes=9, seconds=50) <= delta <= timedelta(minutes=10, seconds=10)

        assert db.query(AuthSession).count() == sessions_before
        assert db.query(User).count() == users_before
        assert db.query(ExternalIdentityBinding).count() == bindings_before

        audit = (
            db.query(AuditLog)
            .filter(AuditLog.action == "OIDC_AUTHORIZATION_TRANSACTION_CREATED")
            .order_by(AuditLog.created_at.desc())
            .first()
        )
        assert audit is not None
        serialized = json.dumps(audit.new_values or {}, sort_keys=True)
        assert payload["state"] not in serialized
        assert payload["nonce"] not in serialized
        assert payload["code_verifier"] not in serialized
        assert audit.user_id is None


def test_start_fails_closed_for_unknown_disabled_non_oidc_or_missing_profile() -> None:
    _, admin_a_id, _, _ = _seed()
    headers = _headers(admin_a_id)

    assert _start(organization_slug="missing-tenant").status_code == 404
    assert _start(
        organization_slug="alpha-oidc-transaction",
        provider_key="missing-provider",
    ).status_code == 404

    _create_provider(
        headers,
        provider_key="disabled-oidc",
        issuer="https://disabled.example.test",
        enabled=False,
    )
    assert _start(
        organization_slug="alpha-oidc-transaction",
        provider_key="disabled-oidc",
    ).status_code == 404

    _create_provider(
        headers,
        provider_key="corp-saml",
        protocol="saml",
        issuer="urn:example:saml:alpha",
    )
    assert _start(
        organization_slug="alpha-oidc-transaction",
        provider_key="corp-saml",
    ).status_code == 404

    _create_provider(
        headers,
        provider_key="no-profile",
        issuer="https://no-profile.example.test",
    )
    assert _start(
        organization_slug="alpha-oidc-transaction",
        provider_key="no-profile",
    ).status_code == 404

    no_runtime = _create_provider(
        headers,
        provider_key="no-runtime",
        issuer="https://no-runtime.example.test",
    )
    _create_profile(headers, str(no_runtime["id"]), audience="no-runtime-audience")
    assert _start(
        organization_slug="alpha-oidc-transaction",
        provider_key="no-runtime",
    ).status_code == 404


def test_internal_consume_is_one_time_and_bound_to_state_nonce_and_pkce() -> None:
    _, admin_a_id, _, _ = _seed()
    headers = _headers(admin_a_id)
    provider = _create_provider(headers)
    _create_profile(headers, str(provider["id"]))
    _create_runtime_profile(headers, str(provider["id"]))
    response = _start(organization_slug="alpha-oidc-transaction")
    assert response.status_code == 201
    payload = response.json()
    transaction_id = UUID(payload["transaction_id"])

    with TestingSessionLocal() as db:
        with pytest.raises(ValueError, match="proof does not match"):
            consume_oidc_authorization_transaction(
                db,
                transaction_id=transaction_id,
                state="wrong-state",
                nonce=payload["nonce"],
                code_verifier=payload["code_verifier"],
            )
        db.rollback()

    with TestingSessionLocal() as db:
        row = consume_oidc_authorization_transaction(
            db,
            transaction_id=transaction_id,
            state=payload["state"],
            nonce=payload["nonce"],
            code_verifier=payload["code_verifier"],
        )
        assert row.consumed_at is not None
        db.commit()

    with TestingSessionLocal() as db:
        with pytest.raises(ValueError, match="already consumed"):
            consume_oidc_authorization_transaction(
                db,
                transaction_id=transaction_id,
                state=payload["state"],
                nonce=payload["nonce"],
                code_verifier=payload["code_verifier"],
            )


def test_expired_cancelled_or_disabled_source_transaction_fails_closed() -> None:
    _, admin_a_id, _, _ = _seed()
    headers = _headers(admin_a_id)
    provider = _create_provider(headers)
    _create_profile(headers, str(provider["id"]))
    _create_runtime_profile(headers, str(provider["id"]))

    expired = _start(organization_slug="alpha-oidc-transaction").json()
    with TestingSessionLocal() as db:
        row = db.get(OidcAuthorizationTransaction, UUID(expired["transaction_id"]))
        assert row is not None
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    with TestingSessionLocal() as db:
        with pytest.raises(ValueError, match="expired"):
            consume_oidc_authorization_transaction(
                db,
                transaction_id=UUID(expired["transaction_id"]),
                state=expired["state"],
                nonce=expired["nonce"],
                code_verifier=expired["code_verifier"],
            )

    cancelled = _start(organization_slug="alpha-oidc-transaction").json()
    with TestingSessionLocal() as db:
        cancel_oidc_authorization_transaction(
            db,
            transaction_id=UUID(cancelled["transaction_id"]),
            state=cancelled["state"],
        )
        db.commit()
    with TestingSessionLocal() as db:
        with pytest.raises(ValueError, match="cancelled"):
            consume_oidc_authorization_transaction(
                db,
                transaction_id=UUID(cancelled["transaction_id"]),
                state=cancelled["state"],
                nonce=cancelled["nonce"],
                code_verifier=cancelled["code_verifier"],
            )

    disabled = _start(organization_slug="alpha-oidc-transaction").json()
    response = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/disable",
        headers=headers,
    )
    assert response.status_code == 200
    with TestingSessionLocal() as db:
        with pytest.raises(ValueError, match="source is unavailable"):
            consume_oidc_authorization_transaction(
                db,
                transaction_id=UUID(disabled["transaction_id"]),
                state=disabled["state"],
                nonce=disabled["nonce"],
                code_verifier=disabled["code_verifier"],
            )


def test_profile_rotation_preserves_existing_transaction_snapshot_and_tenant_binding() -> None:
    _, admin_a_id, _, admin_b_id = _seed()
    alpha_headers = _headers(admin_a_id)
    beta_headers = _headers(admin_b_id)

    provider_a = _create_provider(alpha_headers)
    profile_v1 = _create_profile(
        alpha_headers,
        str(provider_a["id"]),
        audience="audience-v1",
    )
    runtime_v1 = _create_runtime_profile(alpha_headers, str(provider_a["id"]))

    beta_issuer = "https://issuer.beta.example.test"
    provider_b = _create_provider(
        beta_headers,
        issuer=beta_issuer,
    )
    _create_profile(beta_headers, str(provider_b["id"]), audience="beta-audience")
    _create_runtime_profile(
        beta_headers,
        str(provider_b["id"]),
        issuer=beta_issuer,
    )

    alpha_start = _start(organization_slug="alpha-oidc-transaction")
    beta_start = _start(organization_slug="beta-oidc-transaction")
    assert alpha_start.status_code == 201
    assert beta_start.status_code == 201
    alpha = alpha_start.json()
    beta = beta_start.json()
    assert alpha["trust_profile_id"] == profile_v1["id"]
    assert alpha["runtime_profile_id"] == runtime_v1["id"]
    assert alpha["issuer_identifier"] != beta["issuer_identifier"]

    profile_v2 = _create_profile(
        alpha_headers,
        str(provider_a["id"]),
        audience="audience-v2",
    )
    assert profile_v2["profile_number"] == 2

    # A newly initiated flow must not silently pair trust v2 with stale runtime v1.
    blocked = _start(organization_slug="alpha-oidc-transaction")
    assert blocked.status_code == 404

    with TestingSessionLocal() as db:
        row = db.get(OidcAuthorizationTransaction, UUID(alpha["transaction_id"]))
        assert row is not None
        assert row.trust_profile_id == UUID(profile_v1["id"])
        assert row.trust_profile_number == 1
        assert row.trust_profile_hash == profile_v1["profile_hash"]
        assert row.runtime_profile_id == UUID(runtime_v1["id"])
        assert row.runtime_profile_number == runtime_v1["runtime_profile_number"]
        assert row.runtime_profile_hash == runtime_v1["runtime_profile_hash"]

        consumed = consume_oidc_authorization_transaction(
            db,
            transaction_id=row.id,
            state=alpha["state"],
            nonce=alpha["nonce"],
            code_verifier=alpha["code_verifier"],
        )
        assert consumed.consumed_at is not None
        db.commit()

    runtime_v2 = _create_runtime_profile(
        alpha_headers,
        str(provider_a["id"]),
        suffix="v2",
    )
    assert runtime_v2["trust_profile_id"] == profile_v2["id"]

    alpha_v2_start = _start(organization_slug="alpha-oidc-transaction")
    assert alpha_v2_start.status_code == 201
    alpha_v2 = alpha_v2_start.json()
    assert alpha_v2["trust_profile_id"] == profile_v2["id"]
    assert alpha_v2["runtime_profile_id"] == runtime_v2["id"]
    assert alpha_v2["trust_profile_id"] != alpha["trust_profile_id"]
    assert alpha_v2["runtime_profile_id"] != alpha["runtime_profile_id"]
