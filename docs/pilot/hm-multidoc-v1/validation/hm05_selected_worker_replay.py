"""Synthetic-only service/worker replay; no reviewer or source approval assertions."""
import asyncio, hashlib, io, json, os, sys
assert os.getuid() == 1000
sys.path.insert(0, "/app")
from datetime import date
from pathlib import Path
from sqlalchemy import select, func
from starlette.datastructures import UploadFile, Headers
from fastapi import Response
from app.db.metadata import Base
from app.db.session import create_session
from app.core.config import get_settings
from sqlalchemy.engine import make_url
from app.modules.organizations.models import Organization
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from app.modules.claims.models import Claim
from app.modules.claims.facts import ClaimFact
from app.modules.assessments.models import InitialAssessment
from app.modules.documents.models import ConfidentialityLevel, Document, DocumentMalwareScanStatus
from app.modules.documents.service import create_document_from_upload
from app.modules.processing.service import claim_next_job, process_job
from app.modules.processing.models import DocumentTextExtraction, DocumentTextSegment, ProcessingJobStatus
from app.modules.processing.router import read_unverified_source_segments
from app.core.security import hash_password
settings = get_settings()
assert settings.app_env == "test" and settings.ai_provider == "disabled"
assert settings.ocr_enabled and settings.ocr_languages == "eng+fas"
assert settings.malware_scan_enabled
assert not settings.external_evidence_live_provider_adapters_enabled
assert not settings.external_evidence_live_sftp_adapters_enabled
assert make_url(settings.database_url).database == "hm05_synthetic"
Base.registry.configure()
raw=Path('/review/original.png').read_bytes()
assert hashlib.sha256(raw).hexdigest()=='1eef5de99985ee76048f93b04b7184c9a5daf4b6f33441b36c99e9a850e56d4c'
with create_session() as db:
    # Refuse an existing organization/claim/document dataset before any writes.
    for model in (Organization, Claim, Document):
        assert db.scalar(select(func.count()).select_from(model)) == 0
    org=Organization(name='Invented HM05 selected-worker rehearsal',slug='hm05-selected-worker-synthetic')
    db.add(org); db.flush()
    user=User(organization_id=org.id,email='hm05-fixture@example.invalid',full_name='Synthetic fixture operator, not independent reviewer',password_hash=hash_password('Invented-local-fixture-password-2026'),role=UserRole.CLAIMS_HANDLER,is_active=True)
    vessel=Vessel(organization_id=org.id,name='SYNTHETIC HM05 ONLY')
    db.add_all([user,vessel]); db.flush()
    claim=Claim(organization_id=org.id,vessel_id=vessel.id,claim_reference='HM05-SELECTED-WORKER-SYNTHETIC',incident_date=date(2026,9,11),notification_date=date(2026,9,12),incident_description='Invented replay fixture; dates are fixture setup, not OCR adjudication.',currency='USD')
    db.add(claim);db.commit()
    upload=UploadFile(file=io.BytesIO(raw),filename='original.png',headers=Headers({'content-type':'image/png'}))
    document=asyncio.run(create_document_from_upload(db,claim=claim,current_user=user,upload=upload,document_type='chief_engineer_report',confidentiality_level=ConfidentialityLevel.INTERNAL))
    assert document.file_hash==hashlib.sha256(raw).hexdigest()
    assert document.malware_scan_status==DocumentMalwareScanStatus.CLEAN and document.malware_scanned_at is not None
    job=claim_next_job(db,worker_id='hm05-selected-runtime-synthetic')
    assert job is not None and job.document_id==document.id
    process_job(db,job=job);db.refresh(job);db.refresh(document)
    assert job.status==ProcessingJobStatus.COMPLETED
    extraction=db.scalar(select(DocumentTextExtraction).where(DocumentTextExtraction.document_id==document.id))
    segments=list(db.scalars(select(DocumentTextSegment).where(DocumentTextSegment.document_id==document.id).order_by(DocumentTextSegment.segment_index)))
    text='\n\n'.join(s.text for s in segments)
    assert extraction.text_hash==hashlib.sha256(text.encode()).hexdigest()
    response=Response()
    preview=read_unverified_source_segments(claim_id=claim.id,document_id=document.id,current_user=user,db=db,response=response,offset=0,limit=5)
    assert preview.review_disposition=='machine_unverified'
    assert preview.source_text_quality_state=='ocr_human_source_comparison_required'
    assert db.scalar(select(func.count()).select_from(ClaimFact))==0
    assert db.scalar(select(func.count()).select_from(InitialAssessment))==0
    print(json.dumps({'synthetic_only':True,'scan_verdict':document.malware_scan_status.value,'actual_scanner_used':True,'scanner_freshness_accepted':False,'source_file_hash':document.file_hash,'document_version':document.version_number,'extraction_method':extraction.extraction_method,'requires_ocr':extraction.requires_ocr,'persisted_text_hash':extraction.text_hash,'persisted_transcript':text,'source_locators':[{'segment_index':s.segment_index,'locator_type':s.locator_type,'locator_value':s.locator_value} for s in segments],'review_disposition':preview.review_disposition,'source_text_quality_state':preview.source_text_quality_state,'claim_fact_count':0,'assessment_count':0,'independent_review_performed':False,'pilot_accepted':False},ensure_ascii=False))
