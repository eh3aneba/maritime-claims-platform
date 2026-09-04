from datetime import UTC, datetime

from sqlalchemy import select

from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim
from app.modules.documents.models import (
    Document,
    DocumentMalwareScanStatus,
    DocumentProcessingStatus,
)
from app.modules.intelligence.models import DocumentExtraction
from app.modules.intelligence.service import run_running_hours_intelligence, run_workshop_report_intelligence
from app.modules.review.service import review_extraction
from app.modules.technical.service import build_technical_review
from app.modules.users.models import User
from tests.db_harness import TestingSessionLocal, reset_database
from tests.test_maintenance_workshop_intelligence import FakeProvider, sb, seed_claim_and_document, ss


def setup_function():
    reset_database()


def _review_workshop_evidence():
    text = "Workshop found bearing heavily damaged. Workshop suspects lubrication deficiency. Rotor repair possible."
    claim_id, document_id, user_id = seed_claim_and_document("workshop_report", text)
    null = ss(None, None, 0)
    payload = {
        "classification": {"document_type": "workshop_report", "confidence": .99},
        "workshop_name": null,
        "attendance_date": null,
        "vessel_name": null,
        "equipment_name": ss("Turbocharger", "Turbocharger"),
        "equipment_maker": null,
        "equipment_model": null,
        "equipment_serial_number": null,
        "repairable": sb(True, "Rotor repair possible"),
        "temporary_repair": sb(None, None, 0),
        "damage_findings": [
            {
                "component": ss("Bearing", "bearing"),
                "description": ss("Heavily damaged", "heavily damaged"),
                "extent": null,
                "measurement": null,
            }
        ],
        "repair_options": [
            {
                "scope": ss("Rotor repair", "Rotor repair possible"),
                "repair_or_replace": ss("repair", "Rotor repair possible"),
                "duration": null,
                "parts_required": null,
                "lead_time": null,
            }
        ],
        "suspected_cause_opinions": [
            ss("Lubrication deficiency", "Workshop suspects lubrication deficiency")
        ],
        "recommendations": [],
    }
    with TestingSessionLocal() as db:
        run = run_workshop_report_intelligence(
            db,
            document=db.get(Document, document_id),
            requested_by_id=user_id,
            provider=FakeProvider(payload),
        )
        rows = {
            row.field_path: row
            for row in db.scalars(select(DocumentExtraction).where(DocumentExtraction.ai_run_id == run.id))
        }
        user = db.get(User, user_id)
        review_extraction(
            db,
            extraction=rows["workshop.suspected_cause_opinions[0]"],
            reviewer=user,
            action="approve",
        )
        review_extraction(
            db,
            extraction=rows["workshop.damage_findings[0].description"],
            reviewer=user,
            action="approve",
        )
        db.commit()
    return claim_id, document_id


