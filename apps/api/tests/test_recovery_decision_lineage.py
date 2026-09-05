from uuid import UUID

from sqlalchemy import select

from app.modules.recovery_timebar.decision_models import RecoveryActionLog, RecoveryPursuitDecision
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim


def setup_function() -> None:
    reset_database()


def _counterparty(claim_id: str) -> dict:
    response = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/counterparties",
        json={
            "name": "TurboMaker GmbH",
            "role": "Potential workshop / overhaul contractor",
            "allegation_basis": "Human investigation hypothesis only; no platform finding of fault or liability.",
            "source_reference": "Reviewed overhaul correspondence and workshop contract",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _decision(claim_id: str, counterparty_id: str, **overrides) -> dict:
    payload = {
        "counterparty_id": counterparty_id,
        "disposition": "monitor",
        "rationale": "Preserve the potential recovery path while factual and legal review continues.",
        "basis_reference": "Handler recovery review note R-01",
        "next_review_date": "2026-09-20",
    }
    payload.update(overrides)
    response = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/decisions",
        json=payload,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_human_recovery_decision_and_action_log_are_append_only_hash_chains() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    counterparty = _counterparty(claim_id)
    decision = _decision(claim_id, counterparty["id"])

    assert decision["version"] == 1
    assert decision["disposition"] == "monitor"
    assert decision["context_state_status"] == "reference_only"
    assert decision["actions"] == []

    duplicate = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/decisions",
        json={
            "counterparty_id": counterparty["id"],
            "disposition": "pursue",
            "rationale": "A second authoritative path for the same logical counterparty should not be created.",
            "basis_reference": "Duplicate-path test",
        },
    )
    assert duplicate.status_code == 409

    first_action = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/decisions/{decision['decision_key']}/actions",
        json={
            "decision_hash": decision["decision_hash"],
            "action_type": "correspondence",
            "direction": "outbound",
            "occurred_on": "2026-09-05",
            "summary": "Handler sent a preservation notice drafted and approved outside the platform.",
            "source_reference": "Email file REC-001",
        },
    )
    assert first_action.status_code == 201, first_action.text
    action_1 = first_action.json()
    assert action_1["action_number"] == 1
    assert action_1["previous_action_hash"] is None

    second_action = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/decisions/{decision['decision_key']}/actions",
        json={
            "decision_hash": decision["decision_hash"],
            "action_type": "response",
            "direction": "inbound",
            "occurred_on": "2026-09-08",
            "summary": "External counterparty acknowledged receipt without admission.",
            "source_reference": "Email file REC-002",
            "external_status": "Acknowledged — no admission",
            "external_response_date": "2026-09-08",
        },
    )
    assert second_action.status_code == 201, second_action.text
    action_2 = second_action.json()
    assert action_2["action_number"] == 2
    assert action_2["previous_action_hash"] == action_1["action_hash"]
    assert action_2["external_response_date"] == "2026-09-08"

    dashboard = client.get(f"/api/v1/claims/{claim_id}/recovery-timebar/decisions")
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.json()
    assert "explicit human claim-handling records" in body["disclaimer"]
    current = body["decisions"][0]
    assert [row["action_number"] for row in current["actions"]] == [2, 1]

    with TestingSessionLocal() as db:
        decisions = list(
            db.scalars(
                select(RecoveryPursuitDecision).where(
                    RecoveryPursuitDecision.claim_id == UUID(claim_id)
                )
            )
        )
        actions = list(
            db.scalars(
                select(RecoveryActionLog)
                .where(RecoveryActionLog.claim_id == UUID(claim_id))
                .order_by(RecoveryActionLog.action_number.asc())
            )
        )
        assert len(decisions) == 1
        assert len(actions) == 2
        assert actions[1].previous_action_hash == actions[0].action_hash


def test_counterparty_evolution_stales_decision_blocks_actions_and_requires_deliberate_revision() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    counterparty_v1 = _counterparty(claim_id)
    decision_v1 = _decision(claim_id, counterparty_v1["id"])

    revised_counterparty = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/counterparties/{counterparty_v1['counterparty_key']}/revisions",
        json={
            "name": "TurboMaker GmbH",
            "role": "Workshop contractor / overhaul provider",
            "allegation_basis": "Revised human investigation context after further correspondence; liability remains undetermined.",
            "source_reference": "Updated reviewed correspondence",
            "expected_record_hash": counterparty_v1["record_hash"],
        },
    )
    assert revised_counterparty.status_code == 201, revised_counterparty.text
    counterparty_v2 = revised_counterparty.json()

    dashboard = client.get(f"/api/v1/claims/{claim_id}/recovery-timebar/decisions")
    assert dashboard.status_code == 200, dashboard.text
    stale = dashboard.json()["decisions"][0]
    assert stale["id"] == decision_v1["id"]
    assert stale["context_state_status"] == "stale"

    blocked_action = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/decisions/{decision_v1['decision_key']}/actions",
        json={
            "decision_hash": decision_v1["decision_hash"],
            "action_type": "follow_up",
            "direction": "outbound",
            "occurred_on": "2026-09-09",
            "summary": "This write must fail because the decision context is stale.",
            "source_reference": "Regression test",
        },
    )
    assert blocked_action.status_code == 409

    stale_revision = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/decisions/{decision_v1['decision_key']}/revisions",
        json={
            "counterparty_id": counterparty_v2["id"],
            "disposition": "pursue",
            "rationale": "Attempt with stale optimistic hash.",
            "basis_reference": "Regression test",
            "expected_decision_hash": "0" * 64,
        },
    )
    assert stale_revision.status_code == 409

    revised_decision = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/decisions/{decision_v1['decision_key']}/revisions",
        json={
            "counterparty_id": counterparty_v2["id"],
            "disposition": "pursue",
            "rationale": "Handler deliberately refreshes the recovery path against the current human counterparty context.",
            "basis_reference": "Recovery review note R-02",
            "next_review_date": "2026-09-30",
            "expected_decision_hash": decision_v1["decision_hash"],
        },
    )
    assert revised_decision.status_code == 201, revised_decision.text
    decision_v2 = revised_decision.json()
    assert decision_v2["version"] == 2
    assert decision_v2["supersedes_id"] == decision_v1["id"]
    assert decision_v2["previous_decision_hash"] == decision_v1["decision_hash"]
    assert decision_v2["context_state_status"] == "reference_only"

    accepted_action = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/decisions/{decision_v2['decision_key']}/actions",
        json={
            "decision_hash": decision_v2["decision_hash"],
            "action_type": "note",
            "direction": "internal",
            "occurred_on": "2026-09-09",
            "summary": "Current decision context reviewed; next externally approved recovery step remains human-controlled.",
            "source_reference": "Recovery review note R-02",
        },
    )
    assert accepted_action.status_code == 201, accepted_action.text

    history = client.get(
        f"/api/v1/claims/{claim_id}/recovery-timebar/decisions/{decision_v1['decision_key']}/history"
    )
    assert history.status_code == 200, history.text
    items = history.json()
    assert [row["version"] for row in items] == [2, 1]
    assert items[0]["context_state_status"] == "reference_only"
    assert items[1]["context_state_status"] == "stale"
    assert items[1]["decision_hash"] == decision_v1["decision_hash"]
