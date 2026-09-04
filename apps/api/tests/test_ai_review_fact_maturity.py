from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.modules.audit.models import AuditLog
from app.modules.claims.facts import ClaimFact, ClaimFactRevision
from app.modules.intelligence.models import AIFeedback, AIRun, AISemanticKind, AIReviewStatus, DocumentExtraction
from app.modules.processing.models import DocumentTextExtraction, DocumentTextSegment
from app.modules.users.models import User
from tests.db_harness import TestingSessionLocal, client, reset_database
from tests.test_human_ai_review import login, seed_review_candidates


def setup_function() -> None:
    reset_database()


def _add_intake_fact_and_ai_candidate(ids: dict[str, str]) -> str:
    with TestingSessionLocal() as db:
        claim_id = UUID(ids["claim_id"])
        document_id = UUID(ids["document_id"])
        user = db.scalar(select(User).where(User.organization_id == UUID(ids["alpha_org_id"])))
        text_extraction = db.scalar(
            select(DocumentTextExtraction).where(DocumentTextExtraction.document_id == document_id)
        )
        segment = db.scalar(
            select(DocumentTextSegment).where(DocumentTextSegment.document_id == document_id)
        )
        run = db.scalar(select(AIRun).where(AIRun.document_id == document_id))
        assert user is not None and text_extraction is not None and segment is not None and run is not None

        intake_fact = ClaimFact(
            organization_id=UUID(ids["alpha_org_id"]),
            claim_id=claim_id,
            field_path="claim.incident_description",
            value="Turbocharger failure",
            provenance_kind="intake_review",
            source_extraction_id=None,
            source_text_extraction_id=text_extraction.id,
            source_document_id=document_id,
            source_segment_id=segment.id,
            approved_by_id=user.id,
            approved_at=datetime.now(UTC),
            version=1,
        )
        candidate = DocumentExtraction(
            organization_id=UUID(ids["alpha_org_id"]),
            claim_id=claim_id,
            document_id=document_id,
            ai_run_id=run.id,
            source_segment_id=segment.id,
            field_path="claim.incident_description",
            semantic_kind=AISemanticKind.FACT,
            raw_value="Main engine turbocharger failure with abnormal vibration.",
            normalized_value="Main engine turbocharger failure with abnormal vibration.",
            confidence=Decimal("0.950"),
            source_locator_type="document",
            source_locator_value="body",
            source_quote="Turbocharger failure",
            source_verified=True,
            human_status=AIReviewStatus.PENDING,
        )
        db.add_all([intake_fact, candidate])
        db.commit()
        return str(candidate.id)


def test_ai_approval_replaces_intake_fact_with_constraint_correct_provenance() -> None:
    ids = seed_review_candidates()
    candidate_id = _add_intake_fact_and_ai_candidate(ids)
    login("alpha", "alpha@example.com")

    response = client.post(f"/api/v1/ai-review/{candidate_id}", json={"action": "approve"})
    assert response.status_code == 200, response.text
    assert response.json()["promoted"] is True

    with TestingSessionLocal() as db:
        fact = db.scalar(
            select(ClaimFact).where(
                ClaimFact.claim_id == UUID(ids["claim_id"]),
                ClaimFact.field_path == "claim.incident_description",
            )
        )
        assert fact is not None
        assert fact.value == "Main engine turbocharger failure with abnormal vibration."
        assert fact.provenance_kind == "ai_review"
        assert fact.source_extraction_id == UUID(candidate_id)
        assert fact.source_text_extraction_id is None
        assert fact.version == 2

        revisions = list(
            db.scalars(
                select(ClaimFactRevision)
                .where(
                    ClaimFactRevision.claim_id == UUID(ids["claim_id"]),
                    ClaimFactRevision.field_path == "claim.incident_description",
                )
                .order_by(ClaimFactRevision.version)
            )
        )
        assert [row.version for row in revisions] == [1, 2]
        assert revisions[0].provenance_kind == "intake_review"
        assert revisions[0].source_text_extraction_id is not None
        assert revisions[1].provenance_kind == "ai_review"
        assert revisions[1].source_extraction_id == UUID(candidate_id)
        assert revisions[1].source_text_extraction_id is None


