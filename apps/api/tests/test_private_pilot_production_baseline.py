from datetime import UTC, date, datetime, timedelta

from tests.db_harness import client, reset_database
from tests.test_claims_api import login
from tests.test_design_partner_rehearsal import _create_ready_rehearsal, _record_all


def setup_function() -> None:
    reset_database()


ARCHITECTURE_CONTROLS = [
    "identity_access", "application_security", "evidence_storage", "observability",
    "backup_dr", "data_governance", "deployment_iac", "interoperability", "ai_governance",
]


def _go_rehearsal(key: str = "pilot-execution-rehearsal") -> tuple[dict, str]:
    rehearsal = _create_ready_rehearsal(key)
    _record_all(rehearsal["id"])
    completed = client.post(f"/api/v1/pilot-operations/rehearsals/{rehearsal['id']}/complete", json={
        "outcome": "go", "confirm_decision": True,
        "note": "All rehearsal controls passed and private pilot execution may be planned.",
    })
    assert completed.status_code == 200, completed.text
    claim_id = client.get("/api/v1/claims").json()["items"][0]["id"]
    return completed.json(), claim_id


def _execution(rehearsal_id: str, *, key: str = "private-pilot-one",
               data_mode: str = "synthetic", authorization: str | None = None) -> dict:
    response = client.post("/api/v1/pilot-operations/pilot-executions", json={
        "rehearsal_id": rehearsal_id, "execution_key": key,
        "design_partner_label": "Bounded Design Partner A", "data_mode": data_mode,
        "data_authorization_reference": authorization,
        "objectives": ["Measure the end-to-end claims workflow", "Capture accountable product gaps"],
        "target_case_runs": 1,
    })
    assert response.status_code == 201, response.text
    return response.json()


def _case_payload(claim_id: str) -> dict:
    return {
        "claim_id": claim_id, "case_outcome": "completed",
        "evidence_reference": "artifact://pilot/case-run-001",
        "triage_minutes": 18, "evidence_review_minutes": 42,
        "assessment_minutes": 35, "adjustment_minutes": 51,
        "ai_candidates_reviewed": 12, "ai_accepted": 8, "ai_edited": 3,
        "ai_rejected": 1, "rule_findings_reviewed": 5, "rule_findings_helpful": 4,
        "open_conflicts": 1, "open_requirements": 2,
    }


def test_private_pilot_baseline_blocks_p0_then_freezes_proceed_outcome() -> None:
    rehearsal, claim_id = _go_rehearsal()
    execution = _execution(rehearsal["id"])
    started = client.post(f"/api/v1/pilot-operations/pilot-executions/{execution['id']}/start")
    assert started.status_code == 200 and started.json()["status"] == "in_progress"

    invalid = _case_payload(claim_id); invalid["ai_rejected"] = 2
    assert client.put(
        f"/api/v1/pilot-operations/pilot-executions/{execution['id']}/case-runs",
        json=invalid,
    ).status_code == 422
    recorded = client.put(
        f"/api/v1/pilot-operations/pilot-executions/{execution['id']}/case-runs",
        json=_case_payload(claim_id),
    )
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["aggregate_metrics"]["totals"]["ai_accepted"] == 8
    assert recorded.json()["aggregate_metrics"]["content_included"] is False

    gap = client.post(f"/api/v1/pilot-operations/pilot-executions/{execution['id']}/gaps", json={
        "case_run_id": recorded.json()["case_runs"][0]["id"], "priority": "p0",
        "category": "security", "title": "Session control requires remediation",
        "summary": "The pilot exposed a blocking session-control gap that must be remediated.",
        "owner_label": "Security Owner", "due_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
        "evidence_reference": "ticket://security/session-control-001",
    })
    assert gap.status_code == 201 and gap.json()["product_gaps"][0]["status"] == "open"
    blocked = client.post(f"/api/v1/pilot-operations/pilot-executions/{execution['id']}/complete", json={
        "outcome": "proceed", "confirm_outcome": True,
        "note": "Proceed must remain blocked while the P0 product gap is unresolved.",
    })
    assert blocked.status_code == 409
    gap_id = gap.json()["product_gaps"][0]["id"]
    resolved = client.post(
        f"/api/v1/pilot-operations/pilot-executions/{execution['id']}/gaps/{gap_id}/transition",
        json={"action": "resolve", "note": "Session control remediated and evidence verified."},
    )
    assert resolved.status_code == 200 and resolved.json()["product_gaps"][0]["status"] == "resolved"
    completed = client.post(f"/api/v1/pilot-operations/pilot-executions/{execution['id']}/complete", json={
        "outcome": "proceed", "confirm_outcome": True,
        "note": "Target case completed and every blocking product gap is resolved.",
    })
    assert completed.status_code == 200, completed.text
    assert completed.json()["outcome"] == "proceed" and len(completed.json()["outcome_hash"]) == 64
    immutable = client.put(
        f"/api/v1/pilot-operations/pilot-executions/{execution['id']}/case-runs",
        json=_case_payload(claim_id),
    )
    assert immutable.status_code == 409


