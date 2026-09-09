import hashlib
import hmac
import json
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from app.core.security import create_access_token
from app.modules.auth.mfa_policy_models import MfaPolicy
from app.modules.auth.service import create_auth_session
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.claims.retention_models import ClaimLegalHold, LegalHoldProposal
from app.modules.claims.retention_service import create_retention_policy
from app.modules.claims.retention_signal_models import PreservationSignalProfile
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, client, reset_database


def setup_function() -> None:
    reset_database()


def _seed_tenant(*, slug: str, claim_age_days: int = 120) -> tuple[UUID, UUID, UUID, UUID]:
    with TestingSessionLocal() as db:
        org = Organization(name=f"Signal {slug}", slug=slug)
        db.add(org)
        db.flush()
        admin = User(
            organization_id=org.id,
            email=f"admin-{slug}@example.com",
            full_name=f"Admin {slug}",
            password_hash="local",
            role=UserRole.ADMIN,
            is_active=True,
        )
        manager = User(
            organization_id=org.id,
            email=f"manager-{slug}@example.com",
            full_name=f"Manager {slug}",
            password_hash="local",
            role=UserRole.CLAIMS_MANAGER,
            is_active=True,
        )
        vessel = Vessel(organization_id=org.id, name=f"MT {slug.upper()}")
        db.add_all([admin, manager, vessel])
        db.flush()
        anchor = datetime.now(timezone.utc) - timedelta(days=claim_age_days)
        claim = Claim(
            organization_id=org.id,
            vessel_id=vessel.id,
            handler_id=manager.id,
            claim_reference=f"SIG-{slug.upper()}-001",
            status=ClaimStatus.CLOSED,
            incident_date=date(2026, 1, 1),
            notification_date=date(2026, 1, 2),
            incident_description="Closed claim used for preservation signal intake tests.",
            currency="USD",
            created_at=anchor,
            updated_at=anchor,
        )
        db.add(claim)
        db.flush()
        create_retention_policy(
            db,
            organization_id=org.id,
            closed_claim_retention_days=30,
            evidence_retention_days=30,
            enabled=True,
            disposal_enabled=True,
            created_by_id=admin.id,
        )
        db.commit()
        return org.id, admin.id, manager.id, claim.id


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
    admin_id: UUID,
    *,
    name: str = "outside-counsel",
    enabled: bool = True,
    allowed: list[str] | None = None,
) -> tuple[UUID, str, int]:
    response = client.post(
        "/api/v1/claims/retention/signal-intake/profiles",
        headers=_headers(admin_id),
        json={
            "name": name,
            "enabled": enabled,
            "allowed_hold_sources": allowed or ["litigation", "regulatory", "investigation"],
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return UUID(body["profile"]["id"]), body["signing_secret"], body["profile"]["secret_version"]


def _raw_payload(claim_id: UUID, *, event_type: str = "litigation.notice", reason: str | None = None) -> bytes:
    return json.dumps(
        {
            "claim_id": str(claim_id),
            "recommended_hold_source": "litigation",
            "reason": reason or "Outside counsel requests preservation review for this claim.",
            "event_type": event_type,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _signed_headers(
    *,
    secret: str,
    version: int,
    raw_body: bytes,
    signal_id: str,
    timestamp: int | None = None,
) -> dict[str, str]:
    value = str(timestamp if timestamp is not None else int(datetime.now(timezone.utc).timestamp()))
    signing_input = value.encode() + b"." + str(version).encode() + b"." + raw_body
    signature = hmac.new(secret.encode(), signing_input, hashlib.sha256).hexdigest()
    return {
        "X-MCRI-Signal-ID": signal_id,
        "X-MCRI-Signal-Timestamp": value,
        "X-MCRI-Signal-Key-Version": str(version),
        "X-MCRI-Signal-Signature": f"sha256={signature}",
        "Content-Type": "application/json",
    }


def test_signed_signal_creates_pending_proposal_is_idempotent_and_never_creates_hold() -> None:
    org_id, admin_id, _manager_id, claim_id = _seed_tenant(slug="signed")
    profile_id, secret, version = _create_profile(admin_id)
    raw = _raw_payload(claim_id)
    headers = _signed_headers(
        secret=secret,
        version=version,
        raw_body=raw,
        signal_id="matter-2026-001",
    )
    url = f"/api/v1/claims/retention/signal-intake/profiles/{profile_id}/signals"

    first = client.post(url, headers=headers, content=raw)
    assert first.status_code == 202, first.text
    assert first.json()["created"] is True
    proposal_id = UUID(first.json()["proposal_id"])

    replay = client.post(url, headers=headers, content=raw)
    assert replay.status_code == 202, replay.text
    assert replay.json()["created"] is False
    assert UUID(replay.json()["proposal_id"]) == proposal_id

    with TestingSessionLocal() as db:
        proposal = db.get(LegalHoldProposal, proposal_id)
        assert proposal is not None
        assert proposal.organization_id == org_id
        assert proposal.claim_id == claim_id
        assert proposal.source_kind == "webhook"
        assert proposal.status == "pending"
        assert db.query(LegalHoldProposal).filter(LegalHoldProposal.claim_id == claim_id).count() == 1
        assert db.query(ClaimLegalHold).filter(ClaimLegalHold.claim_id == claim_id).count() == 0

    preview = client.get(
        f"/api/v1/claims/{claim_id}/disposal-eligibility",
        headers=_headers(admin_id),
    )
    assert preview.status_code == 200
    assert preview.json()["eligible"] is False
    assert preview.json()["pending_proposal_ids"] == [str(proposal_id)]
    assert "pending_legal_hold_proposal" in preview.json()["blocking_reasons"]


def test_reused_signal_identity_with_changed_semantics_fails_closed() -> None:
    _org_id, admin_id, _manager_id, claim_id = _seed_tenant(slug="tamper")
    profile_id, secret, version = _create_profile(admin_id)
    url = f"/api/v1/claims/retention/signal-intake/profiles/{profile_id}/signals"
    first_raw = _raw_payload(claim_id)
    first_headers = _signed_headers(
        secret=secret,
        version=version,
        raw_body=first_raw,
        signal_id="stable-signal-id",
    )
    assert client.post(url, headers=first_headers, content=first_raw).status_code == 202

    changed_raw = _raw_payload(claim_id, event_type="litigation.notice.changed")
    changed_headers = _signed_headers(
        secret=secret,
        version=version,
        raw_body=changed_raw,
        signal_id="stable-signal-id",
    )
    changed = client.post(url, headers=changed_headers, content=changed_raw)
    assert changed.status_code == 409
    assert "different payload" in changed.json()["detail"]


def test_signature_freshness_profile_enablement_and_tenant_scope_fail_closed() -> None:
    _org_id, admin_id, _manager_id, claim_id = _seed_tenant(slug="auth")
    _other_org_id, _other_admin_id, _other_manager_id, other_claim_id = _seed_tenant(slug="other")
    profile_id, secret, version = _create_profile(admin_id, enabled=True)
    url = f"/api/v1/claims/retention/signal-intake/profiles/{profile_id}/signals"
    raw = _raw_payload(claim_id)

    invalid = _signed_headers(secret=secret, version=version, raw_body=raw, signal_id="bad-signature")
    invalid["X-MCRI-Signal-Signature"] = "sha256=" + ("0" * 64)
    assert client.post(url, headers=invalid, content=raw).status_code == 401

    stale_time = int((datetime.now(timezone.utc) - timedelta(minutes=10)).timestamp())
    stale = _signed_headers(
        secret=secret,
        version=version,
        raw_body=raw,
        signal_id="stale",
        timestamp=stale_time,
    )
    assert client.post(url, headers=stale, content=raw).status_code == 401

    cross_raw = _raw_payload(other_claim_id)
    cross = _signed_headers(
        secret=secret,
        version=version,
        raw_body=cross_raw,
        signal_id="cross-tenant",
    )
    assert client.post(url, headers=cross, content=cross_raw).status_code == 404

    disabled_id, disabled_secret, disabled_version = _create_profile(
        admin_id,
        name="disabled-source",
        enabled=False,
    )
    disabled_raw = _raw_payload(claim_id)
    disabled_headers = _signed_headers(
        secret=disabled_secret,
        version=disabled_version,
        raw_body=disabled_raw,
        signal_id="disabled",
    )
    disabled_url = (
        f"/api/v1/claims/retention/signal-intake/profiles/{disabled_id}/signals"
    )
    assert client.post(disabled_url, headers=disabled_headers, content=disabled_raw).status_code == 401


def test_secret_rotation_accepts_previous_key_during_grace_and_does_not_persist_secret() -> None:
    _org_id, admin_id, _manager_id, claim_id = _seed_tenant(slug="rotation")
    profile_id, old_secret, old_version = _create_profile(admin_id)
    admin_headers = _headers(admin_id)
    rotated = client.post(
        f"/api/v1/claims/retention/signal-intake/profiles/{profile_id}/rotate-secret",
        headers=admin_headers,
    )
    assert rotated.status_code == 200, rotated.text
    new_secret = rotated.json()["signing_secret"]
    new_version = rotated.json()["profile"]["secret_version"]
    assert new_version == old_version + 1
    assert new_secret != old_secret

    old_raw = _raw_payload(claim_id, event_type="litigation.notice.old-key")
    old_headers = _signed_headers(
        secret=old_secret,
        version=old_version,
        raw_body=old_raw,
        signal_id="old-key-grace",
    )
    url = f"/api/v1/claims/retention/signal-intake/profiles/{profile_id}/signals"
    assert client.post(url, headers=old_headers, content=old_raw).status_code == 202

    with TestingSessionLocal() as db:
        profile = db.get(PreservationSignalProfile, profile_id)
        assert profile is not None
        assert profile.previous_secret_version == old_version
        assert profile.previous_secret_valid_until is not None
        column_names = set(PreservationSignalProfile.__table__.columns.keys())
        assert "signing_secret" not in column_names
        assert old_secret not in str(profile.__dict__)
        assert new_secret not in str(profile.__dict__)


def test_profile_admin_and_mfa_authority_are_enforced() -> None:
    org_id, admin_id, manager_id, _claim_id = _seed_tenant(slug="authority")
    manager_denied = client.post(
        "/api/v1/claims/retention/signal-intake/profiles",
        headers=_headers(manager_id),
        json={
            "name": "manager-must-not-create",
            "enabled": False,
            "allowed_hold_sources": ["litigation"],
        },
    )
    assert manager_denied.status_code == 403

    profile_id, _secret, _version = _create_profile(admin_id, enabled=False)
    admin_headers = _headers(admin_id)
    with TestingSessionLocal() as db:
        db.add(
            MfaPolicy(
                organization_id=org_id,
                is_enabled=True,
                required_roles=[UserRole.ADMIN.value],
                updated_by_id=admin_id,
            )
        )
        db.commit()

    blocked = client.patch(
        f"/api/v1/claims/retention/signal-intake/profiles/{profile_id}",
        headers=admin_headers,
        json={"enabled": True},
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "mfa_enrollment_required"
