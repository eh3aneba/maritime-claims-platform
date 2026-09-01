from uuid import UUID

from sqlalchemy import select

from app.modules.claim_intelligence.service import build_claim_intelligence, snapshot_response
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.documents.models import Document
from app.modules.financial.service import build_financial_review
from app.modules.intelligence.service import run_invoice_intelligence
from app.modules.rules.models import ClaimIssue, RuleEvaluationRun
from app.modules.users.models import User
from tests.db_harness import TestingSessionLocal, reset_database
from tests.test_claim_intelligence import _add_fact, _build, _set_status
from tests.test_claims_api import create_orion_claim
from tests.test_financial_intelligence import FP, approve_all, sb, seed, ss


def setup_function() -> None:
    reset_database()


def test_claim_intelligence_consumes_structured_marine_rule_issue() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)
    _add_fact(claim_id, "repair.replacement", True)

    snapshot = _build(claim_id)

    marine_item = next(
        item
        for item in snapshot["items"]
        if any(ref["kind"] == "rule" and ref["id"] == "HM-REPAIR-001" for ref in item["source_refs"])
    )
    assert marine_item["category"] == "issue_flag"
    assert "replacement" in marine_item["description"].lower()
    assert "recoverability decision" in marine_item["rationale"].lower()

    with TestingSessionLocal() as db:
        issue = db.scalar(
            select(ClaimIssue).where(
                ClaimIssue.claim_id == UUID(claim_id),
                ClaimIssue.issue_key == "marine_hm_repair_001",
                ClaimIssue.is_active.is_(True),
            )
        )
        assert issue is not None
        assert issue.rule_version == "1.0.0"
        assert issue.evidence["marine_rule_status"] == "insufficient_evidence"
        assert len(issue.evidence["definition_hash"]) == 64
        assert len(issue.evidence["evaluation_hash"]) == 64
        assert issue.evidence["missing_prerequisites"]

        run = db.scalar(
            select(RuleEvaluationRun).where(
                RuleEvaluationRun.claim_id == UUID(claim_id),
                RuleEvaluationRun.trigger == "claims_intelligence",
            ).order_by(RuleEvaluationRun.created_at.desc())
        )
        assert run is not None
        assert run.summary["marine_registry_version"] == "12B.2.0"
        assert run.summary["active_marine_issue_count"] >= 1


def test_non_applicable_marine_issue_is_not_materialized_into_intelligence() -> None:
    result = create_orion_claim()
    claim_id = result["claim"]["id"]
    _set_status(claim_id, ClaimStatus.INVESTIGATION)

    snapshot = _build(claim_id)

    assert not any(
        any(ref["kind"] == "rule" and ref["id"] == "HM-REPAIR-001" for ref in item["source_refs"])
        for item in snapshot["items"]
    )
    with TestingSessionLocal() as db:
        issue = db.scalar(
            select(ClaimIssue).where(
                ClaimIssue.claim_id == UUID(claim_id),
                ClaimIssue.issue_key == "marine_hm_repair_001",
                ClaimIssue.is_active.is_(True),
            )
        )
        assert issue is None


def test_claim_intelligence_uses_structured_d2_issue_not_legacy_keyword_cost_lead() -> None:
    text = "ABC Invoice INV-BUNKER dated 2026-07-12 USD. Bunker fuel consumed during STS standby 12000 USD. Total 12000 USD."
    claim_id, document_id, user_id = seed("invoice", text, "d")
    payload = {
        "classification": {"document_type": "invoice", "confidence": 0.99},
        "supplier": ss("ABC", "ABC"),
        "invoice_number": ss("INV-BUNKER", "INV-BUNKER"),
        "invoice_date": ss("2026-07-12", "2026-07-12"),
        "purchase_order": ss(None, None, 0),
        "related_quotation_number": ss(None, None, 0),
        "currency": ss("USD", "USD"),
        "subtotal": ss("12000", "12000"),
        "tax": ss(None, None, 0),
        "discount": ss(None, None, 0),
        "total": ss("12000", "Total 12000 USD"),
        "payment_terms": ss(None, None, 0),
        "line_items": [{
            "description": ss("Bunker fuel consumed during STS standby", "Bunker fuel consumed during STS standby"),
            "quantity": ss("1", "12000 USD"),
            "unit": ss(None, None, 0),
            "unit_price": ss("12000", "12000 USD"),
            "amount": ss("12000", "12000 USD"),
            "category_candidate": ss("Bunkers", "Bunker fuel"),
            "potential_betterment_cue": sb(False, "Bunker fuel"),
            "potential_ordinary_maintenance_cue": sb(False, "Bunker fuel"),
        }],
    }

    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        claim = db.get(Claim, claim_id)
        document = db.get(Document, document_id)
        assert user is not None and claim is not None and document is not None
        run = run_invoice_intelligence(db, document=document, requested_by_id=user_id, provider=FP(payload))
        approve_all(db, run, user)
        build_financial_review(db, claim=claim, user_id=user_id)
        db.commit()
        snapshot = build_claim_intelligence(db, claim=claim, user=user)
        rendered = snapshot_response(db, snapshot)

    assert not any(item["item_key"].startswith("cost-aaa-d") for item in rendered["items"])
    d2_item = next(
        item
        for item in rendered["items"]
        if any(ref["kind"] == "rule" and ref["id"] == "AAA-D2" for ref in item["source_refs"])
    )
    assert d2_item["category"] == "issue_flag"
    assert "insufficient" in d2_item["description"].lower() or "fuel" in d2_item["title"].lower()
    assert any(ref["kind"] == "claim_issue" for ref in d2_item["source_refs"])
