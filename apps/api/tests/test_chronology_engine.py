from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from app.core.security import hash_password
from app.modules.audit.models import AuditLog
from app.modules.chronology.models import ChronologyEvent, ChronologyMateriality, ConflictStatus, EvidenceConflict
from app.modules.chronology.service import build_chronology
from app.modules.claims.models import Claim
from app.modules.documents.models import ConfidentialityLevel, Document, DocumentProcessingStatus
from app.modules.intelligence.models import AIRun, AIRunStatus, AISemanticKind, AIReviewStatus, DocumentExtraction
from app.modules.organizations.models import Organization
from app.modules.processing.models import DocumentTextExtraction, DocumentTextSegment
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, client, reset_database

PASSWORD = "Strong-Chronology-Test-2026"


def setup_function() -> None:
    reset_database()


def login(slug: str, email: str) -> None:
    response = client.post("/api/v1/auth/login", json={"organization_slug": slug, "email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text


def _document(db, *, org, claim, user, name: str, doc_type: str, hash_char: str):
    document = Document(
        organization_id=org.id,
        claim_id=claim.id,
        uploaded_by_id=user.id,
        filename=f"server-{name}",
        original_filename=name,
        document_type=doc_type,
        mime_type="application/pdf",
        file_size_bytes=1000,
        file_hash=hash_char * 64,
        storage_key=f"{org.id}/{claim.id}/{name}",
        version_number=1,
        processing_status=DocumentProcessingStatus.PROCESSED,
        confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
    )
    db.add(document); db.flush()
    text = DocumentTextExtraction(
        organization_id=org.id,
        document_id=document.id,
        extraction_method="test",
        extractor_version="1.0",
        char_count=200,
        segment_count=1,
        requires_ocr=False,
        text_hash=("f" if hash_char != "f" else "e") * 64,
    )
    db.add(text); db.flush()
    segment = DocumentTextSegment(
        organization_id=org.id,
        document_id=document.id,
        extraction_id=text.id,
        segment_index=0,
        locator_type="page",
        locator_value="1",
        text=f"Chronology evidence from {name}",
        char_count=50,
    )
    db.add(segment); db.flush()
    run = AIRun(
        organization_id=org.id,
        claim_id=claim.id,
        document_id=document.id,
        requested_by_id=user.id,
        task="chief_engineer_report_extract" if doc_type == "chief_engineer_report" else "engine_log_extract",
        status=AIRunStatus.COMPLETED,
        provider="fake",
        model="fake-v1",
        prompt_name="test",
        prompt_version="1.0",
        schema_name="test",
        schema_version="1.0",
        input_text_hash="c" * 64,
        input_char_count=50,
        document_type_candidate=doc_type,
        classification_confidence=Decimal("0.990"),
    )
    db.add(run); db.flush()
    return document, segment, run


def _extraction(db, *, org, claim, document, segment, run, path: str, value, kind=AISemanticKind.FACT):
    row = DocumentExtraction(
        organization_id=org.id,
        claim_id=claim.id,
        document_id=document.id,
        ai_run_id=run.id,
        source_segment_id=segment.id,
        field_path=path,
        semantic_kind=kind,
        raw_value=value,
        normalized_value=value,
        confidence=Decimal("0.970"),
        source_locator_type="page",
        source_locator_value="1",
        source_quote=str(value),
        source_verified=True,
        human_status=AIReviewStatus.APPROVED,
        approved_value=value,
    )
    db.add(row); db.flush()
    return row


def seed_timeline(*, ce_time="10:30", engine_time="10:52", ce_stopped=True, engine_shutdown=True, engine_date="2026-07-10") -> dict[str, str]:
    with TestingSessionLocal() as db:
        alpha = Organization(name="Alpha Marine", slug="alpha")
        beta = Organization(name="Beta Marine", slug="beta")
        db.add_all([alpha, beta]); db.flush()
        alpha_user = User(organization_id=alpha.id, email="alpha@example.com", full_name="Alpha Handler", password_hash=hash_password(PASSWORD), role=UserRole.CLAIMS_HANDLER, is_active=True)
        beta_user = User(organization_id=beta.id, email="beta@example.com", full_name="Beta Handler", password_hash=hash_password(PASSWORD), role=UserRole.CLAIMS_HANDLER, is_active=True)
        vessel = Vessel(organization_id=alpha.id, name="MT ORION", imo_number="7000301")
        db.add_all([alpha_user, beta_user, vessel]); db.flush()
        claim = Claim(organization_id=alpha.id, vessel_id=vessel.id, claim_reference="MCRI-HM-2026-0001", incident_date=date(2026,7,10), notification_date=date(2026,7,11), incident_description="Turbocharger failure", currency="USD")
        db.add(claim); db.flush()

        ce_doc, ce_seg, ce_run = _document(db, org=alpha, claim=claim, user=alpha_user, name="CE_Report.pdf", doc_type="chief_engineer_report", hash_char="a")
        _extraction(db, org=alpha, claim=claim, document=ce_doc, segment=ce_seg, run=ce_run, path="incident.date", value="2026-07-10")
        _extraction(db, org=alpha, claim=claim, document=ce_doc, segment=ce_seg, run=ce_run, path="incident.time", value=ce_time)
        _extraction(db, org=alpha, claim=claim, document=ce_doc, segment=ce_seg, run=ce_run, path="incident.timezone", value="UTC")
        ce_time_ex = None
        if ce_stopped is True:
            _extraction(db, org=alpha, claim=claim, document=ce_doc, segment=ce_seg, run=ce_run, path="reported_events[0].date", value="2026-07-10")
            ce_time_ex = _extraction(db, org=alpha, claim=claim, document=ce_doc, segment=ce_seg, run=ce_run, path="reported_events[0].time", value=ce_time)
            _extraction(db, org=alpha, claim=claim, document=ce_doc, segment=ce_seg, run=ce_run, path="reported_events[0].timezone", value="UTC")
            _extraction(db, org=alpha, claim=claim, document=ce_doc, segment=ce_seg, run=ce_run, path="reported_events[0].event_type", value="shutdown", kind=AISemanticKind.INFERENCE)
            _extraction(db, org=alpha, claim=claim, document=ce_doc, segment=ce_seg, run=ce_run, path="reported_events[0].description", value="The main engine was stopped for inspection")
        ce_stop = _extraction(db, org=alpha, claim=claim, document=ce_doc, segment=ce_seg, run=ce_run, path="operational_impact.engine_stopped", value=ce_stopped)

        eng_doc, eng_seg, eng_run = _document(db, org=alpha, claim=claim, user=alpha_user, name="Engine_Log.pdf", doc_type="engine_log", hash_char="d")
        _extraction(db, org=alpha, claim=claim, document=eng_doc, segment=eng_seg, run=eng_run, path="engine_log.events[0].date", value=engine_date)
        eng_time_ex = _extraction(db, org=alpha, claim=claim, document=eng_doc, segment=eng_seg, run=eng_run, path="engine_log.events[0].time", value=engine_time)
        _extraction(db, org=alpha, claim=claim, document=eng_doc, segment=eng_seg, run=eng_run, path="engine_log.events[0].timezone", value="UTC")
        eng_shutdown = _extraction(db, org=alpha, claim=claim, document=eng_doc, segment=eng_seg, run=eng_run, path="engine_log.events[0].shutdown", value=engine_shutdown)
        _extraction(db, org=alpha, claim=claim, document=eng_doc, segment=eng_seg, run=eng_run, path="engine_log.events[0].action", value="Turbocharger isolated after engine shutdown")
        db.commit()
        return {
            "claim_id": str(claim.id), "alpha_user_id": str(alpha_user.id), "alpha_org_id": str(alpha.id),
            "ce_time_id": str(ce_time_ex.id) if ce_time_ex else "", "eng_time_id": str(eng_time_ex.id), "ce_stop_id": str(ce_stop.id), "eng_shutdown_id": str(eng_shutdown.id)
        }


def test_events_within_ten_minutes_cluster_and_engine_log_time_becomes_canonical() -> None:
    ids = seed_timeline(ce_time="10:30", engine_time="10:35")
    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(ids["claim_id"])); user = db.get(User, UUID(ids["alpha_user_id"]))
        events, conflicts = build_chronology(db, claim=claim, user=user)
        shutdowns = [event for event in events if event.event_type == "shutdown"]
        assert len(shutdowns) == 1
        assert shutdowns[0].occurred_time.strftime("%H:%M") == "10:35"
        assert conflicts == []
        response = client.get("/api/v1/health")
        assert response.status_code == 200


def test_twenty_two_minute_shutdown_difference_creates_medium_conflict() -> None:
    ids = seed_timeline(ce_time="10:30", engine_time="10:52")
    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(ids["claim_id"])); user = db.get(User, UUID(ids["alpha_user_id"]))
        events, conflicts = build_chronology(db, claim=claim, user=user)
        assert len([event for event in events if event.event_type == "shutdown"]) == 2
        timestamp_conflicts = [conflict for conflict in conflicts if conflict.conflict_type == "timestamp"]
        assert len(timestamp_conflicts) == 1
        assert timestamp_conflicts[0].difference_minutes == Decimal("22.0")
        assert timestamp_conflicts[0].materiality == ChronologyMateriality.MEDIUM
        assert timestamp_conflicts[0].status == ConflictStatus.OPEN


