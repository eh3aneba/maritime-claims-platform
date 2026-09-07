from uuid import UUID

from app.core.security import create_access_token
from app.modules.auth.models import (
    AuthSession,
    EnterpriseIdentityProvider,
    ExternalIdentityBinding,
)
from app.modules.auth.service import create_auth_session
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


def _seed() -> tuple[UUID, UUID, UUID, UUID, UUID]:
    with TestingSessionLocal() as db:
        org_a = Organization(name="Alpha Marine", slug="alpha-external-id")
        org_b = Organization(name="Beta Marine", slug="beta-external-id")
        db.add_all([org_a, org_b])
        db.flush()

        admin_a = User(
            organization_id=org_a.id,
            email="alpha-admin-idp@example.com",
            full_name="Alpha Admin",
            password_hash="",
            role=UserRole.ADMIN,
            is_active=True,
        )
        handler_a = User(
            organization_id=org_a.id,
            email="alpha-handler-idp@example.com",
            full_name="Alpha Handler",
            password_hash="",
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        admin_b = User(
            organization_id=org_b.id,
            email="beta-admin-idp@example.com",
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


def _create_enabled_provider(headers: dict[str, str]) -> dict[str, object]:
    created = client.post(
        "/api/v1/auth/identity-providers",
        headers=headers,
        json={
            "provider_key": "corp-oidc",
            "display_name": "Corporate OIDC",
            "protocol": "oidc",
            "issuer_identifier": "https://identity.example.test/tenant-a",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["is_enabled"] is False

    enabled = client.post(
        f"/api/v1/auth/identity-providers/{body['id']}/enable",
        headers=headers,
    )
    assert enabled.status_code == 200
    assert enabled.json()["is_enabled"] is True
    return enabled.json()


def test_provider_registry_is_tenant_scoped_and_inactive_by_default() -> None:
    _, admin_a_id, _, _, admin_b_id = _seed()
    alpha_headers = _headers(admin_a_id)
    beta_headers = _headers(admin_b_id)

    created = client.post(
        "/api/v1/auth/identity-providers",
        headers=alpha_headers,
        json={
            "provider_key": "corp-saml",
            "display_name": "Corporate SAML",
            "protocol": "saml",
            "issuer_identifier": "urn:example:test:tenant-a",
        },
    )
    assert created.status_code == 201
    provider = created.json()
    assert provider["is_enabled"] is False

    alpha_list = client.get("/api/v1/auth/identity-providers", headers=alpha_headers)
    beta_list = client.get("/api/v1/auth/identity-providers", headers=beta_headers)
    assert alpha_list.status_code == 200
    assert len(alpha_list.json()) == 1
    assert beta_list.status_code == 200
    assert beta_list.json() == []

    cross_tenant = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/enable",
        headers=beta_headers,
    )
    assert cross_tenant.status_code == 404


def test_binding_persists_only_subject_fingerprint_and_does_not_change_authority() -> None:
    _, admin_a_id, handler_a_id, _, _ = _seed()
    headers = _headers(admin_a_id)
    provider = _create_enabled_provider(headers)
    external_subject = "opaque-subject-12345"

    with TestingSessionLocal() as db:
        session_count_before = db.query(AuthSession).count()
        user_count_before = db.query(User).count()
        handler = db.get(User, handler_a_id)
        assert handler is not None
        role_before = handler.role

    created = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/bindings",
        headers=headers,
        json={
            "user_id": str(handler_a_id),
            "external_subject": external_subject,
        },
    )
    assert created.status_code == 201
    binding = created.json()
    assert binding["user_id"] == str(handler_a_id)
    assert len(binding["subject_fingerprint"]) == 64
    assert external_subject not in str(binding)

    with TestingSessionLocal() as db:
        stored = db.get(ExternalIdentityBinding, UUID(binding["id"]))
        assert stored is not None
        assert stored.subject_fingerprint == binding["subject_fingerprint"]
        assert external_subject not in str(stored.__dict__)
        assert db.query(AuthSession).count() == session_count_before
        assert db.query(User).count() == user_count_before
        handler = db.get(User, handler_a_id)
        assert handler is not None
        assert handler.role == role_before


def test_binding_requires_enabled_provider_and_existing_same_tenant_user() -> None:
    _, admin_a_id, handler_a_id, _, admin_b_id = _seed()
    headers = _headers(admin_a_id)

    created = client.post(
        "/api/v1/auth/identity-providers",
        headers=headers,
        json={
            "provider_key": "disabled-oidc",
            "display_name": "Disabled OIDC",
            "protocol": "oidc",
            "issuer_identifier": "https://identity.example.test/disabled",
        },
    )
    assert created.status_code == 201
    provider_id = created.json()["id"]

    disabled_binding = client.post(
        f"/api/v1/auth/identity-providers/{provider_id}/bindings",
        headers=headers,
        json={
            "user_id": str(handler_a_id),
            "external_subject": "opaque-disabled-sub",
        },
    )
    assert disabled_binding.status_code == 409

    assert (
        client.post(
            f"/api/v1/auth/identity-providers/{provider_id}/enable",
            headers=headers,
        ).status_code
        == 200
    )
    cross_tenant_user = client.post(
        f"/api/v1/auth/identity-providers/{provider_id}/bindings",
        headers=headers,
        json={
            "user_id": str(admin_b_id),
            "external_subject": "opaque-beta-sub",
        },
    )
    assert cross_tenant_user.status_code == 404


def test_duplicate_subject_and_active_user_binding_are_rejected() -> None:
    _, admin_a_id, handler_a_id, _, _ = _seed()
    headers = _headers(admin_a_id)
    provider = _create_enabled_provider(headers)

    first = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/bindings",
        headers=headers,
        json={
            "user_id": str(handler_a_id),
            "external_subject": "subject-one",
        },
    )
    assert first.status_code == 201

    duplicate_user = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/bindings",
        headers=headers,
        json={
            "user_id": str(handler_a_id),
            "external_subject": "subject-two",
        },
    )
    assert duplicate_user.status_code == 409

    with TestingSessionLocal() as db:
        provider_model = db.get(
            EnterpriseIdentityProvider,
            UUID(str(provider["id"])),
        )
        assert provider_model is not None
        other_user = User(
            organization_id=provider_model.organization_id,
            email="alpha-other-idp@example.com",
            full_name="Alpha Other",
            password_hash="",
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        db.add(other_user)
        db.commit()
        other_user_id = other_user.id

    duplicate_subject = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/bindings",
        headers=headers,
        json={
            "user_id": str(other_user_id),
            "external_subject": "subject-one",
        },
    )
    assert duplicate_subject.status_code == 409


