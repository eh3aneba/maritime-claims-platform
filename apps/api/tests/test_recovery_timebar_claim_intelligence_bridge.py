from app.modules.claims.models import ClaimStatus
from tests.db_harness import client, reset_database
from tests.test_claim_intelligence import _add_fact, _set_status
from tests.test_claims_api import create_orion_claim


def setup_function() -> None:
    reset_database()


def _build_intelligence(claim_id: str) -> dict:
    response = client.post(f"/api/v1/claims/{claim_id}/intelligence/build")
    assert response.status_code == 201, response.text
    return response.json()


def test_claim_intelligence_consumes_structured_recovery_timebar_without_legacy_recovery_lead() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    _add_fact(claim_id, "recovery.counterparty", "TurboMaker GmbH")
    _add_fact(claim_id, "recovery.basis", "Reviewed recent overhaul / workmanship investigation")
    _add_fact(claim_id, "timebar.source_reference", "Reviewed Workshop Contract clause 12")
    _add_fact(claim_id, "timebar.trigger_date", "2026-07-10")
    _add_fact(claim_id, "timebar.period_value", 6)
    _add_fact(claim_id, "timebar.period_unit", "months")

    snapshot = _build_intelligence(claim_id)

    assert snapshot["summary"]["recovery_timebar_engine_version"] == "12C.1"
    assert snapshot["summary"]["structured_recovery_timebar_count"] == 2
    assert snapshot["summary"]["authoritative_deadline_created"] is False
    assert snapshot["summary"]["recoverability_decision_made"] is False
    assert not any(item["item_key"] == "recovery-preservation-lead" for item in snapshot["items"])
    assert not any(item["item_key"] == "next-recovery-preservation" for item in snapshot["items"])

    recovery = next(
        item
        for item in snapshot["items"]
        if item["category"] == "recovery_lead"
        and any(ref["kind"] == "recovery_timebar_evaluation" for ref in item["source_refs"])
    )
    deadline = next(
        item
        for item in snapshot["items"]
        if item["category"] == "deadline_lead"
        and any(ref["kind"] == "recovery_timebar_evaluation" for ref in item["source_refs"])
    )
    assert recovery["suggested_action"] is None
    assert recovery["action_type"] is None
    assert deadline["suggested_action"] is None
    assert deadline["action_type"] is None
    assert "2027-01-10" in deadline["description"]
    assert "human/legal verification required" in deadline["description"].lower()

    blocked = client.post(
        f"/api/v1/claims/{claim_id}/intelligence/items/{deadline['id']}/decision",
        json={
            "action": "accept",
            "note": "Reviewed proxy item; controlled diary conversion belongs in the Recovery workspace.",
            "convert_to_task": True,
        },
    )
    assert blocked.status_code == 409
    assert "suggested action" in blocked.json()["detail"].lower()


def test_claim_intelligence_recovery_proxy_updates_when_structured_source_state_changes() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    _add_fact(claim_id, "recovery.counterparty", "Potential workshop")

    first = _build_intelligence(claim_id)
    first_recovery = next(
        item
        for item in first["items"]
        if item["category"] == "recovery_lead"
        and any(ref["kind"] == "recovery_timebar_evaluation" for ref in item["source_refs"])
    )
    assert "Missing prerequisites" in first_recovery["description"]

    _add_fact(claim_id, "recovery.basis", "Reviewed workmanship investigation basis")
    second = _build_intelligence(claim_id)

    assert second["snapshot_version"] == first["snapshot_version"] + 1
    assert second["source_state_hash"] != first["source_state_hash"]
    second_recovery = next(
        item
        for item in second["items"]
        if item["category"] == "recovery_lead"
        and any(ref["kind"] == "recovery_timebar_evaluation" for ref in item["source_refs"])
    )
    assert second_recovery["item_hash"] != first_recovery["item_hash"]
