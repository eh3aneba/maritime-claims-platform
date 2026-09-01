from app.modules.claims.models import ClaimStatus
from tests.db_harness import client, reset_database
from tests.test_claims_api import create_orion_claim
from tests.test_rules_engine import _add_fact, _set_status


def setup_function() -> None:
    reset_database()


def _trigger_recent_overhaul(claim_id: str) -> dict:
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    _add_fact(claim_id, "maintenance.last_overhaul_date", "2026-06-20")
    response = client.post(f"/api/v1/claims/{claim_id}/rules/evaluate")
    assert response.status_code == 200, response.text
    payload = response.json()
    evaluation = next(
        row
        for row in payload["summary"]["marine_rule_evaluations"]
        if row["rule_id"] == "TECH-002"
    )
    assert evaluation["status"] == "triggered"
    return {"run_id": payload["run_id"], "evaluation": evaluation}


def _decide(claim_id: str, current: dict, *, action: str, **extra) -> dict:
    response = client.post(
        f"/api/v1/claims/{claim_id}/rules/runs/{current['run_id']}/evaluations/TECH-002/decision",
        json={
            "evaluation_hash": current["evaluation"]["evaluation_hash"],
            "action": action,
            "note": "Human disposition controls whether this rule may feed downstream recovery analysis.",
            **extra,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _build_recovery(claim_id: str) -> dict:
    response = client.post(f"/api/v1/claims/{claim_id}/recovery-timebar/build")
    assert response.status_code == 201, response.text
    return response.json()


def test_dismissed_recent_overhaul_rule_does_not_feed_recovery_engine() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    current = _trigger_recent_overhaul(claim_id)
    decision = _decide(claim_id, current, action="dismiss")
    assert decision["action"] == "dismiss"

    snapshot = _build_recovery(claim_id)
    recovery = next(row for row in snapshot["evaluations"] if row["kind"] == "recovery")
    timebar = next(row for row in snapshot["evaluations"] if row["kind"] == "timebar")

    assert recovery["status"] == "not_applicable"
    assert timebar["status"] == "not_applicable"
    assert not any(
        source.get("kind") == "marine_rule_evaluation" and source.get("id") == "TECH-002"
        for source in recovery["source_refs"]
    )
    assert snapshot["summary"]["recoverability_decision_made"] is False
    assert snapshot["summary"]["authoritative_deadline_created"] is False


def test_edited_recent_overhaul_rule_flows_downstream_with_human_lineage() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    current = _trigger_recent_overhaul(claim_id)

    baseline = _build_recovery(claim_id)
    baseline_recovery = next(row for row in baseline["evaluations"] if row["kind"] == "recovery")
    assert baseline_recovery["status"] == "insufficient_evidence"

    # Refresh the Marine Rules run because building Recovery also evaluates rules and supersedes the prior run.
    refreshed = client.post(f"/api/v1/claims/{claim_id}/rules/evaluate")
    assert refreshed.status_code == 200, refreshed.text
    refreshed_payload = refreshed.json()
    evaluation = next(
        row
        for row in refreshed_payload["summary"]["marine_rule_evaluations"]
        if row["rule_id"] == "TECH-002"
    )
    current = {"run_id": refreshed_payload["run_id"], "evaluation": evaluation}

    edited_implication = (
        "Human review limits the recovery prompt to investigating the recent workshop scope; "
        "no workmanship or responsibility conclusion is adopted."
    )
    edited_action = "Preserve the overhaul file and ask the workshop to clarify the reviewed scope without alleging fault."
    decision = _decide(
        claim_id,
        current,
        action="edit",
        edited_candidate_implication=edited_implication,
        edited_recommended_action=edited_action,
    )
    assert decision["action"] == "edit"

    updated = _build_recovery(claim_id)
    recovery = next(row for row in updated["evaluations"] if row["kind"] == "recovery")

    assert updated["snapshot_version"] == baseline["snapshot_version"] + 1
    assert updated["source_state_hash"] != baseline["source_state_hash"]
    assert recovery["candidate_basis"] == edited_implication
    source = next(
        source
        for source in recovery["source_refs"]
        if source.get("kind") == "marine_rule_evaluation" and source.get("id") == "TECH-002"
    )
    assert source["human_disposition"]["action"] == "edit"
    assert source["human_disposition"]["decision_number"] == decision["decision_number"]
    assert source["human_disposition"]["decision_hash"] == decision["decision_hash"]
    assert recovery["status"] == "insufficient_evidence"
    assert "identified recovery counterparty" in recovery["missing_prerequisites"]
