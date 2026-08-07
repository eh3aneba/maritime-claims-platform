from datetime import date
from pathlib import Path

from sqlalchemy import select

from app.ai.gateway.base import AIRequest, AIResponse
from app.core.security import hash_password
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.documents.models import ConfidentialityLevel, Document, DocumentProcessingStatus
from app.modules.intelligence.models import AISemanticKind, AIReviewStatus, DocumentExtraction
from app.modules.intelligence.service import run_pms_history_intelligence, run_running_hours_intelligence, run_workshop_report_intelligence
from app.modules.organizations.models import Organization
from app.modules.processing.models import DocumentTextExtraction, DocumentTextSegment
from app.modules.review.service import review_extraction
from app.modules.rules.service import evaluate_claim_rules
from app.modules.technical.service import build_technical_review
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, reset_database

PASSWORD = "Strong-Maintenance-Test-2026"


def ss(value, quote, confidence=0.97):
    return {"value": value, "confidence": confidence, "source": {"segment_index": 0 if value is not None else None, "quote": quote}}


def sb(value, quote, confidence=0.97):
    return {"value": value, "confidence": confidence, "source": {"segment_index": 0 if value is not None else None, "quote": quote}}


class FakeProvider:
    name = "fake"
    _model = "fake-maintenance-v1"

    def __init__(self, payload): self.payload = payload
    def generate(self, request: AIRequest) -> AIResponse:
        return AIResponse(provider=self.name, model=self._model, structured_output=self.payload, output_text="{}", usage={}, raw_response_id="resp-maint-1")


def setup_function(): reset_database()


def seed_claim_and_document(doc_type: str, text: str):
    with TestingSessionLocal() as db:
        org = Organization(name="Alpha Marine", slug="alpha")
        db.add(org); db.flush()
        user = User(organization_id=org.id, email="handler@example.com", full_name="Handler", password_hash=hash_password(PASSWORD), role=UserRole.CLAIMS_HANDLER, is_active=True)
        vessel = Vessel(organization_id=org.id, name="MT ORION", imo_number="7000301")
        db.add_all([user, vessel]); db.flush()
        claim = Claim(organization_id=org.id, vessel_id=vessel.id, claim_reference="MCRI-HM-2026-0001", incident_date=date(2026,7,10), notification_date=date(2026,7,11), incident_description="Main engine turbocharger failure", currency="USD", status=ClaimStatus.INVESTIGATION)
        db.add(claim); db.flush()
        document = Document(organization_id=org.id, claim_id=claim.id, uploaded_by_id=user.id, filename=f"{doc_type}.pdf", original_filename=f"{doc_type}.pdf", document_type=doc_type, mime_type="application/pdf", file_size_bytes=100, file_hash=(doc_type[0] * 64), storage_key=f"x/{doc_type}.pdf", processing_status=DocumentProcessingStatus.PROCESSED, confidentiality_level=ConfidentialityLevel.CONFIDENTIAL)
        db.add(document); db.flush()
        extraction = DocumentTextExtraction(organization_id=org.id, document_id=document.id, extraction_method="test", extractor_version="1", char_count=len(text), segment_count=1, requires_ocr=False, text_hash="a"*64)
        db.add(extraction); db.flush()
        segment = DocumentTextSegment(organization_id=org.id, document_id=document.id, extraction_id=extraction.id, segment_index=0, locator_type="page", locator_value="1", text=text, char_count=len(text))
        db.add(segment); db.commit()
        return claim.id, document.id, user.id


def test_running_hours_extracts_promotable_maintenance_facts():
    text = "MT ORION Turbocharger No.2 RH since overhaul 14,800 hours. Last overhaul 2026-01-10. Maker interval 12,000 hours."
    claim_id, document_id, user_id = seed_claim_and_document("running_hours_record", text)
    payload = {"classification":{"document_type":"running_hours_record","confidence":.99}, "vessel_name":ss("MT ORION","MT ORION"), "imo_number":ss(None,None,0), "equipment_name":ss("Turbocharger No.2","Turbocharger No.2"), "equipment_maker":ss(None,None,0), "equipment_model":ss(None,None,0), "equipment_serial_number":ss(None,None,0), "total_running_hours":ss(None,None,0), "running_hours_since_overhaul":ss("14,800 hours","RH since overhaul 14,800 hours"), "last_overhaul_date":ss("2026-01-10","Last overhaul 2026-01-10"), "recommended_overhaul_interval":ss("12,000 hours","Maker interval 12,000 hours"), "interval_extension_approved":sb(None,None,0), "interval_extension_details":ss(None,None,0)}
    with TestingSessionLocal() as db:
        run = run_running_hours_intelligence(db, document=db.get(Document, document_id), requested_by_id=user_id, provider=FakeProvider(payload))
        rows = {r.field_path:r for r in db.scalars(select(DocumentExtraction).where(DocumentExtraction.ai_run_id==run.id))}
        assert rows["maintenance.running_hours_since_overhaul"].normalized_value == {"value":14800.0,"unit":"hours","raw":"14,800 hours"}
        user=db.get(User,user_id)
        for path in ["maintenance.running_hours_since_overhaul","maintenance.last_overhaul_date","maintenance.recommended_overhaul_interval"]:
            review_extraction(db, extraction=rows[path], reviewer=user, action="approve")
        db.commit()
        claim=db.get(Claim,claim_id); evaluate_claim_rules(db, claim=claim, user=user)
        tech = build_technical_review(db, claim_id=claim.id, organization_id=claim.organization_id)
        assert any(row["key"] == "tech_001" for row in tech["matrix"])


