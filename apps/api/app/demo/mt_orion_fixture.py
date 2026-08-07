"""Deterministic synthetic MT ORION AI fixture used only for demo seeding.

This module never calls an external model provider. It mirrors the regression pilot
so a design-partner environment can be populated reproducibly with AI_PROVIDER=disabled.
"""
from app.ai.gateway.base import AIRequest, AIResponse
from app.modules.intelligence.service import (
    run_ce_report_intelligence,
    run_engine_log_intelligence,
    run_invoice_intelligence,
    run_pms_history_intelligence,
    run_quotation_intelligence,
    run_running_hours_intelligence,
    run_workshop_report_intelligence,
)

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

