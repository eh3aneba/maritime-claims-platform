"""Phase 12K browser coverage for AI review/governance/operations localization."""
from __future__ import annotations

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


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    mutations: list[str] = []

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

        # Evaluation gate: language switching cannot create/finalize/review/promote a suite.
        page.goto(f"{BASE_URL}/ai-evaluation", wait_until="networkidle")
        expect(page.get_by_role("heading", name="AI quality, safety and cost evaluation", exact=True)).to_be_visible()
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