def test_pms_rows_are_repeatable_and_deferred_maintenance_creates_issue():
    text = "PMS Turbocharger overhaul status DEFERRED. Job TC-100 scheduled 2026-06-01 status deferred."
    claim_id, document_id, user_id = seed_claim_and_document("pms_record", text)
    null=ss(None,None,0)
    payload={"classification":{"document_type":"pms_history","confidence":.99},"vessel_name":ss(None,None,0),"imo_number":ss(None,None,0),"equipment_name":ss("Turbocharger","Turbocharger"),"overall_status":ss("Deferred","status DEFERRED"),"overhaul_deferred":sb(True,"status DEFERRED"),"running_hours_since_overhaul":null,"last_overhaul_date":null,"records":[{"job_code":ss("TC-100","Job TC-100"),"task":ss("Turbocharger overhaul","Turbocharger overhaul"),"scheduled_date":ss("2026-06-01","scheduled 2026-06-01"),"completed_date":null,"scheduled_running_hours":null,"actual_running_hours":null,"status":ss("deferred","status deferred"),"deferred":sb(True,"status deferred"),"overdue":sb(None,None,0),"remarks":null}]}
    with TestingSessionLocal() as db:
        run=run_pms_history_intelligence(db, document=db.get(Document,document_id), requested_by_id=user_id, provider=FakeProvider(payload))
        rows={r.field_path:r for r in db.scalars(select(DocumentExtraction).where(DocumentExtraction.ai_run_id==run.id))}
        user=db.get(User,user_id)
        review_extraction(db, extraction=rows["maintenance.overhaul_deferred"], reviewer=user, action="approve")
        repeat=rows["pms.records[0].status"]
        _, fact, promoted = review_extraction(db, extraction=repeat, reviewer=user, action="approve")
        assert promoted is False and fact is None
        db.commit(); claim=db.get(Claim,claim_id); evaluate_claim_rules(db, claim=claim, user=user)
        tech=build_technical_review(db,claim_id=claim.id,organization_id=claim.organization_id)
        assert any(row["key"]=="tech_003" for row in tech["matrix"])


def test_workshop_opinion_stays_opinion_and_enters_matrix_after_human_review():
    text="Workshop found bearing heavily damaged. Workshop suspects lubrication deficiency. Rotor repair possible."
    claim_id, document_id, user_id = seed_claim_and_document("workshop_report", text)
    null=ss(None,None,0)
    payload={"classification":{"document_type":"workshop_report","confidence":.99},"workshop_name":null,"attendance_date":null,"vessel_name":null,"equipment_name":ss("Turbocharger","Turbocharger"),"equipment_maker":null,"equipment_model":null,"equipment_serial_number":null,"repairable":sb(True,"Rotor repair possible"),"temporary_repair":sb(None,None,0),"damage_findings":[{"component":ss("Bearing","bearing"),"description":ss("Heavily damaged","heavily damaged"),"extent":null,"measurement":null}],"repair_options":[{"scope":ss("Rotor repair","Rotor repair possible"),"repair_or_replace":ss("repair","Rotor repair possible"),"duration":null,"parts_required":null,"lead_time":null}],"suspected_cause_opinions":[ss("Lubrication deficiency","Workshop suspects lubrication deficiency")],"recommendations":[]}
    with TestingSessionLocal() as db:
        run=run_workshop_report_intelligence(db, document=db.get(Document,document_id), requested_by_id=user_id, provider=FakeProvider(payload))
        rows={r.field_path:r for r in db.scalars(select(DocumentExtraction).where(DocumentExtraction.ai_run_id==run.id))}
        opinion=rows["workshop.suspected_cause_opinions[0]"]
        assert opinion.semantic_kind == AISemanticKind.OPINION
        user=db.get(User,user_id)
        _, fact, promoted=review_extraction(db, extraction=opinion, reviewer=user, action="approve")
        assert fact is None and promoted is False
        review_extraction(db, extraction=rows["workshop.damage_findings[0].description"], reviewer=user, action="approve")
        db.commit()
        tech=build_technical_review(db,claim_id=claim_id,organization_id=db.get(Claim,claim_id).organization_id)
        opinion_rows=[r for r in tech["matrix"] if r["key"].startswith("workshop_opinion_")]
        assert opinion_rows and "Lubricating-oil analysis" in " ".join(opinion_rows[0]["unknown_or_missing"])
        assert len(tech["workshop_findings"]) == 1


def test_new_schemas_are_strict():
    from app.ai.schemas.running_hours import RunningHoursExtraction
    from app.ai.schemas.pms_history import PMSHistoryExtraction
    from app.ai.schemas.workshop_report import WorkshopReportExtraction
    assert RunningHoursExtraction.model_json_schema()["additionalProperties"] is False
    assert PMSHistoryExtraction.model_json_schema()["additionalProperties"] is False
    assert WorkshopReportExtraction.model_json_schema()["additionalProperties"] is False
