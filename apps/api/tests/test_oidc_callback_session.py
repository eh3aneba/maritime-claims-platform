import base64
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from app.modules.auth.models import (
    AuthSession,
    EnterpriseIdentityProvider,
    ExternalIdentityBinding,
    OidcAuthorizationTransaction,
)
from app.modules.auth.oidc_callback import OidcProviderUnavailable
from app.modules.auth.service import create_auth_session, create_external_identity_binding
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


def _seed() -> tuple[UUID, UUID, UUID]:
    with TestingSessionLocal() as db:
        org = Organization(name="OIDC Callback Marine", slug="oidc-callback-marine")
        db.add(org)
        db.flush()
        admin = User(
            organization_id=org.id,
            email="oidc-admin@example.com",
            full_name="OIDC Admin",
            password_hash="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        handler = User(
            organization_id=org.id,
            email="oidc-handler@example.com",
            full_name="OIDC Handler",
            password_hash="",
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        db.add_all([admin, handler])
        db.commit()
        return org.id, admin.id, handler.id


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


def _create_provider_stack(
    headers: dict[str, str],
    *,
    issuer: str = "https://issuer.callback.example.test",
    audience: str = "mcri-callback-client",
    algorithms: list[str] | None = None,
    client_auth_method: str = "none",
) -> dict[str, object]:
    algorithms = algorithms or ["RS256", "ES256"]
    response = client.post(
        "/api/v1/auth/identity-providers",
        headers=headers,
        json={
            "provider_key": "corp-oidc",
            "display_name": "Corporate OIDC",
            "protocol": "oidc",
            "issuer_identifier": issuer,
        },
    )
    assert response.status_code == 201
    provider = response.json()
    response = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/enable",
        headers=headers,
    )
    assert response.status_code == 200
    response = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/oidc-trust-profiles",
        headers=headers,
        json={
            "audience": audience,
            "jwks_uri": f"{issuer}/.well-known/jwks.json",
            "allowed_algorithms": algorithms,
        },
    )
    assert response.status_code == 201
    trust = response.json()
    response = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/oidc-runtime-profiles",
        headers=headers,
        json={
            "authorization_endpoint": f"{issuer}/authorize",
            "token_endpoint": f"{issuer}/token",
            "redirect_uri": "https://mcri.example.test/api/v1/auth/oidc/callback",
            "scopes": ["openid", "profile", "email"],
            "client_auth_method": client_auth_method,
        },
    )
    assert response.status_code == 201
    runtime = response.json()
    return {"provider": provider, "trust": trust, "runtime": runtime}


def _bind(provider_id: str, handler_id: UUID, subject: str = "subject-123") -> None:
    with TestingSessionLocal() as db:
        provider = db.get(EnterpriseIdentityProvider, UUID(provider_id))
        handler = db.get(User, handler_id)
        assert provider is not None
        assert handler is not None
        create_external_identity_binding(
            db,
            provider=provider,
            user=handler,
            external_subject=subject,
        )
        db.commit()


