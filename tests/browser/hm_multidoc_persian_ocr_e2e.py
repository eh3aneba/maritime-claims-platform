"""HM-05 real Persian image OCR -> persisted evidence search, synthetic-only CI.

The source is rendered to a *real raster PNG* through Chromium then
uploaded to the ordinary authenticated manual Evidence endpoint. Real
ClamAV, worker and tesseract:eng+fas must operate before source-linked
lexical retrieval. No fake OCR transcript, AI generation or human signoff.
"""
from __future__ import annotations

import hashlib
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
from scripts.hm_persian_ocr_probe import (
    PROBES, SCOPED_NEGATION_PHRASE, evaluate_literal_probe_retrieval,
)
from hm_multidoc_journey_e2e import (
    API, WEB, ORG, EMAIL, PASSWORD, _ok, _milliseconds,
)

# Only invented fixed source phrases are probed. A recovered phrase is
# NOT a verified claim fact, and missing negation is a quality blocker.


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


def _poll_processed(request, claim_id: str, expected_ids: set[str]) -> list[dict]:
    stop = time.monotonic() + 115
    while time.monotonic() < stop:
        docs = _ok(
            request.get(API + f"/api/v1/claims/{claim_id}/documents"),
            "hm05_document_inventory",
        )["items"]
        found = {d["id"]: d for d in docs}
        if any(
            found.get(uid, {}).get("processing_status") == "failed"
            for uid in expected_ids
        ):
            raise AssertionError("hm05_worker_failed")
        if all(
            uid in found and found[uid]["processing_status"] == "processed"
            and found[uid]["malware_scan_status"] == "clean"
            for uid in expected_ids
        ):
            return docs
        time.sleep(2)
    raise AssertionError("hm05_real_ocr_processing_timeout")


