from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.core.security import hash_password
from app.modules.organizations.models import Organization
from app.modules.pilot_operations.models import ProductionControlVerificationGate
from app.modules.users.models import User, UserRole
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import TEST_PASSWORD, login
from tests.test_production_control_verification import (
    PRODUCTION_CONTROLS, _attested_baseline, _create_gate, _evidence_payload,
)


CHECKS = [
    "release_artifact", "migration_plan", "backup_restore", "observability_alerting",
    "incident_response", "rollback_rehearsal", "support_coverage",
]


def setup_function() -> None:
    reset_database()


def _completed_gate() -> dict:
    baseline = _attested_baseline()
    gate = _create_gate(baseline["id"])
    current = gate
    for control in PRODUCTION_CONTROLS:
        response = client.post(
            f"/api/v1/pilot-operations/control-verification-gates/{gate['id']}/evidence",
            json=_evidence_payload(control),
        )
        assert response.status_code == 201, response.text
        current = response.json()
    latest = {item["control_key"]: item for item in current["evidence"]}
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    for control in PRODUCTION_CONTROLS:
        response = client.post(
            f"/api/v1/pilot-operations/control-verification-gates/{gate['id']}"
            f"/evidence/{latest[control]['id']}/review",
            json={"action": "verify",
                  "review_reference": f"artifact://review/{control}-operational-prerequisite",
                  "note": f"Independent reviewer reproduced the {control} prerequisite check."},
        )
        assert response.status_code == 200, response.text
    completed = client.post(
        f"/api/v1/pilot-operations/control-verification-gates/{gate['id']}/complete",
        json={"confirm_verified": True,
              "note": "All nine controls independently verified before operational acceptance."},
    )
    assert completed.status_code == 200, completed.text
    return completed.json()


def _acceptance_payload(gate_id: str, key: str = "operational-acceptance-one",
                        failed_check: str | None = None) -> dict:
    start = datetime.now(UTC) + timedelta(days=1)
    return {
        "control_verification_gate_id": gate_id,
        "acceptance_key": key,
        "release_identifier": "release-2026.08.20",
        "target_environment": "production",
        "change_window_start": start.isoformat(),
        "change_window_end": (start + timedelta(hours=2)).isoformat(),
        "release_owner_label": "Release Owner",
        "rollback_owner_label": "Rollback Owner",
        "incident_commander_label": "Incident Commander",
        "support_owner_label": "Support Owner",
        "checks": [{
            "check_key": check,
            "result": "fail" if check == failed_check else "pass",
            "owner_label": "Operational Control Owner",
            "evidence_reference": f"artifact://go-live/{check}",
            "note": f"Human-reviewed bounded operational evidence for {check}.",
        } for check in CHECKS],
    }


def _add_risk_manager() -> None:
    with TestingSessionLocal() as db:
        alpha = db.scalar(select(Organization).where(Organization.slug == "alpha"))
        assert alpha is not None
        db.add(User(
            organization_id=alpha.id, email="alpha-risk@example.com",
            full_name="Alpha Risk Manager", password_hash=hash_password(TEST_PASSWORD),
            role=UserRole.CLAIMS_MANAGER, is_active=True,
        ))
        db.commit()


def test_operational_acceptance_requires_two_people_and_freezes_expiring_authorization() -> None:
    gate = _completed_gate()
    _add_risk_manager()
    created = client.post("/api/v1/pilot-operations/operational-acceptances",
                          json=_acceptance_payload(gate["id"]))
    assert created.status_code == 201, created.text
    acceptance = created.json()
    assert acceptance["status"] == "pending_approvals"
    assert acceptance["summary"]["pass_count"] == 7
    assert acceptance["summary"]["external_ai_authorization"] is False

    self_approval = client.post(
        f"/api/v1/pilot-operations/operational-acceptances/{acceptance['id']}/approvals",
        json={"approval_role": "operations", "action": "approve",
              "evidence_reference": "artifact://go-live/self-review",
              "note": "The requester must not approve their own operational request."},
    )
    assert self_approval.status_code == 409

    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    operations = client.post(
        f"/api/v1/pilot-operations/operational-acceptances/{acceptance['id']}/approvals",
        json={"approval_role": "operations", "action": "approve",
              "evidence_reference": "artifact://go-live/operations-review",
              "note": "Operations independently confirmed all seven bounded checks."},
    )
    assert operations.status_code == 200, operations.text
    same_person = client.post(
        f"/api/v1/pilot-operations/operational-acceptances/{acceptance['id']}/approvals",
        json={"approval_role": "risk", "action": "approve",
              "evidence_reference": "artifact://go-live/risk-review",
              "note": "A different person must issue the independent risk approval."},
    )
    assert same_person.status_code == 409

    client.cookies.clear(); login("alpha", "alpha-risk@example.com")
    risk = client.post(
        f"/api/v1/pilot-operations/operational-acceptances/{acceptance['id']}/approvals",
        json={"approval_role": "risk", "action": "approve",
              "evidence_reference": "artifact://go-live/risk-review",
              "note": "Risk independently confirmed all seven bounded checks."},
    )
    assert risk.status_code == 200, risk.text
    assert risk.json()["status"] == "decision_ready"
    assert risk.json()["summary"]["independent_approvals_complete"] is True

    handler_decision = client.post(
        f"/api/v1/pilot-operations/operational-acceptances/{acceptance['id']}/decision",
        json={"outcome": "authorize", "confirm_decision": True,
              "note": "Only an Administrator may issue the final bounded authorization."},
    )
    assert handler_decision.status_code == 403

    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    authorized = client.post(
        f"/api/v1/pilot-operations/operational-acceptances/{acceptance['id']}/decision",
        json={"outcome": "authorize", "confirm_decision": True,
              "note": "Administrator authorizes only this bounded release window."},
    )
    assert authorized.status_code == 200, authorized.text
    result = authorized.json()
    assert result["status"] == "authorized" and len(result["decision_hash"]) == 64
    assert result["authorization_expires_at"] == result["change_window_end"]
    assert result["summary"]["go_live_authorization_recorded"] is True
    assert result["summary"]["authorization_active"] is False
    assert result["summary"]["deployment_performed"] is False
    assert result["summary"]["traffic_enabled"] is False
    assert result["summary"]["production_certification"] is False
    assert result["summary"]["external_ai_authorization"] is False
    immutable = client.post(
        f"/api/v1/pilot-operations/operational-acceptances/{acceptance['id']}/approvals",
        json={"approval_role": "risk", "action": "reject",
              "note": "Terminal operational decisions remain immutable."},
    )
    assert immutable.status_code == 409

    with TestingSessionLocal() as db:
        beta = db.scalar(select(Organization).where(Organization.slug == "beta"))
        assert beta is not None
        db.add(User(
            organization_id=beta.id, email="beta-acceptance@example.com",
            full_name="Beta Acceptance Manager", password_hash=hash_password(TEST_PASSWORD),
            role=UserRole.CLAIMS_MANAGER, is_active=True,
        ))
        db.commit()
    client.cookies.clear(); login("beta", "beta-acceptance@example.com")
    dashboard = client.get("/api/v1/pilot-operations")
    assert dashboard.status_code == 200
    assert dashboard.json()["operational_acceptances"] == []
    cross_tenant = client.post(
        f"/api/v1/pilot-operations/operational-acceptances/{acceptance['id']}/approvals",
        json={"approval_role": "operations", "action": "reject",
              "note": "A different tenant cannot access this acceptance attempt."},
    )
    assert cross_tenant.status_code == 404