def test_more_than_thirty_minutes_is_high_and_different_date_is_critical() -> None:
    ids = seed_timeline(ce_time="10:00", engine_time="11:05")
    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(ids["claim_id"])); user = db.get(User, UUID(ids["alpha_user_id"]))
        _, conflicts = build_chronology(db, claim=claim, user=user)
        conflict = next(item for item in conflicts if item.conflict_type == "timestamp")
        assert conflict.materiality == ChronologyMateriality.HIGH
        assert conflict.difference_minutes == Decimal("65.0")

    reset_database()
    ids = seed_timeline(ce_time="10:00", engine_time="10:00", engine_date="2026-07-11")
    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(ids["claim_id"])); user = db.get(User, UUID(ids["alpha_user_id"]))
        _, conflicts = build_chronology(db, claim=claim, user=user)
        conflict = next(item for item in conflicts if item.conflict_type == "timestamp")
        assert conflict.materiality == ChronologyMateriality.CRITICAL
        assert conflict.difference_minutes is None


def test_ce_false_engine_stopped_vs_reviewed_engine_shutdown_creates_content_conflict() -> None:
    ids = seed_timeline(ce_time="10:30", engine_time="10:35", ce_stopped=False)
    with TestingSessionLocal() as db:
        claim = db.get(Claim, UUID(ids["claim_id"])); user = db.get(User, UUID(ids["alpha_user_id"]))
        _, conflicts = build_chronology(db, claim=claim, user=user)
        content = [item for item in conflicts if item.conflict_type == "content"]
        assert len(content) == 1
        assert content[0].topic == "engine stopped"
        assert content[0].materiality == ChronologyMateriality.HIGH
        assert content[0].value_a is False and content[0].value_b is True


