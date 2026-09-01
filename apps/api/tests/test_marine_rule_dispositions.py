from uuid import UUID

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.claims.models import ClaimStatus
from app.modules.rules.models import MarineRuleEvaluationDecision, RuleEvaluationRun
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim
from tests.test_rules_engine import _add_fact, _set_status


def setup_function() -> None:
    reset_database()


def _trigger_tech_001(claim_id: str) -> dict:
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    _add_fact(claim_id, "maintenance.running_hours_since_overhaul", 14800)
    _add_fact(claim_id, "maintenance.recommended_overhaul_interval", 12000)
    response = client.post(f"/api/v1/claims/{claim_id}/rules/evaluate")
    assert response.status_code == 200, response.text
    payload = response.json()
    evaluation = next(
        row for row in payload["summary"]["marine_rule_evaluations"]
        if row["rule_id"] == "TECH-001"
    )
    assert evaluation["status"] == "triggered"
    return {
        "run_id": payload["run_id"],
        "evaluation": evaluation,
    }


def test_marine_rule_decisions_are_append_only_hash_chained_and_do_not_mutate_evaluation() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    current = _trigger_tech_001(claim_id)
    run_id = current["run_id"]
    evaluation = current["evaluation"]
    original_implication = evaluation["candidate_implication"]
    evaluation_hash = evaluation["evaluation_hash"]

    accepted = client.post(
        f"/api/v1/claims/{claim_id}/rules/runs/{run_id}/evaluations/TECH-001/decision",
        json={
            "evaluation_hash": evaluation_hash,
            "action": "accept",
            "note": "Reviewed against the cited running-hours evidence.",
        },
    )
    assert accepted.status_code == 200, accepted.text
    first = accepted.json()
    assert first["decision_number"] == 1
    assert first["previous_decision_hash"] is None
    assert len(first["decision_hash"]) == 64

    edited = client.post(
        f"/api/v1/claims/{claim_id}/rules/runs/{run_id}/evaluations/TECH-001/decision",
        json={
            "evaluation_hash": evaluation_hash,
            "action": "edit",
            "note": "Human wording narrowed after technical review.",
            "edited_candidate_implication": "Running-hours evidence warrants maintenance review only; no causation conclusion is adopted.",
        },
    )
    assert edited.status_code == 200, edited.text
    second = edited.json()
    assert second["decision_number"] == 2
    assert second["previous_decision_hash"] == first["decision_hash"]
    assert second["decision_hash"] != first["decision_hash"]

    summary = client.get(f"/api/v1/claims/{claim_id}/rules")
    assert summary.status_code == 200, summary.text
    latest = next(row for row in summary.json()["marine_rule_evaluations"] if row["rule_id"] == "TECH-001")
    assert latest["evaluation_hash"] == evaluation_hash
    assert latest["candidate_implication"] == original_implication
    assert latest["latest_decision"]["action"] == "edit"
    assert latest["latest_decision"]["decision_number"] == 2
    assert latest["latest_decision"]["edited_candidate_implication"].startswith("Running-hours evidence")

    with TestingSessionLocal() as db:
        decisions = list(
            db.scalars(
                select(MarineRuleEvaluationDecision).where(
                    MarineRuleEvaluationDecision.claim_id == UUID(claim_id),
                    MarineRuleEvaluationDecision.rule_id == "TECH-001",
                    MarineRuleEvaluationDecision.evaluation_hash == evaluation_hash,
                ).order_by(MarineRuleEvaluationDecision.decision_number.asc())
            )
        )
        assert [row.decision_number for row in decisions] == [1, 2]
        run = db.get(RuleEvaluationRun, UUID(run_id))
        assert run is not None
        persisted = next(row for row in run.summary["marine_rule_evaluations"] if row["rule_id"] == "TECH-001")
        assert persisted["candidate_implication"] == original_implication
        assert "latest_decision" not in persisted
        audits = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.action == "REVIEW_MARINE_RULE_EVALUATION",
                    AuditLog.organization_id == run.organization_id,
                )
            )
        )
        assert len(audits) == 2


def test_rejects_decision_on_superseded_marine_rule_run() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    first = _trigger_tech_001(claim_id)

    second_response = client.post(f"/api/v1/claims/{claim_id}/rules/evaluate")
    assert second_response.status_code == 200, second_response.text
    assert second_response.json()["run_id"] != first["run_id"]

    stale = client.post(
        f"/api/v1/claims/{claim_id}/rules/runs/{first['run_id']}/evaluations/TECH-001/decision",
        json={
            "evaluation_hash": first["evaluation"]["evaluation_hash"],
            "action": "accept",
            "note": "Attempt to review an older evaluation run.",
        },
    )
    assert stale.status_code == 409
    assert "superseded" in stale.json()["detail"].lower()


def test_rejects_stale_evaluation_hash_on_latest_run() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    current = _trigger_tech_001(claim_id)

    stale = client.post(
        f"/api/v1/claims/{claim_id}/rules/runs/{current['run_id']}/evaluations/TECH-001/decision",
        json={
            "evaluation_hash": "0" * 64,
            "action": "dismiss",
            "note": "Hash no longer matches the reviewed evaluation.",
        },
    )
    assert stale.status_code == 409
    assert "changed" in stale.json()["detail"].lower()


def test_edit_requires_actual_human_edit() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    current = _trigger_tech_001(claim_id)

    response = client.post(
        f"/api/v1/claims/{claim_id}/rules/runs/{current['run_id']}/evaluations/TECH-001/decision",
        json={
            "evaluation_hash": current["evaluation"]["evaluation_hash"],
            "action": "edit",
            "note": "Edit requested without replacement wording.",
        },
    )
    assert response.status_code == 422
