from sqlalchemy import func, select

from app.modules.audit.models import AuditLog
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim


def setup_function() -> None:
    reset_database()


def _generate(claim_id: str) -> dict:
    response = client.post(
        f"/api/v1/claims/{claim_id}/initial-assessment/generate",
        json={
            "allow_if_not_ready": True,
            "override_reason": "Preliminary human review while critical evidence remains outstanding.",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _approve(claim_id: str, assessment: dict) -> dict:
    fingerprint = assessment["source_fingerprint"]
    assert fingerprint
    for section in assessment["sections"]:
        response = client.post(
            f"/api/v1/claims/{claim_id}/initial-assessment/sections/{section['id']}/review",
            json={
                "action": "approve",
                "text": None,
                "expected_source_fingerprint": fingerprint,
            },
        )
        assert response.status_code == 200, response.text
    response = client.post(
        f"/api/v1/claims/{claim_id}/initial-assessment/{assessment['id']}/approve",
        json={
            "note": "Manager-approved preliminary claim review snapshot.",
            "expected_source_fingerprint": fingerprint,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_history_keeps_approved_version_and_specific_version_semantics_explicit() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]

    approved_v1 = _approve(claim_id, _generate(claim_id))
    approved_hash = approved_v1["approved_content_hash"]
    assert approved_hash
    assert approved_v1["is_latest"] is True
    assert approved_v1["latest_version"] == 1

    changed = client.patch(
        f"/api/v1/claims/{claim_id}",
        json={"incident_description": "Updated human claim description after further reviewed evidence."},
    )
    assert changed.status_code == 200, changed.text

    v2 = _generate(claim_id)
    assert v2["version"] == 2
    assert v2["is_latest"] is True
    assert v2["source_state"] == "current"

    history = client.get(f"/api/v1/claims/{claim_id}/initial-assessment/history")
    assert history.status_code == 200, history.text
    body = history.json()
    assert body["latest_version"] == 2
    assert [row["version"] for row in body["items"]] == [2, 1]
    assert body["items"][0]["is_latest"] is True
    assert body["items"][0]["source_state"] == "current"
    assert body["items"][1]["is_latest"] is False
    assert body["items"][1]["source_state"] == "stale"
    assert body["items"][1]["status"] == "approved"
    assert body["items"][1]["approved_content_hash"] == approved_hash

    historical = client.get(
        f"/api/v1/claims/{claim_id}/initial-assessment/versions/{approved_v1['id']}"
    )
    assert historical.status_code == 200, historical.text
    historical_body = historical.json()
    assert historical_body["version"] == 1
    assert historical_body["is_latest"] is False
    assert historical_body["latest_version"] == 2
    assert historical_body["source_state"] == "stale"
    assert historical_body["approved_content_hash"] == approved_hash

    latest = client.get(f"/api/v1/claims/{claim_id}/initial-assessment")
    assert latest.status_code == 200, latest.text
    assert latest.json()["id"] == v2["id"]
    assert latest.json()["is_latest"] is True


def test_current_domain_status_reuses_human_recovery_state_without_becoming_authority() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    assessment = _generate(claim_id)

    counterparty_response = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/counterparties",
        json={
            "name": "TurboMaker GmbH",
            "role": "Potential workshop / overhaul contractor",
            "allegation_basis": "Human investigation hypothesis only; no platform finding of fault or liability.",
            "source_reference": "Reviewed overhaul correspondence and workshop contract",
        },
    )
    assert counterparty_response.status_code == 201, counterparty_response.text
    counterparty = counterparty_response.json()

    decision_response = client.post(
        f"/api/v1/claims/{claim_id}/recovery-timebar/decisions",
        json={
            "counterparty_id": counterparty["id"],
            "disposition": "monitor",
            "rationale": "Human handler keeps the recovery path under review while evidence and legal advice develop.",
            "basis_reference": "Handler recovery review note R-13.8B",
            "next_review_date": "2026-09-30",
        },
    )
    assert decision_response.status_code == 201, decision_response.text

    response = client.get(f"/api/v1/claims/{claim_id}/initial-assessment/versions/{assessment['id']}")
    assert response.status_code == 200, response.text
    body = response.json()
    status = body["current_domain_status"]
    assert status["authority"] == "read_only_cross_domain_projection"
    assert "does not transfer decision authority" in status["disclaimer"]
    assert status["technical"]["authority_module"] == "technical"
    assert status["financial"]["authority_module"] == "financial"
    assert status["reserve"]["authority_module"] == "reserve"
    assert status["recovery"]["authority_module"] == "recovery_timebar"
    assert status["recovery"]["state"] == "open_recovery_paths"
    assert status["recovery"]["summary"]["human_decision_count"] == 1
    assert status["recovery"]["projection_authority"] == "downstream_human_record_projection_only"


def test_assessment_get_with_domain_projection_is_read_only() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _generate(claim_id)

    with TestingSessionLocal() as db:
        before = db.scalar(select(func.count(AuditLog.id)))

    response = client.get(f"/api/v1/claims/{claim_id}/initial-assessment")
    assert response.status_code == 200, response.text

    with TestingSessionLocal() as db:
        after = db.scalar(select(func.count(AuditLog.id)))
    assert after == before


def test_history_is_empty_before_first_assessment() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    history = client.get(f"/api/v1/claims/{claim_id}/initial-assessment/history")
    assert history.status_code == 200, history.text
    assert history.json()["latest_version"] is None
    assert history.json()["items"] == []