def test_revocation_preserves_history_and_allows_new_subject_binding() -> None:
    _, admin_a_id, handler_a_id, _, _ = _seed()
    headers = _headers(admin_a_id)
    provider = _create_enabled_provider(headers)

    first = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/bindings",
        headers=headers,
        json={
            "user_id": str(handler_a_id),
            "external_subject": "subject-before-revoke",
        },
    )
    assert first.status_code == 201
    first_id = first.json()["id"]

    revoked = client.post(
        f"/api/v1/auth/external-bindings/{first_id}/revoke",
        headers=headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["revoked_at"] is not None

    second = client.post(
        f"/api/v1/auth/identity-providers/{provider['id']}/bindings",
        headers=headers,
        json={
            "user_id": str(handler_a_id),
            "external_subject": "subject-after-revoke",
        },
    )
    assert second.status_code == 201
    second_id = second.json()["id"]

    history = client.get(
        f"/api/v1/auth/identity-providers/{provider['id']}/bindings",
        headers=headers,
    )
    assert history.status_code == 200
    rows = history.json()
    assert len(rows) == 2
    by_id = {row["id"]: row for row in rows}
    assert by_id[first_id]["revoked_at"] is not None
    assert by_id[second_id]["revoked_at"] is None


def test_non_admin_cannot_manage_enterprise_identity_registry() -> None:
    _, _, handler_a_id, _, _ = _seed()
    headers = _headers(handler_a_id)
    response = client.get("/api/v1/auth/identity-providers", headers=headers)
    assert response.status_code == 403
