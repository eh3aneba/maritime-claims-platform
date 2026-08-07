"""End-to-end synthetic pilot for the MT ORION turbocharger claim.

This intentionally uses deterministic fake AI responses against real DOCX/XLSX fixture
files so the workflow can be regression-tested without sending claim evidence to an
external model provider.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from starlette.datastructures import Headers

from app.ai.gateway.base import AIRequest, AIResponse
from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.assessments.service import approve_assessment, generate_assessment, get_assessment, review_section
from app.modules.chronology.models import EvidenceConflict
from app.modules.chronology.service import build_chronology
from app.modules.claims.facts import ClaimFact
from app.modules.claims.models import Claim, ClaimPriority, ClaimStatus, ClaimType
from app.modules.claims.schemas import ClaimCreate
from app.modules.claims.service import change_claim_status, create_claim, update_current_reserve
from app.modules.documents.models import ConfidentialityLevel, Document, DocumentProcessingStatus
from app.modules.documents.service import create_document_from_upload
from app.modules.financial.models import FinancialFlagType, ReserveHistory
from app.modules.financial.service import build_financial_review
from app.modules.intelligence.models import AIReviewStatus, AIRun, DocumentExtraction
from app.modules.intelligence.service import (
    run_ce_report_intelligence,
    run_engine_log_intelligence,
    run_invoice_intelligence,
    run_pms_history_intelligence,
    run_quotation_intelligence,
    run_running_hours_intelligence,
    run_workshop_report_intelligence,
)
from app.modules.organizations.models import Organization
from app.modules.processing.models import DocumentProcessingJob, ProcessingJobStatus, ProcessingJobType
from app.modules.processing.service import process_job
from app.modules.review.service import list_review_groups, review_extraction
from app.modules.rules.models import ClaimIssue, RequirementPriority, RequirementStatus
from app.modules.rules.service import evaluate_claim_rules, get_rule_summary
from app.modules.tasks.schemas import DocumentRequestCreate
from app.modules.tasks.service import create_document_request, mark_request_sent
from app.modules.technical.service import build_technical_review
from app.modules.users.models import User, UserRole
from app.modules.vessels.models import Vessel
from tests.db_harness import TestingSessionLocal, reset_database

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "docs" / "pilot" / "mt-orion" / "documents"
PASSWORD = "Strong-Pilot-2026"


def ss(value, quote, confidence=0.98):
    return {"value": value, "confidence": confidence, "source": {"segment_index": 0 if value is not None else None, "quote": quote}}


def sb(value, quote, confidence=0.98):
    return ss(value, quote, confidence)


class FixtureProvider:
    name = "pilot_fixture"
    _model = "deterministic-pilot-v1"

    def __init__(self, payload):
        self.payload = payload

    def generate(self, request: AIRequest) -> AIResponse:
        return AIResponse(
            provider=self.name,
            model=self._model,
            structured_output=self.payload,
            output_text="{}",
            usage={"input_tokens": 0, "output_tokens": 0},
            raw_response_id="pilot-fixture",
        )


def _ce_payload():
    null = ss(None, None, 0)
    stop_quote = "The main engine was stopped at approximately 10:45 UTC for inspection and Turbocharger No.2 was subsequently isolated."
    reduce_quote = "At approximately 10:40 UTC, main engine load was reduced as a precaution."
    first_quote = "At approximately 10:30 UTC on 10 July 2026, while the vessel was underway, abnormal vibration was first noticed from Main Engine Turbocharger No.2."
    return {
        "classification": {"document_type": "chief_engineer_report", "confidence": 0.99},
        "identification": {
            "vessel_name": ss("MT ORION", "Vessel: MT ORION"),
            "imo_number": ss("7000301", "IMO: 7000301"),
            "report_date": ss("2026-07-11", "Report date: 11 July 2026"),
            "author_name": ss("A. Rahman", "Author: A. Rahman, Chief Engineer"),
            "author_rank": ss("Chief Engineer", "Author: A. Rahman, Chief Engineer"),
        },
        "incident": {
            "date": ss("2026-07-10", first_quote),
            "time": ss("10:30", first_quote),
            "timezone": ss("UTC", first_quote),
            "location": null,
            "voyage_from": null,
            "voyage_to": null,
            "cargo_status": null,
            "first_observation": ss("Abnormal vibration was first noticed from Main Engine Turbocharger No.2.", first_quote),
        },
        "equipment": {
            "equipment_type": ss("Turbocharger", "Equipment: Main Engine Turbocharger No.2"),
            "equipment_name": ss("Main Engine Turbocharger No.2", "Equipment: Main Engine Turbocharger No.2"),
            "maker": null,
            "model": null,
            "serial_number": null,
        },
        "symptoms": [
            ss("Abnormal vibration", first_quote),
            ss("Elevated exhaust temperature", "Exhaust temperature was observed to be elevated compared with the preceding watch."),
        ],
        "immediate_actions": [
            ss("Main engine load was reduced as a precaution.", reduce_quote),
            ss("The main engine was stopped at approximately 10:45 UTC for inspection.", stop_quote),
            ss("Turbocharger No.2 was subsequently isolated.", stop_quote),
        ],
        "reported_events": [
            {
                "date": ss("2026-07-10", first_quote),
                "time": ss("10:30", first_quote),
                "timezone": ss("UTC", first_quote),
                "event_type": ss("observation", first_quote),
                "description": ss("Abnormal vibration was first noticed from Main Engine Turbocharger No.2.", first_quote),
            },
            {
                "date": ss("2026-07-10", reduce_quote),
                "time": ss("10:40", reduce_quote),
                "timezone": ss("UTC", reduce_quote),
                "event_type": ss("load_reduction", reduce_quote),
                "description": ss("Main engine load was reduced as a precaution.", reduce_quote),
            },
            {
                "date": ss("2026-07-10", stop_quote),
                "time": ss("10:45", stop_quote),
                "timezone": ss("UTC", stop_quote),
                "event_type": ss("shutdown", stop_quote),
                "description": ss("The main engine was stopped at approximately 10:45 UTC for inspection.", stop_quote),
            },
            {
                "date": ss("2026-07-10", stop_quote),
                "time": ss(None, None, 0),
                "timezone": ss(None, None, 0),
                "event_type": ss("isolation", stop_quote),
                "description": ss("Turbocharger No.2 was subsequently isolated.", stop_quote),
            },
        ],
        "operational_impact": {
            "engine_stopped": sb(True, stop_quote),
            "load_reduced": sb(True, reduce_quote),
            "speed_reduced": sb(None, None, 0),
            "immobilized": sb(None, None, 0),
            "deviation": sb(None, None, 0),
            "towage": sb(None, None, 0),
        },
        "suspected_cause_opinions": [],
        "recommendations": [ss("Workshop attendance is recommended to dismantle and inspect the rotor assembly and bearings.", "Workshop attendance is recommended to dismantle and inspect the rotor assembly and bearings before deciding whether repair or replacement is required.")],
    }


def _engine_payload():
    null = ss(None, None, 0)
    rows = [
        ("10:30", "680", "82%", "19800", "488 C", "4.1 bar", None, None, None, "observation"),
        ("10:40", "640", "75%", "19000", "496 C", "4 bar", None, None, "Engine load reduced", "load_reduction"),
        ("10:52", "620", "70%", "18400", "510 C", "3.9 bar", "HIGH TURBOCHARGER VIBRATION ALARM", None, "Further load reduction ordered", "alarm"),
        ("11:05", "0", "0%", "0", "442 C", "3.8 bar", None, True, "Main engine stopped for inspection", "shutdown"),
        ("11:12", "0", "0%", "0", "395 C", "3.8 bar", None, None, "Turbocharger No.2 isolated", "isolation"),
    ]
    events = []
    for t, rpm, load, tc, temp, pressure, alarm, shutdown, action, event_type in rows:
        quote = next(line for line in {
            "10:30": "2026-07-10 | 10:30 | UTC | 680 | 82 | 19800 | 488 | 4.1 | Abnormal vibration reported by duty engineer | Monitor closely; Chief Engineer called",
            "10:40": "2026-07-10 | 10:40 | UTC | 640 | 75 | 19000 | 496 | 4 | Vibration persists | Engine load reduced",
            "10:52": "2026-07-10 | 10:52 | UTC | 620 | 70 | 18400 | 510 | 3.9 | HIGH TURBOCHARGER VIBRATION ALARM | Further load reduction ordered",
            "11:05": "2026-07-10 | 11:05 | UTC | 0 | 0 | 0 | 442 | 3.8 | MAIN ENGINE SHUTDOWN | Main engine stopped for inspection",
            "11:12": "2026-07-10 | 11:12 | UTC | 0 | 0 | 0 | 395 | 3.8 | Turbocharger No.2 isolated | Inspection commenced",
        }.values() if f"| {t} |" in line)
        events.append({
            "date": ss("2026-07-10", quote),
            "time": ss(t, quote),
            "timezone": ss("UTC", quote),
            "event_type": ss(event_type, quote),
            "rpm": ss(f"{rpm} rpm", quote),
            "engine_load": ss(load, quote),
            "turbocharger_speed": ss(f"{tc} rpm", quote),
            "exhaust_temperature": ss(temp, quote),
            "lube_oil_pressure": ss(pressure, quote),
            "alarm": ss(alarm, quote) if alarm is not None else null,
            "shutdown": sb(shutdown, quote) if shutdown is not None else sb(None, None, 0),
            "restart": sb(None, None, 0),
            "action": ss(action, quote) if action is not None else null,
            "remarks": ss("Abnormal vibration reported by duty engineer", quote) if t == "10:30" else null,
        })
    return {
        "classification": {"document_type": "engine_log", "confidence": 0.99},
        "identification": {"vessel_name": null, "imo_number": null, "log_date": ss("2026-07-10", events[0]["date"]["source"]["quote"]), "engine_or_equipment": null},
        "events": events,
    }


def _running_hours_payload():
    null = ss(None, None, 0)
    return {
        "classification": {"document_type": "running_hours_record", "confidence": 0.99},
        "vessel_name": ss("MT ORION", "Vessel | MT ORION | Synthetic pilot fixture"),
        "imo_number": null,
        "equipment_name": ss("Main Engine Turbocharger No.2", "Equipment | Main Engine Turbocharger No.2 |"),
        "equipment_maker": null,
        "equipment_model": null,
        "equipment_serial_number": null,
        "total_running_hours": ss("48200 hours", "Total running hours | 48200 | hours"),
        "running_hours_since_overhaul": ss("14800 hours", "Running hours since last overhaul | 14800 | hours"),
        "last_overhaul_date": ss("2026-01-10", "Last overhaul date | 2026-01-10 |"),
        "recommended_overhaul_interval": ss("12000 hours", "Maker recommended overhaul interval | 12000 | hours"),
        # Deliberately over-confident AI candidate: human review rejects this because
        # 'no approved extension on file' does not prove no extension exists elsewhere.
        "interval_extension_approved": sb(False, "Approved interval extension | No approved extension on file |"),
        "interval_extension_details": ss("No approved extension on file", "Approved interval extension | No approved extension on file |"),
    }


def _pms_payload():
    null = ss(None, None, 0)
    q1 = "TC-100 | Turbocharger major overhaul | 2026-05-20 | 12000 | 14800 | Deferred | Yes | Deferred pending spare availability; no maker extension attached"
    q2 = "TC-110 | Turbocharger lube oil filter inspection | 2026-06-15 | 14500 | 14520 | Completed | No | No abnormal contamination recorded"
    q3 = "TC-120 | Turbocharger vibration check | 2026-06-30 | 14700 | 14710 | Completed | No | Vibration within vessel PMS acceptance at that date"
    return {
        "classification": {"document_type": "pms_history", "confidence": 0.99},
        "vessel_name": null,
        "imo_number": null,
        "equipment_name": ss("Turbocharger", q1),
        "overall_status": ss("Deferred", q1),
        "overhaul_deferred": sb(True, q1),
        "running_hours_since_overhaul": ss("14800 hours", q1),
        "last_overhaul_date": null,
        "records": [
            {"job_code": ss("TC-100", q1), "task": ss("Turbocharger major overhaul", q1), "scheduled_date": ss("2026-05-20", q1), "completed_date": null, "scheduled_running_hours": ss("12000 hours", q1), "actual_running_hours": ss("14800 hours", q1), "status": ss("Deferred", q1), "deferred": sb(True, q1), "overdue": sb(None, None, 0), "remarks": ss("Deferred pending spare availability; no maker extension attached", q1)},
            {"job_code": ss("TC-110", q2), "task": ss("Turbocharger lube oil filter inspection", q2), "scheduled_date": ss("2026-06-15", q2), "completed_date": null, "scheduled_running_hours": ss("14500 hours", q2), "actual_running_hours": ss("14520 hours", q2), "status": ss("Completed", q2), "deferred": sb(False, q2), "overdue": sb(None, None, 0), "remarks": ss("No abnormal contamination recorded", q2)},
            {"job_code": ss("TC-120", q3), "task": ss("Turbocharger vibration check", q3), "scheduled_date": ss("2026-06-30", q3), "completed_date": null, "scheduled_running_hours": ss("14700 hours", q3), "actual_running_hours": ss("14710 hours", q3), "status": ss("Completed", q3), "deferred": sb(False, q3), "overdue": sb(None, None, 0), "remarks": ss("Vibration within vessel PMS acceptance at that date", q3)},
        ],
    }


def _workshop_payload():
    null = ss(None, None, 0)
    repair_quote = "The rotor assembly is considered repairable subject to detailed dimensional inspection. A complete turbocharger replacement is also technically possible but represents a materially wider scope."
    cause_quote = "The workshop suspects lubrication deficiency may have contributed to the bearing damage. This is a preliminary workshop opinion only; the cause is not conclusively established."
    return {
        "classification": {"document_type": "workshop_report", "confidence": 0.99},
        "workshop_name": ss("Ocean Turbo Services", "Workshop: Ocean Turbo Services"),
        "attendance_date": ss("2026-07-12", "Attendance date: 12 July 2026"),
        "vessel_name": ss("MT ORION", "Vessel: MT ORION"),
        "equipment_name": ss("Main Engine Turbocharger No.2", "Equipment: Main Engine Turbocharger No.2"),
        "equipment_maker": null,
        "equipment_model": null,
        "equipment_serial_number": null,
        "repairable": sb(True, repair_quote),
        "temporary_repair": sb(None, None, 0),
        "damage_findings": [
            {"component": ss("Journal bearing", "Journal bearing heavily scored and heat affected."), "description": ss("Heavily scored and heat affected", "Journal bearing heavily scored and heat affected."), "extent": null, "measurement": null},
            {"component": ss("Rotor assembly", "Rotor assembly shows contact marks and local blade damage."), "description": ss("Contact marks and local blade damage", "Rotor assembly shows contact marks and local blade damage."), "extent": null, "measurement": null},
            {"component": ss("Bearing clearance", "Measured bearing clearance exceeds the workshop service limit."), "description": ss("Exceeds workshop service limit", "Measured bearing clearance exceeds the workshop service limit."), "extent": null, "measurement": ss("Exceeds workshop service limit", "Measured bearing clearance exceeds the workshop service limit.")},
        ],
        "repair_options": [
            {"scope": ss("Rotor assembly repair subject to dimensional inspection", repair_quote), "repair_or_replace": ss("repair", repair_quote), "duration": null, "parts_required": null, "lead_time": null},
            {"scope": ss("Complete turbocharger replacement", repair_quote), "repair_or_replace": ss("replace", repair_quote), "duration": null, "parts_required": null, "lead_time": null},
        ],
        "suspected_cause_opinions": [ss("Lubrication deficiency may have contributed to the bearing damage", cause_quote)],
        "recommendations": [
            ss("Lubricating oil analysis records", "Lubricating oil analysis records"),
            ss("Filter inspection record", "Filter inspection record"),
            ss("Recent PMS history", "Recent PMS history"),
            ss("Previous overhaul report and clearances", "Previous overhaul report and clearances"),
        ],
    }


def _quote_payload(supplier, number, total, scope, items, betterment_index=None):
    null = ss(None, None, 0)
    quote_map = {
        "Q-A-260": {
            "supplier": "Supplier | Ocean Turbo Services |",
            "number": "Quotation No | Q-A-260 |",
            "date": "Date | 2026-07-12 |",
            "currency": "Currency | USD |",
            "scope": "Scope | Rotor assembly repair and bearing renewal |",
            "lead": "Lead Time | 5 | days",
            "duration": "Repair Duration | 4 | days",
            "total": "Total | 260000 |",
        },
        "Q-B-470": {
            "supplier": "Supplier | Global Turbo Marine |",
            "number": "Quotation No | Q-B-470 |",
            "date": "Date | 2026-07-12 |",
            "currency": "Currency | USD |",
            "scope": "Scope | Complete turbocharger replacement with upgraded controller |",
            "lead": "Lead Time | 14 | days",
            "duration": "Repair Duration | 3 | days",
            "total": "Total | 470000 |",
        },
    }[number]
    lines = []
    for i, (desc, amount, notes, category) in enumerate(items):
        q = f"{desc} | {amount} | {notes}"
        lines.append({
            "description": ss(desc, q), "quantity": ss("1", q), "unit": null,
            "unit_price": ss(f"{amount} USD", q), "amount": ss(f"{amount} USD", q),
            "category_candidate": ss(category, q),
            "potential_betterment_cue": sb(i == betterment_index, q),
            "potential_ordinary_maintenance_cue": sb(False, q),
        })
    return {
        "classification": {"document_type": "quotation", "confidence": 0.99},
        "supplier": ss(supplier, quote_map["supplier"]), "quotation_number": ss(number, quote_map["number"]),
        "quotation_date": ss("2026-07-12", quote_map["date"]), "currency": ss("USD", quote_map["currency"]),
        "subtotal": ss(f"{total} USD", f"Subtotal | {total} |"), "tax": null, "freight": null,
        "total": ss(f"{total} USD", quote_map["total"]), "validity": null,
        "lead_time": ss("5 days" if number == "Q-A-260" else "14 days", quote_map["lead"]),
        "repair_duration": ss("4 days" if number == "Q-A-260" else "3 days", quote_map["duration"]),
        "scope_summary": ss(scope, quote_map["scope"]), "exclusions": [], "line_items": lines,
    }


def _invoice_payload():
    null = ss(None, None, 0)
    line = "Emergency technician mobilisation retainer | 25000 | Advance mobilisation charge"
    return {
        "classification": {"document_type": "invoice", "confidence": 0.99},
        "supplier": ss("Ocean Turbo Services", "Supplier | Ocean Turbo Services |"),
        "invoice_number": ss("INV-009", "Invoice No | INV-009 |"),
        "invoice_date": ss("2026-07-09", "Invoice Date | 2026-07-09 |"),
        "purchase_order": null,
        "related_quotation_number": ss("Q-A-260", "Related Quotation | Q-A-260 |"),
        "currency": ss("USD", "Currency | USD |"),
        "subtotal": ss("25000 USD", "Subtotal | 25000 |"),
        "tax": ss("0 USD", "Tax | 0 |"),
        "discount": null,
        "total": ss("25000 USD", "Total | 25000 |"),
        "payment_terms": ss("30 days", "Payment Terms | 30 days |"),
        "line_items": [{
            "description": ss("Emergency technician mobilisation retainer", line),
            "quantity": ss("1", line), "unit": null, "unit_price": ss("25000 USD", line),
            "amount": ss("25000 USD", line), "category_candidate": ss("Technician Attendance", line),
            "potential_betterment_cue": sb(False, line), "potential_ordinary_maintenance_cue": sb(False, line),
        }],
    }


AI_CASES = {
    "02_chief_engineer_report.docx": (run_ce_report_intelligence, _ce_payload),
    "03_engine_log.xlsx": (run_engine_log_intelligence, _engine_payload),
    "04_running_hours.xlsx": (run_running_hours_intelligence, _running_hours_payload),
    "05_pms_history.xlsx": (run_pms_history_intelligence, _pms_payload),
    "06_workshop_report.docx": (run_workshop_report_intelligence, _workshop_payload),
    "07_quotation_A.xlsx": (run_quotation_intelligence, lambda: _quote_payload(
        "Ocean Turbo Services", "Q-A-260", 260000, "Rotor assembly repair and bearing renewal",
        [("Rotor assembly repair", 210000, "Repair existing rotor assembly", "Permanent Repair"), ("Bearing set renewal", 28000, "Standard replacement bearing set", "Spare Parts"), ("Technician attendance", 22000, "Four-day attendance", "Technician Attendance")],
    )),
    "08_quotation_B.xlsx": (run_quotation_intelligence, lambda: _quote_payload(
        "Global Turbo Marine", "Q-B-470", 470000, "Complete turbocharger replacement with upgraded controller",
        [("Complete turbocharger unit", 420000, "New replacement unit", "Spare Parts"), ("Upgraded electronic controller", 30000, "Latest generation controller", "Spare Parts"), ("Commissioning attendance", 20000, "Testing and commissioning", "Commissioning")], betterment_index=1,
    )),
    "09_invoice.xlsx": (run_invoice_intelligence, _invoice_payload),
}

DOC_TYPES = {
    "01_claim_notification.docx": "claim_notification",
    "02_chief_engineer_report.docx": "chief_engineer_report",
    "03_engine_log.xlsx": "engine_log",
    "04_running_hours.xlsx": "running_hours_record",
    "05_pms_history.xlsx": "pms_record",
    "06_workshop_report.docx": "workshop_report",
    "07_quotation_A.xlsx": "quotation",
    "08_quotation_B.xlsx": "quotation",
    "09_invoice.xlsx": "invoice",
}

MIME = {".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}


def setup_function():
    reset_database()


async def _upload(db, claim, user, path: Path):
    with path.open("rb") as fh:
        upload = UploadFile(file=fh, filename=path.name, headers=Headers({"content-type": MIME[path.suffix]}))
        return await create_document_from_upload(
            db, claim=claim, current_user=user, upload=upload,
            document_type=DOC_TYPES[path.name], confidentiality_level=ConfidentialityLevel.CONFIDENTIAL,
        )


def _process_text_jobs(db):
    jobs = list(db.scalars(select(DocumentProcessingJob).where(DocumentProcessingJob.job_type == ProcessingJobType.EXTRACT_TEXT)))
    for job in jobs:
        job.status = ProcessingJobStatus.RUNNING
        job.attempt_count = max(job.attempt_count, 1)
        process_job(db, job=job)


def _review_run(db, run: AIRun, reviewer: User):
    for extraction in list(db.scalars(select(DocumentExtraction).where(DocumentExtraction.ai_run_id == run.id).order_by(DocumentExtraction.field_path))):
        if extraction.field_path == "maintenance.interval_extension_approved":
            review_extraction(db, extraction=extraction, reviewer=reviewer, action="reject", reason="Source only states that no approved extension is on file; it does not prove that no valid extension exists elsewhere.")
        else:
            review_extraction(db, extraction=extraction, reviewer=reviewer, action="approve", reason="Synthetic pilot source reviewed.")
    db.commit()


def test_mt_orion_full_pilot_workflow(tmp_path):
    settings = get_settings()
    previous_storage = settings.local_storage_path
    settings.local_storage_path = str(tmp_path / "evidence-store")
    try:
        with TestingSessionLocal() as db:
            org = Organization(name="Pilot Marine Insurer", slug="pilot")
            db.add(org); db.flush()
            manager = User(organization_id=org.id, email="manager@demo.mcri.app", full_name="Pilot Claims Manager", password_hash=hash_password(PASSWORD), role=UserRole.CLAIMS_MANAGER, is_active=True)
            vessel = Vessel(organization_id=org.id, name="MT ORION", imo_number="7000301", vessel_type="Oil Tanker", flag="Marshall Islands", class_society="Pilot Class")
            db.add_all([manager, vessel]); db.flush()
            claim = create_claim(db, organization_id=org.id, current_user=manager, payload=ClaimCreate(
                vessel_id=vessel.id, incident_date=date(2026,7,10), notification_date=date(2026,7,11),
                incident_description="Main engine turbocharger No.2 failure with abnormal vibration, load reduction and subsequent shutdown.",
                claim_type=ClaimType.HULL_MACHINERY, priority=ClaimPriority.HIGH, estimated_loss=Decimal("550000"), currency="USD", handler_id=manager.id,
            ))
            db.commit()
            assert claim.claim_reference == "MCRI-HM-2026-0001"

            # Progress the claim to investigation before document completeness is evaluated.
            change_claim_status(db, claim=claim, new_status=ClaimStatus.TRIAGE, current_user=manager)
            change_claim_status(db, claim=claim, new_status=ClaimStatus.INVESTIGATION, current_user=manager)
            db.commit()

            uploaded = {}
            for path in sorted(FIXTURE_DIR.iterdir()):
                uploaded[path.name] = asyncio.run(_upload(db, claim, manager, path))
            assert len(uploaded) == 9
            _process_text_jobs(db)
            assert all(doc.processing_status == DocumentProcessingStatus.PROCESSED for doc in uploaded.values())

            runs = []
            for filename, (runner, payload_factory) in AI_CASES.items():
                run = runner(db, document=uploaded[filename], requested_by_id=manager.id, provider=FixtureProvider(payload_factory()))
                _review_run(db, run, manager)
                runs.append(run)
            assert len(runs) == 8
            assert all(run.status.value == "completed" for run in runs)

            # Usability hardening groups repeatable rows/line-items so the human review
            # workload is measured in meaningful evidence units rather than raw fields.
            candidate_count = len(list(db.scalars(select(DocumentExtraction).where(DocumentExtraction.claim_id == claim.id))))
            review_groups = list_review_groups(
                db, organization_id=claim.organization_id, claim_id=claim.id, human_status=None, limit_groups=500
            )
            assert len(review_groups) < candidate_count
            assert candidate_count - len(review_groups) >= 50

            # The pilot intentionally rejects one over-confident candidate.
            rejected = db.scalar(select(DocumentExtraction).where(DocumentExtraction.field_path == "maintenance.interval_extension_approved"))
            assert rejected and rejected.human_status == AIReviewStatus.REJECTED
            assert db.scalar(select(ClaimFact).where(ClaimFact.claim_id == claim.id, ClaimFact.field_path == "maintenance.interval_extension_approved")) is None

            # Rules / technical review.
            evaluate_claim_rules(db, claim=claim, user=manager, trigger="pilot_after_review")
            issues = list(db.scalars(select(ClaimIssue).where(ClaimIssue.claim_id == claim.id, ClaimIssue.is_active.is_(True))))
            rule_ids = {issue.rule_id for issue in issues}
            assert {"TECH-001", "TECH-003"}.issubset(rule_ids)
            technical = build_technical_review(db, claim_id=claim.id, organization_id=claim.organization_id)
            assert any(row["key"] == "tech_001" for row in technical["matrix"])
            assert any(row["key"] == "tech_003" for row in technical["matrix"])
            assert any(row["key"].startswith("workshop_opinion_") for row in technical["matrix"])

            # Chronology and conflict detection.
            events, conflicts = build_chronology(db, claim=claim, user=manager)
            db.commit()
            assert len(events) >= 5
            shutdown_conflicts = [c for c in conflicts if c.topic == "shutdown time"]
            assert len(shutdown_conflicts) == 1
            # CE v2 preserves the narrative shutdown time (approximately 10:45) instead
            # of copying incident.time=10:30, so the reviewed difference is 20 minutes.
            assert shutdown_conflicts[0].difference_minutes == Decimal("20.0")
            assert shutdown_conflicts[0].materiality.value == "medium"
            # The CE isolation statement has no explicit clock time and must remain
            # relative/undated rather than inheriting 10:30.
            relative_isolations = [e for e in events if e.event_type == "isolation" and e.occurred_time is None]
            assert relative_isolations

            # Financial review after entering the financial stage.
            change_claim_status(db, claim=claim, new_status=ClaimStatus.FINANCIAL_REVIEW, current_user=manager)
            db.commit(); evaluate_claim_rules(db, claim=claim, user=manager, trigger="pilot_financial_stage")
            financial = build_financial_review(db, claim=claim, user_id=manager.id)
            db.commit()
            flag_types = {flag.flag_type for flag in financial["flags"] if flag.status.value == "open"}
            assert FinancialFlagType.INVOICE_PREDATES_INCIDENT in flag_types
            assert FinancialFlagType.QUOTE_SCOPE_DIFFERENCE in flag_types
            assert FinancialFlagType.POTENTIAL_BETTERMENT in flag_types
            assert financial["totals_by_currency"]["USD"] == Decimal("25000.00")

            # Reserve history.
            update_current_reserve(db, claim=claim, amount=Decimal("575000"))
            db.add(ReserveHistory(organization_id=claim.organization_id, claim_id=claim.id, amount=Decimal("575000"), currency="USD", reason="Two repair alternatives reviewed; replacement exposure remains possible.", created_by_id=manager.id, created_at=datetime.now(UTC)))
            db.commit()

            # Missing critical evidence becomes an auditable external request workflow.
            evaluate_claim_rules(db, claim=claim, user=manager, trigger="pilot_before_request")
            summary = get_rule_summary(db, claim=claim)
            critical_missing = [r for r in summary.requirements if r.priority == RequirementPriority.CRITICAL and r.status == RequirementStatus.MISSING]
            missing_labels = {r.document_label for r in critical_missing}
            assert "H&M Policy / Wording" in missing_labels
            assert "Last Overhaul Report" in missing_labels
            batch, tasks = create_document_request(db, claim=claim, user=manager, payload=DocumentRequestCreate(all_critical=True, due_date=date(2026,7,17), recipient_label="Shipowner / Technical Manager"))
            mark_request_sent(db, claim=claim, batch=batch, user=manager)
            assert len(tasks) == len(critical_missing)

            # Full assessment is correctly blocked; a preliminary assessment is generated.
            assessment = generate_assessment(db, claim=claim, user=manager, allow_if_not_ready=True, override_reason="Synthetic pilot assessment while policy and overhaul evidence remain outstanding.")
            assessment, sections = get_assessment(db, claim=claim, assessment_id=assessment.id)
            assert assessment.is_preliminary is True
            assert len(sections) == 11
            financial_section = next(section for section in sections if section.section_key == "financial")
            assert "Reviewed invoiced/claimed cost: USD 25,000.00" in financial_section.draft_text
            assert "Ocean Turbo Services Q-A-260: USD 260,000.00" in financial_section.draft_text
            assert "Global Turbo Marine Q-B-470: USD 470,000.00" in financial_section.draft_text
            assert "not cumulative claim exposure" in financial_section.draft_text
            assert "755,000.00" not in financial_section.draft_text
            for section in sections:
                review_section(db, claim=claim, section=section, user=manager, action="approve", text=None)
            approve_assessment(db, claim=claim, assessment=assessment, user=manager, note="Synthetic end-to-end pilot complete")
            assert assessment.status.value == "approved"

            # Final smoke metrics.
            assert db.scalar(select(Document).where(Document.claim_id == claim.id).count()) if False else True
            assert len(list(db.scalars(select(Document).where(Document.claim_id == claim.id)))) == 9
            assert len(list(db.scalars(select(AIRun).where(AIRun.claim_id == claim.id)))) == 8
            assert len(list(db.scalars(select(EvidenceConflict).where(EvidenceConflict.claim_id == claim.id, EvidenceConflict.is_active.is_(True))))) >= 1
    finally:
        settings.local_storage_path = previous_storage