def test_failed_check_blocks_approval_and_rejection_allows_new_attempt() -> None:
    gate = _completed_gate()
    failed = client.post("/api/v1/pilot-operations/operational-acceptances",
                         json=_acceptance_payload(gate["id"], failed_check="backup_restore"))
    assert failed.status_code == 201, failed.text
    failed_id = failed.json()["id"]
    client.cookies.clear(); login("alpha", "alpha-admin@example.com")
    blocked = client.post(
        f"/api/v1/pilot-operations/operational-acceptances/{failed_id}/approvals",
        json={"approval_role": "operations", "action": "approve",
              "evidence_reference": "artifact://go-live/operations-review",
              "note": "A failing restore check must block operational approval."},
    )
    assert blocked.status_code == 409
    rejected = client.post(
        f"/api/v1/pilot-operations/operational-acceptances/{failed_id}/approvals",
        json={"approval_role": "operations", "action": "reject",
              "note": "Restore evidence failed; reject and create a fresh attempt."},
    )
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"

    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    retry = client.post("/api/v1/pilot-operations/operational-acceptances",
                        json=_acceptance_payload(gate["id"], key="operational-acceptance-two"))
    assert retry.status_code == 201, retry.text
    assert retry.json()["attempt_number"] == 2


def test_acceptance_rejects_legacy_gate_bad_window_unbounded_reference_and_handler() -> None:
    baseline = _attested_baseline()
    with TestingSessionLocal() as db:
        alpha = db.scalar(select(Organization).where(Organization.slug == "alpha"))
        admin = db.scalar(select(User).where(User.email == "alpha-admin@example.com"))
        assert alpha is not None and admin is not None
        legacy = ProductionControlVerificationGate(
            organization_id=alpha.id, architecture_baseline_id=UUID(baseline["id"]),
            created_by_id=admin.id, completed_by_id=admin.id,
            gate_key="legacy-completed-foundational-gate",
            verification_profile="foundational_v1", status="completed",
            outcome_note="Historical five-control completion only.",
            outcome_hash="0" * 64, completed_at=datetime.now(UTC),
        )
        db.add(legacy); db.commit(); legacy_id = str(legacy.id)

    client.cookies.clear(); login("alpha", "alpha-handler@example.com")
    denied = client.post("/api/v1/pilot-operations/operational-acceptances",
                         json=_acceptance_payload(legacy_id))
    assert denied.status_code == 403
    client.cookies.clear(); login("alpha", "alpha-manager@example.com")
    legacy_denied = client.post("/api/v1/pilot-operations/operational-acceptances",
                                json=_acceptance_payload(legacy_id))
    assert legacy_denied.status_code == 409



def test_acceptance_rejects_bad_window_and_unbounded_reference() -> None:
    gate = _completed_gate()
    invalid = _acceptance_payload(gate["id"], key="invalid-reference-attempt")
    invalid["checks"][0]["evidence_reference"] = "https://example.com/raw-runbook"
    invalid_reference = client.post("/api/v1/pilot-operations/operational-acceptances",
                                    json=invalid)
    assert invalid_reference.status_code == 422

    window = _acceptance_payload(gate["id"], key="invalid-window-attempt")
    window["change_window_start"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    window["change_window_end"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    invalid_window = client.post("/api/v1/pilot-operations/operational-acceptances", json=window)
    assert invalid_window.status_code == 422
