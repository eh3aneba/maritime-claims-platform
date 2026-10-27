"""Synthetic H&M evidence admissibility at human AI fact-review time.

A reviewer note cannot authorize a superseded, unprocessed or quarantined
source as a current Claim Fact. Rejections remain available for cleanup.
"""
from uuid import UUID

import pytest
from sqlalchemy import select

from app.modules.claims.facts import ClaimFact
from app.modules.documents.models import (
    Document, DocumentMalwareScanStatus, DocumentProcessingStatus,
)
from app.modules.intelligence.models import AIReviewStatus, DocumentExtraction
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_human_ai_review import login, seed_review_candidates


def setup_function() -> None:
    reset_database()


@pytest.mark.parametrize(
    "column,bad_value",
    [
        ("is_current", False),
        ("processing_status", DocumentProcessingStatus.FAILED),
        ("processing_status", DocumentProcessingStatus.UPLOADED),
        ("processing_status", DocumentProcessingStatus.PROCESSING),
        ("malware_scan_status", DocumentMalwareScanStatus.INFECTED_QUARANTINED),
        ("malware_scan_status", DocumentMalwareScanStatus.SCAN_ERROR),
    ],
)
def test_unusable_original_source_cannot_be_approved_even_with_reason(column, bad_value) -> None:
    ids = seed_review_candidates()
    with TestingSessionLocal() as db:
        document = db.get(Document, UUID(ids["document_id"]))
        setattr(document, column, bad_value)
        db.commit()

    login("alpha", "alpha@example.com")
    response = client.get("/api/v1/ai-review")
    assert response.status_code == 200, response.text
    maker = next(item for item in response.json()["items"] if item["extraction_id"] == ids["maker_id"])
    assert maker["source_verified"] is True  # machine quote match, not current admissibility
    assert maker["source_approval_blocked"] is True
    assert maker["bulk_approvable"] is False
    assert any("approval is blocked" in warning for warning in maker["validation_warnings"])

    groups = client.get("/api/v1/ai-review/groups?attention_only=false")
    assert groups.status_code == 200, groups.text
    group = next(item for item in groups.json()["groups"] if any(
        row["extraction_id"] == ids["maker_id"] for row in item["items"]
    ))
    assert group["group_approvable"] is False
    assert group["needs_attention"] is True

    direct = client.post(
        f"/api/v1/ai-review/{ids['maker_id']}",
        json={"action": "approve", "reason": "Synthetic reviewer examined this source."},
    )
    assert direct.status_code == 409, direct.text
    assert "superseded" in direct.json()["detail"]

    edited = client.post(
        f"/api/v1/ai-review/{ids['maker_id']}",
        json={"action": "edit", "value": "ABB Marine", "reason": "Operator suggests correction."},
    )
    assert edited.status_code == 409, edited.text

    bulk = client.post(
        "/api/v1/ai-review/bulk/approve",
        json={"extraction_ids": [ids["maker_id"]], "reason": "Manual reason does not override source status."},
    )
    assert bulk.status_code == 409, bulk.text

    grouped = client.post(
        "/api/v1/ai-review/groups/review",
        json={"extraction_ids": [ids["maker_id"]], "action": "approve", "reason": "Synthetic review note."},
    )
    assert grouped.status_code == 409, grouped.text

    with TestingSessionLocal() as db:
        item = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        assert item.human_status == AIReviewStatus.PENDING
        assert db.scalar(select(ClaimFact).where(ClaimFact.source_extraction_id == item.id)) is None

    rejection = client.post(
        f"/api/v1/ai-review/{ids['maker_id']}", json={"action": "reject", "reason": "Stale evidence."},
    )
    assert rejection.status_code == 200, rejection.text
    assert rejection.json()["human_status"] == "rejected"


def test_current_processed_legacy_or_clean_native_source_still_allows_approval() -> None:
    for scanned in (False, True):
        reset_database()
        ids = seed_review_candidates()
        if scanned:
            with TestingSessionLocal() as db:
                document = db.get(Document, UUID(ids["document_id"]))
                document.malware_scan_status = DocumentMalwareScanStatus.CLEAN
                db.commit()
        login("alpha", "alpha@example.com")
        queued = client.get("/api/v1/ai-review")
        maker = next(item for item in queued.json()["items"] if item["extraction_id"] == ids["maker_id"])
        assert maker["source_approval_blocked"] is False
        assert maker["bulk_approvable"] is True
        ok = client.post(f"/api/v1/ai-review/{ids['maker_id']}", json={"action": "approve"})
        assert ok.status_code == 200, ok.text


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
