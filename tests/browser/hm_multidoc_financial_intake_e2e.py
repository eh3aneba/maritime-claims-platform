"""HM-06: real manual financial-source intake with AI fully disabled.

Isolated CI browser uses four truly uploadable invented DOCX records:
notice, alternative USD repair quote, alternative EUR repair quote and
an inspection invoice of unknown payment status. The financial screen
must list the three source documents WITHOUT pricing, currency
conversion, loss/settlement/reserve assertions or cost approval.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.hm_multidoc_packs import load_corpus, make_upload_bytes
from hm_multidoc_journey_e2e import (
    API, WEB, ORG, EMAIL, PASSWORD, _ok, _milliseconds,
)


def _guard() -> None:
    if (
        os.getenv("APP_ENV") != "test"
        or os.getenv("MCRI_SYNTHETIC_ONLY_CONFIRM") != "YES"
        or os.getenv("AI_PROVIDER") != "disabled"
        or WEB != "http://127.0.0.1:3000"
        or API != "http://127.0.0.1:8000"
        or len(PASSWORD) < 12
    ):
        raise SystemExit("isolated_synthetic_browser_test_environment_required")


def main() -> None:
    _guard()
    case = load_corpus()["cases"][5]
    if (
        case["case_id"] != "HM-06"
        or case["dataset_split"] != "holdout"
        or len(case["documents"]) != 4
        or [d["document_type"] for d in case["documents"]]
        != ["claim_notification", "quotation", "quotation", "invoice"]
    ):
        raise ValueError("unexpected_hm06_synthetic_financial_case")
    if not all(
        any(token in line for doc in case["documents"] for line in doc["source_lines"])
        for token in ("USD 265000", "EUR 231000", "USD 18200")
    ):
        raise ValueError("hm06_fixed_source_values_missing")

    start = time.monotonic()
    stages: dict[str, int] = {}
    run_id = uuid4().hex[:10]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1060})
        page = context.new_page()
        stage = time.monotonic()
        page.goto(WEB + "/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")
        request = context.request
        vessel = _ok(
            request.post(API + "/api/v1/vessels", data={
                "name": "SYNTHETIC HM FIR " + run_id,
                "vessel_type": "tanker",
            }), "hm06_create_vessel",
        )
        claim = _ok(
            request.post(API + "/api/v1/claims", data={
                "vessel_id": vessel["id"],
                "incident_date": case["incident_date"],
                "notification_date": case["notification_date"],
                "incident_description": case["claim_description"],
                "external_reference": "SYNTHETIC-HM-06-" + run_id,
                "claim_type": "hull_machinery",
                "claim_subtype": "machinery_damage",
            }), "hm06_create_claim",
        )
        claim_id = claim["id"]
        status = _ok(
            request.post(
                API + f"/api/v1/claims/{claim_id}/status",
                data={"status": "triage", "reason": "Synthetic HM-06 manual-only financial intake rehearsal"},
            ), "hm06_triage",
        )
        if status["status"] != "triage":
            raise AssertionError("hm06_triage_status_missing")
        stages["login_and_create_case_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        uploaded = {}
        for doc in case["documents"]:
            payload, mime = make_upload_bytes(doc)
            actual = _ok(
                request.post(
                    API + f"/api/v1/claims/{claim_id}/documents",
                    multipart={
                        "file": {
                            "name": doc["file_name"],
                            "mimeType": mime,
                            "buffer": payload,
                        },
                        "document_type": doc["document_type"],
                    },
                ), "hm06_upload_source",
            )
            if (
                actual["document_type"] != doc["document_type"]
                or not actual["is_current"]
                or actual["version_number"] != 1
                or actual["claim_id"] != claim_id
                or len(actual["file_hash"]) != 64
            ):
                raise AssertionError("hm06_financial_source_provenance_invalid")
            uploaded[doc["source_id"]] = actual
        stages["four_actual_document_uploads_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        deadline = time.monotonic() + 115
        while time.monotonic() < deadline:
            documents = _ok(
                request.get(API + f"/api/v1/claims/{claim_id}/documents"),
                "hm06_inventory",
            )["items"]
            if len(documents) == 4 and all(
                d["processing_status"] == "processed"
                and d["malware_scan_status"] == "clean"
                for d in documents
            ):
                break
            if any(d["processing_status"] == "failed" for d in documents):
                raise AssertionError("hm06_source_text_processing_failed")
            time.sleep(2)
        else:
            raise AssertionError("hm06_financial_source_processing_timeout")
        stages["malware_and_worker_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        financial = _ok(
            request.get(API + f"/api/v1/claims/{claim_id}/financial-review"),
            "hm06_financial_read",
        )
        if financial["claim_id"] != claim_id:
            raise AssertionError("hm06_financial_wrong_claim")
        if (
            financial["totals_by_currency"] != {}
            or financial["items"] != []
            or financial["quotations"] != []
            or financial["reserve_history"] != []
            or financial["historical_reviews"] != []
            or financial["summary"]["current_item_count"] != 0
            or financial["summary"]["current_decision_count"] != 0
        ):
            raise AssertionError("hm06_unreviewed_documents_promoted_to_financial_amounts")

        page.goto(WEB + f"/claims/{claim_id}/financial", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Financial review", exact=True)).to_be_visible()
        group = page.get_by_test_id("financial-source-documents")
        for doc in case["documents"][1:]:
            row = page.get_by_test_id("financial-source-" + uploaded[doc["source_id"]]["id"])
            expect(row).to_be_visible()
            expect(row.get_by_text(doc["file_name"], exact=True)).to_be_visible()
            expect(row.get_by_text("v1", exact=True)).to_be_visible()
        expect(group.get_by_text("Quotation alternative — not an incurred loss")).to_have_count(2)
        expect(group.get_by_text("Invoice received — payment not confirmed")).to_have_count(1)
        expect(page.get_by_text("USD 265000")).to_have_count(0)
        expect(page.get_by_text("EUR 231000")).to_have_count(0)
        expect(page.get_by_text("USD 18200")).to_have_count(0)
        stages["financial_api_and_real_ui_ms"] = _milliseconds(stage)

        report = {
            "scope": "isolated_synthetic_manual_financial_ci_only",
            "case_code": case["case_id"],
            "corpus_version": "1.0.0",
            "invented_source_documents": 4,
            "quotation_alternative_documents": 2,
            "invoice_source_documents": 1,
            "different_currency_quotes_still_distinct": True,
            "source_document_values_not_promoted_to_costs": True,
            "unreviewed_quoted_amounts_not_summed": True,
            "no_invoice_marked_paid": True,
            "human_financial_review_completed": False,
            "exchange_rate_verified": False,
            "coverage_deductible_verified": False,
            "any_cost_approved": False,
            "reserve_or_payment_authorized": False,
            "human_work_time_measured": False,
            "local_llm_used": False,
            "real_customer_data_used": False,
            "pilot_accepted": False,
            "machine_stage_elapsed_ms_observed": stages,
            "machine_total_elapsed_ms_observed": _milliseconds(start),
        }
        output = Path("artifacts/hm06-financial-source-intake.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        browser.close()
    print("HM-06 real financial file receipt (unverified, no summation): PASS.")
    print("Machine stage times only:", json.dumps(stages, sort_keys=True))


if __name__ == "__main__":
    main()
