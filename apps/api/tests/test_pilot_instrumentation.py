from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.core.security import hash_password
from app.modules.claims.models import Claim
from app.modules.organizations.models import Organization
from app.modules.pilot.models import PilotEvent, PilotFeedback, PilotSession
from app.modules.pilot.service import add_feedback, build_scorecard, calculate_metrics, end_session, record_active_event, record_event, start_session
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, client, reset_database

PASSWORD = "Pilot-Instrumentation-2026!"


def setup_function():
    reset_database()


def seed():
    with TestingSessionLocal() as db:
        org = Organization(name="Pilot Marine", slug="pilot-metrics")
        other = Organization(name="Other Marine", slug="other-metrics")
        db.add_all([org, other]); db.flush()
        user = User(organization_id=org.id, email="handler@pilotmetrics.example.com", full_name="Pilot Handler", password_hash=hash_password(PASSWORD), role=UserRole.CLAIMS_HANDLER, is_active=True)
        other_user = User(organization_id=other.id, email="handler@othermetrics.example.com", full_name="Other Handler", password_hash=hash_password(PASSWORD), role=UserRole.CLAIMS_HANDLER, is_active=True)
        db.add_all([user, other_user]); db.flush()
        vessel = Vessel(organization_id=org.id, name="MT ORION", imo_number="7000999")
        other_vessel = Vessel(organization_id=other.id, name="MT OTHER", imo_number="7000998")
        db.add_all([vessel, other_vessel]); db.flush()
        claim = Claim(organization_id=org.id, vessel_id=vessel.id, handler_id=user.id, claim_reference="MCRI-HM-2026-PILOT", incident_date=date(2026,7,10), notification_date=date(2026,7,11), incident_description="Turbocharger failure pilot", currency="USD")
        other_claim = Claim(organization_id=other.id, vessel_id=other_vessel.id, handler_id=other_user.id, claim_reference="MCRI-HM-2026-OTHER", incident_date=date(2026,7,10), notification_date=date(2026,7,11), incident_description="Other tenant claim", currency="USD")
        db.add_all([claim, other_claim]); db.commit()
        for obj in [org, other, user, other_user, vessel, other_vessel, claim, other_claim]: db.refresh(obj)
        return {"org": org, "other": other, "user": user, "other_user": other_user, "claim": claim, "other_claim": other_claim}


