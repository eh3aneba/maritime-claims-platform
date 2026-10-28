"""HM-04: real synthetic Evidence replacement must stale prior assessment.

Runs only in a disposable authenticated local CI stack with external AI
disabled. Tests version lineage and source-linked current-only assessment.
No model output, customer files, professional approval or claim payment.
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
    API, EMAIL, ORG, PASSWORD, WEB, _milliseconds, _ok,
)

REASON = (
    "Synthetic correction to initial engineer report shutdown time, "
    "superseding only the earlier document; old evidence remains archived."
)


def _require_local_test_host() -> None:
    if (
        os.getenv("APP_ENV") != "test"
        or os.getenv("MCRI_SYNTHETIC_ONLY_CONFIRM") != "YES"
        or os.getenv("AI_PROVIDER") != "disabled"
        or WEB != "http://127.0.0.1:3000"
        or API != "http://127.0.0.1:8000"
        or len(PASSWORD) < 12
    ):
        raise SystemExit("isolated_synthetic_browser_test_environment_required")


def _wait_processed(request, claim_id: str, expected_ids: set[str], timeout=90) -> list[dict]:
    cutoff = time.monotonic() + timeout
    while time.monotonic() < cutoff:
        items = _ok(
            request.get(API + f"/api/v1/claims/{claim_id}/documents"),
            "document_version_poll",
        )["items"]
        seen = {doc["id"]: doc for doc in items}
        if any(
            seen.get(doc_id, {}).get("processing_status") == "failed"
            for doc_id in expected_ids
        ):
            raise AssertionError("synthetic_version_processing_failed")
        if all(
            doc_id in seen
            and seen[doc_id]["processing_status"] == "processed"
            and seen[doc_id]["malware_scan_status"] == "clean"
            for doc_id in expected_ids
        ):
            return items
        time.sleep(2)
    raise AssertionError("synthetic_version_processing_timeout")


def _generate(request, claim_id: str, label: str) -> dict:
    # A worker can finish a source-state write just as assessment sections
    # are being assembled. The API deliberately rejects that attempt without
    # committing an assessment. Retry only this exact safe snapshot-drift
    # conflict, never a generic 409 or a permission/readiness failure.
    drift_detail = (
        "Claim evidence changed while the assessment version was being generated. "
        "No assessment version was committed; generate again from the current claim state."
    )
    result = None
    for attempt in range(3):
        response = request.post(
            API + f"/api/v1/claims/{claim_id}/initial-assessment/generate",
            data={
                "allow_if_not_ready": True,
                "override_reason": f"HM-04 invented source-version rehearsal {label}; no human adjudication",
            },
        )
        if response.status == 409:
            try:
                detail = response.json().get("detail")
            except (ValueError, TypeError, AttributeError):
                detail = None
            if detail == drift_detail and attempt < 2:
                time.sleep(0.5)
                continue
        result = _ok(response, "generate_versioned_assessment")
        break
    if result is None:
        raise AssertionError("synthetic_versioned_assessment_retry_exhausted")
    if (
        result["source_state"] != "current"
        or not result["is_preliminary"]
        or len(result.get("source_fingerprint") or "") != 64
        or result["approved_by_id"] is not None
    ):
        raise AssertionError("synthetic_versioned_assessment_not_source_bound")
    return result


def _document_manifest_ids(assessment: dict) -> set[str]:
    section = next(
        (s for s in assessment["sections"] if s["section_key"] == "documents"),
        None,
    )
    if section is None:
        raise AssertionError("synthetic_documents_assessment_section_missing")
    return {
        item["id"] for item in section["source_manifest"]
        if item.get("kind") == "document"
    }


def main() -> None:
    _require_local_test_host()
    case = load_corpus()["cases"][3]
    if (
        case["case_id"] != "HM-04" or case["dataset_split"] != "development"
        or len(case["documents"]) != 5
        or case["documents"][-1]["replaces_source_id"] != "engineer"
    ):
        raise RuntimeError("unexpected_synthetic_replacement_fixture")

    start = time.monotonic()
    stage_times: dict[str, int] = {}
    marker = uuid4().hex[:10]

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1420, "height": 1100})
        page = context.new_page()
        page.goto(WEB + "/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")
        request = context.request

        stage = time.monotonic()
        vessel = _ok(request.post(API + "/api/v1/vessels", data={
            "name": "SYNTHETIC HM DUNE " + marker, "vessel_type": "tanker",
        }), "hm04_vessel_create")
        claim = _ok(request.post(API + "/api/v1/claims", data={
            "vessel_id": vessel["id"],
            "incident_date": case["incident_date"],
            "notification_date": case["notification_date"],
            "incident_description": case["claim_description"],
            "external_reference": "SYNTHETIC-HM-04-" + marker,
            "claim_type": "hull_machinery",
            "claim_subtype": "machinery_damage",
        }), "hm04_claim_create")
        claim_id = claim["id"]
        status = _ok(request.post(
            API + f"/api/v1/claims/{claim_id}/status",
            data={"status": "triage", "reason": "Synthetic review starts with real H&M policy gate."},
        ), "hm04_triage")
        if status["status"] != "triage":
            raise AssertionError("synthetic_hm04_triage_failed")
        stage_times["case_and_triage_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        originals = {}
        for doc in case["documents"][:-1]:
            payload, mime = make_upload_bytes(doc)
            record = _ok(
                request.post(
                    API + f"/api/v1/claims/{claim_id}/documents",
                    multipart={
                        "file": {
                            "name": doc["file_name"], "mimeType": mime, "buffer": payload,
                        },
                        "document_type": doc["document_type"],
                    },
                ), "hm04_original_upload",
            )
            originals[doc["source_id"]] = record
            if (
                record["version_number"] != 1 or not record["is_current"]
                or record["supersedes_document_id"] is not None
            ):
                raise AssertionError("synthetic_initial_document_lineage_invalid")
        _wait_processed(request, claim_id, {d["id"] for d in originals.values()})
        stage_times["initial_documents_scan_and_process_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        before = _generate(request, claim_id, "before-replacement")
        old_fp = before["source_fingerprint"]
        original_ids = {record["id"] for record in originals.values()}
        if _document_manifest_ids(before) != original_ids:
            raise AssertionError("synthetic_initial_manifest_incorrect")
        old_engineer = originals["engineer"]
        stage_times["assessment_version_one_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        replacement_fixture = case["documents"][-1]
        payload, mime = make_upload_bytes(replacement_fixture)
        new_engineer = _ok(
            request.post(
                API + f"/api/v1/claims/{claim_id}/documents/{old_engineer['id']}/replacements",
                multipart={
                    "file": {
                        "name": replacement_fixture["file_name"],
                        "mimeType": mime,
                        "buffer": payload,
                    },
                    "replacement_reason": REASON,
                    "document_type": replacement_fixture["document_type"],
                },
            ), "hm04_real_replacement_upload",
        )
        if (
            new_engineer["version_number"] != 2
            or new_engineer["supersedes_document_id"] != old_engineer["id"]
            or new_engineer["document_family_id"] != old_engineer["document_family_id"]
            or new_engineer["file_hash"] == old_engineer["file_hash"]
            or not new_engineer["is_current"]
        ):
            raise AssertionError("synthetic_corrected_version_lineage_invalid")
        stage_times["replacement_admission_ms"] = _milliseconds(stage)

        # No stale assessment section may be reviewed/approved, even by an
        # authenticated demo manager. No human approval actually occurs.
        stage = time.monotonic()
        stale = _ok(
            request.get(
                API + f"/api/v1/claims/{claim_id}/initial-assessment/versions/{before['id']}"
            ), "read_stale_assessment",
        )
        if stale["source_state"] != "stale" or stale["source_fingerprint"] != old_fp:
            raise AssertionError("synthetic_superseded_source_did_not_stale_assessment")
        old_section = before["sections"][0]
        unauthorized_stale = request.post(
            API + f"/api/v1/claims/{claim_id}/initial-assessment/sections/{old_section['id']}/review",
            data={
                "action": "approve",
                "text": None,
                "expected_source_fingerprint": old_fp,
            },
        )
        if unauthorized_stale.status != 409:
            raise AssertionError("synthetic_stale_assessment_review_not_blocked")
        second_replacement = request.post(
            API + f"/api/v1/claims/{claim_id}/documents/{old_engineer['id']}/replacements",
            multipart={
                "file": {
                    "name": replacement_fixture["file_name"],
                    "mimeType": mime,
                    "buffer": payload,
                },
                "replacement_reason": REASON,
            },
        )
        if second_replacement.status != 409:
            raise AssertionError("synthetic_superseded_version_can_be_replaced_again")
        stage_times["stale_write_and_old_version_rejection_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        all_docs = _wait_processed(request, claim_id, {new_engineer["id"]})
        if len(all_docs) != 5:
            raise AssertionError("synthetic_hm04_document_history_not_preserved")
        by_id = {doc["id"]: doc for doc in all_docs}
        v1, v2 = by_id[old_engineer["id"]], by_id[new_engineer["id"]]
        if (
            v1["is_current"] or v1["version_number"] != 1
            or v1["superseded_at"] is None
            or v1["file_hash"] != old_engineer["file_hash"]
            or not v2["is_current"] or v2["version_number"] != 2
            or v2["replacement_reason"] != REASON
        ):
            raise AssertionError("synthetic_hm04_historical_evidence_not_preserved")

        after = _generate(request, claim_id, "after-replacement")
        current_manifest = _document_manifest_ids(after)
        if (
            after["version"] != before["version"] + 1
            or after["source_fingerprint"] == old_fp
            or old_engineer["id"] in current_manifest
            or new_engineer["id"] not in current_manifest
            or current_manifest != (
                original_ids - {old_engineer["id"]}
            ) | {new_engineer["id"]}
            or after["approved_by_id"] is not None
        ):
            raise AssertionError("synthetic_updated_assessment_uses_superseded_source")
        history = _ok(
            request.get(API + f"/api/v1/claims/{claim_id}/initial-assessment/history"),
            "hm04_assessment_history",
        )
        by_assessment_id = {a["id"]: a for a in history["items"]}
        if (
            by_assessment_id[before["id"]]["source_state"] != "stale"
            or by_assessment_id[after["id"]]["source_state"] != "current"
            or by_assessment_id[before["id"]]["source_fingerprint"] != old_fp
        ):
            raise AssertionError("synthetic_assessment_history_fingerprints_invalid")
        stage_times["replacement_worker_new_assessment_ms"] = _milliseconds(stage)

        stage = time.monotonic()
        page.goto(WEB + f"/claims/{claim_id}", wait_until="networkidle")
        expect(page.get_by_text(replacement_fixture["file_name"], exact=True).first).to_be_visible()
        expect(page.get_by_text("engineer.docx", exact=True).first).to_be_visible()
        page.goto(WEB + f"/claims/{claim_id}/assessment", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Initial Assessment", exact=True)).to_be_visible()
        stages = {
            **stage_times,
            "current_and_historical_ui_ms": _milliseconds(stage),
        }
        report = {
            "scope": "isolated_synthetic_browser_ci_only",
            "case_code": case["case_id"],
            "corpus_version": "1.0.0",
            "invented_evidence_versions": 5,
            "old_document_immutable_and_superseded": True,
            "old_assessment_marked_stale": True,
            "stale_human_review_write_rejected": True,
            "superseded_document_replacement_rejected": True,
            "new_assessment_version_current_only": True,
            "human_task_time_measured": False,
            "human_hm_review_completed": False,
            "any_assessment_approved": False,
            "local_llm_invoked": False,
            "real_customer_data_used": False,
            "pilot_accepted": False,
            "machine_stage_elapsed_ms_observed": stages,
            "machine_total_elapsed_ms_observed": _milliseconds(start),
        }
        out = Path("artifacts/hm04-version-replacement-journey.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        browser.close()
    print("Synthetic HM-04 real replacement + source-fresh assessment: PASS.")
    print("Machine stage timings only:", json.dumps(stages, sort_keys=True))


if __name__ == "__main__":
    main()
