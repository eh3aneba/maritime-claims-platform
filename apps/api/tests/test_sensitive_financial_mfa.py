from uuid import UUID

from app.modules.auth import mfa
from tests.db_harness import client, reset_database
from tests.test_claims_api import login
from tests.test_settlement_payment_ledger import _approved_adjustment


def setup_function() -> None:
    reset_database()


def test_payment_approval_requires_mfa_when_claims_manager_role_is_policy_required(monkeypatch) -> None:
    claim_id, adjustment, _ = _approved_adjustment()

    # Build an accepted settlement while the organization MFA policy is still disabled.
    client.cookies.clear()
    login("alpha", "alpha-admin@example.com")
    created = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/settlements",
        json={
            "adjustment_statement_id": adjustment["id"],
            "title": "MFA-sensitive payment regression",
            "settlement_type": "final",
            "amount": "1000.00",
            "terms": "Regression fixture for sensitive-operation MFA enforcement.",
        },
    )
    assert created.status_code == 201, created.text
    settlement_id = created.json()["id"]
    submitted = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/settlements/{settlement_id}/submit"
    )
    assert submitted.status_code == 200, submitted.text

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    approved = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/settlements/{settlement_id}/approve",
        json={"note": "Approve before enabling the MFA policy for this regression fixture."},
    )
    assert approved.status_code == 200, approved.text
    accepted = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/settlements/{settlement_id}/disposition/record",
        json={"disposition": "accepted", "note": "Accepted before policy activation."},
    )
    assert accepted.status_code == 200, accepted.text

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    payment = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/payments",
        json={
            "settlement_id": settlement_id,
            "payee": "Orion Shipowning Ltd",
            "amount": "700.00",
            "purpose": "Sensitive payment approval MFA regression.",
        },
    )
    assert payment.status_code == 201, payment.text
    payment_id = payment.json()["id"]
    payment_submit = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/payments/{payment_id}/submit"
    )
    assert payment_submit.status_code == 200, payment_submit.text

    # Require MFA for Claims Managers only. The Admin can enable the policy
    # without being newly subject to that role-specific requirement.
    client.cookies.clear()
    login("alpha", "alpha-admin@example.com")
    policy = client.put(
        "/api/v1/auth/mfa-policy",
        json={"is_enabled": True, "required_roles": ["claims_manager"]},
    )
    assert policy.status_code == 200, policy.text

    # Reproduce F02: a Claims Manager without any enrolled factor must not be
    # able to approve a payment authorization.
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    blocked_without_factor = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/payments/{payment_id}/approve",
        json={"note": "Must be blocked until MFA enrollment and session step-up."},
    )
    assert blocked_without_factor.status_code == 403, blocked_without_factor.text
    assert blocked_without_factor.json()["detail"]["code"] == "mfa_enrollment_required"

    enrollment = client.post("/api/v1/auth/mfa/totp/enroll")
    assert enrollment.status_code == 201, enrollment.text
    factor_id = UUID(enrollment.json()["factor_id"])
    secret = enrollment.json()["secret"]

    first_step = mfa._current_time_step()
    confirmation = client.post(
        f"/api/v1/auth/mfa/totp/{factor_id}/confirm",
        json={"code": mfa._totp_code(secret, first_step)},
    )
    assert confirmation.status_code == 200, confirmation.text

    # Enrollment alone is insufficient; the current session still needs step-up.
    blocked_without_step_up = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/payments/{payment_id}/approve",
        json={"note": "Must remain blocked until this session verifies MFA."},
    )
    assert blocked_without_step_up.status_code == 403, blocked_without_step_up.text
    assert blocked_without_step_up.json()["detail"]["code"] == "mfa_verification_required"

    second_step = first_step + 1
    monkeypatch.setattr(mfa, "_current_time_step", lambda period_seconds=30: second_step)
    verification = client.post(
        "/api/v1/auth/mfa/totp/verify",
        json={"code": mfa._totp_code(secret, second_step)},
    )
    assert verification.status_code == 200, verification.text

    allowed = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/payments/{payment_id}/approve",
        json={"note": "MFA-verified independent first approval."},
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["status"] == "first_approved"
