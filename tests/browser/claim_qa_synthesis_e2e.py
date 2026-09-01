"""Focused browser coverage for Phase 12G governed Claim Q&A controls."""
from __future__ import annotations

import os

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})

        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")

        page.goto(f"{BASE_URL}/claims", wait_until="networkidle")
        page.get_by_placeholder("Search claim, vessel or IMO…").fill("MCRI-DEMO-MT-ORION")
        page.get_by_role("button", name="Apply filters").click()
        claim_link = page.locator('a[href^="/claims/"]').filter(has_text="MCRI-HM-").first
        expect(claim_link).to_be_visible()
        claim_href = claim_link.get_attribute("href")
        if not claim_href:
            raise AssertionError("Demo claim link did not expose an href")

        page.goto(f"{BASE_URL}{claim_href}", wait_until="networkidle")
        page.get_by_role("link", name="Open Claim Q&A").click()
        expect(page.get_by_role("heading", name="Claim Q&A")).to_be_visible()
        page.get_by_label("Claim Q&A answer mode").select_option("governed_synthesis")
        expect(page.get_by_text("Governed synthesis requested.", exact=False)).to_be_visible()
        page.get_by_label("Claim Q&A retrieval mode").select_option("hybrid")
        page.get_by_label("Claim Q&A question").fill(
            "What were the turbocharger operating hours before casualty?"
        )

        with page.expect_response(
            lambda response: response.url.endswith("/evidence-search/qa/synthesize")
            and response.request.method == "POST"
        ) as response_info:
            page.get_by_role("button", name="Ask with governed synthesis").click()
        response = response_info.value
        if not response.ok:
            raise AssertionError(f"Governed Claim Q&A failed: HTTP {response.status}")
        payload = response.json()
        if payload.get("synthesis_used") is not False:
            raise AssertionError("CI environment unexpectedly executed governed external synthesis")
        if payload.get("fallback_used") is not True:
            raise AssertionError("Governed synthesis did not preserve the safe extractive fallback")
        if payload.get("claim_facts_updated") is not False:
            raise AssertionError("Governed Q&A reported an authoritative ClaimFact mutation")
        if payload.get("provider") is not None:
            raise AssertionError("Blocked/bypassed CI synthesis unexpectedly recorded an external provider")

        expect(page.locator('section[aria-label="Governed synthesis status"]')).to_be_visible()
        expect(page.get_by_text("Governed synthesis not used — extractive fallback returned.", exact=True)).to_be_visible()
        expect(page.locator('section[aria-label="Claim Q&A source statements"] article').first).to_be_visible()

        browser.close()

    print("Governed Claim Q&A browser E2E passed.")


if __name__ == "__main__":
    main()
