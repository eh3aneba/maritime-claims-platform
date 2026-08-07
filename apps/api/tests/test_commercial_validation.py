from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from app.core.security import hash_password
from app.modules.claims.models import Claim
from app.modules.organizations.models import Organization
from app.modules.pilot.models import PilotCommercialValidation
from app.modules.pilot.service import (
    add_feedback,
    build_commercial_scorecard,
    end_session,
    record_event,
    start_session,
    upsert_commercial_validation,
)
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, client, reset_database

PASSWORD = "Commercial-Validation-2026!"


def setup_function():
    reset_database()


def seed():
    with TestingSessionLocal() as db:
        org = Organization(name="Commercial Pilot", slug="commercial-pilot")
        other = Organization(name="Other Commercial", slug="other-commercial")
        db.add_all([org, other]); db.flush()
        user = User(organization_id=org.id, email="handler@commercial.example.com", full_name="Commercial Handler", password_hash=hash_password(PASSWORD), role=UserRole.CLAIMS_HANDLER, is_active=True)
        other_user = User(organization_id=other.id, email="other@commercial.example.com", full_name="Other Handler", password_hash=hash_password(PASSWORD), role=UserRole.CLAIMS_HANDLER, is_active=True)
        db.add_all([user, other_user]); db.flush()
        vessel = Vessel(organization_id=org.id, name="MT ORION", imo_number="7000888")
        other_vessel = Vessel(organization_id=other.id, name="MT OTHER", imo_number="7000887")
        db.add_all([vessel, other_vessel]); db.flush()
        claim = Claim(organization_id=org.id, vessel_id=vessel.id, handler_id=user.id, claim_reference="MCRI-HM-2026-COMM", incident_date=date(2026, 7, 10), notification_date=date(2026, 7, 11), incident_description="Turbocharger failure", currency="USD")
        other_claim = Claim(organization_id=other.id, vessel_id=other_vessel.id, handler_id=other_user.id, claim_reference="MCRI-HM-2026-OTHER-COMM", incident_date=date(2026, 7, 10), notification_date=date(2026, 7, 11), incident_description="Other", currency="USD")
        db.add_all([claim, other_claim]); db.commit()
        for obj in [org, other, user, other_user, claim, other_claim]: db.refresh(obj)
        return {"org": org, "other": other, "user": user, "other_user": other_user, "claim": claim, "other_claim": other_claim}


