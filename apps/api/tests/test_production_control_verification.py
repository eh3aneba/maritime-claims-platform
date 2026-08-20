from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.core.security import hash_password
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import TEST_PASSWORD, login
from tests.test_private_pilot_production_baseline import (
    ARCHITECTURE_CONTROLS, _case_payload, _execution, _go_rehearsal,
)


FOUNDATIONAL_CONTROLS = [
    "identity_access", "evidence_storage", "observability", "backup_dr", "deployment_iac",
]


def setup_function() -> None:
    reset_database()


def _attested_baseline() -> dict:
    rehearsal, claim_id = _go_rehearsal("control-verification-rehearsal")
    execution = _execution(rehearsal["id"], key="control-verification-pilot")
    started = client.post(f"/api/v1/pilot-operations/pilot-executions/{execution['id']}/start")
    assert started.status_code == 200, started.text
    case_run = client.put(
        f"/api/v1/pilot-operations/pilot-executions/{execution['id']}/case-runs",
        json=_case_payload(claim_id),
    )
    assert case_run.status_code == 200, case_run.text
    completed = client.post(
        f"/api/v1/pilot-operations/pilot-executions/{execution['id']}/complete",
        json={"outcome": "proceed", "confirm_outcome": True,
              "note": "Bounded pilot case completed with no unresolved blocking product gap."},
    )
    assert completed.status_code == 200, completed.text
    baseline = client.post("/api/v1/pilot-operations/architecture-baselines", json={
        "pilot_execution_id": execution["id"], "baseline_key": "verification-architecture",
        "deployment_model": "single_tenant_managed", "data_residency_region": "EU approved region",
    })
    assert baseline.status_code == 201, baseline.text
    current = baseline.json()
    for control in ARCHITECTURE_CONTROLS:
        response = client.put(
            f"/api/v1/pilot-operations/architecture-baselines/{baseline.json()['id']}/controls",
            json={
                "control_key": control, "current_state": "partial",
                "target_architecture": f"Accountable production target for {control} with verification boundaries.",
                "risk_note": f"Residual implementation and evidence risk remains for {control}.",
                "owner_label": "Production Architecture Owner",
                "target_date": (date.today() + timedelta(days=90)).isoformat(),
                "evidence_reference": f"artifact://architecture/{control}-target",
            },
        )
        assert response.status_code == 200, response.text
        current = response.json()
    assert current["status"] == "review_ready"
    attested = client.post(
        f"/api/v1/pilot-operations/architecture-baselines/{baseline.json()['id']}/attest",
        json={"confirm_reviewed": True,
              "note": "All architecture domains reviewed while every implementation gap remains explicit."},
    )
    assert attested.status_code == 200, attested.text
    return attested.json()


def _create_gate(baseline_id: str) -> dict:
    response = client.post("/api/v1/pilot-operations/control-verification-gates", json={
        "architecture_baseline_id": baseline_id, "gate_key": "foundation-verification-one",
    })
    assert response.status_code == 201, response.text
    return response.json()


def _evidence_payload(control: str, version: int = 1) -> dict:
    return {
        "control_key": control,
        "implementation_summary": f"Implemented the bounded production design for {control} and recorded version {version} evidence.",
        "verification_method": f"An independent reviewer reproduces the {control} checks from the referenced runbook.",
        "rollback_plan": f"Restore the last approved {control} configuration and verify service health before reopening traffic.",
        "owner_label": "Production Control Owner",
        "implementation_completed_at": datetime.now(UTC).isoformat(),
        "evidence_reference": f"artifact://production/{control}-implementation-v{version}",
    }


