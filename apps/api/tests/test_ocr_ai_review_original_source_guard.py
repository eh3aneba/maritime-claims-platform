"""OCR transcript quotation != verified original scan: review guards.

This test uses only fictional H&M claim records from the existing
review harness. No real customer images or human attestation is created.
"""
from uuid import UUID

import pytest
from sqlalchemy import select

from app.modules.claims.facts import ClaimFact
from app.modules.intelligence.models import AIReviewStatus, DocumentExtraction
from app.modules.processing.models import DocumentTextExtraction
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_human_ai_review import login, seed_review_candidates


def setup_function() -> None:
    reset_database()


def _set_method(ids: dict[str, str], *, method: str, requires_ocr: bool = False) -> None:
    with TestingSessionLocal() as db:
        row = db.scalar(
            select(DocumentTextExtraction).where(
                DocumentTextExtraction.document_id == UUID(ids["document_id"]),
                DocumentTextExtraction.organization_id == UUID(ids["alpha_org_id"]),
            )
        )
        assert row is not None
        row.extraction_method = method
        row.requires_ocr = requires_ocr
        db.commit()


@pytest.mark.parametrize(
    "method",
    ["tesseract:eng+fas", "pypdf+selective-tesseract:eng+fas", "future_ocr_engine:v1"],
)
def test_ocr_citation_match_does_not_enable_bulk_approval(method: str) -> None:
    ids = seed_review_candidates()
    _set_method(ids, method=method)
    login("alpha", "alpha@example.com")
    queued = client.get("/api/v1/ai-review")
    assert queued.status_code == 200, queued.text
    maker = next(x for x in queued.json()["items"] if x["extraction_id"] == ids["maker_id"])
    assert maker["source_verified"] is True  # matched machine text, NOT the actual scan
    assert maker["bulk_approvable"] is False
    assert any("original scan" in warning for warning in maker["validation_warnings"])

    # Even a nonempty reason must not turn machine OCR into bulk eligibility.
    denied = client.post(
        "/api/v1/ai-review/bulk/approve",
        json={
            "extraction_ids": [ids["maker_id"]],
            "reason": "An operator wrote a reason, not an independent source attestation.",
        },
    )
    assert denied.status_code == 409, denied.text
    with TestingSessionLocal() as db:
        row = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        assert row.human_status == AIReviewStatus.PENDING
        assert db.scalar(select(ClaimFact).where(
            ClaimFact.source_extraction_id == row.id,
        )) is None


@pytest.mark.parametrize(
    "method,requires_ocr",
    [
        ("tesseract:eng+fas", False),
        ("pypdf+selective-tesseract:eng+fas", False),
        ("pypdf+ocr_unavailable", True),
        ("future_ocr_engine:v1", False),
    ],
)
def test_individual_ocr_approval_needs_documented_original_comparison(
    method: str, requires_ocr: bool,
) -> None:
    ids = seed_review_candidates()
    _set_method(ids, method=method, requires_ocr=requires_ocr)
    login("alpha", "alpha@example.com")
    url = f"/api/v1/ai-review/{ids['maker_id']}"
    no_reason = client.post(url, json={"action": "approve"})
    assert no_reason.status_code == 409, no_reason.text
    assert "original document" in no_reason.json()["detail"]
    accepted = client.post(
        url,
        json={
            "action": "approve",
            "reason": "Operator compared the source page, maker name and technical context manually.",
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["promoted"] is True
    # A reason is an operator assertion and DOES NOT certify OCR accuracy.


def test_grouped_ocr_approval_rejects_reasonless_batch_without_partial_review() -> None:
    ids = seed_review_candidates()
    _set_method(ids, method="tesseract:eng+fas")
    login("alpha", "alpha@example.com")
    response = client.post(
        "/api/v1/ai-review/groups/review",
        json={"extraction_ids": [ids["maker_id"]], "action": "approve"},
    )
    assert response.status_code == 409, response.text
    with TestingSessionLocal() as db:
        maker = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        assert maker.human_status == AIReviewStatus.PENDING


def test_native_document_remains_eligible_for_prior_bulk_flow() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    queued = client.get("/api/v1/ai-review")
    assert queued.status_code == 200
    maker = next(x for x in queued.json()["items"] if x["extraction_id"] == ids["maker_id"])
    assert maker["bulk_approvable"] is True
    approved = client.post(
        "/api/v1/ai-review/bulk/approve",
        json={"extraction_ids": [ids["maker_id"]]},
    )
    assert approved.status_code == 200, approved.text


def test_incomplete_text_extraction_status_fails_closed_for_bulk() -> None:
    # Simulate an incomplete/failed OCR source even though an AI candidate exists
    # in the fictional fixture, to ensure status never makes bulk review safe.
    ids = seed_review_candidates()
    _set_method(ids, method="pypdf+ocr_unavailable", requires_ocr=True)
    login("alpha", "alpha@example.com")
    queued = client.get("/api/v1/ai-review")
    assert queued.status_code == 200
    maker = next(x for x in queued.json()["items"] if x["extraction_id"] == ids["maker_id"])
    assert maker["bulk_approvable"] is False
