"""HM-03: actual fictional contradictory alarm records, no unearned reconciliation.

This is an authenticated offline-browser/worker journey on a disposable stack.
It demonstrates both conflicting original sources were ingested and retained,
but does NOT claim that two raw PDFs/DOCXs alone create human-reviewed
chronology facts or a resolved conflict. No LLM, real claim or expert signoff.
"""
from __future__ import annotations

from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4
from zipfile import ZipFile
from xml.etree import ElementTree

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.hm_multidoc_packs import load_corpus, make_upload_bytes
from hm_multidoc_journey_e2e import API, WEB, ORG, EMAIL, PASSWORD, _ok, _milliseconds


def _local_guard() -> None:
    if (
        os.getenv("APP_ENV") != "test"
        or os.getenv("MCRI_SYNTHETIC_ONLY_CONFIRM") != "YES"
        or os.getenv("AI_PROVIDER") != "disabled"
        or API != "http://127.0.0.1:8000"
        or WEB != "http://127.0.0.1:3000"
        or len(PASSWORD) < 12
    ):
        raise SystemExit("isolated_synthetic_browser_test_environment_required")


def _docx_lines(content: bytes) -> list[str]:
    with ZipFile(BytesIO(content)) as zf:
        root = ElementTree.fromstring(zf.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    return [
        "".join(node.text or "" for node in paragraph.findall(".//w:t", ns))
        for paragraph in root.findall(".//w:p", ns)
    ]


def main() -> None:
    _local_guard()
    case = load_corpus()["cases"][2]
    docs = case["documents"]
    if (
        case["case_id"] != "HM-03"
        or case["dataset_split"] != "development"
        or case["scenario_focus"] != "conflict"
        or len(docs) != 4
        or any(d["format"] != "docx" or d["source_version"] != 1 for d in docs)
    ):
        raise AssertionError("hm03_fixed_fictional_source_contract_changed")

    source_lines = {d["source_id"]: d["source_lines"] for d in docs}
    if not (
        any("11:30 UTC" in line for line in source_lines["engineer"])
        and any("11:55 UTC" in line for line in source_lines["workshop"])
        and not any("11:55 UTC" in line for line in source_lines["engineer"])
        and not any("11:30 UTC" in line for line in source_lines["workshop"])
        and any("not been verified" in line for line in source_lines["workshop"])
        and any("unavailable" in line for line in source_lines["engineer"])
    ):
        raise AssertionError("hm03_fictional_attributed_alarm_disagreement_lost")

    began = time.monotonic()
    stages: dict[str, int] = {}
    marker = uuid4().hex[:10]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1100})
        page = context.new_page()
        page.goto(WEB + "/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")
        req = context.request

        stage = time.monotonic()
        vessel = _ok(req.post(API + "/api/v1/vessels", data={
            "name": "SYNTHETIC HM CEDAR " + marker, "vessel_type": "tanker",
        }), "hm03_create_vessel")
        claim = _ok(req.post(API + "/api/v1/claims", data={
            "vessel_id": vessel["id"],
            "incident_date": case["incident_date"],
            "notification_date": case["notification_date"],
            "incident_description": case["claim_description"],
            "external_reference": "FICTION-HM03-" + marker,
            "claim_type": "hull_machinery",
            "claim_subtype": "machinery_damage",
        }), "hm03_create_claim")
        claim_id = claim["id"]
        status = _ok(req.post(
            API + f"/api/v1/claims/{claim_id}/status",
            data={"status": "triage", "reason": "Fictional unresolved alarm sources; original records not authenticated"},
        ), "hm03_triage")
        if status["status"] != "triage":
            raise AssertionError("hm03_claim_not_in_triage")
        stages["create_and_triage_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        uploaded: dict[str, dict] = {}
        for doc in docs:
            content, mime = make_upload_bytes(doc)
            record = _ok(req.post(
                API + f"/api/v1/claims/{claim_id}/documents",
                multipart={
                    "file": {"name": doc["file_name"], "mimeType": mime, "buffer": content},
                    "document_type": doc["document_type"],
                },
            ), "hm03_upload")
            if (
                record["document_type"] != doc["document_type"]
                or record["version_number"] != 1
                or not record["is_current"]
                or record["file_hash"] != hashlib.sha256(content).hexdigest()
            ):
                raise AssertionError("hm03_document_lineage_incorrect")
            uploaded[doc["source_id"]] = record
        stages["four_authenticated_uploads_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        deadline = time.monotonic() + 110
        while time.monotonic() < deadline:
            inventory = _ok(
                req.get(API + f"/api/v1/claims/{claim_id}/documents"),
                "hm03_inventory",
            )["items"]
            if len(inventory) == 4 and all(
                item["processing_status"] == "processed"
                and item["malware_scan_status"] == "clean"
                for item in inventory
            ):
                break
            if any(item["processing_status"] == "failed" for item in inventory):
                raise AssertionError("hm03_worker_failed")
            time.sleep(2)
        else:
            raise AssertionError("hm03_worker_timeout")
        stages["malware_scan_and_processing_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        # Read the *persisted original bytes* through the actual authorized
        # download endpoint. No OCR/LLM interpretation can substitute for them.
        for source in ("engineer", "workshop"):
            record = uploaded[source]
            response = req.get(
                API + f"/api/v1/claims/{claim_id}/documents/{record['id']}/download"
            )
            if not response.ok or hashlib.sha256(response.body()).hexdigest() != record["file_hash"]:
                raise AssertionError("hm03_original_download_integrity_failed")
            if _docx_lines(response.body()) != source_lines[source]:
                raise AssertionError("hm03_original_alarm_source_mutated")

        # Before independent human comparison, neither reading documents nor
        # rebuilding chronology may invent a single reconciled alarm time.
        facts = _ok(req.get(API + f"/api/v1/claims/{claim_id}/facts"), "hm03_facts")
        if facts["total"] != 0:
            raise AssertionError("hm03_unreviewed_alarm_was_promoted_to_fact")
        _ok(req.post(API + f"/api/v1/claims/{claim_id}/chronology/rebuild"), "hm03_chronology_rebuild")
        chronology = _ok(req.get(API + f"/api/v1/claims/{claim_id}/chronology"), "hm03_chronology")
        if (
            chronology["event_count"] != 0
            or chronology["open_conflict_count"] != 0
            or chronology["events"]
            or chronology["conflicts"]
        ):
            raise AssertionError("hm03_unreviewed_alarm_invented_chronology_or_resolution")
        stages["original_download_and_nonpromotion_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        assessment = _ok(req.post(
            API + f"/api/v1/claims/{claim_id}/initial-assessment/generate",
            data={
                "allow_if_not_ready": True,
                "override_reason": "Synthetic unresolved source conflict; preliminary aid only, no expert alarm chronology",
            },
        ), "hm03_preliminary_assessment")
        docs_section = next(
            (s for s in assessment["sections"] if s["section_key"] == "documents"),
            None,
        )
        if docs_section is None:
            raise AssertionError("hm03_assessment_missing_document_section")
        assessment_source_ids = {
            row["id"] for row in docs_section["source_manifest"]
            if row.get("kind") == "document"
        }
        if (
            not assessment["is_preliminary"]
            or assessment["approved_by_id"] is not None
            or assessment["source_state"] != "current"
            or assessment_source_ids != {d["id"] for d in uploaded.values()}
        ):
            raise AssertionError("hm03_assessment_not_source_linked_preliminary")
        page.goto(WEB + f"/claims/{claim_id}", wait_until="networkidle")
        for record in uploaded.values():
            expect(page.get_by_text(record["original_filename"], exact=True).first).to_be_visible()
        page.goto(WEB + f"/claims/{claim_id}/chronology", wait_until="networkidle")
        # The page is real, but a manually reviewed alarm conflict is still absent.
        expect(page.locator("main")).to_be_visible()
        stages["assessment_and_browser_visibility_ms"] = _milliseconds(stage)

        report = {
            "scope": "isolated_synthetic_manual_multi_document_ci_only",
            "case_code": "HM-03",
            "corpus_version": "1.0.0",
            "invented_sources": 4,
            "independently_attributed_alarm_sources_retained": 2,
            "original_bytes_verified_after_processing": True,
            "source_manifest_matches_original_documents": True,
            "chronology_has_no_unreviewed_auto_reconciliation": True,
            "machine_generated_alarm_conflict_detected": False,
            "alarm_time_truth_adjudicated": False,
            "independent_log_or_clock_verified": False,
            "human_hm_review_completed": False,
            "assessment_approved": False,
            "ai_provider_used": False,
            "real_claims_processed": False,
            "pilot_accepted": False,
            "machine_stage_elapsed_ms": stages,
            "machine_total_elapsed_ms": _milliseconds(began),
        }
        out = Path("artifacts/hm03-attributed-alarm-intake.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        browser.close()
    print("HM-03 fictional conflicting alarm intake and nonpromotion: PASS")
    print("Machine stage durations only:", json.dumps(stages, sort_keys=True))


if __name__ == "__main__":
    main()
