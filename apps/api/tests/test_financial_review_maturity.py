from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.modules.claims.models import Claim
from app.modules.documents.models import (
    Document,
    DocumentMalwareScanStatus,
    DocumentProcessingStatus,
)
from app.modules.financial.models import CostReviewDecision, CostReviewStatus
from app.modules.financial.service import (
    CostReviewConflictError,
    build_financial_review,
    record_cost_review_decision,
)
from app.modules.intelligence.models import DocumentExtraction
from app.modules.intelligence.service import run_invoice_intelligence
from app.modules.organizations.models import Organization
from app.modules.review.service import review_extraction
from app.modules.users.models import User
from tests.db_harness import TestingSessionLocal, reset_database
from tests.test_financial_intelligence import FP, PASSWORD, approve_all, sb, seed, ss


def setup_function():
    reset_database()


def _invoice_payload(amount: str = "240,000 USD"):
    return {
        "classification": {"document_type": "invoice", "confidence": .99},
        "supplier": ss("ABC", "ABC"),
        "invoice_number": ss("INV-1", "INV-1"),
        "invoice_date": ss("2026-07-12", "2026-07-12"),
        "purchase_order": ss(None, None, 0),
        "related_quotation_number": ss(None, None, 0),
        "currency": ss("USD", "USD"),
        "subtotal": ss(amount, amount),
        "tax": ss(None, None, 0),
        "discount": ss(None, None, 0),
        "total": ss(amount, amount),
        "payment_terms": ss(None, None, 0),
        "line_items": [
            {
                "description": ss("Rotor assembly", "Rotor assembly"),
                "quantity": ss("1", "Rotor assembly"),
                "unit": ss(None, None, 0),
                "unit_price": ss(amount, amount),
                "amount": ss(amount, amount),
                "category_candidate": ss("Spare Parts", "Rotor assembly"),
                "potential_betterment_cue": sb(False, "Rotor assembly"),
                "potential_ordinary_maintenance_cue": sb(False, "Rotor assembly"),
            }
        ],
    }


def _seed_reviewed_invoice():
    claim_id, document_id, user_id = seed(
        "invoice",
        "ABC Invoice INV-1 dated 2026-07-12 USD. Rotor assembly 240,000 USD. Total 240,000 USD.",
        "f",
    )
    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        run = run_invoice_intelligence(
            db,
            document=db.get(Document, document_id),
            requested_by_id=user_id,
            provider=FP(_invoice_payload()),
        )
        approve_all(db, run, user)
        db.commit()
        return claim_id, document_id, user_id, run.id


def _review(db, claim_id, user_id):
    return build_financial_review(
        db,
        claim=db.get(Claim, claim_id),
        user_id=user_id,
    )


def test_financial_review_only_admits_current_usable_sources():
    claim_id, document_id, user_id, _ = _seed_reviewed_invoice()

    with TestingSessionLocal() as db:
        baseline = _review(db, claim_id, user_id)
        assert len(baseline["items"]) == 1
        evidence = baseline["items"][0]
        assert evidence["document_version"] == 1
        assert evidence["document_is_current"] is True
        assert evidence["document_processing_status"] == "processed"
        assert evidence["document_malware_scan_status"] == "legacy_unscanned"
        assert evidence["source_state"] == "current_usable"

        document = db.get(Document, document_id)
        document.processing_status = DocumentProcessingStatus.FAILED
        db.commit()
        assert _review(db, claim_id, user_id)["items"] == []

        document.processing_status = DocumentProcessingStatus.PROCESSED
        document.malware_scan_status = DocumentMalwareScanStatus.INFECTED_QUARANTINED
        db.commit()
        assert _review(db, claim_id, user_id)["items"] == []

        document.malware_scan_status = DocumentMalwareScanStatus.SCAN_ERROR
        db.commit()
        assert _review(db, claim_id, user_id)["items"] == []

        document.malware_scan_status = DocumentMalwareScanStatus.LEGACY_UNSCANNED
        document.is_current = False
        db.commit()
        assert _review(db, claim_id, user_id)["items"] == []

        document.is_current = True
        document.deleted_at = datetime.now(UTC)
        db.commit()
        assert _review(db, claim_id, user_id)["items"] == []


