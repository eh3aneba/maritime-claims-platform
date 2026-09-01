from datetime import date
from uuid import UUID

from sqlalchemy import select

from app.modules.claims.models import ClaimStatus
from app.modules.recovery_timebar.models import RecoveryTimebarDecision, RecoveryTimebarSnapshot
from app.modules.tasks.models import ClaimTask, TaskSource
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claim_intelligence import _add_fact, _set_status
from tests.test_claims_api import create_orion_claim


def setup_function() -> None:
    reset_database()


def _build(claim_id: str) -> dict:
    response = client.post(f"/api/v1/claims/{claim_id}/recovery-timebar/build")
    assert response.status_code == 201, response.text
    return response.json()


def _complete_recovery_timebar_facts(claim_id: str) -> None:
    _add_fact(claim_id, "recovery.counterparty", "TurboMaker GmbH")
    _add_fact(claim_id, "recovery.basis", "Reviewed recent overhaul / workmanship investigation")
    _add_fact(claim_id, "recovery.evidence_preservation", "Preserve overhaul report, removed parts and workshop correspondence")
    _add_fact(claim_id, "timebar.source_reference", "Reviewed Workshop Contract clause 12")
    _add_fact(claim_id, "timebar.trigger_date", "2026-07-10")
    _add_fact(claim_id, "timebar.period_value", 6)
    _add_fact(claim_id, "timebar.period_unit", "months")
    _add_fact(claim_id, "timebar.label", "Workshop contractual notice review")


def test_builds_source_linked_candidate_deadline_and_reuses_same_day_snapshot() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    _complete_recovery_timebar_facts(claim_id)

    first = _build(claim_id)
    second = _build(claim_id)

    assert first["id"] == second["id"]
    assert first["snapshot_version"] == 1
    assert first["engine_version"] == "12C.1"
    assert date.fromisoformat(first["evaluation_date"])
    assert len(first["source_state_hash"]) == 64
    assert len(first["snapshot_hash"]) == 64
    assert first["summary"]["non_authoritative"] is True
    assert first["summary"]["authoritative_deadline_created"] is False
    assert first["summary"]["recoverability_decision_made"] is False

    recovery = next(row for row in first["evaluations"] if row["kind"] == "recovery")
    timebar = next(row for row in first["evaluations"] if row["kind"] == "timebar")
    assert recovery["status"] == "triggered"
    assert recovery["counterparty"] == "TurboMaker GmbH"
    assert timebar["status"] == "triggered"
    assert timebar["trigger_date"] == "2026-07-10"
    assert timebar["candidate_deadline"] == "2027-01-10"
    assert timebar["missing_prerequisites"] == []
    assert all(ref["kind"] == "claim_fact" for ref in timebar["source_refs"])
    assert len(timebar["evaluation_hash"]) == 64


def test_incomplete_timebar_never_invents_candidate_date() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    _add_fact(claim_id, "recovery.counterparty", "Potential workshop")

    snapshot = _build(claim_id)
    recovery = next(row for row in snapshot["evaluations"] if row["kind"] == "recovery")
    timebar = next(row for row in snapshot["evaluations"] if row["kind"] == "timebar")

    assert recovery["status"] == "insufficient_evidence"
    assert timebar["status"] == "insufficient_evidence"
    assert timebar["candidate_deadline"] is None
    assert timebar["days_remaining"] is None
    assert "reviewed time-bar / notice source reference" in timebar["missing_prerequisites"]
    assert "human-approved trigger date" in timebar["missing_prerequisites"]
    assert "reviewed period value" in timebar["missing_prerequisites"]


def test_recent_overhaul_marine_rule_creates_recovery_evidence_gap_without_fault_finding() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    _add_fact(claim_id, "maintenance.last_overhaul_date", "2026-06-20")

    snapshot = _build(claim_id)
    recovery = next(row for row in snapshot["evaluations"] if row["kind"] == "recovery")

    assert recovery["status"] == "insufficient_evidence"
    assert "identified recovery counterparty" in recovery["missing_prerequisites"]
    assert any(
        ref["kind"] == "marine_rule_evaluation" and ref["id"] == "TECH-002"
        for ref in recovery["source_refs"]
    )
    assert "not determined fault" in recovery["rationale"].lower()
    assert recovery["candidate_deadline"] is None


def test_human_task_conversion_uses_candidate_date_and_prevents_duplicate_or_stale_actions() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    _complete_recovery_timebar_facts(claim_id)
    first = _build(claim_id)
    timebar = next(row for row in first["evaluations"] if row["kind"] == "timebar")

    accepted = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/evaluations/{timebar['id']}/decision",
        json={
            "action": "accept",
            "evaluation_hash": timebar["evaluation_hash"],
            "note": "Reviewed the cited contract source and candidate diary date.",
            "convert_to_task": True,
        },
    )
    assert accepted.status_code == 200, accepted.text
    decision = accepted.json()
    assert decision["converted_task_id"] is not None
    assert len(decision["decision_hash"]) == 64

    duplicate = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/evaluations/{timebar['id']}/decision",
        json={
            "action": "accept",
            "evaluation_hash": timebar["evaluation_hash"],
            "note": "Attempted duplicate diary conversion after prior human review.",
            "convert_to_task": True,
        },
    )
    assert duplicate.status_code == 409

    with TestingSessionLocal() as db:
        task = db.get(ClaimTask, UUID(decision["converted_task_id"]))
        assert task is not None
        assert task.source == TaskSource.RULE
        assert task.due_date == date(2027, 1, 10)
        rows = list(db.scalars(select(RecoveryTimebarDecision).where(
            RecoveryTimebarDecision.evaluation_id == UUID(timebar["id"])
        )))
        assert len(rows) == 1
        assert rows[0].snapshot_id == UUID(first["id"])

    _add_fact(claim_id, "recovery.notice_requirement", "Reviewed written notice requirement")
    second = _build(claim_id)
    assert second["snapshot_version"] == 2
    assert second["id"] != first["id"]

    stale = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/evaluations/{timebar['id']}/decision",
        json={
            "action": "dismiss",
            "evaluation_hash": timebar["evaluation_hash"],
            "note": "Attempted review of a superseded immutable evaluation.",
            "convert_to_task": False,
        },
    )
    assert stale.status_code == 409

    with TestingSessionLocal() as db:
        snapshots = list(db.scalars(select(RecoveryTimebarSnapshot).where(
            RecoveryTimebarSnapshot.claim_id == UUID(claim_id)
        ).order_by(RecoveryTimebarSnapshot.snapshot_version.asc())))
        assert [row.snapshot_version for row in snapshots] == [1, 2]
