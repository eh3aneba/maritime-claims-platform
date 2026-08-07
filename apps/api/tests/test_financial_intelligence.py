from datetime import date
from sqlalchemy import select
from app.ai.gateway.base import AIRequest, AIResponse
from app.core.security import hash_password
from app.modules.claims.models import Claim, ClaimStatus
from app.modules.documents.models import ConfidentialityLevel, Document, DocumentProcessingStatus
from app.modules.intelligence.models import DocumentExtraction
from app.modules.intelligence.service import run_invoice_intelligence, run_quotation_intelligence
from app.modules.organizations.models import Organization
from app.modules.processing.models import DocumentTextExtraction, DocumentTextSegment
from app.modules.review.service import review_extraction
from app.modules.financial.service import build_financial_review
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, reset_database
PASSWORD='Strong-Finance-Test-2026'
def ss(v,q,c=.98): return {'value':v,'confidence':c,'source':{'segment_index':0 if v is not None else None,'quote':q}}
def sb(v,q,c=.98): return {'value':v,'confidence':c,'source':{'segment_index':0 if v is not None else None,'quote':q}}
class FP:
 name='fake';_model='fake-fin-v1'
 def __init__(self,p):self.p=p
 def generate(self,r:AIRequest):return AIResponse(provider='fake',model=self._model,structured_output=self.p,output_text='{}',usage={},raw_response_id='x')
def setup_function():reset_database()
def seed(dtype,text,hashchar):
 with TestingSessionLocal() as db:
  org=db.scalar(select(Organization).where(Organization.slug=='alpha'))
  if not org:
   org=Organization(name='Alpha',slug='alpha');db.add(org);db.flush();u=User(organization_id=org.id,email='h@x.com',full_name='H',password_hash=hash_password(PASSWORD),role=UserRole.CLAIMS_MANAGER,is_active=True);v=Vessel(organization_id=org.id,name='MT ORION',imo_number='7000301');db.add_all([u,v]);db.flush();c=Claim(organization_id=org.id,vessel_id=v.id,claim_reference='MCRI-HM-2026-0001',incident_date=date(2026,7,10),notification_date=date(2026,7,11),incident_description='Main engine turbocharger failure',currency='USD',status=ClaimStatus.FINANCIAL_REVIEW);db.add(c);db.flush()
  else:
   u=db.scalar(select(User).where(User.organization_id==org.id));c=db.scalar(select(Claim).where(Claim.organization_id==org.id))
  d=Document(organization_id=org.id,claim_id=c.id,uploaded_by_id=u.id,filename=dtype+'.pdf',original_filename=dtype+'.pdf',document_type=dtype,mime_type='application/pdf',file_size_bytes=100,file_hash=hashchar*64,storage_key='x/'+hashchar,processing_status=DocumentProcessingStatus.PROCESSED,confidentiality_level=ConfidentialityLevel.CONFIDENTIAL);db.add(d);db.flush();e=DocumentTextExtraction(organization_id=org.id,document_id=d.id,extraction_method='test',extractor_version='1',char_count=len(text),segment_count=1,requires_ocr=False,text_hash=hashchar*64);db.add(e);db.flush();db.add(DocumentTextSegment(organization_id=org.id,document_id=d.id,extraction_id=e.id,segment_index=0,locator_type='page',locator_value='1',text=text,char_count=len(text)));db.commit();return c.id,d.id,u.id

def approve_all(db,run,user):
 for x in db.scalars(select(DocumentExtraction).where(DocumentExtraction.ai_run_id==run.id)):
  review_extraction(db,extraction=x,reviewer=user,action='approve',reason='reviewed source')
 db.commit()
def test_invoice_materializes_cost_and_predate_flag():
 text='ABC Invoice INV-1 dated 2026-07-01 USD. Rotor assembly 240,000 USD. Total 240,000 USD.';cid,did,uid=seed('invoice',text,'a')
 payload={'classification':{'document_type':'invoice','confidence':.99},'supplier':ss('ABC','ABC'),'invoice_number':ss('INV-1','INV-1'),'invoice_date':ss('2026-07-01','2026-07-01'),'purchase_order':ss(None,None,0),'related_quotation_number':ss(None,None,0),'currency':ss('USD','USD'),'subtotal':ss('240,000 USD','240,000 USD'),'tax':ss(None,None,0),'discount':ss(None,None,0),'total':ss('240,000 USD','Total 240,000 USD'),'payment_terms':ss(None,None,0),'line_items':[{'description':ss('Rotor assembly','Rotor assembly'),'quantity':ss('1','Rotor assembly 240,000 USD'),'unit':ss(None,None,0),'unit_price':ss('240,000 USD','240,000 USD'),'amount':ss('240,000 USD','240,000 USD'),'category_candidate':ss('Spare Parts','Rotor assembly'),'potential_betterment_cue':sb(False,'Rotor assembly'),'potential_ordinary_maintenance_cue':sb(False,'Rotor assembly')}]}
 with TestingSessionLocal() as db:
  run=run_invoice_intelligence(db,document=db.get(Document,did),requested_by_id=uid,provider=FP(payload));approve_all(db,run,db.get(User,uid));r=build_financial_review(db,claim=db.get(Claim,cid),user_id=uid);db.commit();assert str(r['items'][0].amount)=='240000.00';assert any(f.flag_type.value=='invoice_predates_incident' for f in r['flags'])
def test_quote_scope_difference_flag():
 q1='ABC Quote Q1 USD 260000 Rotor repair scope. Total 260000.';cid,d1,uid=seed('quotation',q1,'b');q2='XYZ Quote Q2 USD 470000 Complete turbocharger replacement. Total 470000.';_,d2,_=seed('quotation',q2,'c')
 def payload(sup,num,total,scope):return {'classification':{'document_type':'quotation','confidence':.99},'supplier':ss(sup,sup),'quotation_number':ss(num,num),'quotation_date':ss('2026-07-12','2026-07-12'),'currency':ss('USD','USD'),'subtotal':ss(str(total),str(total)),'tax':ss(None,None,0),'freight':ss(None,None,0),'total':ss(str(total),str(total)),'validity':ss(None,None,0),'lead_time':ss(None,None,0),'repair_duration':ss(None,None,0),'scope_summary':ss(scope,scope),'exclusions':[],'line_items':[{'description':ss(scope,scope),'quantity':ss('1',scope),'unit':ss(None,None,0),'unit_price':ss(str(total),str(total)),'amount':ss(str(total),str(total)),'category_candidate':ss('Permanent Repair',scope),'potential_betterment_cue':sb(False,scope),'potential_ordinary_maintenance_cue':sb(False,scope)}]}
 with TestingSessionLocal() as db:
  u=db.get(User,uid);r1=run_quotation_intelligence(db,document=db.get(Document,d1),requested_by_id=uid,provider=FP(payload('ABC','Q1',260000,'Rotor repair scope')));approve_all(db,r1,u);r2=run_quotation_intelligence(db,document=db.get(Document,d2),requested_by_id=uid,provider=FP(payload('XYZ','Q2',470000,'Complete turbocharger replacement')));approve_all(db,r2,u);fr=build_financial_review(db,claim=db.get(Claim,cid),user_id=uid);db.commit();assert len(fr['quotations'])==2;assert any(f.flag_type.value=='quote_scope_difference' for f in fr['flags'])