def login(slug="pilot-metrics", email="handler@pilotmetrics.example.com"):
    response = client.post("/api/v1/auth/login", json={"organization_slug": slug, "email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text


def test_start_session_is_idempotent_for_same_user_and_claim():
    data = seed()
    with TestingSessionLocal() as db:
        claim=db.get(Claim,data["claim"].id); user=db.get(User,data["user"].id)
        first=start_session(db, claim=claim, user=user, participant_role="claims_handler", objective="Assess usability", baseline_assessment_minutes=120)
        db.flush()
        second=start_session(db, claim=claim, user=user, participant_role="claims_handler", objective="Ignored duplicate", baseline_assessment_minutes=90)
        assert first.id == second.id
        assert len(list(db.scalars(select(PilotSession)))) == 1


def test_metrics_calculate_ai_rates_time_reduction_and_feedback_accuracy():
    data=seed()
    with TestingSessionLocal() as db:
        claim=db.get(Claim,data["claim"].id); user=db.get(User,data["user"].id)
        session=start_session(db, claim=claim, user=user, participant_role="claims_handler", objective=None, baseline_assessment_minutes=120)
        session.started_at=datetime.now(UTC)-timedelta(minutes=60)
        record_event(db,session=session,user_id=user.id,event_type="ai_review_approved",event_data={"count":8})
        record_event(db,session=session,user_id=user.id,event_type="ai_review_edited",event_data={"count":1})
        record_event(db,session=session,user_id=user.id,event_type="ai_review_rejected",event_data={"count":1})
        assessment_event=record_event(db,session=session,user_id=user.id,event_type="initial_assessment_generated")
        assessment_event.created_at=session.started_at+timedelta(minutes=60)
        add_feedback(db,session=session,user=user,category="missing_document",severity="low",verdict="true_positive",rating=9,comment="Correctly requested PMS",entity_type="requirement",entity_id=None)
        add_feedback(db,session=session,user=user,category="missing_document",severity="medium",verdict="false_positive",rating=None,comment="Maker manual was already covered by equivalent evidence",entity_type="requirement",entity_id=None)
        metrics=calculate_metrics(db,session=session)
        assert metrics.ai_review_total == 10
        assert metrics.ai_acceptance_rate == 0.8
        assert metrics.ai_edit_rate == 0.1
        assert metrics.ai_reject_rate == 0.1
        assert metrics.time_to_first_assessment_minutes == 60.0
        assert metrics.estimated_time_reduction_percent == 50.0
        assert metrics.missing_document_precision == 0.5
        assert metrics.average_rating == 9.0


def test_scorecard_prioritizes_false_positive_feedback_into_backlog():
    data=seed()
    with TestingSessionLocal() as db:
        claim=db.get(Claim,data["claim"].id); user=db.get(User,data["user"].id)
        session=start_session(db, claim=claim, user=user, participant_role="claims_handler", objective=None, baseline_assessment_minutes=None)
        add_feedback(db,session=session,user=user,category="rules",severity="high",verdict="false_positive",rating=8,comment="Technical issue triggered without enough evidence",entity_type="claim_issue",entity_id=None)
        add_feedback(db,session=session,user=user,category="usability",severity="low",verdict=None,rating=9,comment="Navigation was easy",entity_type=None,entity_id=None)
        end_session(db,session=session,user=user,status="completed",note=None)
        scorecard=build_scorecard(db,session=session)
        assert scorecard.backlog[0].priority == "P1"
        assert scorecard.backlog[0].category == "rules"
        assert scorecard.metrics.feedback_count == 2


def test_record_active_event_is_noop_without_active_session_then_records_when_started():
    data=seed()
    with TestingSessionLocal() as db:
        claim=db.get(Claim,data["claim"].id); user=db.get(User,data["user"].id)
        assert record_active_event(db,organization_id=user.organization_id,claim_id=claim.id,user_id=user.id,event_type="ai_review_approved") is None
        session=start_session(db,claim=claim,user=user,participant_role="claims_handler",objective=None,baseline_assessment_minutes=None)
        event=record_active_event(db,organization_id=user.organization_id,claim_id=claim.id,user_id=user.id,event_type="ai_review_approved",event_data={"count":3})
        assert event is not None and event.session_id == session.id


def test_pilot_api_is_tenant_scoped_and_accepts_feedback():
    data=seed(); login()
    response=client.post("/api/v1/pilot/sessions",json={"claim_id":str(data["claim"].id),"participant_role":"claims_handler","baseline_assessment_minutes":90})
    assert response.status_code == 200, response.text
    session_id=response.json()["id"]
    feedback=client.post(f"/api/v1/pilot/sessions/{session_id}/feedback",json={"category":"value","severity":"low","rating":9,"comment":"Would use this for machinery claims."})
    assert feedback.status_code == 201
    metrics=client.get(f"/api/v1/pilot/sessions/{session_id}/metrics")
    assert metrics.status_code == 200 and metrics.json()["average_rating"] == 9.0

    client.cookies.clear(); login("other-metrics","handler@othermetrics.example.com")
    hidden=client.get(f"/api/v1/pilot/sessions/{session_id}/metrics")
    assert hidden.status_code == 404


def test_end_session_prevents_second_close():
    data=seed()
    with TestingSessionLocal() as db:
        claim=db.get(Claim,data["claim"].id); user=db.get(User,data["user"].id)
        session=start_session(db,claim=claim,user=user,participant_role="claims_handler",objective=None,baseline_assessment_minutes=None)
        end_session(db,session=session,user=user,status="completed",note="Finished")
        assert session.status == "completed" and session.ended_at is not None
        try:
            end_session(db,session=session,user=user,status="completed",note=None)
            assert False, "Expected a closed-session error"
        except ValueError:
            pass


def test_ai_review_endpoint_records_server_telemetry_for_active_pilot():
    from decimal import Decimal
    from app.modules.documents.models import Document, ConfidentialityLevel, DocumentProcessingStatus
    from app.modules.intelligence.models import AIRun, AIRunStatus, AISemanticKind, DocumentExtraction

    data=seed()
    with TestingSessionLocal() as db:
        claim=db.get(Claim,data["claim"].id); user=db.get(User,data["user"].id)
        session=start_session(db,claim=claim,user=user,participant_role="claims_handler",objective=None,baseline_assessment_minutes=None)
        document=Document(organization_id=user.organization_id,claim_id=claim.id,uploaded_by_id=user.id,filename="ce.docx",original_filename="ce.docx",document_type="chief_engineer_report",mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",file_size_bytes=100,file_hash="a"*64,storage_key="pilot/ce.docx",processing_status=DocumentProcessingStatus.PROCESSED,confidentiality_level=ConfidentialityLevel.INTERNAL)
        db.add(document);db.flush()
        run=AIRun(organization_id=user.organization_id,claim_id=claim.id,document_id=document.id,requested_by_id=user.id,task="ce_report",status=AIRunStatus.COMPLETED,provider="fake",model="fake",prompt_name="ce",prompt_version="2.0",schema_name="ce",schema_version="2.0",input_text_hash="b"*64,input_char_count=100)
        db.add(run);db.flush()
        extraction=DocumentExtraction(organization_id=user.organization_id,claim_id=claim.id,document_id=document.id,ai_run_id=run.id,field_path="equipment.maker",semantic_kind=AISemanticKind.FACT,raw_value="ABB",normalized_value="ABB",confidence=Decimal("0.950"),source_verified=True)
        db.add(extraction);db.commit(); extraction_id=extraction.id; session_id=session.id

    login()
    response=client.post(f"/api/v1/ai-review/{extraction_id}",json={"action":"approve"})
    assert response.status_code == 200, response.text
    metrics=client.get(f"/api/v1/pilot/sessions/{session_id}/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["ai_review_total"] == 1
    assert metrics.json()["ai_approved"] == 1
