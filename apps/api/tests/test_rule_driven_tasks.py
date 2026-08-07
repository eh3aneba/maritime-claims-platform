from datetime import date
from pathlib import Path
from uuid import UUID

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.claims.models import ClaimStatus
from app.modules.documents import service as document_service
from app.modules.rules.models import ClaimDocumentRequirement, RequirementStatus
from app.modules.tasks.models import ClaimTask, DocumentRequestBatch, TaskStatus
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_claims_api import create_orion_claim, login


def setup_function() -> None:
    reset_database()


def _set_status(claim_id: str, status: ClaimStatus) -> None:
    with TestingSessionLocal() as db:
        claim = db.get(__import__('app.modules.claims.models', fromlist=['Claim']).Claim, UUID(claim_id))
        claim.status = status
        db.commit()


def _evaluate(claim_id: str) -> dict:
    response = client.post(f"/api/v1/claims/{claim_id}/rules/evaluate")
    assert response.status_code == 200, response.text
    return response.json()["summary"]


def _configure_storage(tmp_path: Path) -> None:
    document_service.settings.local_storage_path = str(tmp_path / "documents")
    document_service.settings.max_upload_mb = 1


def test_request_all_critical_creates_draft_and_tasks_then_human_marks_requested() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.TRIAGE)
    summary = _evaluate(claim_id)
    assert summary["readiness"]["critical_missing_count"] == 3

    response = client.post(
        f"/api/v1/claims/{claim_id}/document-requests",
        json={"all_critical": True, "due_date": "2026-08-12", "recipient_label": "Owners"},
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["batch"]["status"] == "draft"
    assert payload["batch"]["recipient_label"] == "Owners"
    assert "Chief Engineer Report" in payload["batch"]["draft_body"]
    assert len(payload["tasks"]) == 3
    assert all(task["status"] == "open" for task in payload["tasks"])
    assert all(task["source"] == "rule" for task in payload["tasks"])
    assert all(task["priority"] == "critical" for task in payload["tasks"])

    rules = client.get(f"/api/v1/claims/{claim_id}/rules").json()
    assert {r["status"] for r in rules["requirements"]} == {"missing"}  # Drafting is not the same as sending.
    marked = client.post(f"/api/v1/claims/{claim_id}/document-requests/{payload['batch']['id']}/mark-sent")
    assert marked.status_code == 200, marked.text
    assert marked.json()["status"] == "sent_externally"
    rules = client.get(f"/api/v1/claims/{claim_id}/rules").json()
    assert {r["status"] for r in rules["requirements"]} == {"requested"}
    assert rules["readiness"]["critical_missing_count"] == 3  # Requested is not satisfied.


def test_request_selected_requirement_does_not_duplicate_open_task() -> None:
    result = create_orion_claim(); claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.TRIAGE)
    summary = _evaluate(claim_id)
    ce = next(r for r in summary["requirements"] if r["document_type"] == "chief_engineer_report")
    for _ in range(2):
        response = client.post(f"/api/v1/claims/{claim_id}/document-requests", json={"requirement_ids": [ce["id"]]})
        assert response.status_code == 201, response.text
    tasks = client.get(f"/api/v1/claims/{claim_id}/tasks").json()
    assert tasks["total"] == 1
    with TestingSessionLocal() as db:
        batches = list(db.scalars(select(DocumentRequestBatch).where(DocumentRequestBatch.claim_id == UUID(claim_id))))
        assert len(batches) == 2  # Each draft is preserved for audit; the follow-up task is reused.


