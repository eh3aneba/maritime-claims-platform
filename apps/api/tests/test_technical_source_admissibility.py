from datetime import UTC, datetime

from sqlalchemy import select

from app.modules.claims.models import Claim
from app.modules.documents.models import (
    Document,
    DocumentMalwareScanStatus,
    DocumentProcessingStatus,
)
from app.modules.intelligence.models import DocumentExtraction
from app.modules.intelligence.service import run_workshop_report_intelligence
from app.modules.review.service import review_extraction
from app.modules.technical.service import (
    build_technical_review,
    record_technical_decision,
    technical_decision_history,
)
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
    return claim_id, document_id, user_id


def _review(db, claim_id):
    claim = db.get(Claim, claim_id)
    return build_technical_review(db, claim_id=claim.id, organization_id=claim.organization_id)


def test_technical_review_only_admits_current_usable_workshop_sources():
    claim_id, document_id, _ = _review_workshop_evidence()

    with TestingSessionLocal() as db:
        baseline = _review(db, claim_id)
        assert len(baseline["workshop_cause_opinions"]) == 1
        assert len(baseline["workshop_findings"]) == 1
        evidence = baseline["workshop_cause_opinions"][0]
        assert evidence["document_version"] == 1
        assert evidence["document_is_current"] is True
        assert evidence["document_processing_status"] == "processed"
        assert evidence["document_malware_scan_status"] == "legacy_unscanned"
        assert evidence["source_state"] == "current_usable"

        document = db.get(Document, document_id)
        document.processing_status = DocumentProcessingStatus.FAILED
        db.commit()
        failed = _review(db, claim_id)
        assert failed["workshop_cause_opinions"] == []
        assert failed["workshop_findings"] == []

        document.processing_status = DocumentProcessingStatus.PROCESSED
        document.malware_scan_status = DocumentMalwareScanStatus.INFECTED_QUARANTINED
        db.commit()
        quarantined = _review(db, claim_id)
        assert quarantined["workshop_cause_opinions"] == []
        assert quarantined["workshop_findings"] == []

        document.malware_scan_status = DocumentMalwareScanStatus.LEGACY_UNSCANNED
        document.is_current = False
        db.commit()
        superseded = _review(db, claim_id)
        assert superseded["workshop_cause_opinions"] == []
        assert superseded["workshop_findings"] == []

        document.is_current = True
        document.deleted_at = datetime.now(UTC)
        db.commit()
        deleted = _review(db, claim_id)
        assert deleted["workshop_cause_opinions"] == []
        assert deleted["workshop_findings"] == []


def test_unusable_source_retains_stale_lineage_and_supports_deliberate_re_review():
    claim_id, document_id, user_id = _review_workshop_evidence()

    with TestingSessionLocal() as db:
        claim = db.get(Claim, claim_id)
        baseline = build_technical_review(db, claim_id=claim.id, organization_id=claim.organization_id)
        topic = next(row for row in baseline["matrix"] if row["topic_kind"] == "workshop_opinion")

        first = record_technical_decision(
            db,
            claim_id=claim.id,
            organization_id=claim.organization_id,
            topic_key=topic["key"],
            action="needs_more_evidence",
            note="Keep this workshop opinion open pending independent technical evidence.",
            expected_state_fingerprint=topic["state_fingerprint"],
            expected_state_version=topic["state_version"],
            confirm_re_review=False,
            decided_by_id=user_id,
        )
        db.commit()
        first_hash = first.decision_hash

        document = db.get(Document, document_id)
        document.malware_scan_status = DocumentMalwareScanStatus.INFECTED_QUARANTINED
        db.commit()

        evolved = build_technical_review(db, claim_id=claim.id, organization_id=claim.organization_id)
        assert evolved["workshop_cause_opinions"] == []
        historical = next(row for row in evolved["matrix"] if row["key"] == topic["key"])
        assert historical["status"] == "historical_evidence_unavailable"
        assert historical["decision_state"] == "stale"
        assert historical["state_version"] == topic["state_version"] + 1
        assert historical["evidence_for"] == []
        assert historical["latest_decision"]["decision_hash"] == first_hash

        stale_history = technical_decision_history(
            db,
            claim_id=claim.id,
            organization_id=claim.organization_id,
            topic_key=topic["key"],
        )
        assert stale_history["decision_state"] == "stale"
        assert stale_history["current_state_fingerprint"] == historical["state_fingerprint"]
        assert stale_history["current_state_version"] == historical["state_version"]
        assert len(stale_history["items"]) == 1

        second = record_technical_decision(
            db,
            claim_id=claim.id,
            organization_id=claim.organization_id,
            topic_key=topic["key"],
            action="keep_open",
            note="Source is no longer usable; keep the investigation open pending replacement evidence.",
            expected_state_fingerprint=historical["state_fingerprint"],
            expected_state_version=historical["state_version"],
            confirm_re_review=True,
            decided_by_id=user_id,
        )
        db.commit()

        refreshed = build_technical_review(db, claim_id=claim.id, organization_id=claim.organization_id)
        historical_current = next(row for row in refreshed["matrix"] if row["key"] == topic["key"])
        assert historical_current["decision_state"] == "current"
        assert historical_current["latest_decision"]["decision_hash"] == second.decision_hash

        history = technical_decision_history(
            db,
            claim_id=claim.id,
            organization_id=claim.organization_id,
            topic_key=topic["key"],
        )
        assert len(history["items"]) == 2
        assert history["items"][1]["previous_decision_hash"] == history["items"][0]["decision_hash"]
        assert history["decision_state"] == "current"
