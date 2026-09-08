import json
from hashlib import sha256
from uuid import UUID

from app.core.security import create_access_token
from app.modules.audit.models import AuditLog
from app.modules.auth.mfa_policy_models import MfaPolicy
from app.modules.auth.service import create_auth_session
from app.modules.auth.webauthn_models import WebAuthnRegistrationTransaction
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


def _seed_org(slug: str) -> tuple[UUID, UUID, UUID]:
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
        handler = User(
            organization_id=org.id,
            email=f"handler-{slug}@example.com",
            full_name="Claims Handler",
            password_hash="",
            role=UserRole.CLAIMS_HANDLER,
            is_active=True,
        )
        db.add_all([admin, handler])
        db.commit()
        return org.id, admin.id, handler.id


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


def _create_profile(admin_headers: dict[str, str], *, rp_name: str = "MCRI Claims") -> dict:
    response = client.post(
        "/api/v1/auth/webauthn/rp-profiles",
        headers=admin_headers,
        json={
            "rp_id": "claims.example.com",
            "rp_name": rp_name,
            "allowed_origins": [
                "https://app.claims.example.com/",
                "https://claims.example.com",
            ],
            "user_verification": "required",
            "attestation": "none",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_webauthn_profile_and_registration_challenge_are_governed_and_hash_only() -> None:
    org_id, admin_id, handler_id = _seed_org("webauthn-primary")
    admin_headers, _ = _headers(admin_id)
    handler_headers, handler_session_id = _headers(handler_id)

    profile = _create_profile(admin_headers)
    assert profile["profile_number"] == 1
    assert profile["rp_id"] == "claims.example.com"
    assert profile["allowed_origins"] == [
        "https://app.claims.example.com",
        "https://claims.example.com",
    ]
    assert profile["user_verification"] == "required"
    assert profile["attestation"] == "none"

    begun = client.post(
        "/api/v1/auth/webauthn/registration/begin",
        headers=handler_headers,
    )
    assert begun.status_code == 201, begun.text
    payload = begun.json()
    transaction_id = UUID(payload["transaction_id"])
    challenge = payload["challenge"]
    assert len(challenge) >= 40
    assert payload["timeout_ms"] == 300000
    assert payload["rp"] == {"id": "claims.example.com", "name": "MCRI Claims"}
    assert payload["user"]["name"] == "handler-webauthn-primary@example.com"
    assert payload["authenticator_selection"]["user_verification"] == "required"
    assert payload["attestation"] == "none"
    assert {item["alg"] for item in payload["pub_key_cred_params"]} == {-7, -257}

    with TestingSessionLocal() as db:
        transaction = db.get(WebAuthnRegistrationTransaction, transaction_id)
        assert transaction is not None
        assert transaction.organization_id == org_id
        assert transaction.user_id == handler_id
        assert transaction.auth_session_id == handler_session_id
        assert transaction.challenge_hash == sha256(challenge.encode("ascii")).hexdigest()
        assert challenge not in json.dumps(transaction.__dict__, default=str)

        audits = (
            db.query(AuditLog)
            .filter(AuditLog.entity_id == transaction_id)
            .all()
        )
        assert audits
        assert challenge not in json.dumps(
            [
                {
                    "action": audit.action,
                    "old_values": audit.old_values,
                    "new_values": audit.new_values,
                    "details": audit.details,
                }
                for audit in audits
            ],
            default=str,
        )

    replacement = client.post(
        "/api/v1/auth/webauthn/registration/begin",
        headers=handler_headers,
    )
    assert replacement.status_code == 201, replacement.text
    assert replacement.json()["challenge"] != challenge
    replacement_id = UUID(replacement.json()["transaction_id"])

    with TestingSessionLocal() as db:
        original = db.get(WebAuthnRegistrationTransaction, transaction_id)
        replacement_tx = db.get(WebAuthnRegistrationTransaction, replacement_id)
        assert original is not None and original.cancelled_at is not None
        assert replacement_tx is not None and replacement_tx.cancelled_at is None
        open_count = (
            db.query(WebAuthnRegistrationTransaction)
            .filter(
                WebAuthnRegistrationTransaction.auth_session_id == handler_session_id,
                WebAuthnRegistrationTransaction.consumed_at.is_(None),
                WebAuthnRegistrationTransaction.cancelled_at.is_(None),
            )
            .count()
        )
        assert open_count == 1


def test_webauthn_registration_is_exact_session_scoped_and_profile_rotation_is_immutable() -> None:
    _, admin_id, handler_id = _seed_org("webauthn-session")
    admin_headers, _ = _headers(admin_id)
    first_headers, _ = _headers(handler_id)
    second_headers, _ = _headers(handler_id)
    first_profile = _create_profile(admin_headers)

    begun = client.post(
        "/api/v1/auth/webauthn/registration/begin",
        headers=first_headers,
    )
    assert begun.status_code == 201
    transaction_id = UUID(begun.json()["transaction_id"])

    foreign_session_cancel = client.post(
        f"/api/v1/auth/webauthn/registration/{transaction_id}/cancel",
        headers=second_headers,
    )
    assert foreign_session_cancel.status_code == 409

    second_profile = _create_profile(admin_headers, rp_name="MCRI Claims Rotated")
    assert second_profile["profile_number"] == 2
    assert second_profile["previous_profile_hash"] == first_profile["profile_hash"]

    cancelled = client.post(
        f"/api/v1/auth/webauthn/registration/{transaction_id}/cancel",
        headers=first_headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["profile_number"] == 1
    assert cancelled.json()["profile_hash"] == first_profile["profile_hash"]

    next_begin = client.post(
        "/api/v1/auth/webauthn/registration/begin",
        headers=first_headers,
    )
    assert next_begin.status_code == 201
    next_id = UUID(next_begin.json()["transaction_id"])
    with TestingSessionLocal() as db:
        next_tx = db.get(WebAuthnRegistrationTransaction, next_id)
        assert next_tx is not None
        assert next_tx.profile_number == 2
        assert next_tx.profile_hash == second_profile["profile_hash"]


def test_webauthn_surfaces_obey_enabled_tenant_mfa_policy() -> None:
    org_id, admin_id, handler_id = _seed_org("webauthn-policy")
    admin_headers, _ = _headers(admin_id)
    handler_headers, _ = _headers(handler_id)
    with TestingSessionLocal() as db:
        db.add(
            MfaPolicy(
                organization_id=org_id,
                is_enabled=True,
                required_roles=["admin", "claims_handler"],
                updated_by_id=admin_id,
            )
        )
        db.commit()

    profile_blocked = client.post(
        "/api/v1/auth/webauthn/rp-profiles",
        headers=admin_headers,
        json={
            "rp_id": "claims.example.com",
            "rp_name": "MCRI Claims",
            "allowed_origins": ["https://claims.example.com"],
        },
    )
    assert profile_blocked.status_code == 403
    assert profile_blocked.json()["detail"]["code"] == "mfa_enrollment_required"

    registration_blocked = client.post(
        "/api/v1/auth/webauthn/registration/begin",
        headers=handler_headers,
    )
    assert registration_blocked.status_code == 403
    assert registration_blocked.json()["detail"]["code"] == "mfa_enrollment_required"
