"""Synthetic-only regression: a second OCR/text run invalidates old AI citations."""
from uuid import UUID

from sqlalchemy import select

from app.modules.claims.facts import ClaimFact
from app.modules.intelligence.models import AIReviewStatus, DocumentExtraction
from app.modules.processing.models import AI_SOURCE_REPROCESSED_WARNING
from app.modules.processing.service import _invalidate_ai_citations_after_text_reprocessing
from app.modules.documents.models import Document, DocumentProcessingStatus
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_human_ai_review import login, seed_review_candidates


def setup_function() -> None:
    reset_database()


def test_reprocessing_invalidates_matching_old_ai_candidates_without_rewriting_fields() -> None:
    ids = seed_review_candidates()
    with TestingSessionLocal() as db:
        document = db.get(Document, UUID(ids["document_id"]))
        maker = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        before_value, before_run = maker.raw_value, maker.ai_run_id
        assert document.processing_status == DocumentProcessingStatus.PROCESSED
        assert maker.source_verified is True

        changed = _invalidate_ai_citations_after_text_reprocessing(db, document=document)
        assert changed == 4  # all fictional AI candidates, including opinion & invalid quote
        assert _invalidate_ai_citations_after_text_reprocessing(db, document=document) == 4
        db.commit()
        db.refresh(maker)
        assert maker.source_verified is False
        assert maker.validation_warnings.count(AI_SOURCE_REPROCESSED_WARNING) == 1
        assert maker.raw_value == before_value
        assert maker.ai_run_id == before_run
        assert maker.human_status == AIReviewStatus.PENDING
        assert document.processing_status == DocumentProcessingStatus.PROCESSED

    login("alpha", "alpha@example.com")
    queue = client.get("/api/v1/ai-review")
    assert queue.status_code == 200, queue.text
    maker_row = next(x for x in queue.json()["items"] if x["extraction_id"] == ids["maker_id"])
    assert maker_row["source_approval_blocked"] is True
    assert maker_row["bulk_approvable"] is False
    assert AI_SOURCE_REPROCESSED_WARNING in maker_row["validation_warnings"]

    # A reason and a formerly quoted, high-confidence fact must not bypass
    # drift; nor may bulk or grouped approval turn it into a ClaimFact.
    url = f"/api/v1/ai-review/{ids['maker_id']}"
    approve = client.post(url, json={"action": "approve", "reason": "Original scan was viewed."})
    assert approve.status_code == 409, approve.text
    assert "reprocessed" in approve.json()["detail"]
    edit = client.post(url, json={"action": "edit", "value": "ABB New", "reason": "Reviewed source."})
    assert edit.status_code == 409, edit.text
    bulk = client.post("/api/v1/ai-review/bulk/approve", json={"extraction_ids": [ids["maker_id"]]})
    assert bulk.status_code == 409, bulk.text
    grouped = client.post(
        "/api/v1/ai-review/groups/review",
        json={"extraction_ids": [ids["maker_id"]], "action": "approve", "reason": "Viewed."},
    )
    assert grouped.status_code == 409, grouped.text
    with TestingSessionLocal() as db:
        maker = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        assert maker.human_status == AIReviewStatus.PENDING
        assert db.scalar(select(ClaimFact).where(ClaimFact.source_extraction_id == maker.id)) is None

    reject = client.post(url, json={"action": "reject", "reason": "Source was reprocessed; rerun AI."})
    assert reject.status_code == 200, reject.text


def test_invalidation_preserves_historical_human_decisions_and_current_fact_for_re_review() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    approved = client.post(f"/api/v1/ai-review/{ids['maker_id']}", json={"action": "approve"})
    assert approved.status_code == 200, approved.text
    with TestingSessionLocal() as db:
        document = db.get(Document, UUID(ids["document_id"]))
        maker = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        old = db.scalar(select(ClaimFact).where(ClaimFact.source_extraction_id == maker.id))
        assert old is not None
        old_id, old_value = old.id, old.value
        _invalidate_ai_citations_after_text_reprocessing(db, document=document)
        db.commit()
        db.refresh(maker)
        assert maker.human_status == AIReviewStatus.APPROVED
        assert maker.source_verified is False
        assert AI_SOURCE_REPROCESSED_WARNING in maker.validation_warnings
        fact = db.get(ClaimFact, old_id)
        assert fact is not None and fact.value == old_value
        # A processing worker must not silently change historical H&M judgment.
        # Review of any such canonical fact requires a separate governance flow.

    denied = client.post(
        f"/api/v1/ai-review/{ids['maker_id']}",
        json={"action": "approve", "reason": "Re-review confirmed.", "confirm_re_review": True},
    )
    assert denied.status_code == 409, denied.text


def test_reprocessing_unrelated_document_does_not_mutate_original_candidates() -> None:
    ids = seed_review_candidates()
    with TestingSessionLocal() as db:
        maker = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        original = db.get(Document, UUID(ids["document_id"]))
        old_warnings = list(maker.validation_warnings or [])
        unrelated = Document(
            organization_id=original.organization_id,
            claim_id=original.claim_id,
            uploaded_by_id=original.uploaded_by_id,
            filename="unrelated.pdf",
            original_filename="unrelated.pdf",
            file_size_bytes=200,
            file_hash="d" * 64,
            mime_type="application/pdf",
            storage_key="fictional/unrelated.pdf",
            processing_status=DocumentProcessingStatus.PROCESSED,
        )
        db.add(unrelated)
        db.flush()
        assert _invalidate_ai_citations_after_text_reprocessing(db, document=unrelated) == 0
        db.commit()
        db.refresh(maker)
        assert maker.source_verified is True
        assert list(maker.validation_warnings or []) == old_warnings
