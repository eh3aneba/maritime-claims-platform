"""Browser smoke test for the synthetic MT ORION design-partner environment.

Prerequisites:
  pip install -r tests/browser/requirements.txt
  playwright install chromium
  docker compose up -d --build
  docker compose --profile demo run --rm demo-seed

Environment variables may override the defaults below.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")
SCREENSHOT = Path(os.getenv("MCRI_E2E_SCREENSHOT", "artifacts/design-partner-e2e.png"))


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()

        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")
        expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()

        page.goto(f"{BASE_URL}/claims", wait_until="networkidle")
        page.get_by_placeholder("Search claim, vessel or IMO…").fill("MCRI-DEMO-MT-ORION")
        page.get_by_role("button", name="Apply filters").click()
        expect(page.get_by_text("MT ORION", exact=True)).to_be_visible()
        claim_link = page.locator('a[href^="/claims/"]').filter(has_text="MCRI-HM-").first
        expect(claim_link).to_be_visible()
        claim_href = claim_link.get_attribute("href")
        if not claim_href:
            raise AssertionError("Demo claim link did not expose an href")
        page.goto(f"{BASE_URL}{claim_href}", wait_until="networkidle")
        expect(page.get_by_role("heading", name="MT ORION")).to_be_visible()
        expect(page.get_by_text("MCRI-DEMO-MT-ORION", exact=True)).to_be_visible()

        checks = [
            ("Open requirements", "Requirements & workflow"),
            ("Open chronology", "Claim chronology"),
            ("Open technical review", "Technical review matrix"),
            ("Open evidence matrix", "Evidence Matrix"),
            ("Open claim-pack exports", "Claim Pack Export"),
            ("Open financial review", "Financial review"),
            ("Open initial assessment", "Initial Assessment"),
        ]
        for link_name, heading in checks:
            page.goto(f"{BASE_URL}{claim_href}", wait_until="networkidle")
            page.get_by_role("link", name=link_name).click()
            expect(page.get_by_role("heading", name=heading)).to_be_visible()

        page.goto(f"{BASE_URL}{claim_href}", wait_until="networkidle")
        page.get_by_role("link", name="Open claim-pack exports").click()
        expect(page.get_by_role("heading", name="Claim Pack Export")).to_be_visible()
        page.get_by_role(
            "checkbox",
            name=re.compile(r"I understand this export is a review aid"),
        ).check()
        with page.expect_response(
            lambda response: "/api/v1/claims/" in response.url
            and "/claim-pack-exports" in response.url
            and response.request.method == "POST"
        ) as export_response_info:
            page.get_by_role("button", name="Generate PDF").click()
        export_response = export_response_info.value
        if not export_response.ok:
            raise AssertionError(
                f"Claim-pack generation failed: HTTP {export_response.status}"
            )
        expect(page.get_by_text(re.compile(r"PDF snapshot generated"))).to_be_visible()
        with page.expect_download() as download_info:
            page.get_by_role("button", name="Download").first.click()
        if not download_info.value.suggested_filename.endswith(".pdf"):
            raise AssertionError("Claim-pack download did not return a PDF filename")

        page.goto(f"{BASE_URL}{claim_href}", wait_until="networkidle")
        with page.expect_response(
            lambda response: "/api/v1/ai-review/groups?" in response.url
            and response.request.method == "GET"
        ) as review_response_info:
            page.get_by_role("link", name="Open AI review queue").click()
        review_response = review_response_info.value
        if not review_response.ok:
            raise AssertionError(
                f"AI review groups request failed: HTTP {review_response.status}"
            )
        expect(page.get_by_role("heading", name="AI Review")).to_be_visible()
        expect(page.get_by_text("Loading review queue…", exact=True)).to_be_hidden()
        expect(
            page.get_by_text(
                re.compile(r"\d+ review groups? · \d+ need attention"),
                exact=True,
            )
        ).to_be_visible()

        page.screenshot(path=str(SCREENSHOT), full_page=True)
        browser.close()

    print("Design-partner browser E2E passed.")
    print(f"Screenshot: {SCREENSHOT}")


if __name__ == "__main__":
    main()
