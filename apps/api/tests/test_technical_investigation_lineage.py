from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select

from app.modules.claims.models import Claim, ClaimPriority, ClaimStatus
from app.modules.organizations.models import Organization
from app.modules.rules.models import ClaimIssue, IssueCategory, IssueSeverity, IssueStatus
from app.modules.technical.models import TechnicalInvestigationDecision
from app.modules.technical.service import (
    TechnicalDecisionConflictError,
    TechnicalTopicNotFoundError,
    build_technical_review,
    record_technical_decision,
    technical_decision_history,
)
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, reset_database


def _seed_claim():
    reset_database()
    with TestingSessionLocal() as db:
        org = Organization(name="Technical Test Club", slug="technical-test")
        db.add(org)
        db.flush()
        user = User(
            organization_id=org.id,
            email="handler@technical.test",
            full_name="Technical Handler",
            password_hash="not-used-in-service-test",
            role=UserRole.CLAIMS_HANDLER,
        )
        vessel = Vessel(organization_id=org.id, name="MT LINEAGE", imo_number="1234567")
        db.add_all([user, vessel])
        db.flush()
        claim = Claim(
            organization_id=org.id,
            vessel_id=vessel.id,
            handler_id=user.id,
            claim_reference="MCRI-HM-TECH-LINEAGE",
            status=ClaimStatus.TECHNICAL_REVIEW,
            priority=ClaimPriority.HIGH,
            incident_date=date(2026, 9, 1),
            notification_date=date(2026, 9, 1),
            incident_description="Synthetic machinery damage for technical lineage acceptance.",
            currency="USD",
        )
        db.add(claim)
        db.flush()
        issue = ClaimIssue(
            organization_id=org.id,
            claim_id=claim.id,
            issue_key="TECH-LINEAGE-001",
            rule_id="TECH-001",
            rule_version="1.0",
            category=IssueCategory.TECHNICAL,
            title="Maintenance interval investigation",
            description="Review whether running hours exceeded the applicable interval.",
            severity=IssueSeverity.HIGH,
            status=IssueStatus.UNDER_REVIEW,
            evidence={"running_hours": 12600, "maker_interval_hours": 12000},
            explanation="Running hours appear above the recorded maker interval; extension evidence must be checked.",
            is_active=True,
        )
        db.add(issue)
        db.commit()
        return org.id, user.id, claim.id, issue.id


def test_technical_decision_lineage_stale_re_review_and_idempotency() -> None:
    organization_id, user_id, claim_id, issue_id = _seed_claim()
    with TestingSessionLocal() as db:
        review = build_technical_review(db, claim_id=claim_id, organization_id=organization_id)
        row = next(item for item in review["matrix"] if item["key"] == "TECH-LINEAGE-001")
        assert row["decision_state"] == "none"
        assert row["state_version"] == 1
        first_fingerprint = row["state_fingerprint"]

        kwargs = dict(
            claim_id=claim_id,
            organization_id=organization_id,
            topic_key=row["key"],
            action="needs_more_evidence",
            note="Obtain maker interval-extension evidence before advancing the technical investigation.",
            expected_state_fingerprint=first_fingerprint,
            expected_state_version=1,
            confirm_re_review=False,
            decided_by_id=user_id,
        )
        first = record_technical_decision(db, **kwargs)
        db.commit()
        first_id, first_hash = first.id, first.decision_hash

        replay = record_technical_decision(db, **kwargs)
        db.commit()
        assert replay.id == first_id
        assert db.scalar(select(func.count()).select_from(TechnicalInvestigationDecision)) == 1

        current = build_technical_review(db, claim_id=claim_id, organization_id=organization_id)
        current_row = next(item for item in current["matrix"] if item["key"] == row["key"])
        assert current_row["decision_state"] == "current"
        assert current_row["latest_decision"]["decision_hash"] == first_hash

        issue = db.get(ClaimIssue, issue_id)
        assert issue is not None
        issue.evidence = {"running_hours": 13100, "maker_interval_hours": 12000, "new_measurement": True}
        db.commit()

        evolved = build_technical_review(db, claim_id=claim_id, organization_id=organization_id)
        evolved_row = next(item for item in evolved["matrix"] if item["key"] == row["key"])
        assert evolved_row["decision_state"] == "stale"
        assert evolved_row["state_version"] == 2
        assert evolved_row["state_fingerprint"] != first_fingerprint

        with pytest.raises(TechnicalDecisionConflictError, match="evidence changed"):
            record_technical_decision(
                db,
                claim_id=claim_id,
                organization_id=organization_id,
                topic_key=row["key"],
                action="supported_for_investigation",
                note="The updated running-hours evidence remains relevant for technical investigation.",
                expected_state_fingerprint=first_fingerprint,
                expected_state_version=1,
                confirm_re_review=True,
                decided_by_id=user_id,
            )
        db.rollback()

        with pytest.raises(TechnicalDecisionConflictError, match="Explicit re-review"):
            record_technical_decision(
                db,
                claim_id=claim_id,
                organization_id=organization_id,
                topic_key=row["key"],
                action="supported_for_investigation",
                note="The updated running-hours evidence remains relevant for technical investigation.",
                expected_state_fingerprint=evolved_row["state_fingerprint"],
                expected_state_version=2,
                confirm_re_review=False,
                decided_by_id=user_id,
            )
        db.rollback()

        second = record_technical_decision(
            db,
            claim_id=claim_id,
            organization_id=organization_id,
            topic_key=row["key"],
            action="supported_for_investigation",
            note="The updated running-hours evidence remains relevant for technical investigation.",
            expected_state_fingerprint=evolved_row["state_fingerprint"],
            expected_state_version=2,
            confirm_re_review=True,
            decided_by_id=user_id,
        )
        db.commit()
        assert second.decision_number == 2
        assert second.previous_decision_hash == first_hash

        history = technical_decision_history(
            db,
            claim_id=claim_id,
            organization_id=organization_id,
            topic_key=row["key"],
        )
        assert history["decision_state"] == "current"
        assert history["current_state_version"] == 2
        assert len(history["items"]) == 2
        assert history["items"][1]["previous_decision_hash"] == history["items"][0]["decision_hash"]


def test_technical_topic_history_is_tenant_scoped() -> None:
    _, _, claim_id, _ = _seed_claim()
    with TestingSessionLocal() as db:
        other_org = Organization(name="Other Club", slug="other-club")
        db.add(other_org)
        db.commit()
        with pytest.raises(TechnicalTopicNotFoundError):
            technical_decision_history(
                db,
                claim_id=claim_id,
                organization_id=other_org.id,
                topic_key="TECH-LINEAGE-001",
            )
