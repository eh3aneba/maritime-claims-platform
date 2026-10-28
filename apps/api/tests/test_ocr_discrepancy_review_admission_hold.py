"""Synthetic-only safety hold on *reported*, unresolved source OCR discrepancies.

The receipt is an operator observation, never a verified transcript, correction,
expert conclusion or claim adjudication. AI facts cannot be promoted from the
currently reported source; historic decisions are not retroactively rewritten.
"""
from uuid import UUID

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.claims.facts import ClaimFact
from app.modules.documents.models import Document
from app.modules.intelligence.models import AIFeedback, AIReviewStatus, DocumentExtraction
from app.modules.processing.models import DocumentTextExtraction
from app.modules.users.models import User
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_human_ai_review import login, seed_review_candidates


def setup_function() -> None:
    reset_database()


def _mark_synthetic_source_as_ocr(ids: dict[str, str]) -> None:
    with TestingSessionLocal() as db:
        row = db.scalar(select(DocumentTextExtraction).where(
            DocumentTextExtraction.document_id == UUID(ids["document_id"]),
        ))
        assert row is not None
        row.extraction_method = "tesseract:eng+fas"
        db.commit()


def _report_fake_discrepancy(
    ids: dict[str, str], *,
    original_hash: str | None = None,
    tenant_id: str | None = None,
) -> None:
    with TestingSessionLocal() as db:
        doc = db.get(Document, UUID(ids["document_id"]))
        source = db.scalar(select(DocumentTextExtraction).where(
            DocumentTextExtraction.document_id == doc.id,
        ))
        user = db.scalar(select(User).where(
            User.organization_id == doc.organization_id,
        ))
        assert doc and source and user
        db.add(AuditLog(
            organization_id=UUID(tenant_id) if tenant_id else doc.organization_id,
            user_id=user.id if tenant_id is None else None,
            action="REPORT_OCR_SOURCE_DISCREPANCY",
            entity_type="document",
            entity_id=doc.id,
            new_values={
                "claim_id": str(doc.claim_id),
                "document_version": doc.version_number,
                "source_file_hash": original_hash if original_hash is not None else doc.file_hash,
                "extraction_text_hash": source.text_hash,
                "segment_index": 0,
                "locator_type": "document",
                "locator_value": "body",
                "issue_kind": "negation_missing",
                "review_state": "reported_unverified",
                "source_compared_by_operator": True,
                "claim_fact_approved": False,
            },
        ))
        db.commit()


def test_reported_source_hold_blocks_individual_group_and_bulk_without_side_effects() -> None:
    ids = seed_review_candidates()
    _mark_synthetic_source_as_ocr(ids)
    _report_fake_discrepancy(ids)
    login("alpha", "alpha@example.com")

    queue = client.get("/api/v1/ai-review")
    assert queue.status_code == 200, queue.text
    maker = next(x for x in queue.json()["items"] if x["extraction_id"] == ids["maker_id"])
    assert maker["source_approval_blocked"] is True
    assert maker["bulk_approvable"] is False
    assert any("Unresolved operator-reported OCR source discrepancy" in value
               for value in maker["validation_warnings"])

    attempts = [
        (f"/api/v1/ai-review/{ids['maker_id']}",
         {"action": "approve", "reason": "Operator manually checked the original page."}),
        (f"/api/v1/ai-review/{ids['maker_id']}",
         {"action": "edit", "value": "ABB corrected", "reason": "Operator checked image."}),
        ("/api/v1/ai-review/groups/review",
         {"extraction_ids": [ids["maker_id"], ids["time_id"]],
          "action": "approve", "reason": "Operator checked the original pages."}),
        ("/api/v1/ai-review/bulk/approve",
         {"extraction_ids": [ids["maker_id"]], "reason": "Operator checked image."}),
    ]
    for url, payload in attempts:
        result = client.post(url, json=payload)
        assert result.status_code == 409, result.text

    with TestingSessionLocal() as db:
        maker = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        other = db.get(DocumentExtraction, UUID(ids["time_id"]))
        assert maker.human_status == AIReviewStatus.PENDING
        assert other.human_status == AIReviewStatus.PENDING
        assert not list(db.scalars(select(ClaimFact).where(
            ClaimFact.claim_id == UUID(ids["claim_id"]),
        )))
        assert not list(db.scalars(select(AIFeedback).where(
            AIFeedback.document_id == UUID(ids["document_id"]),
        )))

    # Rejecting a known-unreliable extraction is always permitted.
    reject = client.post(
        f"/api/v1/ai-review/{ids['maker_id']}", json={"action": "reject"}
    )
    assert reject.status_code == 200, reject.text
    assert reject.json()["human_status"] == "rejected"
    assert reject.json()["promoted"] is False


def test_an_old_or_another_tenants_report_does_not_block_current_source() -> None:
    ids = seed_review_candidates()
    _mark_synthetic_source_as_ocr(ids)
    _report_fake_discrepancy(ids, original_hash="e" * 64)
    _report_fake_discrepancy(ids, tenant_id=str(UUID("00000000-0000-4000-8000-000000000123")))
    login("alpha", "alpha@example.com")
    queue = client.get("/api/v1/ai-review")
    assert queue.status_code == 200, queue.text
    maker = next(x for x in queue.json()["items"] if x["extraction_id"] == ids["maker_id"])
    assert maker["source_approval_blocked"] is False
    assert maker["original_source_comparison_required"] is True
    approve = client.post(
        f"/api/v1/ai-review/{ids['maker_id']}",
        json={"action": "approve", "reason": "Manual original source comparison asserted."},
    )
    assert approve.status_code == 200, approve.text
    assert approve.json()["promoted"] is True


def test_source_hold_survives_reprocessing_and_blocks_deliberate_re_review() -> None:
    ids = seed_review_candidates()
    _mark_synthetic_source_as_ocr(ids)
    login("alpha", "alpha@example.com")
    previously_approved = client.post(
        f"/api/v1/ai-review/{ids['maker_id']}",
        json={"action": "approve", "reason": "Operator asserted earlier source check."},
    )
    assert previously_approved.status_code == 200
    _report_fake_discrepancy(ids)
    with TestingSessionLocal() as db:
        source = db.scalar(select(DocumentTextExtraction).where(
            DocumentTextExtraction.document_id == UUID(ids["document_id"]),
        ))
        assert source is not None
        source.text_hash = "d" * 64
        db.commit()

    queue = client.get("/api/v1/ai-review", params={"review_status": "all"})
    assert queue.status_code == 200
    maker = next(x for x in queue.json()["items"] if x["extraction_id"] == ids["maker_id"])
    assert maker["source_approval_blocked"] is True
    reapprove = client.post(
        f"/api/v1/ai-review/{ids['maker_id']}",
        json={
            "action": "edit", "value": "ABB renewed",
            "reason": "A different OCR run is not independent error resolution.",
            "confirm_re_review": True,
        },
    )
    assert reapprove.status_code == 409
    with TestingSessionLocal() as db:
        old = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        assert old.human_status == AIReviewStatus.APPROVED
        fact = db.scalar(select(ClaimFact).where(
            ClaimFact.source_extraction_id == old.id,
        ))
        # This PR cannot invalidate previously approved facts retroactively.
        assert fact is not None and fact.value == "ABB"
