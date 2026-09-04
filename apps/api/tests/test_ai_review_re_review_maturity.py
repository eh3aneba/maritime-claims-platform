import importlib
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.modules.claims.facts import ClaimFact
from app.modules.intelligence.models import AIFeedback, AISemanticKind, AIReviewStatus, DocumentExtraction
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_human_ai_review import login, seed_review_candidates

review_router = importlib.import_module("app.modules.review.router")


def setup_function() -> None:
    reset_database()


def _add_candidate(ids: dict[str, str], field_path: str, value: str) -> str:
    with TestingSessionLocal() as db:
        source = db.get(DocumentExtraction, UUID(ids["maker_id"]))
        assert source is not None
        candidate = DocumentExtraction(
            organization_id=source.organization_id,
            claim_id=source.claim_id,
            document_id=source.document_id,
            ai_run_id=source.ai_run_id,
            source_segment_id=source.source_segment_id,
            field_path=field_path,
            semantic_kind=AISemanticKind.FACT,
            raw_value=value,
            normalized_value=value,
            confidence=Decimal("0.970"),
            source_locator_type=source.source_locator_type,
            source_locator_value=source.source_locator_value,
            source_quote=source.source_quote,
            source_verified=True,
            human_status=AIReviewStatus.PENDING,
        )
        db.add(candidate)
        db.commit()
        return str(candidate.id)


def _assert_review_rollback(ids: list[str]) -> None:
    extraction_ids = [UUID(value) for value in ids]
    with TestingSessionLocal() as db:
        rows = [db.get(DocumentExtraction, extraction_id) for extraction_id in extraction_ids]
        assert all(row is not None and row.human_status == AIReviewStatus.PENDING for row in rows)
        feedback = list(db.scalars(select(AIFeedback).where(AIFeedback.extraction_id.in_(extraction_ids))))
        assert feedback == []
        facts = list(db.scalars(select(ClaimFact).where(ClaimFact.source_extraction_id.in_(extraction_ids))))
        assert facts == []


def _inject_stale_second_item(monkeypatch, second_id: str) -> None:
    real_review = review_router.review_extraction
    calls = 0

    def race_review(db, **kwargs):
        nonlocal calls
        calls += 1
        result = real_review(db, **kwargs)
        if calls == 1:
            second = db.get(DocumentExtraction, UUID(second_id))
            assert second is not None
            second.human_status = AIReviewStatus.APPROVED
            second.approved_value = second.normalized_value
            db.flush()
        return result

    monkeypatch.setattr(review_router, "review_extraction", race_review)


def test_bulk_review_rechecks_pending_state_after_lock_and_rolls_back_stale_batch(monkeypatch) -> None:
    ids = seed_review_candidates()
    second_id = _add_candidate(ids, "equipment.serial_number", "SN-001")
    _inject_stale_second_item(monkeypatch, second_id)
    login("alpha", "alpha@example.com")

    response = client.post(
        "/api/v1/ai-review/bulk/approve",
        json={
            "extraction_ids": [ids["maker_id"], second_id],
            "reason": "Reviewed identity metadata as one batch.",
        },
    )
    assert response.status_code == 409, response.text
    assert "stale" in response.json()["detail"].lower()
    _assert_review_rollback([ids["maker_id"], second_id])


def test_group_review_rechecks_pending_state_after_lock_and_rolls_back_stale_batch(monkeypatch) -> None:
    ids = seed_review_candidates()
    first_id = _add_candidate(ids, "engine_log.events[7].time", "10:52")
    second_id = _add_candidate(ids, "engine_log.events[7].rpm", "620")
    _inject_stale_second_item(monkeypatch, second_id)
    login("alpha", "alpha@example.com")

    response = client.post(
        "/api/v1/ai-review/groups/review",
        json={
            "extraction_ids": [first_id, second_id],
            "action": "approve",
            "reason": "Reviewed complete Engine Log row against source.",
        },
    )
    assert response.status_code == 409, response.text
    assert "stale" in response.json()["detail"].lower()
    _assert_review_rollback([first_id, second_id])
