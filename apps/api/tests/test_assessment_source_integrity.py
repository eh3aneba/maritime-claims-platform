from datetime import date

from fastapi import HTTPException
from sqlalchemy import select

from app.core.security import hash_password
from app.modules.assessments.models import AssessmentSection, AssessmentStatus
from app.modules.assessments.service import approve_assessment, generate_assessment, get_assessment, review_section
from app.modules.assessments.source_integrity import assessment_source_state
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.organizations.models import Organization
from app.modules.rules.service import evaluate_claim_rules
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, reset_database


def setup_function():
    reset_database()


def _seed() -> tuple[object, object]:
    with TestingSessionLocal() as db:
        organization = Organization(name="Assessment Integrity", slug="assessment-integrity")
        db.add(organization)
        db.flush()
        user = User(
            organization_id=organization.id,
            email="manager@assessment.test",
            full_name="Claims Manager",
            password_hash=hash_password("Strong-Assessment-Integrity-2026"),
            role=UserRole.CLAIMS_MANAGER,
            is_active=True,
        )
        vessel = Vessel(organization_id=organization.id, name="MT ORION", imo_number="7000399")
        db.add_all([user, vessel])
        db.flush()
        claim = Claim(
            organization_id=organization.id,
            vessel_id=vessel.id,
            claim_reference="MCRI-HM-2026-ASSESSMENT-INTEGRITY",
            incident_date=date(2026, 7, 10),
            notification_date=date(2026, 7, 11),
            incident_description="Main engine turbocharger failure",
            status=ClaimStatus.INVESTIGATION,
            currency="USD",
        )
        db.add(claim)
        db.flush()
        evaluate_claim_rules(db, claim=claim, user=user)
        return claim.id, user.id


def test_source_evolution_blocks_stale_review_and_deliberate_new_version_can_be_approved():
    claim_id, user_id = _seed()
    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        user = db.get(User, user_id)
        first = generate_assessment(
            db,
            claim=claim,
            user=user,
            allow_if_not_ready=True,
            override_reason="Preliminary source-bound assessment",
        )
        assert first.source_snapshot
        assert first.source_snapshot["schema"] == "assessment-source-v1"
        assert first.source_fingerprint and len(first.source_fingerprint) == 64
        assert first.approved_content_hash is None
        state, current = assessment_source_state(db, claim=claim, assessment=first)
        assert state == "current"
        assert current == first.source_fingerprint

        _, first_sections = get_assessment(db, claim=claim, assessment_id=first.id)
        claim.incident_description = "Main engine turbocharger failure; later human evidence update recorded"
        db.flush()

        state, current = assessment_source_state(db, claim=claim, assessment=first)
        assert state == "stale"
        assert current != first.source_fingerprint

        try:
            review_section(
                db,
                claim=claim,
                section=first_sections[0],
                user=user,
                action="approve",
                text=None,
                expected_source_fingerprint=first.source_fingerprint,
            )
        except HTTPException as exc:
            assert exc.status_code == 409
            assert "stale" in str(exc.detail).lower()
        else:
            raise AssertionError("stale assessment review should fail closed")

        second = generate_assessment(
            db,
            claim=claim,
            user=user,
            allow_if_not_ready=True,
            override_reason="Deliberate new version after source evolution",
        )
        assert second.version == 2
        assert second.source_fingerprint != first.source_fingerprint
        state, current = assessment_source_state(db, claim=claim, assessment=second)
        assert state == "current"
        assert current == second.source_fingerprint

        second, second_sections = get_assessment(db, claim=claim, assessment_id=second.id)
        for section in second_sections:
            review_section(
                db,
                claim=claim,
                section=section,
                user=user,
                action="approve",
                text=None,
                expected_source_fingerprint=second.source_fingerprint,
            )
        approve_assessment(
            db,
            claim=claim,
            assessment=second,
            user=user,
            note="Human reviewed source-bound version",
            expected_source_fingerprint=second.source_fingerprint,
        )
        assert second.status == AssessmentStatus.APPROVED
        assert second.approved_content_hash and len(second.approved_content_hash) == 64
        approved_hash = second.approved_content_hash

        claim.incident_description = "Further evidence received after approval"
        db.flush()
        state, _ = assessment_source_state(db, claim=claim, assessment=second)
        assert state == "stale"
        assert second.approved_content_hash == approved_hash
        assert db.get(Claim, claim_id).id == claim_id


def test_optimistic_source_hash_and_legacy_unbound_rows_fail_closed():
    claim_id, user_id = _seed()
    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        user = db.get(User, user_id)
        assessment = generate_assessment(
            db,
            claim=claim,
            user=user,
            allow_if_not_ready=True,
            override_reason="Preliminary assessment",
        )
        section = db.scalar(
            select(AssessmentSection).where(
                AssessmentSection.assessment_id == assessment.id,
                AssessmentSection.section_key == "incident",
            )
        )

        try:
            review_section(
                db,
                claim=claim,
                section=section,
                user=user,
                action="approve",
                text=None,
                expected_source_fingerprint="0" * 64,
            )
        except HTTPException as exc:
            assert exc.status_code == 409
            assert "session" in str(exc.detail).lower()
        else:
            raise AssertionError("optimistic source fingerprint mismatch should fail closed")

        assessment.source_fingerprint = None
        assessment.source_snapshot = None
        db.commit()
        state, current = assessment_source_state(db, claim=claim, assessment=assessment)
        assert state == "legacy_unbound"
        assert current is None

        try:
            review_section(
                db,
                claim=claim,
                section=section,
                user=user,
                action="approve",
                text=None,
                expected_source_fingerprint=None,
            )
        except HTTPException as exc:
            assert exc.status_code == 409
            assert "predates source-state binding" in str(exc.detail)
        else:
            raise AssertionError("legacy unbound assessment should not accept writes")
