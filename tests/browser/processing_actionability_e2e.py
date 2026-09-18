"""Browser coverage for A04 document-processing actionability."""
from __future__ import annotations

import json
import os

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")

CLAIM_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
FAILED_DOCUMENT_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
STALE_DOCUMENT_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    claim = {
        "id": CLAIM_ID,
        "organization_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "claim_reference": "MCRI-HM-2026-A04",
        "external_reference": None,
        "claim_type": "hull_machinery",
        "claim_subtype": "machinery_damage",
        "status": "investigation",
        "priority": "high",
        "incident_date": "2026-09-01",
        "notification_date": "2026-09-02",
        "incident_description": "A04 browser regression fixture.",
        "estimated_loss": "250000.00",
        "current_reserve": "100000.00",
        "currency": "USD",
        "vessel": {
            "id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
            "name": "MT A04",
            "imo_number": "9999999",
        },
        "handler": None,
        "created_at": "2026-09-01T00:00:00Z",
        "updated_at": "2026-09-01T00:00:00Z",
    }

    def document(document_id: str, filename: str, processing_status: str) -> dict:
        return {
            "id": document_id,
            "claim_id": CLAIM_ID,
            "filename": filename,
            "original_filename": filename,
            "document_type": "survey_report",
            "mime_type": "application/pdf",
            "file_size_bytes": 2048,
            "file_hash": "ab" * 32,
            "document_family_id": document_id,
            "supersedes_document_id": None,
            "version_number": 1,
            "is_current": True,
            "replacement_reason": None,
            "superseded_at": None,
            "superseded_by_id": None,
            "processing_status": processing_status,
            "confidentiality_level": "confidential",
            "malware_scan_status": "clean",
            "malware_scanned_at": "2026-09-01T00:00:00Z",
            "uploaded_by_id": None,
            "created_at": "2026-09-01T00:00:00Z",
        }

    documents = {
        "items": [
            document(FAILED_DOCUMENT_ID, "failed-report.pdf", "failed"),
            document(STALE_DOCUMENT_ID, "stale-report.pdf", "processing"),
        ],
        "total": 2,
        "quarantined_items": [],
        "quarantined_total": 0,
    }

    states = {
        FAILED_DOCUMENT_ID: "failed",
        STALE_DOCUMENT_ID: "running",
    }
    retry_calls = {FAILED_DOCUMENT_ID: 0, STALE_DOCUMENT_ID: 0}

    def summary(document_id: str) -> dict:
        state = states[document_id]
        if state == "queued":
            return {
                "job": {
                    "id": f"11111111-1111-1111-1111-{document_id[-12:]}",
                    "document_id": document_id,
                    "job_type": "extract_text",
                    "status": "pending",
                    "attempt_count": 1,
                    "max_attempts": 3,
                    "last_error": None,
                    "result": None,
                    "created_at": "2026-09-01T00:00:00Z",
                    "completed_at": None,
                },
                "text_extraction": None,
                "operator_status": "queued",
                "can_retry": False,
                "retry_recommended": False,
            }
        if state == "running":
            return {
                "job": {
                    "id": f"22222222-2222-2222-2222-{document_id[-12:]}",
                    "document_id": document_id,
                    "job_type": "extract_text",
                    "status": "running",
                    "attempt_count": 1,
                    "max_attempts": 3,
                    "last_error": None,
                    "result": None,
                    "created_at": "2026-09-01T00:00:00Z",
                    "completed_at": None,
                },
                "text_extraction": None,
                "operator_status": "running",
                "can_retry": True,
                "retry_recommended": True,
            }
        return {
            "job": {
                "id": f"33333333-3333-3333-3333-{document_id[-12:]}",
                "document_id": document_id,
                "job_type": "extract_text",
                "status": "failed",
                "attempt_count": 3,
                "max_attempts": 3,
                "last_error": "internal detail must never be rendered",
                "result": None,
                "created_at": "2026-09-01T00:00:00Z",
                "completed_at": "2026-09-01T00:10:00Z",
            },
            "text_extraction": None,
            "operator_status": "failed",
            "can_retry": True,
            "retry_recommended": True,
        }

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1200})
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")

        page.route(
            f"**/api/v1/claims/{CLAIM_ID}",
            lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(claim)),
        )
        page.route(
            f"**/api/v1/claims/{CLAIM_ID}/facts",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"items": [], "total": 0}),
            ),
        )
        page.route(
            f"**/api/v1/claims/{CLAIM_ID}/documents",
            lambda route: route.fulfill(status=200, content_type="application/json", body=json.dumps(documents)),
        )

        def route_processing(route) -> None:
            url = route.request.url
            document_id = FAILED_DOCUMENT_ID if FAILED_DOCUMENT_ID in url else STALE_DOCUMENT_ID
            if route.request.method == "POST" and url.endswith("/retry"):
                retry_calls[document_id] += 1
                states[document_id] = "queued"
                body = summary(document_id)["job"]
                route.fulfill(status=202, content_type="application/json", body=json.dumps(body))
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(summary(document_id)),
            )

        page.route(f"**/api/v1/claims/{CLAIM_ID}/documents/*/processing**", route_processing)
        page.goto(f"{BASE_URL}/claims/{CLAIM_ID}", wait_until="networkidle")

        expect(page.get_by_text("Processing · failed", exact=True)).to_be_visible()
        expect(page.get_by_text("Processing · running", exact=True)).to_be_visible()
        expect(page.get_by_text("Attempts 3/3", exact=True)).to_be_visible()
        expect(page.get_by_text("internal detail must never be rendered", exact=True)).to_have_count(0)

        recover = page.get_by_role("button", name="Recover processing")
        expect(recover).to_be_visible()
        recover.dblclick()
        expect(page.get_by_text("Processing · queued", exact=True).first).to_be_visible()
        assert retry_calls[STALE_DOCUMENT_ID] == 1, retry_calls

        retry = page.get_by_role("button", name="Retry processing")
        expect(retry).to_be_visible()
        retry.click()
        expect(page.get_by_text("Processing · queued", exact=True)).to_have_count(2)
        assert retry_calls[FAILED_DOCUMENT_ID] == 1, retry_calls

        expect(page.get_by_role("button", name="Recover processing")).to_have_count(0)
        expect(page.get_by_role("button", name="Retry processing")).to_have_count(0)

        browser.close()

    print("A04 processing actionability browser E2E passed.")


if __name__ == "__main__":
    main()
