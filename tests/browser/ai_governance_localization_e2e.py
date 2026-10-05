"""Phase 12K browser coverage for AI review/governance/operations localization."""
from __future__ import annotations

import json
import os

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")

TRACKED = (
    "/ai-review",
    "/ai-governance",
    "/ai-evaluation",
    "/ai-operations",
    "/ai-provider",
    "/governance-webhooks",
)


def _evaluation_suite(status: str = "collecting") -> dict:
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "activation_request_id": "22222222-2222-2222-2222-222222222222",
        "requested_by_id": "33333333-3333-3333-3333-333333333333",
        "finalized_by_id": None,
        "revoked_by_id": None,
        "attempt_number": 1,
        "suite_key": "browser-measured-inputs",
        "benchmark_profile": "content-free-browser-fixture",
        "activation_model": "synthetic-governed-model",
        "prompt_bundle_version": "prompt-v1",
        "schema_bundle_version": "schema-v1",
        "max_input_chars": 12000,
        "max_output_tokens": 1500,
        "data_mode": "synthetic",
        "thresholds": {},
        "status": status,
        "outcome": None,
        "metrics": None,
        "failure_reasons": [],
        "evaluation_hash": None,
        "evaluation_note": None,
        "evaluated_at": None,
        "decision_note": None,
        "decision_hash": None,
        "decided_at": None,
        "promotion_expires_at": None,
        "revoked_at": None,
        "revocation_note": None,
        "summary": {
            "case_count": 0 if status == "collecting" else 12,
            "required_case_count": 12,
            "thresholds_passed": status != "collecting",
            "independent_reviews_complete": False,
            "promotion_active": False,
        },
        "cases": [],
        "reviews": [],
        "created_at": "2026-10-04T00:00:00Z",
    }


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    mutations: list[str] = []
    evaluation_fixture = {"suites": [_evaluation_suite()]}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1100})

        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")

        def record_request(request) -> None:
            if request.method not in {"GET", "HEAD", "OPTIONS"} and any(part in request.url for part in TRACKED):
                mutations.append(f"{request.method} {request.url}")

        def fulfill_evaluation(route) -> None:
            if route.request.method != "GET":
                route.continue_()
                return
            route.fulfill(status=200, content_type="application/json", body=json.dumps(evaluation_fixture))

        page.on("request", record_request)

        # AI Review: shell/local controls switch language; locale change must not approve/edit/reject anything.
        page.goto(f"{BASE_URL}/ai-review", wait_until="networkidle")
        expect(page.get_by_role("heading", name="AI Review", exact=True)).to_be_visible()
        expect(page.locator("html")).to_have_attribute("dir", "ltr")
        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.get_by_role("heading", name="بازبینی AI", exact=True)).to_be_visible()
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        assert mutations == [], f"AI Review locale switch caused mutation: {mutations}"

        # AI Governance: status and controls localize without creating/reviewing/authorizing/revoking anything.
        page.goto(f"{BASE_URL}/ai-governance", wait_until="networkidle")
        expect(page.get_by_role("heading", name="فعال‌سازی ارائه‌دهنده AI", exact=True)).to_be_visible()
        page.get_by_role("button", name="EN", exact=True).click()
        expect(page.get_by_role("heading", name="AI provider activation", exact=True)).to_be_visible()
        expect(page.locator("html")).to_have_attribute("dir", "ltr")
        assert mutations == [], f"AI Governance locale switch caused mutation: {mutations}"

        # Evaluation gate: real measurement fields must start unknown/blank and reviewer approval
        # must remain disabled until the reviewer supplies bounded evidence plus a human note.
        page.route("**/api/v1/ai-evaluation", fulfill_evaluation)
        page.goto(f"{BASE_URL}/ai-evaluation", wait_until="networkidle")
        expect(page.get_by_role("heading", name="AI quality, safety and cost evaluation", exact=True)).to_be_visible()
        benchmark_section = page.locator("section").filter(has_text="Record an observed benchmark result")
        expect(benchmark_section).to_have_count(1)
        measured_inputs = benchmark_section.locator('input[type="number"]')
        expect(measured_inputs).to_have_count(14)
        for index in range(14):
            expect(measured_inputs.nth(index)).to_have_value("")
        expect(benchmark_section.get_by_label("Measured result", exact=True)).to_have_value("")
        expect(benchmark_section.get_by_label("Boundary control outcome", exact=True)).to_have_value("")
        expect(benchmark_section.get_by_label("Bounded evidence reference", exact=True)).to_have_value("")
        expect(benchmark_section.get_by_label("Human verification note", exact=True)).to_have_value("")
        assert "reviewer reproduced the benchmark" not in page.content().lower()
        assert mutations == [], f"Loading blank evaluation form caused mutation: {mutations}"

        evaluation_fixture["suites"] = [_evaluation_suite("review_ready")]
        page.reload(wait_until="networkidle")
        approve_buttons = page.get_by_role("button", name="Approve with evidence", exact=True)
        expect(approve_buttons).to_have_count(2)
        expect(approve_buttons.nth(0)).to_be_disabled()
        expect(approve_buttons.nth(1)).to_be_disabled()
        evidence_inputs = page.get_by_label("Reviewer evidence reference", exact=True)
        note_inputs = page.get_by_label("Reviewer note", exact=True)
        expect(evidence_inputs).to_have_count(2)
        expect(note_inputs).to_have_count(2)
        assert evidence_inputs.nth(0).input_value() == ""
        assert note_inputs.nth(0).input_value() == ""
        note_inputs.nth(0).fill("Independent benchmark evidence checked.")
        expect(approve_buttons.nth(0)).to_be_disabled()
        evidence_inputs.nth(0).fill("artifact://evaluation/quality-review")
        expect(approve_buttons.nth(0)).to_be_enabled()
        assert mutations == [], f"Entering reviewer evidence without approval caused mutation: {mutations}"

        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.get_by_role("heading", name="ارزیابی کیفیت، ایمنی و هزینه AI", exact=True)).to_be_visible()
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        assert mutations == [], f"AI Evaluation locale switch caused mutation: {mutations}"

        # AI Operations: content-free governance plane remains read-only on locale changes.
        page.goto(f"{BASE_URL}/ai-operations", wait_until="networkidle")
        expect(page.get_by_role("heading", name="لاگ تصمیم AI / عملیات AI", exact=True)).to_be_visible()
        page.get_by_role("button", name="EN", exact=True).click()
        expect(page.get_by_role("heading", name="AI Decision Log / AI Operations", exact=True)).to_be_visible()
        expect(page.locator("html")).to_have_attribute("dir", "ltr")
        assert mutations == [], f"AI Operations locale switch caused mutation: {mutations}"

        # Integrations: editable destination content remains unchanged while the operator shell localizes.
        page.goto(f"{BASE_URL}/ai-integrations", wait_until="networkidle")
        expect(page.get_by_role("heading", name="AI Integrations / SIEM Webhooks", exact=True)).to_be_visible()
        name_input = page.get_by_label("Name", exact=True)
        endpoint_input = page.get_by_label("HTTPS endpoint", exact=True)
        original_name = name_input.input_value()
        original_endpoint = endpoint_input.input_value()
        expect(endpoint_input).to_have_attribute("dir", "ltr")

        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.get_by_role("heading", name="یکپارچه‌سازی‌های AI / وب‌هوک‌های SIEM", exact=True)).to_be_visible()
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        assert page.get_by_label("نام", exact=True).input_value() == original_name, "Locale switch rewrote destination name content"
        assert page.get_by_label("endpoint HTTPS", exact=True).input_value() == original_endpoint, "Locale switch rewrote endpoint content"
        expect(page.get_by_label("endpoint HTTPS", exact=True)).to_have_attribute("dir", "ltr")
        assert mutations == [], f"AI Integrations locale switch caused mutation: {mutations}"

        browser.close()


if __name__ == "__main__":
    main()