def main() -> None:
    _guard()
    case = load_corpus()["cases"][4]
    if (
        case["case_id"] != "HM-05"
        or case["dataset_split"] != "holdout"
        or len(case["documents"]) != 4
        or [x["format"] for x in case["documents"]].count("png") != 1
    ):
        raise RuntimeError("unexpected_synthetic_farsi_scan_case")
    scan = next(x for x in case["documents"] if x["format"] == "png")
    if not all(any(probe in line for line in scan["source_lines"]) for probe in PROBES):
        raise ValueError("synthetic_farsi_source_probe_not_anchored")
    if not any(SCOPED_NEGATION_PHRASE in line for line in scan["source_lines"]):
        raise ValueError("synthetic_farsi_scoped_phrase_not_anchored")

    stages: dict[str, int] = {}
    started = time.monotonic()
    suffix = uuid4().hex[:10]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1080})
        page = context.new_page()
        stage = time.monotonic()
        page.goto(WEB + "/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")
        request = context.request
        vessel = _ok(request.post(API + "/api/v1/vessels", data={
            "name": "SYNTHETIC HM ELM " + suffix, "vessel_type": "tanker",
        }), "hm05_vessel_create")
        claim = _ok(request.post(API + "/api/v1/claims", data={
            "vessel_id": vessel["id"],
            "incident_date": case["incident_date"],
            "notification_date": case["notification_date"],
            "incident_description": case["claim_description"],
            "external_reference": "SYNTHETIC-HM-05-" + suffix,
            "claim_type": "hull_machinery",
            "claim_subtype": "machinery_damage",
        }), "hm05_claim_create")
        claim_id = claim["id"]
        triage = _ok(request.post(
            API + f"/api/v1/claims/{claim_id}/status",
            data={
                "status": "triage",
                "reason": "Synthetic H&M OCR test activates policy and missing records.",
            },
        ), "hm05_triage")
        if triage["status"] != "triage":
            raise AssertionError("hm05_triage_not_activated")
        stages["login_claim_triage_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        # Render the image-only Persian source; never upload fake text in its place.
        raster_page = context.new_page()
        image, image_mime = make_upload_bytes(scan, raster_page)
        raster_page.close()
        if not image.startswith(b"\x89PNG\r\n\x1a\n") or image_mime != "image/png":
            raise AssertionError("hm05_not_real_png")
        stages["raster_generation_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        uploaded: dict[str, dict] = {}
        for doc in case["documents"]:
            if doc["source_id"] == scan["source_id"]:
                payload, mime = image, image_mime
            else:
                payload, mime = make_upload_bytes(doc)
            result = _ok(
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
                ), "hm05_manual_evidence_upload",
            )
            if (
                result["claim_id"] != claim_id
                or result["version_number"] != 1
                or not result["is_current"]
                or result["supersedes_document_id"] is not None
                or len(result["file_hash"]) != 64
            ):
                raise AssertionError("hm05_uploaded_source_lineage_incorrect")
            uploaded[doc["source_id"]] = result
        stages["four_uploads_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        docs = _poll_processed(request, claim_id, {
            d["id"] for d in uploaded.values()
        })
        if len(docs) != 4:
            raise AssertionError("hm05_all_four_source_documents_not_present")
        extracted = _ok(
            request.get(API + f"/api/v1/claims/{claim_id}/documents/"
                        + uploaded[scan["source_id"]]["id"] + "/processing"),
            "hm05_persisted_ocr_metadata",
        )
        ocr = extracted.get("text_extraction")
        if (
            extracted.get("operator_status") != "completed"
            or type(ocr) is not dict
            or ocr.get("extraction_method") != "tesseract:eng+fas"
            or ocr.get("source_text_quality_state") != "ocr_human_source_comparison_required"
            or ocr.get("requires_ocr") is not False
            or not isinstance(ocr.get("char_count"), int)
            or ocr["char_count"] < 25
            or not isinstance(ocr.get("segment_count"), int)
            or ocr["segment_count"] < 1
            or len(ocr.get("text_hash") or "") != 64
        ):
            raise AssertionError("hm05_real_persian_ocr_not_available_for_review")
        # Compare the *persisted* OCR text itself with lexical retrieval.
        # The tenant-scoped endpoint returns exact text only when its
        # bounded preview is not truncated. Never infer a word from source.
        source_read = _ok(
            request.get(
                API + f"/api/v1/claims/{claim_id}/documents/"
                + uploaded[scan["source_id"]]["id"]
                + "/processing/source-segments",
                params={"offset": 0, "limit": 5},
            ), "hm05_unverified_persisted_ocr_segment_read",
        )
        source_segments = source_read["segments"]
        if (
            source_read["review_disposition"] != "machine_unverified"
            or source_read["source_text_quality_state"]
            != "ocr_human_source_comparison_required"
            or source_read["document_id"] != uploaded[scan["source_id"]]["id"]
            or source_read["document_version"] != 1
            or source_read["source_file_hash"] != uploaded[scan["source_id"]]["file_hash"]
            or source_read["extraction_text_hash"] != ocr["text_hash"]
            or source_read["extraction_method"] != "tesseract:eng+fas"
            or source_read["total_segments"] != 1
            or len(source_segments) != 1
            or source_segments[0]["segment_index"] != 0
            or source_segments[0]["locator_type"] != "page"
            or source_segments[0]["locator_value"] != "1"
            or source_segments[0]["text_truncated"]
        ):
            raise AssertionError("hm05_ocr_machine_transcript_unavailable_or_incomplete")
        raw_ocr_text = source_segments[0]["text_preview"]
        if (
            source_segments[0]["source_char_count"] != len(raw_ocr_text)
            or hashlib.sha256(raw_ocr_text.strip().encode("utf-8")).hexdigest()
            != ocr["text_hash"]
        ):
            raise AssertionError("hm05_ocr_persisted_text_hash_mismatch")
        raw_ocr_probes = {probe: probe in raw_ocr_text for probe in PROBES}
        raw_ocr_scoped_phrase = SCOPED_NEGATION_PHRASE in raw_ocr_text
        stages["real_worker_and_ocr_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        # Retrieve *persisted* OCR rather than the synthetic transcript.
        # Do not claim complete negation recognition when the worker omits it.
        observed_probes: dict[str, bool] = {}
        for probe in PROBES:
            result = _ok(
                request.post(
                    API + f"/api/v1/claims/{claim_id}/evidence-search",
                    data={
                        "query": probe,
                        "top_k": 10,
                        "retrieval_mode": "lexical",
                        "document_ids": [uploaded[scan["source_id"]]["id"]],
                    },
                ), "hm05_persian_source_search",
            )
            matches = [
                entry for entry in result["results"]
                if entry["document_id"] == uploaded[scan["source_id"]]["id"]
                and entry["document_version"] == 1
                and entry["is_current_document"] is True
                and entry["source_file_hash"] == uploaded[scan["source_id"]]["file_hash"]
                and entry["extraction_text_hash"] == ocr["text_hash"]
                and entry["locator_type"] == "page"
                and entry["locator_value"] == "1"
                and entry["snippet"] and probe in entry["snippet"]
            ]
            if result["retrieval_mode"] != "lexical" or result["semantic_used"]:
                raise AssertionError("hm05_nonlocal_model_retrieval_unexpected")
            observed_probes[probe] = bool(matches)
        # A whole-clause retrieval is diagnostically stronger than isolated
        # token presence. This is still a lexical snippet test, NOT
        # verification that negation correctly scopes the causal statement.
        scoped_result = _ok(
            request.post(
                API + f"/api/v1/claims/{claim_id}/evidence-search",
                data={
                    "query": SCOPED_NEGATION_PHRASE,
                    "exact_phrase": True,
                    "top_k": 10,
                    "retrieval_mode": "lexical",
                    "document_ids": [uploaded[scan["source_id"]]["id"]],
                },
            ), "hm05_scoped_negation_source_search",
        )
        if scoped_result["retrieval_mode"] != "lexical" or scoped_result["semantic_used"]:
            raise AssertionError("hm05_scoped_probe_used_nonlocal_retrieval")
        scoped_matches = [
            entry for entry in scoped_result["results"]
            if entry["document_id"] == uploaded[scan["source_id"]]["id"]
            and entry["document_version"] == 1
            and entry["is_current_document"] is True
            and entry["source_file_hash"] == uploaded[scan["source_id"]]["file_hash"]
            and entry["extraction_text_hash"] == ocr["text_hash"]
            and entry["locator_type"] == "page"
            and entry["locator_value"] == "1"
            and entry["snippet"]
            and SCOPED_NEGATION_PHRASE in entry["snippet"]
        ]
        quality = evaluate_literal_probe_retrieval(
            observed_probes, scoped_phrase_retrieved=bool(scoped_matches)
        )
        if (
            any(observed_probes[probe] and not raw_ocr_probes[probe] for probe in PROBES)
            or (bool(scoped_matches) and not raw_ocr_scoped_phrase)
        ):
            raise AssertionError("hm05_search_results_not_supported_by_persisted_ocr")
        missing_clause_stage = (
            "ocr_extraction_or_persistence"
            if not raw_ocr_scoped_phrase
            else "lexical_search_or_snippet"
            if not scoped_matches
            else "not_missing_but_semantics_unverified"
        )
        # Fail closed on loss of even the baseline technical identifier:
        # the controlled Persian OCR search path must remain usable.
        if not quality["machinery_term_retrieved"]:
            raise AssertionError("hm05_technical_identifier_not_retrievable")
        # Negation omission is a captured quality **failure**, not
        # an invented positive probe and not a claimed acceptance.
        if (
            quality["critical_fact_authorization_granted"]
            or not quality["human_bilingual_review_required"]
            or quality["pilot_accepted"]
        ):
            raise AssertionError("hm05_ocr_quality_was_falsely_approved")
        stages["persian_search_locator_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        # The actual handler document table MUST disclose unverified
        # OCR even though the local worker has completed successfully.
        page.goto(WEB + f"/claims/{claim_id}", wait_until="networkidle")
        scan_warning = page.get_by_test_id(
            "ocr-source-review-" + uploaded[scan["source_id"]]["id"]
        )
        expect(scan_warning).to_be_visible()
        expect(scan_warning).to_contain_text("OCR text is not verified")
        # The operator can open a bounded, read-only page of *persisted*
        # OCR, compare it with the original download, then close it.
        # This is neither expert approval nor transcript correction.
        page.get_by_role("button", name="Inspect machine OCR text").click()
        preview_panel = page.get_by_test_id(
            "ocr-comparison-" + uploaded[scan["source_id"]]["id"]
        )
        expect(preview_panel).to_be_visible()
        expect(preview_panel.get_by_text("UNVERIFIED · no human approval recorded")).to_be_visible()
        expect(preview_panel.get_by_role(
            "button", name="Download original for comparison"
        )).to_be_visible()
        expect(preview_panel.get_by_test_id("ocr-transcript-segment-0")).to_be_visible()
        expect(preview_panel.get_by_test_id("ocr-transcript-segment-0")).to_contain_text(
            "توربوشارژر"
        )
        # Read-only UX check. A scripted test must never impersonate a
        # real bilingual reviewer or assert human source comparison.
        operator_report = preview_panel.get_by_test_id("ocr-discrepancy-workspace")
        expect(operator_report.get_by_role(
            "button", name="Report an OCR discrepancy"
        )).to_be_visible()
        operator_report.get_by_role(
            "button", name="Report an OCR discrepancy"
        ).click()
        submit_report = operator_report.get_by_test_id("ocr-report-submit")
        expect(submit_report).to_be_disabled()
        operator_report.get_by_test_id("ocr-report-segment").select_option("0")
        expect(submit_report).to_be_disabled()
        expect(operator_report.get_by_test_id("ocr-report-attestation")).not_to_be_checked()
        # Do not click attestation, do not POST or fabricate a human report.
        preview_panel.get_by_role("button", name="Close and clear preview").click()
        expect(preview_panel).to_have_count(0)
        page.goto(WEB + f"/claims/{claim_id}/assessment", wait_until="networkidle")
        expect(page.get_by_role(
            "heading", name="Initial Assessment", exact=True,
        )).to_be_visible()
        assessment = _ok(
            request.post(
                API + f"/api/v1/claims/{claim_id}/initial-assessment/generate",
                data={
                    "allow_if_not_ready": True,
                    "override_reason": "Invented Persian OCR case, no bilingual human verification.",
                },
            ), "hm05_preliminary_assessment",
        )
        scanned_id = uploaded[scan["source_id"]]["id"]
        docs_section = next(
            (sec for sec in assessment["sections"] if sec["section_key"] == "documents"),
            None,
        )
        if (
            assessment["is_preliminary"] is not True
            or assessment["source_state"] != "current"
            or assessment["approved_by_id"] is not None
            or not docs_section
            or scanned_id not in {
                ref["id"] for ref in docs_section["source_manifest"]
                if ref.get("kind") == "document"
            }
        ):
            raise AssertionError("hm05_preliminary_source_assessment_not_bound")
        stages["initial_assessment_review_aid_ms"] = _milliseconds(stage)

        # This is an automated OCR/locator *regression*, NOT human QA:
        # recognizing two literals does not validate negation scope,
        # causal assertions, timings or all source lines.
        report = {
            "scope": "isolated_synthetic_hm05_ci_only",
            "case_code": case["case_id"],
            "corpus_version": "1.0.0",
            "real_image_only_raster_used": True,
            "real_tesseract_eng_fas_executed": True,
            "operator_ocr_human_source_comparison_warning_visible": True,
            "operator_unverified_ocr_read_only_preview_exercised": True,
            "malware_clean_and_worker_processed_documents": 4,
            "ocr_source_locator_is_page_one_for_observed_matches": True,
            "literal_probe_observations": quality,
            "persisted_machine_ocr_token_presence": raw_ocr_probes,
            "persisted_machine_ocr_whole_clause_present": raw_ocr_scoped_phrase,
            "whole_clause_missing_stage": missing_clause_stage,
            "persisted_machine_transcript_hash_matched": True,
            "source_extraction_preview_complete": True,
            "ocr_char_count_observed": ocr["char_count"],
            "ocr_segment_count_observed": ocr["segment_count"],
            "full_transcript_accuracy_verified": False,
            "uncertainty_semantics_verified": False,
            "human_bilingual_review_completed": False,
            "human_work_time_measured": False,
            "independent_expert_reference_approved": False,
            "external_ai_used": False,
            "real_customer_data_used": False,
            "pilot_accepted": False,
            "machine_stage_elapsed_ms_observed": stages,
            "machine_total_elapsed_ms_observed": _milliseconds(started),
        }
        output = Path("artifacts/hm05-real-persian-ocr-journey.json")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        browser.close()
    print("Synthetic HM-05 OCR availability and fail-closed quality labeling: PASS.")
    print("OCR negation literal recovered:", quality["negation_retrieved"])
    print("OCR full negation clause retrieved:", quality["scoped_negation_phrase_retrieved"])
    print("OCR-vs-search missing stage:", missing_clause_stage)
    print("OCR semantic quality / pilot: NOT ACCEPTED, bilingual review required.")
    print("Machine stage timings only:", json.dumps(stages, sort_keys=True))


if __name__ == "__main__":
    main()