def test_control_gate_requires_independent_review_preserves_rejections_and_freezes() -> None:
    baseline = _attested_baseline()
    gate = _create_gate(baseline["id"])
    first = client.post(
        f"/api/v1/pilot-operations/control-verification-gates/{gate['id']}/evidence",
        json=_evidence_payload("identity_access"),
    )
    assert first.status_code == 201, first.text
    identity_v1 = first.json()["evidence"][0]
    early = client.post(
        f"/api/v1/pilot-operations/control-verification-gates/{gate['id']}/complete",
        json={"confirm_verified": True, "note": "Incomplete evidence must not complete the gate."},
    )
    assert early.status_code == 409
    self_review = client.post(
        f"/api/v1/pilot-operations/control-verification-gates/{gate['id']}/evidence/{identity_v1['id']}/review",
        json={"action": "verify", "review_reference": "artifact://review/identity-self-review",
              "note": "The evidence submitter must not verify their own control evidence."},
    )
    assert self_review.status_code == 409

    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    rejected = client.post(
        f"/api/v1/pilot-operations/control-verification-gates/{gate['id']}/evidence/{identity_v1['id']}/review",
        json={"action": "reject", "note": "Independent reproduction did not include the privileged-access rollback check."},
    )
    assert rejected.status_code == 200 and rejected.json()["evidence"][0]["status"] == "rejected"

    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    resubmitted = client.post(
        f"/api/v1/pilot-operations/control-verification-gates/{gate['id']}/evidence",
        json=_evidence_payload("identity_access", version=2),
    )
    assert resubmitted.status_code == 201, resubmitted.text
    identity_versions = [item["submission_version"] for item in resubmitted.json()["evidence"]
                         if item["control_key"] == "identity_access"]
    assert identity_versions == [1, 2]
    current = resubmitted.json()
    for control in FOUNDATIONAL_CONTROLS[1:]:
        response = client.post(
            f"/api/v1/pilot-operations/control-verification-gates/{gate['id']}/evidence",
            json=_evidence_payload(control),
        )
        assert response.status_code == 201, response.text
        current = response.json()

    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    latest = {}
    for item in current["evidence"]:
        latest[item["control_key"]] = item
    for control in FOUNDATIONAL_CONTROLS:
        response = client.post(
            f"/api/v1/pilot-operations/control-verification-gates/{gate['id']}/evidence/{latest[control]['id']}/review",
            json={"action": "verify",
                  "review_reference": f"artifact://review/{control}-independent-check",
                  "note": f"Independent reviewer reproduced the bounded {control} verification method."},
        )
        assert response.status_code == 200, response.text
        current = response.json()
    assert current["status"] == "review_ready"
    assert current["summary"]["all_independently_verified"] is True

    completed = client.post(
        f"/api/v1/pilot-operations/control-verification-gates/{gate['id']}/complete",
        json={"confirm_verified": True,
              "note": "Five foundational controls independently verified; this is not a go-live authorization."},
    )
    assert completed.status_code == 200, completed.text
    result = completed.json()
    assert result["status"] == "completed" and len(result["outcome_hash"]) == 64
    assert result["summary"]["production_certification"] is False
    assert result["summary"]["go_live_authorization"] is False
    immutable = client.post(
        f"/api/v1/pilot-operations/control-verification-gates/{gate['id']}/evidence",
        json=_evidence_payload("backup_dr", version=2),
    )
    assert immutable.status_code == 409


def test_control_gate_is_manager_only_tenant_scoped_and_rejects_unbounded_references() -> None:
    baseline = _attested_baseline()
    client.cookies.clear(); login("alpha", "alpha-handler@example.com")
    denied = client.post("/api/v1/pilot-operations/control-verification-gates", json={
        "architecture_baseline_id": baseline["id"], "gate_key": "handler-created-gate",
    })
    assert denied.status_code == 403
    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    gate = _create_gate(baseline["id"])
    invalid = _evidence_payload("observability")
    invalid["evidence_reference"] = "https://example.com/raw-production-secret"
    blocked = client.post(
        f"/api/v1/pilot-operations/control-verification-gates/{gate['id']}/evidence", json=invalid)
    assert blocked.status_code == 422
    future = _evidence_payload("observability")
    future["implementation_completed_at"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    blocked_future = client.post(
        f"/api/v1/pilot-operations/control-verification-gates/{gate['id']}/evidence", json=future)
    assert blocked_future.status_code == 422

    with TestingSessionLocal() as db:
        beta = db.scalar(select(Organization).where(Organization.slug == "beta"))
        assert beta is not None
        beta_manager = User(
            organization_id=beta.id, email="beta-manager@example.com", full_name="Beta Manager",
            password_hash=hash_password(TEST_PASSWORD), role=UserRole.CLAIMS_MANAGER, is_active=True,
        )
        db.add(beta_manager); db.commit()
    client.cookies.clear(); login("beta", "beta-manager@example.com")
    dashboard = client.get("/api/v1/pilot-operations")
    assert dashboard.status_code == 200 and dashboard.json()["control_verification_gates"] == []
    cross_tenant = client.post(
        f"/api/v1/pilot-operations/control-verification-gates/{gate['id']}/evidence",
        json=_evidence_payload("observability"),
    )
    assert cross_tenant.status_code == 404