def _start() -> dict[str, object]:
    response = client.post(
        "/api/v1/auth/oidc/transactions",
        json={
            "organization_slug": "oidc-callback-marine",
            "provider_key": "corp-oidc",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["authorization_url"].startswith(
        "https://issuer.callback.example.test/authorize?"
    )
    assert "response_type=code" in payload["authorization_url"]
    assert "code_challenge_method=S256" in payload["authorization_url"]
    assert payload["state"] in payload["authorization_url"]
    return payload


def _b64_uint(value: int, size: int | None = None) -> str:
    if size is None:
        size = max(1, (value.bit_length() + 7) // 8)
    raw = value.to_bytes(size, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _rsa_signer() -> tuple[object, dict[str, str]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    return private_key, {
        "kty": "RSA",
        "kid": "rsa-key-1",
        "use": "sig",
        "alg": "RS256",
        "n": _b64_uint(numbers.n),
        "e": _b64_uint(numbers.e),
    }


def _ec_signer() -> tuple[object, dict[str, str]]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    numbers = private_key.public_key().public_numbers()
    return private_key, {
        "kty": "EC",
        "kid": "ec-key-1",
        "use": "sig",
        "alg": "ES256",
        "crv": "P-256",
        "x": _b64_uint(numbers.x, 32),
        "y": _b64_uint(numbers.y, 32),
    }


def _id_token(
    *,
    private_key,
    jwk: dict[str, str],
    nonce: str,
    subject: str = "subject-123",
    issuer: str = "https://issuer.callback.example.test",
    audience: str | list[str] = "mcri-callback-client",
    algorithm: str | None = None,
    overrides: dict[str, object] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    claims: dict[str, object] = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "nonce": nonce,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "groups": ["tenant-admin", "claims-manager"],
        "role": "admin",
    }
    if overrides:
        claims.update(overrides)
    alg = algorithm or jwk["alg"]
    return jwt.encode(
        claims,
        private_key,
        algorithm=alg,
        headers={"kid": jwk["kid"]},
    )


def _install_provider_responses(monkeypatch, *, id_token: str, jwk: dict[str, str]) -> None:
    monkeypatch.setattr(
        "app.modules.auth.oidc_callback._post_token_request",
        lambda **_: {"token_type": "Bearer", "access_token": "never-persist-me", "id_token": id_token},
    )
    monkeypatch.setattr(
        "app.modules.auth.oidc_callback._get_jwks",
        lambda **_: {"keys": [jwk]},
    )


def _callback(start: dict[str, object], *, code: str = "authorization-code"):
    return client.post(
        "/api/v1/auth/oidc/callback",
        json={
            "transaction_id": start["transaction_id"],
            "state": start["state"],
            "nonce": start["nonce"],
            "code_verifier": start["code_verifier"],
            "authorization_code": code,
        },
    )


def test_valid_rs256_callback_issues_one_bound_session_and_db_role_wins(monkeypatch) -> None:
    _, admin_id, handler_id = _seed()
    headers = _headers(admin_id)
    stack = _create_provider_stack(headers)
    _bind(str(stack["provider"]["id"]), handler_id)
    start = _start()
    private_key, jwk = _rsa_signer()
    token = _id_token(private_key=private_key, jwk=jwk, nonce=str(start["nonce"]))
    _install_provider_responses(monkeypatch, id_token=token, jwk=jwk)

    with TestingSessionLocal() as db:
        users_before = db.query(User).count()
        bindings_before = db.query(ExternalIdentityBinding).count()
        sessions_before = db.query(AuthSession).count()

    response = _callback(start, code="super-secret-code")
    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["id"] == str(handler_id)
    assert payload["user"]["role"] == UserRole.CLAIMS_HANDLER.value
    assert response.cookies

    session_response = client.get(
        "/api/v1/auth/session",
        headers={"Authorization": f"Bearer {payload['access_token']}"},
    )
    assert session_response.status_code == 200
    session_payload = session_response.json()
    assert session_payload["identity_source"] == "oidc"
    assert session_payload["auth_method"] == "oidc"
    assert session_payload["external_identity_provider_id"] == stack["provider"]["id"]
    assert session_payload["oidc_authorization_transaction_id"] == start["transaction_id"]

    with TestingSessionLocal() as db:
        assert db.query(User).count() == users_before
        assert db.query(ExternalIdentityBinding).count() == bindings_before
        assert db.query(AuthSession).count() == sessions_before + 1
        transaction = db.get(OidcAuthorizationTransaction, UUID(str(start["transaction_id"])))
        assert transaction is not None and transaction.consumed_at is not None
        session = db.query(AuthSession).filter(
            AuthSession.oidc_authorization_transaction_id == transaction.id
        ).one()
        assert session.user_id == handler_id
        audits = db.query(AuditLog).filter(
            AuditLog.action.in_(["OIDC_LOGIN_SUCCESS", "OIDC_AUTHORIZATION_TRANSACTION_CONSUMED"])
        ).all()
        serialized = json.dumps(
            [row.new_values or {} for row in audits],
            sort_keys=True,
        )
        for secret in (
            "super-secret-code",
            "never-persist-me",
            token,
            "subject-123",
            str(start["nonce"]),
            str(start["code_verifier"]),
        ):
            assert secret not in serialized

    replay = _callback(start)
    assert replay.status_code == 401
    with TestingSessionLocal() as db:
        assert db.query(AuthSession).count() == sessions_before + 1


def test_valid_es256_callback_verifies_signed_identity(monkeypatch) -> None:
    _, admin_id, handler_id = _seed()
    headers = _headers(admin_id)
    stack = _create_provider_stack(headers, algorithms=["ES256"])
    _bind(str(stack["provider"]["id"]), handler_id)
    start = _start()
    private_key, jwk = _ec_signer()
    token = _id_token(private_key=private_key, jwk=jwk, nonce=str(start["nonce"]))
    _install_provider_responses(monkeypatch, id_token=token, jwk=jwk)

    response = _callback(start)
    assert response.status_code == 200
    assert response.json()["user"]["id"] == str(handler_id)


@pytest.mark.parametrize(
    "mutation",
    ["issuer", "audience", "nonce", "expired", "future_iat"],
)
def test_signed_claim_mismatch_fails_closed_without_consuming(monkeypatch, mutation: str) -> None:
    _, admin_id, handler_id = _seed()
    headers = _headers(admin_id)
    stack = _create_provider_stack(headers)
    _bind(str(stack["provider"]["id"]), handler_id)
    start = _start()
    private_key, jwk = _rsa_signer()
    kwargs: dict[str, object] = {}
    overrides: dict[str, object] = {}
    if mutation == "issuer":
        kwargs["issuer"] = "https://wrong-issuer.example.test"
    elif mutation == "audience":
        kwargs["audience"] = "wrong-audience"
    elif mutation == "nonce":
        kwargs["nonce"] = "wrong-token-nonce"
    elif mutation == "expired":
        overrides["exp"] = int((datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp())
    elif mutation == "future_iat":
        overrides["iat"] = int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp())
    token = _id_token(
        private_key=private_key,
        jwk=jwk,
        nonce=str(kwargs.pop("nonce", start["nonce"])),
        overrides=overrides,
        **kwargs,
    )
    _install_provider_responses(monkeypatch, id_token=token, jwk=jwk)

    response = _callback(start)
    assert response.status_code == 401
    with TestingSessionLocal() as db:
        transaction = db.get(OidcAuthorizationTransaction, UUID(str(start["transaction_id"])))
        assert transaction is not None and transaction.consumed_at is None
        assert db.query(AuthSession).filter(
            AuthSession.oidc_authorization_transaction_id == transaction.id
        ).count() == 0


def test_missing_or_ambiguous_signing_key_fails_closed(monkeypatch) -> None:
    _, admin_id, handler_id = _seed()
    headers = _headers(admin_id)
    stack = _create_provider_stack(headers)
    _bind(str(stack["provider"]["id"]), handler_id)
    start = _start()
    private_key, jwk = _rsa_signer()
    token = _id_token(private_key=private_key, jwk=jwk, nonce=str(start["nonce"]))
    monkeypatch.setattr(
        "app.modules.auth.oidc_callback._post_token_request",
        lambda **_: {"id_token": token},
    )
    monkeypatch.setattr(
        "app.modules.auth.oidc_callback._get_jwks",
        lambda **_: {"keys": [jwk, dict(jwk)]},
    )
    assert _callback(start).status_code == 401


def test_unbound_revoked_or_inactive_application_identity_fails_closed(monkeypatch) -> None:
    _, admin_id, handler_id = _seed()
    headers = _headers(admin_id)
    stack = _create_provider_stack(headers)
    start = _start()
    private_key, jwk = _rsa_signer()
    token = _id_token(private_key=private_key, jwk=jwk, nonce=str(start["nonce"]))
    _install_provider_responses(monkeypatch, id_token=token, jwk=jwk)
    assert _callback(start).status_code == 401

    _bind(str(stack["provider"]["id"]), handler_id)
    with TestingSessionLocal() as db:
        handler = db.get(User, handler_id)
        assert handler is not None
        handler.is_active = False
        db.commit()
    assert _callback(start).status_code == 401


def test_client_secret_basic_is_not_operational_without_secret_custody(monkeypatch) -> None:
    _, admin_id, handler_id = _seed()
    headers = _headers(admin_id)
    stack = _create_provider_stack(headers, client_auth_method="client_secret_basic")
    _bind(str(stack["provider"]["id"]), handler_id)
    start = _start()

    called = {"token": False}

    def _unexpected_token_request(**_):
        called["token"] = True
        return {}

    monkeypatch.setattr(
        "app.modules.auth.oidc_callback._post_token_request",
        _unexpected_token_request,
    )
    response = _callback(start)
    assert response.status_code == 409
    assert called["token"] is False
    with TestingSessionLocal() as db:
        transaction = db.get(OidcAuthorizationTransaction, UUID(str(start["transaction_id"])))
        assert transaction is not None and transaction.consumed_at is None


def test_transient_provider_failure_does_not_burn_transaction(monkeypatch) -> None:
    _, admin_id, handler_id = _seed()
    headers = _headers(admin_id)
    stack = _create_provider_stack(headers)
    _bind(str(stack["provider"]["id"]), handler_id)
    start = _start()
    private_key, jwk = _rsa_signer()
    token = _id_token(private_key=private_key, jwk=jwk, nonce=str(start["nonce"]))

    def _temporary_failure(**_):
        raise OidcProviderUnavailable("temporary")

    monkeypatch.setattr(
        "app.modules.auth.oidc_callback._post_token_request",
        _temporary_failure,
    )
    assert _callback(start).status_code == 502
    with TestingSessionLocal() as db:
        transaction = db.get(OidcAuthorizationTransaction, UUID(str(start["transaction_id"])))
        assert transaction is not None and transaction.consumed_at is None

    _install_provider_responses(monkeypatch, id_token=token, jwk=jwk)
    assert _callback(start).status_code == 200


def test_refresh_token_response_is_rejected_without_consuming(monkeypatch) -> None:
    _, admin_id, handler_id = _seed()
    headers = _headers(admin_id)
    stack = _create_provider_stack(headers)
    _bind(str(stack["provider"]["id"]), handler_id)
    start = _start()
    private_key, jwk = _rsa_signer()
    token = _id_token(private_key=private_key, jwk=jwk, nonce=str(start["nonce"]))
    monkeypatch.setattr(
        "app.modules.auth.oidc_callback._post_token_request",
        lambda **_: {"id_token": token, "refresh_token": "forbidden-refresh-token"},
    )
    monkeypatch.setattr(
        "app.modules.auth.oidc_callback._get_jwks",
        lambda **_: {"keys": [jwk]},
    )
    assert _callback(start).status_code == 401
    with TestingSessionLocal() as db:
        transaction = db.get(OidcAuthorizationTransaction, UUID(str(start["transaction_id"])))
        assert transaction is not None and transaction.consumed_at is None