def test_cost_review_lineage_becomes_stale_on_human_evidence_edit_and_rereviews_explicitly():
    claim_id, _, user_id, run_id = _seed_reviewed_invoice()

    with TestingSessionLocal() as db:
        first_review = _review(db, claim_id, user_id)
        item = first_review["items"][0]
        first = record_cost_review_decision(
            db,
            claim_id=claim_id,
            organization_id=db.get(Claim, claim_id).organization_id,
            item_id=item["id"],
            status=CostReviewStatus.ACCEPTED,
            reason="Reviewed invoice evidence supports this operational cost status.",
            expected_state_fingerprint=item["state_fingerprint"],
            expected_state_version=item["state_version"],
            confirm_re_review=False,
            user_id=user_id,
        )
        db.commit()

        replay = record_cost_review_decision(
            db,
            claim_id=claim_id,
            organization_id=db.get(Claim, claim_id).organization_id,
            item_id=item["id"],
            status=CostReviewStatus.ACCEPTED,
            reason="Reviewed invoice evidence supports this operational cost status.",
            expected_state_fingerprint=item["state_fingerprint"],
            expected_state_version=item["state_version"],
            confirm_re_review=False,
            user_id=user_id,
        )
        assert replay.id == first.id

        amount_extraction = db.scalar(
            select(DocumentExtraction).where(
                DocumentExtraction.ai_run_id == run_id,
                DocumentExtraction.field_path == "invoice.line_items[0].amount",
            )
        )
        review_extraction(
            db,
            extraction=amount_extraction,
            reviewer=db.get(User, user_id),
            action="edit",
            value={"value": 250000.0, "currency": "USD", "raw": "250,000 USD"},
            reason="Workshop invoice amount corrected after source review.",
            confirm_re_review=True,
        )
        db.commit()

        evolved = _review(db, claim_id, user_id)
        current = evolved["items"][0]
        assert current["item_key"] == item["item_key"]
        assert current["state_fingerprint"] != item["state_fingerprint"]
        assert current["state_version"] == 2
        assert current["decision_state"] == "stale"
        assert current["review_status"] == CostReviewStatus.UNDER_REVIEW
        assert current["latest_review_decision"]["decision_hash"] == first.decision_hash

        with pytest.raises(CostReviewConflictError, match="Financial evidence changed"):
            record_cost_review_decision(
                db,
                claim_id=claim_id,
                organization_id=db.get(Claim, claim_id).organization_id,
                item_id=current["id"],
                status=CostReviewStatus.ACCEPTED,
                reason="Stale browser write must not be accepted.",
                expected_state_fingerprint=item["state_fingerprint"],
                expected_state_version=item["state_version"],
                confirm_re_review=True,
                user_id=user_id,
            )

        with pytest.raises(CostReviewConflictError, match="Explicit re-review"):
            record_cost_review_decision(
                db,
                claim_id=claim_id,
                organization_id=db.get(Claim, claim_id).organization_id,
                item_id=current["id"],
                status=CostReviewStatus.UNDER_REVIEW,
                reason="Current evidence needs deliberate re-review.",
                expected_state_fingerprint=current["state_fingerprint"],
                expected_state_version=current["state_version"],
                confirm_re_review=False,
                user_id=user_id,
            )

        second = record_cost_review_decision(
            db,
            claim_id=claim_id,
            organization_id=db.get(Claim, claim_id).organization_id,
            item_id=current["id"],
            status=CostReviewStatus.UNDER_REVIEW,
            reason="Corrected amount reviewed; keep cost item under review.",
            expected_state_fingerprint=current["state_fingerprint"],
            expected_state_version=current["state_version"],
            confirm_re_review=True,
            user_id=user_id,
        )
        db.commit()
        assert second.decision_number == 2
        assert second.previous_decision_hash == first.decision_hash
        assert second.decision_hash != first.decision_hash

        after = _review(db, claim_id, user_id)
        latest = after["items"][0]
        assert latest["decision_state"] == "current"
        assert latest["review_status"] == CostReviewStatus.UNDER_REVIEW
        assert len(latest["review_history"]) == 2


def test_source_becoming_unusable_preserves_historical_human_cost_lineage():
    claim_id, document_id, user_id, _ = _seed_reviewed_invoice()

    with TestingSessionLocal() as db:
        review = _review(db, claim_id, user_id)
        item = review["items"][0]
        decision = record_cost_review_decision(
            db,
            claim_id=claim_id,
            organization_id=db.get(Claim, claim_id).organization_id,
            item_id=item["id"],
            status=CostReviewStatus.POTENTIALLY_RECOVERABLE,
            reason="Human operational review only; no coverage or recoverability determination.",
            expected_state_fingerprint=item["state_fingerprint"],
            expected_state_version=item["state_version"],
            confirm_re_review=False,
            user_id=user_id,
        )
        db.commit()

        document = db.get(Document, document_id)
        document.processing_status = DocumentProcessingStatus.FAILED
        db.commit()

        unavailable = _review(db, claim_id, user_id)
        assert unavailable["items"] == []
        assert len(unavailable["historical_reviews"]) == 1
        historical = unavailable["historical_reviews"][0]
        assert historical["item_key"] == item["item_key"]
        assert historical["decision_state"] == "stale"
        assert historical["current_source_available"] is False
        assert historical["latest_review_decision"]["decision_hash"] == decision.decision_hash
        assert db.scalar(select(CostReviewDecision).where(CostReviewDecision.id == decision.id)) is not None


def test_cost_review_decision_is_tenant_scoped():
    claim_id, _, user_id, _ = _seed_reviewed_invoice()

    with TestingSessionLocal() as db:
        review = _review(db, claim_id, user_id)
        item = review["items"][0]
        other_org = Organization(name="Beta", slug="beta")
        db.add(other_org)
        db.flush()

        with pytest.raises(CostReviewConflictError, match="Claim is no longer available"):
            record_cost_review_decision(
                db,
                claim_id=claim_id,
                organization_id=other_org.id,
                item_id=item["id"],
                status=CostReviewStatus.UNDER_REVIEW,
                reason="Cross-tenant write must fail.",
                expected_state_fingerprint=item["state_fingerprint"],
                expected_state_version=item["state_version"],
                confirm_re_review=False,
                user_id=user_id,
            )
