from datetime import date
from sqlalchemy import select

from app.core.security import hash_password
from app.modules.assessments.models import AssessmentSection, AssessmentSectionStatus, AssessmentStatus, InitialAssessment
from app.modules.assessments.service import approve_assessment, generate_assessment, get_assessment, review_section
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.organizations.models import Organization
from app.modules.rules.service import evaluate_claim_rules
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from fastapi import HTTPException
from tests.db_harness import TestingSessionLocal, reset_database


def setup_function(): reset_database()

def seed():
    with TestingSessionLocal() as db:
        o=Organization(name='Alpha',slug='alpha');db.add(o);db.flush()
        u=User(organization_id=o.id,email='m@x.com',full_name='Manager',password_hash=hash_password('Strong-Assessment-2026'),role=UserRole.CLAIMS_MANAGER,is_active=True)
        v=Vessel(organization_id=o.id,name='MT ORION',imo_number='7000301');db.add_all([u,v]);db.flush()
        c=Claim(organization_id=o.id,vessel_id=v.id,claim_reference='MCRI-HM-2026-0001',incident_date=date(2026,7,10),notification_date=date(2026,7,11),incident_description='Main engine turbocharger failure',status=ClaimStatus.INVESTIGATION,currency='USD')
        db.add(c);db.flush();evaluate_claim_rules(db,claim=c,user=u);return c.id,u.id

def test_not_ready_requires_explicit_override():
    cid,uid=seed()
    with TestingSessionLocal() as db:
        try: generate_assessment(db,claim=db.get(Claim,cid),user=db.get(User,uid),allow_if_not_ready=False,override_reason=None)
        except HTTPException as exc: assert exc.status_code==409
        else: raise AssertionError('expected readiness gate')

def test_preliminary_assessment_is_versioned_and_reviewable():
    cid,uid=seed()
    with TestingSessionLocal() as db:
        c=db.get(Claim,cid);u=db.get(User,uid)
        a=generate_assessment(db,claim=c,user=u,allow_if_not_ready=True,override_reason='Preliminary review required while evidence remains outstanding')
        assert a.version==1 and a.is_preliminary is True
        a,sections=get_assessment(db,claim=c,assessment_id=a.id);assert len(sections)==11
        for s in sections: review_section(db,claim=c,section=s,user=u,action='approve',text=None)
        approve_assessment(db,claim=c,assessment=a,user=u,note='Reviewed as preliminary')
        assert a.status==AssessmentStatus.APPROVED
        b=generate_assessment(db,claim=c,user=u,allow_if_not_ready=True,override_reason='Refresh after further review')
        assert b.version==2
        assert db.scalar(select(InitialAssessment).where(InitialAssessment.id==a.id)).status==AssessmentStatus.APPROVED

def test_section_edit_preserves_draft_and_sources():
    cid,uid=seed()
    with TestingSessionLocal() as db:
        c=db.get(Claim,cid);u=db.get(User,uid);a=generate_assessment(db,claim=c,user=u,allow_if_not_ready=True,override_reason='Preliminary')
        s=db.scalar(select(AssessmentSection).where(AssessmentSection.assessment_id==a.id,AssessmentSection.section_key=='incident'))
        original=s.draft_text;review_section(db,claim=c,section=s,user=u,action='edit',text='Human-edited incident assessment.')
        assert s.status==AssessmentSectionStatus.EDITED and s.draft_text==original and s.approved_text=='Human-edited incident assessment.'


def test_damage_section_includes_human_reviewed_workshop_findings():
    from decimal import Decimal
    from app.modules.documents.models import ConfidentialityLevel, Document, DocumentProcessingStatus
    from app.modules.intelligence.models import AIRun, AIRunStatus, AISemanticKind, AIReviewStatus, DocumentExtraction

    cid, uid = seed()
    with TestingSessionLocal() as db:
        c = db.get(Claim, cid); u = db.get(User, uid)
        doc = Document(
            organization_id=c.organization_id, claim_id=c.id, uploaded_by_id=u.id,
            filename="workshop.docx", original_filename="Workshop_Report.docx", document_type="workshop_report",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", file_size_bytes=100,
            file_hash="d"*64, storage_key=f"{c.organization_id}/{c.id}/workshop.docx", version_number=1,
            processing_status=DocumentProcessingStatus.PROCESSED, confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
        )
        db.add(doc); db.flush()
        run = AIRun(
            organization_id=c.organization_id, claim_id=c.id, document_id=doc.id, requested_by_id=u.id,
            task="workshop_report_extract", status=AIRunStatus.COMPLETED, provider="fake", model="fake-v1",
            prompt_name="workshop_report", prompt_version="1.0", schema_name="workshop_report_v1", schema_version="1.0",
            input_text_hash="e"*64, input_char_count=100,
        )
        db.add(run); db.flush()
        for path, value in [
            ("workshop.damage_findings[0].component", "Turbine rotor"),
            ("workshop.damage_findings[0].damage_description", "Blade tips heavily damaged"),
            ("workshop.damage_findings[0].extent", "Replacement or specialist repair required"),
        ]:
            db.add(DocumentExtraction(
                organization_id=c.organization_id, claim_id=c.id, document_id=doc.id, ai_run_id=run.id,
                field_path=path, semantic_kind=AISemanticKind.FACT, raw_value=value, normalized_value=value,
                confidence=Decimal("0.950"), source_verified=True, human_status=AIReviewStatus.APPROVED,
                approved_value=value, reviewed_by_id=u.id,
            ))
        db.commit()
        a = generate_assessment(db, claim=c, user=u, allow_if_not_ready=True, override_reason="Preliminary")
        _, sections = get_assessment(db, claim=c, assessment_id=a.id)
        damage = next(section for section in sections if section.section_key == "damage")
        assert "Workshop finding — Turbine rotor" in damage.draft_text
        assert "Blade tips heavily damaged" in damage.draft_text
        assert any(source["kind"] == "document_extraction" for source in damage.source_manifest)


def test_approved_assessment_version_is_immutable():
    cid, uid = seed()
    with TestingSessionLocal() as db:
        c = db.get(Claim, cid); u = db.get(User, uid)
        a = generate_assessment(db, claim=c, user=u, allow_if_not_ready=True, override_reason="Preliminary")
        _, sections = get_assessment(db, claim=c, assessment_id=a.id)
        for section in sections:
            review_section(db, claim=c, section=section, user=u, action="approve", text=None)
        approve_assessment(db, claim=c, assessment=a, user=u, note="Approved snapshot")
        try:
            review_section(db, claim=c, section=sections[0], user=u, action="edit", text="Changed after approval")
        except HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("approved assessment version should be immutable")
