import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from app.modules.auth.mfa_policy_models import MfaPolicy
from app.modules.auth.scim_models import ScimProvisioningProfile, ScimProvisioningToken
from app.modules.auth.service import create_auth_session
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


def _seed_actor(
    *,
    slug: str,
    email: str,
    role: UserRole = UserRole.ADMIN,
) -> tuple[UUID, UUID]:
    with TestingSessionLocal() as db:
        org = Organization(name=f"SCIM {slug}", slug=slug)
        db.add(org)
        db.flush()
        user = User(
            organization_id=org.id,
            email=email,
            full_name=f"SCIM Actor {slug}",
            password_hash="",
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        return org.id, user.id


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


def _create_profile(
    headers: dict[str, str],
    *,
    client_name: str = "Corporate Provisioner",
    enabled: bool = True,
    token_ttl_days: int = 30,
):
    return client.post(
        "/api/v1/auth/scim-provisioning/profiles",
        headers=headers,
        json={
            "client_name": client_name,
            "enabled": enabled,
            "token_ttl_days": token_ttl_days,
        },
    )


def _issue(headers: dict[str, str], profile_id: str):
    return client.post(
        f"/api/v1/auth/scim-provisioning/profiles/{profile_id}/tokens",
        headers=headers,
    )


def _service_config(token: str):
    return client.get(
        "/api/v1/scim/v2/ServiceProviderConfig",
        headers={"Authorization": f"Bearer {token}"},
    )


def test_service_config_requires_scim_bearer_and_exposes_only_bounded_capabilities() -> None:
    org_id, admin_id = _seed_actor(slug="service-config", email="scim-admin@example.com")
    headers = _headers(admin_id)

    unauthenticated = client.get("/api/v1/scim/v2/ServiceProviderConfig")
    assert unauthenticated.status_code == 401

    profile = _create_profile(headers)
    assert profile.status_code == 201, profile.text
    issued = _issue(headers, profile.json()["id"])
    assert issued.status_code == 201, issued.text
    plaintext = issued.json()["token"]

    with TestingSessionLocal() as db:
        users_before = db.query(User).filter(User.organization_id == org_id).count()

    response = _service_config(plaintext)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/scim+json")
    body = response.json()
    assert body["schemas"] == [
        "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
    ]
    assert body["patch"]["supported"] is False
    assert body["bulk"]["supported"] is False
    assert body["filter"]["supported"] is False
    assert body["changePassword"]["supported"] is False
    assert body["sort"]["supported"] is False
    assert body["etag"]["supported"] is False
    rendered = json.dumps(body, sort_keys=True)
    assert str(org_id) not in rendered
    assert "scim-admin@example.com" not in rendered

    with TestingSessionLocal() as db:
        users_after = db.query(User).filter(User.organization_id == org_id).count()
        assert users_after == users_before == 1


def test_profile_is_immutable_versioned_and_disabled_by_default() -> None:
    org_id, admin_id = _seed_actor(slug="profiles", email="profiles@example.com")
    headers = _headers(admin_id)

    disabled = client.post(
        "/api/v1/auth/scim-provisioning/profiles",
        headers=headers,
        json={"client_name": "Default Disabled", "token_ttl_days": 14},
    )
    assert disabled.status_code == 201, disabled.text
    assert disabled.json()["enabled"] is False
    assert disabled.json()["profile_number"] == 1

    blocked = _issue(headers, disabled.json()["id"])
    assert blocked.status_code == 409

    enabled = _create_profile(
        headers,
        client_name="Enabled Provisioner",
        enabled=True,
        token_ttl_days=21,
    )
    assert enabled.status_code == 201, enabled.text
    assert enabled.json()["profile_number"] == 2
    assert enabled.json()["previous_profile_hash"] == disabled.json()["profile_hash"]

    history = client.get("/api/v1/auth/scim-provisioning/profiles", headers=headers)
    assert history.status_code == 200
    assert [item["profile_number"] for item in history.json()] == [1, 2]

    with TestingSessionLocal() as db:
        profiles = (
            db.query(ScimProvisioningProfile)
            .filter(ScimProvisioningProfile.organization_id == org_id)
            .order_by(ScimProvisioningProfile.profile_number)
            .all()
        )
        assert len(profiles) == 2
        assert profiles[0].profile_hash == disabled.json()["profile_hash"]
        assert profiles[1].previous_profile_hash == profiles[0].profile_hash


def test_plaintext_token_is_returned_once_but_never_persisted_or_audited() -> None:
    org_id, admin_id = _seed_actor(slug="token-custody", email="custody@example.com")
    headers = _headers(admin_id)
    profile = _create_profile(headers)
    assert profile.status_code == 201

    issued = _issue(headers, profile.json()["id"])
    assert issued.status_code == 201, issued.text
    body = issued.json()
    plaintext = body["token"]
    assert plaintext.startswith("mcri_scim_")
    assert len(plaintext) >= 70
    assert "token_digest" not in body["credential"]

    with TestingSessionLocal() as db:
        record = db.get(ScimProvisioningToken, UUID(body["credential"]["id"]))
        assert record is not None
        assert record.organization_id == org_id
        assert record.token_digest != plaintext
        assert len(record.token_digest) == 64
        assert record.token_prefix == plaintext[:16]
        assert "plaintext_token" not in ScimProvisioningToken.__table__.columns

        audit_rows = (
            db.query(AuditLog)
            .filter(AuditLog.organization_id == org_id)
            .order_by(AuditLog.created_at)
            .all()
        )
        assert audit_rows
        audit_text = json.dumps(
            [
                {
                    "action": row.action,
                    "old": row.old_values,
                    "new": row.new_values,
                    "details": row.details,
                }
                for row in audit_rows
            ],
            sort_keys=True,
        )
        assert plaintext not in audit_text
        assert record.token_digest not in audit_text
        assert "token_digest" not in audit_text


def test_rotation_revocation_expiry_and_profile_rotation_all_fail_closed() -> None:
    _, admin_id = _seed_actor(slug="lifecycle", email="lifecycle@example.com")
    headers = _headers(admin_id)
    profile = _create_profile(headers)
    assert profile.status_code == 201
    profile_id = profile.json()["id"]

    first = _issue(headers, profile_id)
    assert first.status_code == 201
    first_token = first.json()["token"]
    first_id = first.json()["credential"]["id"]
    assert _service_config(first_token).status_code == 200

    second = _issue(headers, profile_id)
    assert second.status_code == 201, second.text
    second_token = second.json()["token"]
    second_id = second.json()["credential"]["id"]
    assert second_token != first_token
    assert _service_config(first_token).status_code == 401
    assert _service_config(second_token).status_code == 200

    with TestingSessionLocal() as db:
        old = db.get(ScimProvisioningToken, UUID(first_id))
        assert old is not None
        assert old.revoked_at is not None
        assert old.revocation_reason == "rotated"

    revoked = client.post(
        f"/api/v1/auth/scim-provisioning/tokens/{second_id}/revoke",
        headers=headers,
    )
    assert revoked.status_code == 200, revoked.text
    assert _service_config(second_token).status_code == 401

    third = _issue(headers, profile_id)
    assert third.status_code == 201
    third_token = third.json()["token"]
    third_id = UUID(third.json()["credential"]["id"])
    with TestingSessionLocal() as db:
        record = db.get(ScimProvisioningToken, third_id)
        assert record is not None
        record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert _service_config(third_token).status_code == 401

    fourth = _issue(headers, profile_id)
    assert fourth.status_code == 201
    fourth_token = fourth.json()["token"]
    assert _service_config(fourth_token).status_code == 200

    disabled_next = _create_profile(
        headers,
        client_name="Provisioning Disabled",
        enabled=False,
    )
    assert disabled_next.status_code == 201
    assert disabled_next.json()["profile_number"] == profile.json()["profile_number"] + 1
    assert _service_config(fourth_token).status_code == 401


def test_control_plane_is_admin_tenant_scoped_and_mfa_sensitive() -> None:
    org_a, admin_a = _seed_actor(slug="tenant-a", email="a@example.com")
    _, admin_b = _seed_actor(slug="tenant-b", email="b@example.com")
    _, handler = _seed_actor(
        slug="tenant-handler",
        email="handler@example.com",
        role=UserRole.CLAIMS_HANDLER,
    )
    headers_a = _headers(admin_a)
    headers_b = _headers(admin_b)
    handler_headers = _headers(handler)

    forbidden = _create_profile(handler_headers)
    assert forbidden.status_code == 403

    profile = _create_profile(headers_a)
    assert profile.status_code == 201
    issued = _issue(headers_a, profile.json()["id"])
    assert issued.status_code == 201
    token_id = issued.json()["credential"]["id"]

    cross_tenant = client.post(
        f"/api/v1/auth/scim-provisioning/tokens/{token_id}/revoke",
        headers=headers_b,
    )
    assert cross_tenant.status_code == 404
    assert _service_config(issued.json()["token"]).status_code == 200

    with TestingSessionLocal() as db:
        policy = MfaPolicy(
            organization_id=org_a,
            is_enabled=True,
            required_roles=[UserRole.ADMIN.value],
            updated_by_id=admin_a,
        )
        db.add(policy)
        db.commit()

    blocked_by_mfa = client.get(
        "/api/v1/auth/scim-provisioning/profile",
        headers=headers_a,
    )
    assert blocked_by_mfa.status_code == 403
    assert blocked_by_mfa.json()["detail"]["code"] == "mfa_enrollment_required"


def test_scim_token_cannot_be_used_as_application_session_and_is_tenant_pinned() -> None:
    org_a, admin_a = _seed_actor(slug="authority-a", email="authority-a@example.com")
    org_b, admin_b = _seed_actor(slug="authority-b", email="authority-b@example.com")
    headers_a = _headers(admin_a)
    headers_b = _headers(admin_b)

    profile_a = _create_profile(headers_a, client_name="A Provisioner")
    profile_b = _create_profile(headers_b, client_name="B Provisioner")
    assert profile_a.status_code == 201 and profile_b.status_code == 201
    token_a = _issue(headers_a, profile_a.json()["id"])
    token_b = _issue(headers_b, profile_b.json()["id"])
    assert token_a.status_code == 201 and token_b.status_code == 201

    plaintext_a = token_a.json()["token"]
    plaintext_b = token_b.json()["token"]
    assert _service_config(plaintext_a).status_code == 200
    assert _service_config(plaintext_b).status_code == 200

    application_auth_attempt = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {plaintext_a}"},
    )
    assert application_auth_attempt.status_code == 401

    with TestingSessionLocal() as db:
        token_record_a = db.get(
            ScimProvisioningToken,
            UUID(token_a.json()["credential"]["id"]),
        )
        token_record_b = db.get(
            ScimProvisioningToken,
            UUID(token_b.json()["credential"]["id"]),
        )
        assert token_record_a is not None and token_record_b is not None
        assert token_record_a.organization_id == org_a
        assert token_record_b.organization_id == org_b
        assert token_record_a.organization_id != token_record_b.organization_id
