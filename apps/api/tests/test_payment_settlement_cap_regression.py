from uuid import UUID

from app.modules.settlements.models import PaymentAuthorization, PaymentStatus
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import login
from tests.test_settlement_payment_ledger import _approved_adjustment


def setup_function() -> None:
    reset_database()


def _accepted_settlement(claim_id: str, adjustment: dict) -> str:
    client.cookies.clear()
    login("alpha", "alpha-admin@example.com")
    created = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/settlements",
        json={
            "adjustment_statement_id": adjustment["id"],
            "title": "Settlement cap regression",
            "settlement_type": "final",
            "amount": "1000.00",
            "terms": "Regression fixture for cumulative payment authorization controls.",
        },
    )
    assert created.status_code == 201, created.text
    settlement_id = created.json()["id"]
    assert client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/settlements/{settlement_id}/submit"
    ).status_code == 200

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    approved = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/settlements/{settlement_id}/approve",
        json={"note": "Independent approval for settlement-cap regression coverage."},
    )
    assert approved.status_code == 200, approved.text
    accepted = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/settlements/{settlement_id}/disposition/record",
        json={"disposition": "accepted", "note": "Accepted for payment-cap regression testing."},
    )
    assert accepted.status_code == 200, accepted.text
    return settlement_id


def _create_payment(claim_id: str, settlement_id: str, amount: str, purpose: str) -> dict:
    response = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/payments",
        json={
            "settlement_id": settlement_id,
            "payee": "Orion Shipowning Ltd",
            "amount": amount,
            "purpose": purpose,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_rejected_payment_cannot_be_resubmitted_when_other_active_authorizations_fill_cap() -> None:
    claim_id, adjustment, _ = _approved_adjustment()
    settlement_id = _accepted_settlement(claim_id, adjustment)

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    payment_a = _create_payment(claim_id, settlement_id, "700.00", "First proposed instalment.")
    assert client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/payments/{payment_a['id']}/submit"
    ).status_code == 200

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    rejected = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/payments/{payment_a['id']}/reject",
        json={"note": "Reject so a different payment may legitimately use the released capacity."},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    payment_b = _create_payment(claim_id, settlement_id, "700.00", "Replacement proposed instalment.")
    resubmit = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/payments/{payment_a['id']}/submit"
    )
    assert resubmit.status_code == 422, resubmit.text
    assert "cannot exceed" in resubmit.json()["detail"]

    ledger = client.get(f"/api/v1/claims/{claim_id}/settlement-ledger")
    by_id = {row["id"]: row for row in ledger.json()["payments"]}
    assert by_id[payment_a["id"]]["status"] == "rejected"
    assert by_id[payment_b["id"]]["status"] == "draft"


def test_approval_revalidates_cap_for_legacy_or_pre_fix_overallocated_state() -> None:
    claim_id, adjustment, _ = _approved_adjustment()
    settlement_id = _accepted_settlement(claim_id, adjustment)

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    payment_a = _create_payment(claim_id, settlement_id, "700.00", "Legacy authorization candidate.")
    assert client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/payments/{payment_a['id']}/submit"
    ).status_code == 200

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    assert client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/payments/{payment_a['id']}/reject",
        json={"note": "Release capacity before creating the competing authorization."},
    ).status_code == 200

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    _create_payment(claim_id, settlement_id, "700.00", "Competing active authorization.")

    # Simulate a legacy/pre-fix row that already re-entered an active review state.
    # Approval must still fail closed instead of converting invalid ledger state
    # into first_approved/authorized authority.
    with TestingSessionLocal() as db:
        row = db.get(PaymentAuthorization, UUID(payment_a["id"]))
        assert row is not None
        row.status = PaymentStatus.UNDER_REVIEW
        db.commit()

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    approval = client.post(
        f"/api/v1/claims/{claim_id}/settlement-ledger/payments/{payment_a['id']}/approve",
        json={"note": "This approval must fail because the cumulative ledger exceeds the settlement cap."},
    )
    assert approval.status_code == 422, approval.text
    assert "cannot exceed" in approval.json()["detail"]

    with TestingSessionLocal() as db:
        row = db.get(PaymentAuthorization, UUID(payment_a["id"]))
        assert row is not None
        assert row.status == PaymentStatus.UNDER_REVIEW
