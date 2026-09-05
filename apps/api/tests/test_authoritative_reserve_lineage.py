from decimal import Decimal

from app.modules.financial.models import CostReviewStatus
from tests.db_harness import client, reset_database
from tests.test_adjustment_controls import (
    _edit_invoice_amount,
    _seed_cost_schedule,
    _treat_all_lines,
)
from tests.test_claims_api import create_orion_claim, login
from tests.test_severity_reserve_support import _add_cost, _build


def setup_function() -> None:
    reset_database()


def _history(claim_id: str) -> dict:
    response = client.get(f"/api/v1/claims/{claim_id}/reserve-history")
    assert response.status_code == 200, response.text
    return response.json()


def _reserve_payload(
    *,
    amount: str,
    reason: str,
    key: str,
    history: dict,
    source_kind: str = "manual",
    source_reference_id: str | None = None,
) -> dict:
    return {
        "amount": amount,
        "reason": reason,
        "idempotency_key": key,
        "expected_reserve_version": history["current_version"],
        "expected_reserve_hash": history["current_hash"],
        "source_kind": source_kind,
        "source_reference_id": source_reference_id,
    }


def test_manual_reserve_is_versioned_idempotent_concurrency_safe_and_hash_chained() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    initial = _history(claim_id)
    assert initial["current_version"] == 0
    assert initial["current_hash"] is None
    assert initial["items"] == []

    first_payload = _reserve_payload(
        amount="250000.00",
        reason="Human manager reserve after review of the current claim file.",
        key="reserve-manual-0001",
        history=initial,
    )
    first = client.post(f"/api/v1/claims/{claim_id}/reserve", json=first_payload)
    assert first.status_code == 200, first.text
    assert first.json()["current_reserve"] == "250000.00"

    after_first = _history(claim_id)
    assert after_first["current_version"] == 1
    assert len(after_first["current_hash"]) == 64
    assert len(after_first["items"]) == 1
    row1 = after_first["items"][0]
    assert row1["sequence"] == 1
    assert row1["source_kind"] == "manual"
    assert row1["source_snapshot"]["amount_inferred"] is False
    assert row1["previous_reserve_hash"] is None
    assert row1["reserve_hash"] == after_first["current_hash"]

    replay = client.post(f"/api/v1/claims/{claim_id}/reserve", json=first_payload)
    assert replay.status_code == 200, replay.text
    assert len(_history(claim_id)["items"]) == 1

    changed_same_key = client.post(
        f"/api/v1/claims/{claim_id}/reserve",
        json={**first_payload, "amount": "260000.00"},
    )
    assert changed_same_key.status_code == 409
    assert "Idempotency key" in changed_same_key.json()["detail"]

    stale = client.post(
        f"/api/v1/claims/{claim_id}/reserve",
        json=_reserve_payload(
            amount="275000.00",
            reason="Stale concurrent reserve write must not succeed.",
            key="reserve-manual-stale-0002",
            history=initial,
        ),
    )
    assert stale.status_code == 409
    assert _history(claim_id)["current_reserve"] == "250000.00"

    second_payload = _reserve_payload(
        amount="300000.00",
        reason="Second deliberate human reserve review against the current lineage token.",
        key="reserve-manual-0002",
        history=after_first,
    )
    second = client.post(f"/api/v1/claims/{claim_id}/reserve", json=second_payload)
    assert second.status_code == 200, second.text
    final = _history(claim_id)
    assert final["current_version"] == 2
    assert final["current_reserve"] == "300000.00"
    assert len(final["items"]) == 2
    row2 = final["items"][0]
    assert row2["sequence"] == 2
    assert row2["previous_reserve_hash"] == row1["reserve_hash"]
    assert row2["reserve_hash"] != row1["reserve_hash"]


