"""Real first-manual synthetic MT ORION CI, not human or release acceptance."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sys
import time
from zipfile import is_zipfile

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.hm_multidoc_packs import make_docx_bytes
from scripts.pilot_demo_seed_guard import check

WEB = "http://127.0.0.1:3000"
API = "http://127.0.0.1:8000/api/v1"


def require(condition, label: str) -> None:
    if not condition:
        raise AssertionError("first_manual_" + label)


def result(response, label: str):
    require(response.ok, label + "_http_" + str(response.status))
    return response.json()


def main() -> None:
    # All inputs are generated inside a dedicated GitHub-hosted CI job.
    # Never accept an operator URL or a file path containing actual evidence.
    require(os.getenv("GITHUB_ACTIONS") == "true"
            and os.getenv("RUNNER_ENVIRONMENT") == "github-hosted"
            and os.getenv("APP_ENV") == "pilot"
            and os.getenv("NEXT_PUBLIC_API_BASE_URL") == API,
            "synthetic_host_scope")
    check(dict(os.environ))
    release_sha = os.environ["MCRI_REHEARSAL_SHA"]
    require(re.fullmatch(r"[0-9a-f]{40}", release_sha) is not None, "candidate_identity")
    password = os.environ["MCRI_DEMO_PASSWORD"]
    require(len(password) >= 12, "synthetic_login_config")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        anon = browser.new_context()
        require(anon.request.get(API + "/claims").status in (401, 403), "anonymous_access_denied")
        anon.close()
        context = browser.new_context(viewport={"width": 1440, "height": 1050})
        page = context.new_page()
        page.goto(WEB + "/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(os.environ["MCRI_DEMO_ORG_SLUG"])
        page.get_by_label("Email").fill(os.environ["MCRI_DEMO_EMAIL"])
        page.get_by_label("Password").fill(password)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")
        request = context.request
        listing = result(request.get(API + "/claims?search=MCRI-DEMO-MT-ORION"), "claim_list")
        require(listing["total"] == 1 and len(listing["items"]) == 1, "single_orion")
        claim = listing["items"][0]
        require(claim["external_reference"] == "MCRI-DEMO-MT-ORION"
                and claim["status"] == "new", "clean_new_claim")
        claim_id = claim["id"]
        endpoint = API + "/claims/" + claim_id
        start = result(request.get(endpoint + "/documents"), "initial_docs")
        require(start["items"] == [], "no_preseeded_evidence")
        history = result(request.get(endpoint + "/initial-assessment/history"), "initial_history")
        # Match the schema's historical version collection (no seeded approvals).
        require(history["items"] == [], "no_preseeded_assessment")

        page.goto(WEB + "/claims/" + claim_id, wait_until="networkidle")
        expect(page.get_by_role("heading", name="MT ORION")).to_be_visible()

        name = "synthetic-orion-chief-engineer.docx"
        native = make_docx_bytes([
            "FICTIONAL MT ORION: manual evidence rehearsal only.",
            "Turbocharger No.2 abnormal vibration reported; cause not established.",
            "No maker recommendation or policy wording available for review.",
        ])
        page.locator('input[type="file"]').first.set_input_files({
            "name": name, "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "buffer": native,
        })
        # A real raster picture is uploaded as a second source. It must not
        # become a machine OCR transcript in this manual-only mode.
        raster = context.new_page()
        raster.set_content("<main style='background:white;color:black;font-size:26px;padding:30px'>FICTIONAL MT ORION scanned note: cause NOT established.</main>")
        image = raster.locator("main").screenshot()
        raster.close()
        image_name = "synthetic-orion-scanned-note.png"
        result(request.post(endpoint + "/documents", multipart={
            "file": {"name": image_name, "mimeType": "image/png", "buffer": image},
            "document_type": "engine_log",
        }), "manual_raster_upload")

        hashes = {name: sha256(native).hexdigest(), image_name: sha256(image).hexdigest()}
        deadline = time.monotonic() + 100
        while time.monotonic() < deadline:
            records = result(request.get(endpoint + "/documents"), "documents")["items"]
            if len(records) == 2 and all(d["processing_status"] == "processed" for d in records):
                break
            require(not any(d["processing_status"] == "failed" for d in records), "worker_processing")
            time.sleep(2)
        else:
            raise AssertionError("first_manual_processing_timeout")
        require({d["original_filename"] for d in records} == set(hashes), "file_census")
        for doc in records:
            require(doc["malware_scan_status"] == "clean" and doc["is_current"]
                    and doc["version_number"] == 1
                    and doc["file_hash"] == hashes[doc["original_filename"]], "source_integrity")
            doc_url = endpoint + "/documents/" + doc["id"]
            download = request.get(doc_url + "/download")
            require(download.ok and sha256(download.body()).hexdigest() == doc["file_hash"], "download_original_bytes")
            processing = result(request.get(doc_url + "/processing"), "processing_summary")
            extraction = processing["text_extraction"]
            require(isinstance(extraction, dict), "extraction_status")
            if doc["original_filename"] == image_name:
                require(extraction["extraction_method"] == "image_requires_ocr"
                        and extraction["requires_ocr"] is True
                        and extraction["char_count"] == 0
                        and extraction["segment_count"] == 0, "ocr_remains_off")
            else:
                require(extraction["char_count"] > 0 and extraction["requires_ocr"] is False,
                        "native_text_available")

        result(request.post(endpoint + "/status", data={
            "status": "triage", "reason": "Fictional manual-only review rehearsal.",
        }), "triage")
        rules = result(request.get(endpoint + "/rules"), "requirements")
        require(rules["readiness"]["state"] == "not_ready" and any(
            x["document_type"] == "policy" and x["status"] not in ("accepted", "under_review")
            for x in rules["requirements"]), "missing_policy")
        denied = request.post(endpoint + "/initial-assessment/generate", data={"allow_if_not_ready": False})
        require(denied.status == 409, "ordinary_assessment_blocked")
        assessment = result(request.post(endpoint + "/initial-assessment/generate", data={
            "allow_if_not_ready": True, "override_reason": "Fictional manual preliminary review aid only.",
        }), "preliminary_assessment")
        require(assessment["is_preliminary"] is True and assessment["approved_by_id"] is None
                and assessment["source_state"] == "current", "unapproved_version")
        doc_section = next(s for s in assessment["sections"] if s["section_key"] == "documents")
        require({d["id"] for d in records}.issubset({
            x["id"] for x in doc_section["source_manifest"] if x.get("kind") == "document"
        }), "source_bound_assessment")
        # Visit actual operator pages without acting as an independent reviewer.
        for link, heading in (
            ("Open requirements", "Requirements & workflow"),
            ("Open chronology", "Claim chronology"),
            ("Open technical review", "Technical review matrix"),
            ("Open financial review", "Financial review"),
            ("Open correspondence centre", "Correspondence Centre"),
            ("Open claim-pack exports", "Claim Pack Export"),
        ):
            page.goto(WEB + "/claims/" + claim_id, wait_until="networkidle")
            page.get_by_role("link", name=link).click()
            expect(page.get_by_role("heading", name=heading)).to_be_visible()
        export = result(request.post(endpoint + "/claim-pack-exports", data={
            "export_format": "xlsx", "acknowledge_review_aid": True,
            "generation_note": "Fictional MT ORION preliminary review aid only.",
        }), "claim_pack")
        download = request.get(endpoint + "/claim-pack-exports/" + export["id"] + "/download")
        require(download.ok and is_zipfile(BytesIO(download.body()))
                and sha256(download.body()).hexdigest() == export["file_hash"]
                and download.headers.get("x-claim-pack-snapshot-sha256") == export["snapshot_hash"],
                "immutable_review_aid")
        browser.close()

    report = {
        "schema": "seeclaims-first-manual-hm-synthetic-ci-v1",
        "candidate_sha": release_sha,
        "app_env": "pilot",
        "case": "MT ORION",
        "authenticated_manual_upload": True,
        "original_bytes_and_scan_verified": True,
        "raster_ocr_not_performed": True,
        "missing_policy_blocks_ordinary_assessment": True,
        "unapproved_source_bound_preliminary_assessment": True,
        "review_aid_download_verified": True,
        "operator_pages_reachable": True,
        "synthetic_only": True,
        "human_review_completed": False,
        "independent_operator_host_verified": False,
        "real_customer_data_authorized": False,
        "security_owner_approved": False,
        "pilot_accepted": False,
    }
    out = Path("artifacts/first-manual-ci/journey.json")
    with out.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print("PASS: first-manual synthetic MT ORION journey. NOT human or release acceptance.")


if __name__ == "__main__":
    main()
