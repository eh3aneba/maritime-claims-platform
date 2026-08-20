from datetime import UTC, datetime, timedelta

from tests.db_harness import client, reset_database
from tests.test_claims_api import create_orion_claim, login


def setup_function() -> None:
    reset_database()


CONTROLS = ["tls", "secret_references", "backup_restore", "migrations", "malware_scan",
            "least_privilege", "retention", "incident_contacts"]


def _create_ready_rehearsal(key: str = "rehearsal-one") -> dict:
    create_orion_claim()
    readiness = client.post("/api/v1/pilot-operations/readiness", json={
        "environment": "pilot", "review_key": f"ready-{key}",
        "controls": {control: True for control in CONTROLS},
    })
    assert readiness.status_code == 201, readiness.text
    attested = client.post(f"/api/v1/pilot-operations/readiness/{readiness.json()['id']}/attest", json={
        "confirm_ready": True, "note": "All eight readiness controls checked against the pilot runbook.",
    })
    assert attested.status_code == 200, attested.text
    rehearsal = client.post("/api/v1/pilot-operations/rehearsals", json={
        "readiness_review_id": readiness.json()["id"], "rehearsal_key": key,
        "name": "MT ORION design-partner rehearsal",
        "objectives": ["Validate the bounded pilot runbook", "Exercise human escalation paths"],
        "participant_roles": ["Claims Manager", "Claims Handler", "Pilot Operations"],
        "scheduled_for": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    })
    assert rehearsal.status_code == 201, rehearsal.text
    return rehearsal.json()


def _record_all(rehearsal_id: str, failed_control: str | None = None) -> dict:
    response = None
    for control in CONTROLS:
        response = client.put(f"/api/v1/pilot-operations/rehearsals/{rehearsal_id}/evidence", json={
            "control_key": control, "evidence_reference": f"artifact://rehearsal/{control}-001",
            "evidence_summary": f"Human-reviewed rehearsal evidence for the {control} control.",
            "result": "fail" if control == failed_control else "pass",
        })
        assert response.status_code == 200, response.text
    return response.json()


def test_rehearsal_requires_complete_evidence_and_freezes_go_snapshot() -> None:
    rehearsal = _create_ready_rehearsal()
    started = client.post(f"/api/v1/pilot-operations/rehearsals/{rehearsal['id']}/start")
    assert started.status_code == 200 and started.json()["status"] == "in_progress"
    recorded = _record_all(rehearsal["id"])
    assert len(recorded["evidence"]) == 8
    completed = client.post(f"/api/v1/pilot-operations/rehearsals/{rehearsal['id']}/complete", json={
        "outcome": "go", "confirm_decision": True,
        "note": "All eight controls passed and no unresolved rehearsal finding remains.",
    })
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed" and completed.json()["outcome"] == "go"
    assert len(completed.json()["decision_hash"]) == 64
    immutable = client.put(f"/api/v1/pilot-operations/rehearsals/{rehearsal['id']}/evidence", json={
        "control_key": "tls", "evidence_reference": "artifact://rehearsal/tls-002",
        "evidence_summary": "Attempt to alter evidence after the rehearsal decision.", "result": "pass",
    })
    assert immutable.status_code == 409


def test_failed_control_and_open_finding_block_go_but_allow_no_go() -> None:
    rehearsal = _create_ready_rehearsal("rehearsal-two")
    recorded = _record_all(rehearsal["id"], failed_control="backup_restore")
    backup = next(item for item in recorded["evidence"] if item["control_key"] == "backup_restore")
    finding = client.post(f"/api/v1/pilot-operations/rehearsals/{rehearsal['id']}/findings", json={
        "evidence_id": backup["id"], "severity": "high", "title": "Restore objective not met",
        "description": "The recovery exercise exceeded the approved recovery-time objective.",
        "owner_label": "Pilot Operations Lead", "due_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
    })
    assert finding.status_code == 201 and finding.json()["findings"][0]["status"] == "open"
    blocked = client.post(f"/api/v1/pilot-operations/rehearsals/{rehearsal['id']}/complete", json={
        "outcome": "go", "confirm_decision": True,
        "note": "This Go decision must be blocked by the failed control and open finding.",
    })
    assert blocked.status_code == 409
    no_go = client.post(f"/api/v1/pilot-operations/rehearsals/{rehearsal['id']}/complete", json={
        "outcome": "no_go", "confirm_decision": True,
        "note": "Pilot remains blocked pending recovery remediation and a fresh rehearsal.",
    })
    assert no_go.status_code == 200 and no_go.json()["outcome"] == "no_go"


def test_rehearsal_completion_is_manager_only_and_tenant_scoped() -> None:
    rehearsal = _create_ready_rehearsal("rehearsal-three")
    _record_all(rehearsal["id"])
    client.cookies.clear(); login("alpha", "alpha-handler@example.com")
    denied = client.post(f"/api/v1/pilot-operations/rehearsals/{rehearsal['id']}/complete", json={
        "outcome": "go", "confirm_decision": True, "note": "Handler cannot make the final Go decision.",
    })
    assert denied.status_code == 403
    client.cookies.clear(); login("beta", "beta-handler@example.com")
    dashboard = client.get("/api/v1/pilot-operations")
    assert dashboard.status_code == 200 and dashboard.json()["rehearsals"] == []
    cross_tenant = client.put(f"/api/v1/pilot-operations/rehearsals/{rehearsal['id']}/evidence", json={
        "control_key": "tls", "evidence_reference": "artifact://rehearsal/cross-tenant",
        "evidence_summary": "Cross-tenant rehearsal evidence must not be accessible.", "result": "pass",
    })
    assert cross_tenant.status_code == 404