def test_exact_individual_review_replay_is_idempotent() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    endpoint = f"/api/v1/ai-review/{ids['maker_id']}"

    first = client.post(endpoint, json={"action": "approve"})
    second = client.post(endpoint, json={"action": "approve"})
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["human_status"] == "approved"
    assert second.json()["promoted"] is True

    with TestingSessionLocal() as db:
        extraction_id = UUID(ids["maker_id"])
        feedback = list(
            db.scalars(select(AIFeedback).where(AIFeedback.extraction_id == extraction_id))
        )
        assert len(feedback) == 1
        fact = db.scalar(select(ClaimFact).where(ClaimFact.source_extraction_id == extraction_id))
        assert fact is not None
        assert fact.version == 1
        revisions = list(
            db.scalars(
                select(ClaimFactRevision).where(
                    ClaimFactRevision.claim_id == UUID(ids["claim_id"]),
                    ClaimFactRevision.field_path == "equipment.maker",
                )
            )
        )
        assert len(revisions) == 1

        review_audit = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.organization_id == UUID(ids["alpha_org_id"]),
                    AuditLog.action == "REVIEW_AI_EXTRACTION",
                    AuditLog.entity_id == extraction_id,
                )
            )
        )
        assert len(review_audit) == 1


def test_same_value_with_new_reason_is_an_intentional_new_review() -> None:
    ids = seed_review_candidates()
    login("alpha", "alpha@example.com")
    endpoint = f"/api/v1/ai-review/{ids['maker_id']}"

    first = client.post(endpoint, json={"action": "approve"})
    second = client.post(
        endpoint,
        json={"action": "approve", "reason": "Reconfirmed against maker plate after second review."},
    )
    assert first.status_code == 200
    assert second.status_code == 200

    with TestingSessionLocal() as db:
        extraction_id = UUID(ids["maker_id"])
        feedback = list(
            db.scalars(
                select(AIFeedback)
                .where(AIFeedback.extraction_id == extraction_id)
                .order_by(AIFeedback.created_at, AIFeedback.id)
            )
        )
        assert len(feedback) == 2
        assert feedback[-1].reason == "Reconfirmed against maker plate after second review."
        fact = db.scalar(select(ClaimFact).where(ClaimFact.source_extraction_id == extraction_id))
        assert fact is not None and fact.version == 2


def test_rejecting_superseding_ai_fact_restores_previous_intake_fact() -> None:
    ids = seed_review_candidates()
    candidate_id = _add_intake_fact_and_ai_candidate(ids)
    login("alpha", "alpha@example.com")
    endpoint = f"/api/v1/ai-review/{candidate_id}"

    approved = client.post(endpoint, json={"action": "approve"})
    assert approved.status_code == 200, approved.text
    rejected = client.post(
        endpoint,
        json={"action": "reject", "reason": "Second human review found the AI description overstates the source."},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["human_status"] == "rejected"
    assert rejected.json()["claim_fact"] is not None
    assert rejected.json()["claim_fact"]["value"] == "Turbocharger failure"

    with TestingSessionLocal() as db:
        fact = db.scalar(
            select(ClaimFact).where(
                ClaimFact.claim_id == UUID(ids["claim_id"]),
                ClaimFact.field_path == "claim.incident_description",
            )
        )
        assert fact is not None
        assert fact.value == "Turbocharger failure"
        assert fact.provenance_kind == "intake_review"
        assert fact.source_extraction_id is None
        assert fact.source_text_extraction_id is not None
        assert fact.version == 3

        revisions = list(
            db.scalars(
                select(ClaimFactRevision)
                .where(
                    ClaimFactRevision.claim_id == UUID(ids["claim_id"]),
                    ClaimFactRevision.field_path == "claim.incident_description",
                )
                .order_by(ClaimFactRevision.version)
            )
        )
        assert [row.version for row in revisions] == [1, 2, 3]
        assert revisions[-1].provenance_kind == "intake_review"
        assert revisions[-1].value == "Turbocharger failure"
        restore_audit = list(
            db.scalars(
                select(AuditLog).where(
                    AuditLog.organization_id == UUID(ids["alpha_org_id"]),
                    AuditLog.action == "RESTORE_APPROVED_CLAIM_FACT",
                )
            )
        )
        assert len(restore_audit) == 1