def test_real_data_execution_requires_governance_and_is_tenant_scoped() -> None:
    rehearsal, claim_id = _go_rehearsal("real-data-rehearsal")
    blocked = client.post("/api/v1/pilot-operations/pilot-executions", json={
        "rehearsal_id": rehearsal["id"], "execution_key": "real-data-pilot",
        "design_partner_label": "Approved Partner", "data_mode": "approved_real",
        "data_authorization_reference": "artifact://governance/real-data-approval",
        "objectives": ["Validate an explicitly authorized real-data workflow"], "target_case_runs": 1,
    })
    assert blocked.status_code == 409
    client.put("/api/v1/pilot-operations/governance", json={
        "pilot_purpose": "Controlled validation of the H&M claims workflow using approved pilot data.",
        "legal_basis": "Documented contractual pilot authorization and data-processing terms.",
        "data_owner": "Alpha Claims Director",
        "retention_statement": "Pilot data follows the approved schedule and legal-hold process.",
        "residency_statement": "Data remains in the approved hosting region.",
        "exit_contact": "exit@alpha.example",
    })
    client.post("/api/v1/pilot-operations/governance/approve", json={
        "confirm_approved": True, "note": "Real-data purpose, basis, retention and residency reviewed.",
    })
    execution = _execution(rehearsal["id"], key="real-data-pilot", data_mode="approved_real",
                           authorization="artifact://governance/real-data-approval")
    assert client.post(
        f"/api/v1/pilot-operations/pilot-executions/{execution['id']}/start"
    ).status_code == 200
    client.put(f"/api/v1/pilot-operations/pilot-executions/{execution['id']}/case-runs",
               json=_case_payload(claim_id))
    client.cookies.clear(); login("alpha", "alpha-handler@example.com")
    denied = client.post(f"/api/v1/pilot-operations/pilot-executions/{execution['id']}/complete", json={
        "outcome": "pause", "confirm_outcome": True,
        "note": "A claims handler must not complete the organization-level pilot outcome.",
    })
    assert denied.status_code == 403
    client.cookies.clear(); login("beta", "beta-handler@example.com")
    dashboard = client.get("/api/v1/pilot-operations")
    assert dashboard.status_code == 200 and dashboard.json()["pilot_executions"] == []
    cross_tenant = client.put(
        f"/api/v1/pilot-operations/pilot-executions/{execution['id']}/case-runs",
        json=_case_payload(claim_id),
    )
    assert cross_tenant.status_code == 404


def test_architecture_baseline_documents_all_controls_and_preserves_gaps() -> None:
    rehearsal, claim_id = _go_rehearsal("architecture-rehearsal")
    execution = _execution(rehearsal["id"], key="architecture-pilot")
    assert client.post(
        f"/api/v1/pilot-operations/pilot-executions/{execution['id']}/start"
    ).status_code == 200
    client.put(f"/api/v1/pilot-operations/pilot-executions/{execution['id']}/case-runs",
               json=_case_payload(claim_id))
    completed = client.post(f"/api/v1/pilot-operations/pilot-executions/{execution['id']}/complete", json={
        "outcome": "proceed", "confirm_outcome": True,
        "note": "Representative pilot case completed with no blocking P0 product gaps.",
    }).json()
    baseline = client.post("/api/v1/pilot-operations/architecture-baselines", json={
        "pilot_execution_id": completed["id"], "baseline_key": "production-baseline-one",
        "deployment_model": "single_tenant_managed", "data_residency_region": "EU approved region",
    })
    assert baseline.status_code == 201 and baseline.json()["status"] == "draft"
    early = client.post(f"/api/v1/pilot-operations/architecture-baselines/{baseline.json()['id']}/attest", json={
        "confirm_reviewed": True, "note": "Incomplete architecture baseline must not be attested.",
    })
    assert early.status_code == 409
    current = baseline.json()
    for control in ARCHITECTURE_CONTROLS:
        current = client.put(
            f"/api/v1/pilot-operations/architecture-baselines/{baseline.json()['id']}/controls",
            json={
                "control_key": control,
                "current_state": "partial" if control == "evidence_storage" else "implemented",
                "target_architecture": f"Documented target architecture for {control} with accountable production controls.",
                "risk_note": f"Human-reviewed residual risk and implementation dependency for {control}.",
                "owner_label": "Production Architecture Owner",
                "target_date": date.today().replace(year=date.today().year + 1).isoformat(),
                "evidence_reference": f"artifact://architecture/{control}-baseline",
            },
        ).json()
    assert current["status"] == "review_ready" and len(current["controls"]) == 9
    attested = client.post(f"/api/v1/pilot-operations/architecture-baselines/{baseline.json()['id']}/attest", json={
        "confirm_reviewed": True,
        "note": "All nine architecture domains reviewed; the remaining storage gap stays visible.",
    })
    assert attested.status_code == 200, attested.text
    assert attested.json()["status"] == "attested_with_gaps"
    assert attested.json()["summary"]["state_counts"]["partial"] == 1
    assert attested.json()["summary"]["production_certification"] is False
    assert len(attested.json()["snapshot_hash"]) == 64
    immutable = client.put(
        f"/api/v1/pilot-operations/architecture-baselines/{baseline.json()['id']}/controls",
        json={
            "control_key": "evidence_storage", "current_state": "implemented",
            "target_architecture": "Attempt to rewrite an attested production architecture control.",
            "risk_note": "This mutation must be rejected after the architecture snapshot is attested.",
            "owner_label": "Architecture Owner", "target_date": date.today().isoformat(),
            "evidence_reference": "artifact://architecture/immutable-check",
        },
    )
    assert immutable.status_code == 409
