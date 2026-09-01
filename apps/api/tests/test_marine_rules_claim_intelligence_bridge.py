from uuid import UUID

from sqlalchemy import select

from app.modules.rules.models import ClaimIssue, RuleEvaluationRun
from tests.db_harness import TestingSessionLocal, reset_database
from tests.test_claim_intelligence import _add_fact, _build, _set_status
from tests.test_claims_api import create_orion_claim
from app.modules.claims.models import ClaimStatus


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