def test_reserve_support_is_advisory_provenance_and_stale_source_requires_explicit_refresh() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _add_cost(
        claim_id,
        amount="100000",
        currency="USD",
        status=CostReviewStatus.ACCEPTED,
        line_index=0,
    )
    support_v1 = _build(claim_id)
    reserve_eval = next(row for row in support_v1["evaluations"] if row["kind"] == "reserve")
    assert reserve_eval["status"] == "triggered"

    initial = _history(claim_id)
    chosen_amount = Decimal("333333.00")
    assert chosen_amount not in {
        Decimal(str(reserve_eval["lower_amount"])),
        Decimal(str(reserve_eval["upper_amount"])),
    }
    first_payload = _reserve_payload(
        amount=str(chosen_amount),
        reason="Manager considered the advisory range but deliberately set a different authoritative reserve.",
        key="reserve-support-0001",
        history=initial,
        source_kind="reserve_support",
        source_reference_id=support_v1["id"],
    )
    first = client.post(f"/api/v1/claims/{claim_id}/reserve", json=first_payload)
    assert first.status_code == 200, first.text
    after_first = _history(claim_id)
    assert after_first["current_reserve"] == "333333.00"
    row1 = after_first["items"][0]
    assert row1["source_kind"] == "reserve_support"
    assert row1["source_reference_id"] == support_v1["id"]
    assert row1["source_snapshot"]["advisory_only"] is True
    assert row1["source_snapshot"]["amount_inferred"] is False
    assert row1["source_snapshot"]["reserve_evaluation_current_verified"] is True

    # Exact replay remains idempotent even though the authoritative reserve now
    # changes the context that a later Support snapshot would include.
    replay = client.post(f"/api/v1/claims/{claim_id}/reserve", json=first_payload)
    assert replay.status_code == 200, replay.text
    assert len(_history(claim_id)["items"]) == 1

    # Refresh is explicit. The first reserve change naturally makes v1 historical.
    support_v2 = _build(claim_id)
    assert support_v2["id"] != support_v1["id"]
    _add_cost(
        claim_id,
        amount="80000",
        currency="USD",
        status=CostReviewStatus.UNDER_REVIEW,
        line_index=1,
    )
    stale_source = client.post(
        f"/api/v1/claims/{claim_id}/reserve",
        json=_reserve_payload(
            amount="360000.00",
            reason="Old advisory support must not be accepted after source evidence evolves.",
            key="reserve-support-stale-0002",
            history=after_first,
            source_kind="reserve_support",
            source_reference_id=support_v2["id"],
        ),
    )
    assert stale_source.status_code == 409
    preserved = _history(claim_id)
    assert preserved["current_reserve"] == "333333.00"
    assert preserved["current_version"] == 1
    assert len(preserved["items"]) == 1

    # A rejected authoritative write must not mutate advisory state as a side
    # effect. The operator deliberately refreshes Support in a separate action.
    unchanged_dashboard = client.get(f"/api/v1/claims/{claim_id}/severity-reserve").json()
    assert unchanged_dashboard["snapshot"]["id"] == support_v2["id"]
    support_v3 = _build(claim_id)
    assert support_v3["id"] != support_v2["id"]

    current_write = client.post(
        f"/api/v1/claims/{claim_id}/reserve",
        json=_reserve_payload(
            amount="360000.00",
            reason="Deliberate reserve update after explicitly refreshing advisory support against current evidence.",
            key="reserve-support-0003",
            history=preserved,
            source_kind="reserve_support",
            source_reference_id=support_v3["id"],
        ),
    )
    assert current_write.status_code == 200, current_write.text
    final = _history(claim_id)
    assert final["current_version"] == 2
    assert final["items"][0]["previous_reserve_hash"] == row1["reserve_hash"]


def test_approved_current_adjustment_can_be_provenance_but_stale_adjustment_cannot_drive_new_write() -> None:
    claim_id, _, refs = _seed_cost_schedule()
    statement = client.post(f"/api/v1/claims/{claim_id}/adjustments", json={"currency": "USD"}).json()
    statement = _treat_all_lines(claim_id, statement)
    submitted = client.post(f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/submit")
    assert submitted.status_code == 200, submitted.text

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    approved = client.post(
        f"/api/v1/claims/{claim_id}/adjustments/{statement['id']}/approve",
        json={"note": "Manager approved the source-bound Adjustment before considering reserve."},
    )
    assert approved.status_code == 200, approved.text
    adjustment = approved.json()

    initial = _history(claim_id)
    chosen_amount = "900.00"
    assert chosen_amount != adjustment["net_adjusted"]
    first = client.post(
        f"/api/v1/claims/{claim_id}/reserve",
        json=_reserve_payload(
            amount=chosen_amount,
            reason="Manager used the approved Adjustment as provenance but entered reserve independently.",
            key="reserve-adjustment-0001",
            history=initial,
            source_kind="adjustment",
            source_reference_id=adjustment["id"],
        ),
    )
    assert first.status_code == 200, first.text
    after_first = _history(claim_id)
    row1 = after_first["items"][0]
    assert row1["source_kind"] == "adjustment"
    assert row1["source_snapshot"]["statement_id"] == adjustment["id"]
    assert row1["source_snapshot"]["content_hash"] == adjustment["content_hash"]
    assert row1["source_snapshot"]["amount_inferred"] is False

    _edit_invoice_amount(
        run_id=refs["usd_run_id"],
        field_path="invoice.line_items[0].amount",
        value="1250.00",
        user_email="alpha-admin@example.com",
    )
    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    stale = client.post(
        f"/api/v1/claims/{claim_id}/reserve",
        json=_reserve_payload(
            amount="1200.00",
            reason="A stale Adjustment must not be reused as current provenance.",
            key="reserve-adjustment-stale-0002",
            history=after_first,
            source_kind="adjustment",
            source_reference_id=adjustment["id"],
        ),
    )
    assert stale.status_code == 409
    preserved = _history(claim_id)
    assert preserved["current_reserve"] == chosen_amount
    assert preserved["current_version"] == 1
    assert len(preserved["items"]) == 1
