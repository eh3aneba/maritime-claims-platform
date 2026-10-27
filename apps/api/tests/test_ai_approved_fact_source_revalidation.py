"""Synthetic H&M approved Claim Facts: disclose lineage drift, never auto-decide."""
from uuid import UUID

from sqlalchemy import select

from app.modules.claims.facts import ClaimFact
from app.modules.documents.models import Document, DocumentProcessingStatus
from app.modules.intelligence.models import DocumentExtraction
from app.modules.processing.models import AI_SOURCE_REPROCESSED_WARNING
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_human_ai_review import login, seed_review_candidates


def setup_function() -> None:
    reset_database()


def _maker_fact(claim_id: str) -> dict:
    response = client.get(f"/api/v1/claims/{claim_id}/facts")
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["items"] if item["field_path"] == "equipment.maker")


def test_approved_ai_fact_reports_source_reprocessed_without_reversing_human_approval() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    approved = client.post(f"/api/v1/ai-review/{ids['maker_id']}", json={"action": "approve"})
    assert approved.status_code == 200, approved.text
    before = _maker_fact(ids["claim_id"])
    assert before["source_revalidation_required"] is False
    assert before["source_revalidation_reason"] is None

    with TestingSessionLocal() as db:
        candidate = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        candidate.source_verified = False
        candidate.validation_warnings = [
            *(candidate.validation_warnings or []), AI_SOURCE_REPROCESSED_WARNING,
        ]
        db.commit()

    after = _maker_fact(ids["claim_id"])
    assert after["source_revalidation_required"] is True
    assert after["source_revalidation_reason"] == "source_reprocessed"
    for key in ("id", "field_path", "value", "approved_by_id", "approved_at", "version"):
        assert after[key] == before[key], key
    with TestingSessionLocal() as db:
        assert db.get(ClaimFact, UUID(before["id"])).source_extraction_id == UUID(ids["maker_id"])
    login("beta", "beta@example.com")
    hidden = client.get(f"/api/v1/claims/{ids['claim_id']}/facts")
    assert hidden.status_code == 404


def test_approved_fact_warns_when_document_superseded_or_processing_fails() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    approved = client.post(f"/api/v1/ai-review/{ids['maker_id']}", json={"action": "approve"})
    assert approved.status_code == 200, approved.text
    with TestingSessionLocal() as db:
        document = db.get(Document, UUID(ids["document_id"]))
        document.is_current = False
        db.commit()
    fact = _maker_fact(ids["claim_id"])
    assert fact["source_revalidation_required"] is True
    assert fact["source_revalidation_reason"] == "source_document_unusable"
    with TestingSessionLocal() as db:
        document = db.get(Document, UUID(ids["document_id"]))
        document.is_current = True
        document.processing_status = DocumentProcessingStatus.FAILED
        db.commit()
    fact = _maker_fact(ids["claim_id"])
    assert fact["source_revalidation_required"] is True
    assert fact["source_revalidation_reason"] == "source_document_unusable"


def test_no_change_to_approved_fact_when_source_is_still_current() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    response = client.post(f"/api/v1/ai-review/{ids['maker_id']}", json={"action": "approve"})
    assert response.status_code == 200, response.text
    fact = _maker_fact(ids["claim_id"])
    assert fact["source_revalidation_required"] is False
    assert fact["source_revalidation_reason"] is None
    # A successful source metadata check is not an assertion of AI/OCR correctness.