def test_document_upload_auto_completes_requirement_task(tmp_path: Path) -> None:
    result = create_orion_claim(); claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.TRIAGE); _configure_storage(tmp_path)
    summary = _evaluate(claim_id)
    ce = next(r for r in summary["requirements"] if r["document_type"] == "chief_engineer_report")
    request = client.post(f"/api/v1/claims/{claim_id}/document-requests", json={"requirement_ids": [ce["id"]], "due_date": "2026-08-12"})
    task_id = request.json()["tasks"][0]["id"]
    batch_id = request.json()["batch"]["id"]
    assert client.post(f"/api/v1/claims/{claim_id}/document-requests/{batch_id}/mark-sent").status_code == 200

    upload = client.post(
        f"/api/v1/claims/{claim_id}/documents",
        files={"file": ("ce.pdf", b"%PDF-1.4\nChief Engineer Report\n%%EOF", "application/pdf")},
        data={"document_type": "chief_engineer_report", "confidentiality_level": "confidential"},
    )
    assert upload.status_code == 201, upload.text
    rules = client.get(f"/api/v1/claims/{claim_id}/rules").json()
    ce_after = next(r for r in rules["requirements"] if r["document_type"] == "chief_engineer_report")
    assert ce_after["status"] == "received"
    tasks = client.get(f"/api/v1/claims/{claim_id}/tasks").json()
    task = next(t for t in tasks["items"] if t["id"] == task_id)
    assert task["status"] == "completed"
    assert "automatically completed" in task["completion_reason"].lower()


def test_manual_task_completion_is_audited() -> None:
    result = create_orion_claim(); claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.TRIAGE)
    summary = _evaluate(claim_id)
    req = summary["requirements"][0]
    created = client.post(f"/api/v1/claims/{claim_id}/document-requests", json={"requirement_ids": [req["id"]]})
    task_id = created.json()["tasks"][0]["id"]
    completed = client.post(f"/api/v1/claims/{claim_id}/tasks/{task_id}/complete", json={"reason": "Owner confirmed this document is unavailable."})
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    with TestingSessionLocal() as db:
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "COMPLETE_CLAIM_TASK", AuditLog.entity_id == UUID(task_id)))
        assert audit is not None


def test_document_requests_are_tenant_scoped() -> None:
    result = create_orion_claim(); claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.TRIAGE); _evaluate(claim_id)
    client.cookies.clear(); login("beta", "beta-handler@example.com")
    assert client.get(f"/api/v1/claims/{claim_id}/tasks").status_code == 404
    assert client.post(f"/api/v1/claims/{claim_id}/document-requests", json={"all_critical": True}).status_code == 404


def test_accepting_equivalent_evidence_auto_completes_open_requirement_task() -> None:
    from uuid import uuid4
    from app.modules.claims.facts import ClaimFact
    from app.modules.claims.models import Claim

    result = create_orion_claim(); claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(claim_id))
        fact = ClaimFact(
            organization_id=claim.organization_id, claim_id=claim.id,
            field_path="maintenance.recommended_overhaul_interval", value={"value": 12000, "unit": "hours"},
            source_extraction_id=uuid4(), source_document_id=uuid4(), source_segment_id=None,
            approved_by_id=None, version=1,
        )
        db.add(fact); db.commit(); db.refresh(fact); fact_id=str(fact.id)
    summary = _evaluate(claim_id)
    req = next(r for r in summary["requirements"] if r["document_type"] == "maker_recommendation")
    request = client.post(f"/api/v1/claims/{claim_id}/document-requests", json={"requirement_ids": [req["id"]]})
    assert request.status_code == 201
    task_id = request.json()["tasks"][0]["id"]
    accepted = client.post(
        f"/api/v1/claims/{claim_id}/rules/requirements/{req['id']}/accept-equivalent",
        json={"claim_fact_id": fact_id, "note": "Reviewed approved maintenance interval as sufficient equivalent evidence."},
    )
    assert accepted.status_code == 200, accepted.text
    tasks = client.get(f"/api/v1/claims/{claim_id}/tasks").json()["items"]
    task = next(row for row in tasks if row["id"] == task_id)
    assert task["status"] == "completed"
    assert "equivalent evidence" in task["completion_reason"].lower()