def test_technical_review_only_admits_current_usable_workshop_sources():
    claim_id, document_id = _review_workshop_evidence()

    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        baseline = build_technical_review(db, claim_id=claim.id, organization_id=claim.organization_id)
        repeat = build_technical_review(db, claim_id=claim.id, organization_id=claim.organization_id)

        assert baseline["evidence_state_fingerprint"] == repeat["evidence_state_fingerprint"]
        assert len(baseline["workshop_cause_opinions"]) == 1
        evidence = baseline["workshop_cause_opinions"][0]
        assert evidence["document_version"] == 1
        assert evidence["document_is_current"] is True
        assert evidence["document_processing_status"] == "processed"
        assert evidence["document_malware_scan_status"] == "legacy_unscanned"
        assert evidence["source_state"] == "current_usable"

        document = db.get(Document, document_id)
        document.processing_status = DocumentProcessingStatus.FAILED
        db.commit()
        failed = build_technical_review(db, claim_id=claim.id, organization_id=claim.organization_id)
        assert failed["workshop_cause_opinions"] == []
        assert failed["workshop_findings"] == []
        assert failed["evidence_state_fingerprint"] != baseline["evidence_state_fingerprint"]

        document.processing_status = DocumentProcessingStatus.PROCESSED
        document.malware_scan_status = DocumentMalwareScanStatus.INFECTED_QUARANTINED
        db.commit()
        quarantined = build_technical_review(db, claim_id=claim.id, organization_id=claim.organization_id)
        assert quarantined["workshop_cause_opinions"] == []
        assert quarantined["workshop_findings"] == []

        document.malware_scan_status = DocumentMalwareScanStatus.LEGACY_UNSCANNED
        document.is_current = False
        db.commit()
        superseded = build_technical_review(db, claim_id=claim.id, organization_id=claim.organization_id)
        assert superseded["workshop_cause_opinions"] == []
        assert superseded["workshop_findings"] == []

        document.is_current = True
        document.deleted_at = datetime.now(UTC)
        db.commit()
        deleted = build_technical_review(db, claim_id=claim.id, organization_id=claim.organization_id)
        assert deleted["workshop_cause_opinions"] == []
        assert deleted["workshop_findings"] == []


def test_canonical_technical_claim_fact_version_changes_live_state_fingerprint():
    text = "MT ORION Turbocharger No.2 RH since overhaul 14,800 hours. Last overhaul 2026-01-10. Maker interval 12,000 hours."
    claim_id, document_id, user_id = seed_claim_and_document("running_hours_record", text)
    payload = {
        "classification": {"document_type": "running_hours_record", "confidence": .99},
        "vessel_name": ss("MT ORION", "MT ORION"),
        "imo_number": ss(None, None, 0),
        "equipment_name": ss("Turbocharger No.2", "Turbocharger No.2"),
        "equipment_maker": ss(None, None, 0),
        "equipment_model": ss(None, None, 0),
        "equipment_serial_number": ss(None, None, 0),
        "total_running_hours": ss(None, None, 0),
        "running_hours_since_overhaul": ss("14,800 hours", "RH since overhaul 14,800 hours"),
        "last_overhaul_date": ss(None, None, 0),
        "recommended_overhaul_interval": ss(None, None, 0),
        "interval_extension_approved": sb(None, None, 0),
        "interval_extension_details": ss(None, None, 0),
    }

    with TestingSessionLocal() as db:
        run = run_running_hours_intelligence(
            db,
            document=db.get(Document, document_id),
            requested_by_id=user_id,
            provider=FakeProvider(payload),
        )
        row = db.scalar(
            select(DocumentExtraction).where(
                DocumentExtraction.ai_run_id == run.id,
                DocumentExtraction.field_path == "maintenance.running_hours_since_overhaul",
            )
        )
        user = db.get(User, user_id)
        review_extraction(db, extraction=row, reviewer=user, action="approve")
        db.commit()

        claim = db.get(Claim, claim_id)
        baseline = build_technical_review(db, claim_id=claim.id, organization_id=claim.organization_id)
        assert baseline["canonical_fact_versions"]["maintenance.running_hours_since_overhaul"] == 1

        fact = db.scalar(
            select(ClaimFact).where(
                ClaimFact.claim_id == claim.id,
                ClaimFact.field_path == "maintenance.running_hours_since_overhaul",
            )
        )
        fact.value = {"value": 15000.0, "unit": "hours", "raw": "15,000 hours"}
        fact.version += 1
        fact.approved_at = datetime.now(UTC)
        db.commit()

        evolved = build_technical_review(db, claim_id=claim.id, organization_id=claim.organization_id)
        assert evolved["canonical_fact_versions"]["maintenance.running_hours_since_overhaul"] == 2
        assert evolved["maintenance_facts"]["maintenance.running_hours_since_overhaul"]["value"] == 15000.0
        assert evolved["evidence_state_fingerprint"] != baseline["evidence_state_fingerprint"]
