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
