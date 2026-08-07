from datetime import date
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.documents import service as document_service
from app.modules.rules.models import ClaimDocumentRequirement, ClaimIssue, RuleEvaluationRun
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim, login


def setup_function() -> None:
    reset_database()


def _set_status(claim_id: str, status: ClaimStatus) -> None:
    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(claim_id))
        assert claim is not None
        claim.status = status
        db.commit()


def _add_fact(claim_id: str, path: str, value) -> None:
    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(claim_id))
        assert claim is not None
        db.add(
            ClaimFact(
                organization_id=claim.organization_id,
                claim_id=claim.id,
                field_path=path,
                value=value,
                source_extraction_id=uuid4(),
                source_document_id=uuid4(),
                source_segment_id=None,
                approved_by_id=None,
                version=1,
            )
        )
        db.commit()


def _evaluate(claim_id: str):
    response = client.post(f"/api/v1/claims/{claim_id}/rules/evaluate")
    assert response.status_code == 200, response.text
    return response.json()["summary"]


def _configure_storage(tmp_path: Path) -> None:
    document_service.settings.local_storage_path = str(tmp_path / "documents")
    document_service.settings.max_upload_mb = 1


def _upload_pdf(claim_id: str, document_type: str, marker: str):
    return client.post(
        f"/api/v1/claims/{claim_id}/documents",
        files={"file": (f"{marker}.pdf", f"%PDF-1.4\n{marker}\n%%EOF".encode(), "application/pdf")},
        data={"document_type": document_type, "confidentiality_level": "confidential"},
    )


def test_triage_activates_only_stage_relevant_base_requirements() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.TRIAGE)
    summary = _evaluate(claim_id)

    by_type = {item["document_type"]: item for item in summary["requirements"]}
    assert set(by_type) == {"chief_engineer_report", "engine_log", "policy"}
    assert all(item["priority"] == "critical" for item in by_type.values())
    assert summary["readiness"]["state"] == "not_ready"
    assert summary["readiness"]["critical_missing_count"] == 3
    assert "Workshop Report" not in summary["readiness"]["blocking_items"]


def test_investigation_turbocharger_adds_equipment_specific_requirements() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    summary = _evaluate(claim_id)
    types = {item["document_type"] for item in summary["requirements"]}

    assert {"workshop_report", "running_hours_record", "overhaul_report", "pms_record", "maker_recommendation"}.issubset(types)
    assert summary["readiness"]["critical_missing_count"] == 7
    assert summary["readiness"]["important_missing_count"] == 1


def test_upload_and_soft_delete_refresh_missing_document_status(tmp_path: Path) -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.TRIAGE)
    _configure_storage(tmp_path)
    _evaluate(claim_id)

    uploaded = _upload_pdf(claim_id, "chief_engineer_report", "ce_report")
    assert uploaded.status_code == 201, uploaded.text
    summary = client.get(f"/api/v1/claims/{claim_id}/rules").json()
    ce = next(item for item in summary["requirements"] if item["document_type"] == "chief_engineer_report")
    assert ce["status"] == "received"
    assert ce["matched_document_id"] == uploaded.json()["id"]

    deleted = client.delete(f"/api/v1/claims/{claim_id}/documents/{uploaded.json()['id']}")
    assert deleted.status_code == 204
    summary = client.get(f"/api/v1/claims/{claim_id}/rules").json()
    ce = next(item for item in summary["requirements"] if item["document_type"] == "chief_engineer_report")
    assert ce["status"] == "missing"
    assert ce["matched_document_id"] is None


def test_towage_fact_activates_conditional_document_requirements() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    _add_fact(claim_id, "operational_impact.towage", True)
    summary = _evaluate(claim_id)
    types = {item["document_type"] for item in summary["requirements"]}
    assert "towage_contract" in types
    assert "towage_report" in types
    assert "towage_invoice" not in types  # Financial-stage requirement is not active yet.


def test_overdue_hours_create_explainable_issue_without_causation_finding() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    _add_fact(claim_id, "maintenance.running_hours_since_overhaul", 14800)
    _add_fact(claim_id, "maintenance.recommended_overhaul_interval", 12000)
    summary = _evaluate(claim_id)

    issue = next(item for item in summary["issues"] if item["rule_id"] == "TECH-001")
    assert issue["severity"] == "high"
    assert issue["evidence"]["variance_hours"] == "2800"
    assert "investigation flag" in issue["explanation"].lower()
    assert "caused" not in issue["description"].lower()


def test_recent_overhaul_creates_review_issue() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    _add_fact(claim_id, "maintenance.last_overhaul_date", "2026-06-15")
    summary = _evaluate(claim_id)
    issue = next(item for item in summary["issues"] if item["rule_id"] == "TECH-002")
    assert issue["evidence"]["days_between"] == 25
    assert "workmanship" in issue["explanation"].lower()


def test_rule_evaluation_is_idempotent_for_requirements_and_issues() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    _add_fact(claim_id, "maintenance.running_hours_since_overhaul", 14800)
    _add_fact(claim_id, "maintenance.recommended_overhaul_interval", 12000)
    _evaluate(claim_id)
    _evaluate(claim_id)

    with TestingSessionLocal() as db:
        requirements = list(db.scalars(select(ClaimDocumentRequirement).where(ClaimDocumentRequirement.claim_id == UUID(claim_id))))
        issues = list(db.scalars(select(ClaimIssue).where(ClaimIssue.claim_id == UUID(claim_id))))
        runs = list(db.scalars(select(RuleEvaluationRun).where(RuleEvaluationRun.claim_id == UUID(claim_id))))
        assert len(requirements) == 8
        assert len([issue for issue in issues if issue.rule_id == "TECH-001"]) == 1
        assert len(runs) == 2


def test_status_change_automatically_refreshes_stage_requirements() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    # create_orion_claim leaves the admin authenticated.
    triage = client.post(f"/api/v1/claims/{claim_id}/status", json={"status": "triage", "reason": "Triage started"})
    assert triage.status_code == 200
    summary = client.get(f"/api/v1/claims/{claim_id}/rules").json()
    assert {item["document_type"] for item in summary["requirements"]} == {"chief_engineer_report", "engine_log", "policy"}

    investigation = client.post(f"/api/v1/claims/{claim_id}/status", json={"status": "investigation", "reason": "Initial review completed"})
    assert investigation.status_code == 200
    summary = client.get(f"/api/v1/claims/{claim_id}/rules").json()
    assert "workshop_report" in {item["document_type"] for item in summary["requirements"]}


def test_rules_endpoint_is_tenant_scoped() -> None:
    result = create_orion_claim()
    data = result["seed"]
    with TestingSessionLocal() as db:
        beta_claim = Claim(
            organization_id=data["beta"].id,
            vessel_id=data["beta_vessel"].id,
            claim_reference="MCRI-HM-2026-0999",
            incident_date=date(2026, 7, 10),
            notification_date=date(2026, 7, 11),
            incident_description="Beta turbocharger claim",
            currency="USD",
        )
        db.add(beta_claim)
        db.commit()
        db.refresh(beta_claim)
        beta_claim_id = beta_claim.id

    client.cookies.clear()
    login("alpha", "alpha-admin@example.com")
    assert client.get(f"/api/v1/claims/{beta_claim_id}/rules").status_code == 404
    assert client.post(f"/api/v1/claims/{beta_claim_id}/rules/evaluate").status_code == 404


def test_rule_run_is_audited() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.TRIAGE)
    _evaluate(claim_id)
    with TestingSessionLocal() as db:
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "EVALUATE_CLAIM_RULES", AuditLog.entity_id == UUID(claim_id)))
        assert audit is not None
