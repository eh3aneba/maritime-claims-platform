"""NEW H&M readiness is stage-blocked even with zero active requirements.

This is a database-backed assessment and rules-service regression, not
an insurer's expert judgment or permission to use real claim data.
"""
from datetime import date

from fastapi import HTTPException
from sqlalchemy import select

from app.core.security import hash_password
from app.modules.assessments.models import AssessmentStatus, InitialAssessment
from app.modules.assessments.service import (
    approve_assessment,
    generate_assessment,
    get_assessment,
)
from app.modules.assessments.source_integrity import assessment_source_state
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.organizations.models import Organization
from app.modules.rules.service import (
    NEW_CLAIM_TRIAGE_BLOCKER,
    evaluate_claim_rules,
    get_rule_summary,
)
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, reset_database


def setup_function():
    reset_database()


def _seed_new_claim():
    with TestingSessionLocal() as db:
        org = Organization(name="R5 New Gate", slug="r5-new-gate")
        db.add(org)
        db.flush()
        user = User(
            organization_id=org.id,
            email="manager@synthetic-r5.test",
            full_name="Synthetic Claims Manager",
            password_hash=hash_password("Synthetic-R5-Strong-2026"),
            role=UserRole.CLAIMS_MANAGER,
            is_active=True,
        )
        vessel = Vessel(
            organization_id=org.id,
            name="SYNTHETIC H&M NEW vessel",
            imo_number="7000444",
        )
        db.add_all([user, vessel])
        db.flush()
        claim = Claim(
            organization_id=org.id,
            vessel_id=vessel.id,
            claim_reference="SYNTHETIC-R5-NEW-01",
            incident_date=date(2026, 10, 11),
            notification_date=date(2026, 10, 12),
            incident_description="Synthetic main engine turbocharger stoppage",
            status=ClaimStatus.NEW,
            currency="USD",
        )
        db.add(claim)
        db.flush()
        run = evaluate_claim_rules(db, claim=claim, user=user)
        assert run.summary["readiness_state"] == "not_ready"
        assert run.summary["readiness_score"] <= 10
        return claim.id, user.id


def test_new_claim_cannot_appear_ready_or_auto_generate_final_assessment():
    claim_id, user_id = _seed_new_claim()
    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        user = db.get(User, user_id)
        summary = get_rule_summary(db, claim=claim)
        assert claim.status == ClaimStatus.NEW
        assert len(summary.requirements) == 0
        assert summary.readiness.state == "not_ready"
        assert summary.readiness.score <= 10
        assert NEW_CLAIM_TRIAGE_BLOCKER in summary.readiness.blocking_items

        try:
            generate_assessment(
                db, claim=claim, user=user,
                allow_if_not_ready=False, override_reason=None,
            )
        except HTTPException as error:
            assert error.status_code == 409
            assert NEW_CLAIM_TRIAGE_BLOCKER in error.detail["blocking_items"]
        else:
            raise AssertionError("NEW claim without override generated non-preliminary assessment")
        assert not list(
            db.scalars(select(InitialAssessment).where(InitialAssessment.claim_id == claim_id))
        )

        preliminary = generate_assessment(
            db, claim=claim, user=user,
            allow_if_not_ready=True,
            override_reason="Synthetic only: stage NEW; no mandatory H&M evidence review",
        )
        assert preliminary.is_preliminary is True
        assert preliminary.readiness_state == "not_ready"
        assert preliminary.readiness_score <= 10
        assert NEW_CLAIM_TRIAGE_BLOCKER in preliminary.blocking_items
        assert preliminary.approved_by_id is None
        assert preliminary.status == AssessmentStatus.DRAFT
        assert len(preliminary.source_fingerprint) == 64
        _, sections = get_assessment(db, claim=claim, assessment_id=preliminary.id)
        assert sections

        # Even a manager cannot approve a NEW assessment, regardless of
        # whether section review UI has been visited.
        try:
            approve_assessment(
                db,
                claim=claim,
                assessment=preliminary,
                user=user,
                note="Synthetic attempt before TRIAGE",
                expected_source_fingerprint=preliminary.source_fingerprint,
            )
        except HTTPException as error:
            assert error.status_code == 409
            assert "TRIAGE" in str(error.detail)
        else:
            raise AssertionError("NEW-stage manager approval should be denied")
        db.refresh(preliminary)
        assert preliminary.status == AssessmentStatus.DRAFT
        assert preliminary.approved_by_id is None
        assert preliminary.approved_content_hash is None


def test_transition_to_triage_activates_policy_and_stales_new_source_version():
    claim_id, user_id = _seed_new_claim()
    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        user = db.get(User, user_id)
        old = generate_assessment(
            db,
            claim=claim,
            user=user,
            allow_if_not_ready=True,
            override_reason="Synthetic early preliminary evidence review",
        )
        old_fingerprint = old.source_fingerprint

        claim.status = ClaimStatus.TRIAGE
        db.flush()
        evaluate_claim_rules(db, claim=claim, user=user, trigger="status_change")
        db.refresh(claim)
        summary = get_rule_summary(db, claim=claim)
        assert summary.readiness.state == "not_ready"
        assert NEW_CLAIM_TRIAGE_BLOCKER not in summary.readiness.blocking_items
        assert any(
            requirement.document_type == "policy"
            for requirement in summary.requirements
        )
        assert "H&M Policy / Wording" in summary.readiness.blocking_items
        state, current_hash = assessment_source_state(db, claim=claim, assessment=old)
        assert state == "stale"
        assert current_hash != old_fingerprint

        next_version = generate_assessment(
            db,
            claim=claim,
            user=user,
            allow_if_not_ready=True,
            override_reason="Synthetic TRIAGE with policy requirement outstanding",
        )
        assert next_version.version == old.version + 1
        assert next_version.source_fingerprint != old_fingerprint
        assert next_version.readiness_state == "not_ready"
        assert next_version.is_preliminary is True
        assert next_version.approved_by_id is None
        assert NEW_CLAIM_TRIAGE_BLOCKER not in next_version.blocking_items
        assert "H&M Policy / Wording" in next_version.blocking_items