def test_chronology_api_is_tenant_scoped_and_resolution_is_audited() -> None:
    ids = seed_timeline(ce_time="10:30", engine_time="10:52")
    login("alpha", "alpha@example.com")
    built = client.post(f"/api/v1/claims/{ids['claim_id']}/chronology/rebuild")
    assert built.status_code == 200, built.text
    assert built.json()["event_count"] >= 2
    assert built.json()["open_conflict_count"] == 1

    summary = client.get(f"/api/v1/claims/{ids['claim_id']}/chronology")
    assert summary.status_code == 200, summary.text
    conflict_id = summary.json()["conflicts"][0]["id"]
    resolved = client.post(
        f"/api/v1/claims/{ids['claim_id']}/chronology/conflicts/{conflict_id}/resolve",
        json={"status": "explained", "note": "CE report refers to first operational response; engine log records formal shutdown."},
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "explained"

    with TestingSessionLocal() as db:
        conflict = db.get(EvidenceConflict, UUID(conflict_id))
        assert conflict.resolution_note.startswith("CE report")
        audits = list(db.scalars(select(AuditLog).where(AuditLog.organization_id == UUID(ids["alpha_org_id"]))))
        assert any(row.action == "BUILD_CLAIM_CHRONOLOGY" for row in audits)
        assert any(row.action == "RESOLVE_EVIDENCE_CONFLICT" and row.entity_id == conflict.id for row in audits)

    login("beta", "beta@example.com")
    denied = client.get(f"/api/v1/claims/{ids['claim_id']}/chronology")
    assert denied.status_code == 404


def test_rebuild_is_idempotent_and_preserves_resolution_for_same_conflict() -> None:
    ids = seed_timeline(ce_time="10:30", engine_time="10:52")
    login("alpha", "alpha@example.com")
    first = client.post(f"/api/v1/claims/{ids['claim_id']}/chronology/rebuild")
    assert first.status_code == 200
    summary = client.get(f"/api/v1/claims/{ids['claim_id']}/chronology").json()
    event_ids = {event["id"] for event in summary["events"]}
    conflict_id = summary["conflicts"][0]["id"]
    client.post(f"/api/v1/claims/{ids['claim_id']}/chronology/conflicts/{conflict_id}/resolve", json={"status": "accepted_difference", "note": "Different timestamps describe different recording conventions."})

    second = client.post(f"/api/v1/claims/{ids['claim_id']}/chronology/rebuild")
    assert second.status_code == 200
    after = client.get(f"/api/v1/claims/{ids['claim_id']}/chronology").json()
    assert {event["id"] for event in after["events"]} == event_ids
    conflict = next(item for item in after["conflicts"] if item["id"] == conflict_id)
    assert conflict["status"] == "accepted_difference"
    assert conflict["resolution_note"].startswith("Different timestamps")


def test_pending_or_rejected_evidence_never_enters_chronology() -> None:
    ids = seed_timeline(ce_time="10:30", engine_time="10:52")
    with TestingSessionLocal() as db:
        eng_time = db.get(DocumentExtraction, UUID(ids["eng_time_id"]))
        eng_time.human_status = AIReviewStatus.PENDING
        ce_time = db.get(DocumentExtraction, UUID(ids["ce_time_id"]))
        ce_time.human_status = AIReviewStatus.REJECTED
        db.commit()
        claim = db.get(Claim, UUID(ids["claim_id"])); user = db.get(User, UUID(ids["alpha_user_id"]))
        events, conflicts = build_chronology(db, claim=claim, user=user)
        # The reviewed CE statement is preserved as an undated/relative event rather
        # than being assigned incident.time. Pending Engine Log timing cannot create a
        # timestamped event or conflict.
        assert len(events) == 1
        assert events[0].event_type == "shutdown"
        assert events[0].occurred_time is None
        assert conflicts == []
