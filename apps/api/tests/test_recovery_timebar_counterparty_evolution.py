from tests.db_harness import client, reset_database
from tests.test_claims_api import create_orion_claim, login
from tests.test_recovery_timebar_maturity import _scenario_payload


def setup_function() -> None:
    reset_database()


def test_counterparty_revision_marks_linked_scenario_stale_until_deliberately_revised() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]

    created = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/counterparties",
        json={
            "name": "TurboMaker GmbH",
            "role": "Potential overhaul contractor",
            "allegation_basis": "Human investigation hypothesis only; fault and liability remain undetermined.",
            "source_reference": "Reviewed overhaul correspondence",
        },
    )
    assert created.status_code == 201, created.text
    counterparty_v1 = created.json()

    scenario = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/scenarios",
        json=_scenario_payload(counterparty_id=counterparty_v1["id"]),
    )
    assert scenario.status_code == 201, scenario.text
    scenario_v1 = scenario.json()
    assert scenario_v1["source_state_status"] == "reference_only"

    revised_counterparty = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/counterparties/{counterparty_v1['counterparty_key']}/revisions",
        json={
            "name": "TurboMaker GmbH",
            "role": "Workshop contractor / overhaul provider",
            "allegation_basis": "Revised human investigation context after additional correspondence; no liability finding.",
            "source_reference": "Updated reviewed overhaul correspondence",
            "expected_record_hash": counterparty_v1["record_hash"],
        },
    )
    assert revised_counterparty.status_code == 201, revised_counterparty.text
    counterparty_v2 = revised_counterparty.json()

    dashboard = client.get(f"/api/v1/claims/{claim_id}/recovery-timebar/maturity")
    assert dashboard.status_code == 200, dashboard.text
    stale_scenario = next(row for row in dashboard.json()["scenarios"] if row["id"] == scenario_v1["id"])
    assert stale_scenario["source_state_status"] == "stale"

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    blocked = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/scenarios/{scenario_v1['id']}/review",
        json={
            "action": "confirm",
            "scenario_hash": scenario_v1["scenario_hash"],
            "note": "This review must fail because the linked counterparty context evolved.",
        },
    )
    assert blocked.status_code == 409

    client.cookies.clear()
    login("alpha", "alpha-handler@example.com")
    revised_scenario = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/scenarios/{scenario_v1['scenario_key']}/revisions",
        json={
            **_scenario_payload(counterparty_id=counterparty_v2["id"]),
            "expected_scenario_hash": scenario_v1["scenario_hash"],
        },
    )
    assert revised_scenario.status_code == 201, revised_scenario.text
    scenario_v2 = revised_scenario.json()
    assert scenario_v2["version"] == 2
    assert scenario_v2["supersedes_id"] == scenario_v1["id"]
    assert scenario_v2["source_state_status"] == "reference_only"

    history = client.get(
        f"/api/v1/claims/{claim_id}/recovery-timebar/scenarios/{scenario_v1['scenario_key']}/history"
    )
    assert history.status_code == 200, history.text
    items = history.json()
    assert [row["version"] for row in items] == [2, 1]
    assert items[1]["source_state_status"] == "stale"
    assert items[1]["scenario_hash"] == scenario_v1["scenario_hash"]

    client.cookies.clear()
    login("alpha", "alpha-manager@example.com")
    accepted = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/scenarios/{scenario_v2['id']}/review",
        json={
            "action": "confirm",
            "scenario_hash": scenario_v2["scenario_hash"],
            "note": "Manager reviewed the deliberately revised scenario against the current human counterparty context.",
        },
    )
    assert accepted.status_code == 200, accepted.text
