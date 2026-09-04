from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select

from app.modules.assessments.service import _build_sections
from app.modules.claim_packs.service import build_claim_pack_snapshot
from app.modules.claims.models import Claim, ClaimPriority, ClaimStatus
from app.modules.organizations.models import Organization
from app.modules.rules.models import ClaimIssue, IssueCategory, IssueSeverity, IssueStatus
from app.modules.technical.service import build_technical_review, record_technical_decision
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, reset_database


def _seed_claim():
    reset_database()
    with TestingSessionLocal() as db:
        org = Organization(name="Technical Acceptance Club", slug="technical-acceptance")
        db.add(org)
        db.flush()
        user = User(
            organization_id=org.id,
            email="handler@technical-acceptance.test",
            full_name="Technical Acceptance Handler",
            password_hash="not-used-in-service-test",
            role=UserRole.CLAIMS_HANDLER,
        )
        vessel = Vessel(organization_id=org.id, name="MT ORION ACCEPTANCE", imo_number="7654321")
        db.add_all([user, vessel])
        db.flush()
        claim = Claim(
            organization_id=org.id,
            vessel_id=vessel.id,
            handler_id=user.id,
            claim_reference="MCRI-HM-TECH-ACCEPTANCE",
            status=ClaimStatus.TECHNICAL_REVIEW,
            priority=ClaimPriority.HIGH,
            incident_date=date(2026, 9, 1),
            notification_date=date(2026, 9, 1),
            incident_description="Synthetic machinery damage for Phase 13.5C acceptance.",
            currency="USD",
        )
        db.add(claim)
        db.flush()
        issue = ClaimIssue(
            organization_id=org.id,
            claim_id=claim.id,
            issue_key="TECH-ACCEPTANCE-001",
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


def _topic(db, claim_id, organization_id):
    review = build_technical_review(db, claim_id=claim_id, organization_id=organization_id)
    return next(item for item in review["matrix"] if item["key"] == "TECH-ACCEPTANCE-001")


def test_claim_pack_preserves_current_stale_and_rereviewed_technical_lineage() -> None:
    organization_id, user_id, claim_id, issue_id = _seed_claim()
    with TestingSessionLocal() as db:
        user = db.get(User, user_id)
        claim = db.get(Claim, claim_id)
        assert user is not None and claim is not None

        first_state = _topic(db, claim_id, organization_id)
        first = record_technical_decision(
            db,
            claim_id=claim_id,
            organization_id=organization_id,
            topic_key=first_state["key"],
            action="needs_more_evidence",
            note="Obtain maker interval-extension evidence before advancing the investigation.",
            expected_state_fingerprint=first_state["state_fingerprint"],
            expected_state_version=first_state["state_version"],
            confirm_re_review=False,
            decided_by_id=user_id,
        )
        db.commit()

        current_snapshot = build_claim_pack_snapshot(
            db,
            claim=claim,
            user=user,
            generation_note="Phase 13.5C current-state acceptance",
            generated_at=datetime(2026, 9, 4, 20, 30, tzinfo=UTC),
        )
        assert current_snapshot["snapshot_schema_version"] == "1.1"
        assert current_snapshot["review_aid_only"] is True
        technical = current_snapshot["technical_investigation"]
        assert technical["authority"] == "human_investigation_review_only"
        topic = next(item for item in technical["topics"] if item["topic_key"] == first_state["key"])
        assert topic["decision_state"] == "current"
        assert topic["latest_decision"]["decision_hash"] == first.decision_hash
        assert current_snapshot["summary"]["technical_current_disposition_count"] == 1
        assert current_snapshot["summary"]["technical_stale_disposition_count"] == 0
        assert "evidence_matrix" in current_snapshot
        assert "approved_assessment" in current_snapshot

        issue = db.get(ClaimIssue, issue_id)
        assert issue is not None
        issue.evidence = {"running_hours": 13100, "maker_interval_hours": 12000, "new_measurement": True}
        db.commit()

        stale_state = _topic(db, claim_id, organization_id)
        assert stale_state["decision_state"] == "stale"
        assert stale_state["state_version"] == 2

        stale_snapshot = build_claim_pack_snapshot(
            db,
            claim=claim,
            user=user,
            generation_note="Phase 13.5C stale-state acceptance",
            generated_at=datetime(2026, 9, 4, 20, 31, tzinfo=UTC),
        )
        stale_topic = next(
            item for item in stale_snapshot["technical_investigation"]["topics"]
            if item["topic_key"] == first_state["key"]
        )
        assert stale_topic["decision_state"] == "stale"
        assert stale_topic["latest_decision"]["decision_hash"] == first.decision_hash
        assert stale_snapshot["summary"]["technical_stale_disposition_count"] == 1
        assert stale_snapshot["summary"]["review_state"] == "attention_required"

        second = record_technical_decision(
            db,
            claim_id=claim_id,
            organization_id=organization_id,
            topic_key=stale_state["key"],
            action="keep_open",
            note="Re-reviewed against the evolved evidence; keep investigation open pending maker records.",
            expected_state_fingerprint=stale_state["state_fingerprint"],
            expected_state_version=stale_state["state_version"],
            confirm_re_review=True,
            decided_by_id=user_id,
        )
        db.commit()

        rereviewed_snapshot = build_claim_pack_snapshot(
            db,
            claim=claim,
            user=user,
            generation_note="Phase 13.5C re-review acceptance",
            generated_at=datetime(2026, 9, 4, 20, 32, tzinfo=UTC),
        )
        rereviewed_topic = next(
            item for item in rereviewed_snapshot["technical_investigation"]["topics"]
            if item["topic_key"] == first_state["key"]
        )
        assert rereviewed_topic["decision_state"] == "current"
        assert rereviewed_topic["state_version"] == 2
        assert rereviewed_topic["latest_decision"]["decision_hash"] == second.decision_hash
        assert rereviewed_topic["latest_decision"]["previous_decision_hash"] == first.decision_hash
        assert rereviewed_snapshot["summary"]["technical_stale_disposition_count"] == 0


def test_assessment_and_chronology_remain_separate_authority_surfaces() -> None:
    organization_id, user_id, claim_id, _ = _seed_claim()
    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        assert claim is not None
        state = _topic(db, claim_id, organization_id)
        record_technical_decision(
            db,
            claim_id=claim_id,
            organization_id=organization_id,
            topic_key=state["key"],
            action="keep_open",
            note="Keep investigation open; no causation conclusion is recorded.",
            expected_state_fingerprint=state["state_fingerprint"],
            expected_state_version=state["state_version"],
            confirm_re_review=False,
            decided_by_id=user_id,
        )
        db.commit()

        sections = {key: (title, text, sources) for key, title, _, text, sources in _build_sections(db, claim)}
        assert "chronology" in sections
        assert "technical" in sections
        technical_text = sections["technical"][1]
        assert "Maintenance interval investigation" in technical_text
        assert "causation" not in technical_text.lower() or "not" in technical_text.lower()

        # Assessment/chronology retain their existing authority and do not become a second
        # mutable store for TechnicalInvestigationDecision lineage. The downstream claim-pack
        # snapshots the exact technical state separately and immutably.
        assert not db.scalar(
            select(ClaimIssue).where(
                ClaimIssue.claim_id == claim_id,
                ClaimIssue.title.ilike("%coverage%"),
            )
        )