def login(slug="commercial-pilot", email="handler@commercial.example.com"):
    response = client.post("/api/v1/auth/login", json={"organization_slug": slug, "email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text


def _completed_product_session(db, data):
    user = db.get(User, data["user"].id); claim = db.get(Claim, data["claim"].id)
    session = start_session(db, claim=claim, user=user, participant_role="claims_handler", objective="Commercial validation", baseline_assessment_minutes=120)
    session.started_at = datetime.now(UTC) - timedelta(minutes=60)
    record_event(db, session=session, user_id=user.id, event_type="ai_review_approved", event_data={"count": 8})
    record_event(db, session=session, user_id=user.id, event_type="ai_review_edited", event_data={"count": 1})
    record_event(db, session=session, user_id=user.id, event_type="ai_review_rejected", event_data={"count": 1})
    assessment = record_event(db, session=session, user_id=user.id, event_type="initial_assessment_generated")
    assessment.created_at = session.started_at + timedelta(minutes=60)
    add_feedback(db, session=session, user=user, category="value", severity="low", verdict="correct", rating=9, comment="Would use this for machinery claims.", entity_type=None, entity_id=None)
    end_session(db, session=session, user=user, status="completed", note="Pilot complete")
    return session, user


def test_commercial_roi_and_go_decision_require_real_buying_signals():
    data = seed()
    with TestingSessionLocal() as db:
        session, user = _completed_product_session(db, data)
        row = upsert_commercial_validation(db, session=session, user=user, values={
            "annual_claim_volume": 300,
            "expected_users": 8,
            "fully_loaded_hourly_cost": Decimal("80"),
            "adoption_rate": Decimal("0.50"),
            "currency": "USD",
            "buyer_role": "Head of Marine Claims",
            "champion_role": "Senior H&M Claims Handler",
            "budget_owner_role": "Chief Claims Officer",
            "budget_status": "budget_identified",
            "buying_stage": "business_case",
            "pilot_fee_willingness": Decimal("10000"),
            "annual_wtp_min": Decimal("30000"),
            "annual_wtp_max": Decimal("50000"),
            "preferred_pricing_model": "annual_platform",
            "deployment_preference": "private_cloud",
            "respondent_outcome": "business_case",
            "next_step": "Prepare security review and paid pilot proposal.",
            "blockers": [],
            "value_hypotheses": ["reduce claim review time", "improve auditability"],
            "must_have_features": ["private deployment"],
            "required_integrations": [],
            "security_requirements": ["SSO later"],
            "commercial_notes": "Synthetic validation record.",
        })
        db.commit(); db.refresh(row)
        score = build_commercial_scorecard(db, session=session)
        assert score.roi.minutes_saved_per_claim == 60.0
        assert score.roi.annual_claims_in_scope == 150.0
        assert score.roi.annual_hours_saved == 150.0
        assert score.roi.annual_labor_value == 12000.0
        assert score.roi.annual_wtp_midpoint == 40000.0
        assert score.recommended_validation_decision == "GO"
        assert score.checks["buyer_identified"] is True
        assert score.checks["willingness_to_pay_signal"] is True


def test_stop_requires_explicit_no_interest_and_no_commercial_signal():
    data = seed()
    with TestingSessionLocal() as db:
        session, user = _completed_product_session(db, data)
        upsert_commercial_validation(db, session=session, user=user, values={
            "currency": "USD",
            "budget_status": "no_budget",
            "buying_stage": "no_interest",
            "preferred_pricing_model": "unknown",
            "deployment_preference": "unknown",
            "respondent_outcome": "no_interest",
            "value_hypotheses": [], "must_have_features": [], "required_integrations": [], "security_requirements": [], "blockers": [],
        })
        score = build_commercial_scorecard(db, session=session)
        assert score.recommended_validation_decision == "STOP"


def test_interest_without_wtp_or_next_step_is_pivot_not_go():
    data = seed()
    with TestingSessionLocal() as db:
        session, user = _completed_product_session(db, data)
        upsert_commercial_validation(db, session=session, user=user, values={
            "currency": "USD", "buyer_role": "Claims Manager", "champion_role": "Claims Handler",
            "budget_status": "exploring", "buying_stage": "solution_evaluation", "preferred_pricing_model": "unknown",
            "deployment_preference": "private_cloud", "respondent_outcome": "interested",
            "value_hypotheses": [], "must_have_features": [], "required_integrations": [], "security_requirements": [], "blockers": [],
        })
        score = build_commercial_scorecard(db, session=session)
        assert score.recommended_validation_decision == "PIVOT"
        assert score.checks["willingness_to_pay_signal"] is False


def test_commercial_api_is_tenant_scoped_and_validates_wtp_range():
    data = seed(); login()
    started = client.post("/api/v1/pilot/sessions", json={"claim_id": str(data["claim"].id), "baseline_assessment_minutes": 120})
    assert started.status_code == 200
    session_id = started.json()["id"]
    bad = client.put(f"/api/v1/pilot/sessions/{session_id}/commercial-validation", json={"annual_wtp_min": 50000, "annual_wtp_max": 30000})
    assert bad.status_code == 422
    saved = client.put(f"/api/v1/pilot/sessions/{session_id}/commercial-validation", json={
        "currency": "usd", "buyer_role": "Head of Claims", "champion_role": "H&M Handler", "annual_claim_volume": 250,
        "fully_loaded_hourly_cost": 75, "adoption_rate": 0.5, "budget_status": "exploring", "buying_stage": "pilot",
        "annual_wtp_min": 20000, "annual_wtp_max": 40000, "preferred_pricing_model": "annual_platform",
        "deployment_preference": "private_cloud", "respondent_outcome": "pilot_extension", "next_step": "Run second pilot.",
        "value_hypotheses": ["speed"], "must_have_features": [], "required_integrations": [], "security_requirements": [], "blockers": []
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["currency"] == "USD"
    with TestingSessionLocal() as db:
        assert db.query(PilotCommercialValidation).count() == 1

    client.cookies.clear(); login("other-commercial", "other@commercial.example.com")
    hidden = client.get(f"/api/v1/pilot/sessions/{session_id}/commercial-scorecard")
    assert hidden.status_code == 404
