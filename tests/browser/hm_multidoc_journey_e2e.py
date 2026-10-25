"""One REAL synthetic UI/upload -> source-linked Assessment -> export acceptance.

No model is invoked, no claim of human/insurer acceptance; the CI demo host
is disposable. Browser creates a unique invented vessel and claim, uploads
four valid DOCX documents (one through the actual UI), lets the real worker
process the files, generates a PRELIMINARY versioned assessment, then
downloads the immutable review-aid Excel. Timings are machine measurements,
NOT handler task duration or ROI.
"""
from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4
from zipfile import is_zipfile

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.hm_multidoc_packs import load_corpus, make_upload_bytes, observed_source_digest

WEB = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
API = os.getenv("MCRI_API_URL", "http://127.0.0.1:8000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")


def _ok(response, operation: str) -> dict:
    if not response.ok:
        # No API error bodies, claim details or authentication tokens in logs.
        raise AssertionError(f"synthetic_{operation}_http_{response.status}")
    return response.json()


def _milliseconds(start: float) -> int:
    return max(0, int((time.monotonic() - start) * 1000))


def main() -> None:
    if (
        os.getenv("APP_ENV") != "test"
        or os.getenv("MCRI_SYNTHETIC_ONLY_CONFIRM") != "YES"
        or os.getenv("AI_PROVIDER") != "disabled"
        or WEB != "http://127.0.0.1:3000"
        or API != "http://127.0.0.1:8000"
        or len(PASSWORD) < 12
    ):
        raise SystemExit("isolated_synthetic_browser_test_environment_required")

    case = load_corpus()["cases"][0]
    if case["case_id"] != "HM-01" or case["dataset_split"] != "development":
        raise RuntimeError("unexpected_synthetic_journey_case")
    sample = uuid4().hex[:10]
    stages: dict[str, int] = {}
    start_total = time.monotonic()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1050})
        page = context.new_page()

        stage = time.monotonic()
        page.goto(WEB + "/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")
        stages["authentication_ms"] = _milliseconds(stage)

        request = context.request
        stage = time.monotonic()
        vessel = _ok(request.post(API + "/api/v1/vessels", data={
            "name": "SYNTHETIC HM ALDER " + sample, "vessel_type": "tanker",
        }), "vessel_create")
        claim = _ok(request.post(API + "/api/v1/claims", data={
            "vessel_id": vessel["id"],
            "incident_date": case["incident_date"],
            "notification_date": case["notification_date"],
            "incident_description": case["claim_description"],
            "external_reference": "SYNTHETIC-HM-01-" + sample,
            "claim_type": "hull_machinery",
            "claim_subtype": "machinery_damage",
        }), "claim_create")
        claim_id = claim["id"]
        page.goto(WEB + "/claims/" + claim_id, wait_until="networkidle")
        expect(page.get_by_text("SYNTHETIC HM ALDER " + sample, exact=True).first).to_be_visible()
        stages["case_creation_and_ui_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        # Upload the first actual DOCX through the handler's input control.
        first = case["documents"][0]
        payload, mime = make_upload_bytes(first)
        page.locator('input[type="file"]').first.set_input_files({
            "name": first["file_name"], "mimeType": mime, "buffer": payload,
        })
        deadline = time.monotonic() + 60
        ui_received = False
        while time.monotonic() < deadline:
            response = request.get(API + f"/api/v1/claims/{claim_id}/documents")
            records = _ok(response, "read_documents")["items"]
            if any(x["original_filename"] == first["file_name"] for x in records):
                ui_received = True
                break
            time.sleep(1)
        if not ui_received:
            raise AssertionError("synthetic_ui_upload_did_not_create_source")
        stages["first_ui_document_upload_ms"] = _milliseconds(stage)

        # Upload remaining independently typed documents through the same
        # authenticated manual-upload endpoint (not the external connector).
        stage = time.monotonic()
        for doc in case["documents"][1:]:
            payload, mime = make_upload_bytes(doc)
            uploaded = _ok(
                request.post(API + f"/api/v1/claims/{claim_id}/documents",
                             multipart={
                                 "file": {"name": doc["file_name"], "mimeType": mime, "buffer": payload},
                                 "document_type": doc["document_type"],
                             }),
                "manual_document_upload",
            )
            if uploaded["claim_id"] != claim_id or uploaded["file_hash"] is None:
                raise AssertionError("synthetic_uploaded_document_lineage_invalid")
        stages["remaining_manual_upload_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        deadline = time.monotonic() + 105
        expected = {doc["file_name"] for doc in case["documents"]}
        final_documents = []
        while time.monotonic() < deadline:
            snapshot = _ok(
                request.get(API + f"/api/v1/claims/{claim_id}/documents"),
                "list_documents",
            )
            final_documents = snapshot["items"]
            selected = [d for d in final_documents if d["original_filename"] in expected]
            if len(selected) == len(expected) and all(
                d["processing_status"] == "processed" for d in selected
            ):
                break
            if any(d["processing_status"] == "failed" for d in selected):
                raise AssertionError("synthetic_document_processing_failed")
            time.sleep(2)
        else:
            raise AssertionError("synthetic_documents_not_processed_on_real_worker")
        if len(final_documents) != 4 or any(
            d["malware_scan_status"] != "clean" or not d["is_current"]
            or d["version_number"] != 1 for d in final_documents
        ):
            raise AssertionError("synthetic_document_scanning_or_versions_invalid")
        stages["malware_and_worker_processing_ms"] = _milliseconds(stage)

        # A just-created claim is NEW: critical H&M document obligations
        # enter scope at TRIAGE (DOC-001/002/004). Do not fake Preliminary
        # on NEW merely because the rules have not yet been activated.
        stage = time.monotonic()
        triage = _ok(
            request.post(
                API + f"/api/v1/claims/{claim_id}/status",
                data={
                    "status": "triage",
                    "reason": "Synthetic handler starts TRIAGE so policy and evidence requirements activate.",
                },
            ), "move_claim_to_triage",
        )
        if triage["status"] != "triage":
            raise AssertionError("synthetic_claim_not_in_triage")
        summary = _ok(
            request.get(API + f"/api/v1/claims/{claim_id}/rules"),
            "read_triage_requirements",
        )
        requirements = summary["requirements"]
        missing_policy = [
            item for item in requirements if
            item["document_type"] == "policy"
            and item["status"] not in ("accepted", "under_review")
        ]
        if summary["readiness"]["state"] != "not_ready" or not missing_policy:
            raise AssertionError("synthetic_triage_policy_gate_not_active")
        stages["triage_requirements_activation_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        page.goto(WEB + f"/claims/{claim_id}/assessment", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Initial Assessment", exact=True)).to_be_visible()
        assessment = _ok(
            request.post(
                API + f"/api/v1/claims/{claim_id}/initial-assessment/generate",
                data={
                    "allow_if_not_ready": True,
                    "override_reason": "Synthetic-only assessment rehearsal; no professional H&M review yet.",
                },
            ), "generate_preliminary_assessment",
        )
        if (
            assessment["claim_id"] != claim_id
            or not assessment["is_preliminary"]
            or assessment["source_state"] != "current"
            or len(assessment.get("source_fingerprint") or "") != 64
            or not assessment["sections"]
        ):
            raise AssertionError("synthetic_assessment_not_preliminary_or_source_bound")
        doc_section = next((s for s in assessment["sections"] if s["section_key"] == "documents"), None)
        if doc_section is None:
            raise AssertionError("synthetic_document_section_missing")
        doc_ids = {d["id"] for d in final_documents}
        section_ids = {source["id"] for source in doc_section["source_manifest"]
                       if source.get("kind") == "document"}
        if not doc_ids.issubset(section_ids):
            raise AssertionError("synthetic_assessment_missing_document_sources")
        if assessment["approved_by_id"] is not None:
            raise AssertionError("synthetic_auto_approval_disallowed")
        stages["preliminary_assessment_ui_and_build_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        page.goto(WEB + f"/claims/{claim_id}/claim-pack", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Claim Pack Export", exact=True)).to_be_visible()
        export = _ok(
            request.post(API + f"/api/v1/claims/{claim_id}/claim-pack-exports",
                         data={
                             "export_format": "xlsx",
                             "acknowledge_review_aid": True,
                             "generation_note": "Synthetic HM-01 preliminary non-approved source review aid",
                         }), "review_aid_export",
        )
        response = request.get(
            API + f"/api/v1/claims/{claim_id}/claim-pack-exports/{export['id']}/download"
        )
        if not response.ok or not is_zipfile(BytesIO(response.body())):
            raise AssertionError("synthetic_claim_pack_download_invalid")
        if (
            response.headers.get("x-claim-pack-snapshot-sha256") != export["snapshot_hash"]
            or response.headers.get("x-claim-pack-file-sha256") != export["file_hash"]
        ):
            raise AssertionError("synthetic_immutable_claim_pack_hash_mismatch")
        stages["claim_pack_export_and_download_ms"] = _milliseconds(stage)

        # A build only: no human acted on the assessment, no consultant was
        # involved and no production release authority is implied.
        report = {
            "scope": "isolated_synthetic_browser_ci_only",
            "corpus_version": "1.0.0",
            "case_code": case["case_id"],
            "invented_documents_processed": 4,
            "source_versions_preserved": True,
            "document_source_manifest_complete": True,
            "assessment_preliminary": True,
            "claim_pack_review_aid_downloaded": True,
            "human_task_time_measured": False,
            "human_quality_assessed": False,
            "independent_hm_reference_approved": False,
            "local_llm_used": False,
            "real_customer_data_used": False,
            "pilot_accepted": False,
            "source_packet_sha256_observed": observed_source_digest(case),
            "stage_elapsed_ms_observed": stages,
            "total_elapsed_ms_observed": _milliseconds(start_total),
        }
        output = Path("artifacts/hm-six-pack-browser-journey.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        browser.close()
    print("Synthetic HM-01 upload->processing->preliminary assessment->export: PASS.")
    print("Stage timings (CI machine, not human):", json.dumps(stages, sort_keys=True))


if __name__ == "__main__":
    main()
