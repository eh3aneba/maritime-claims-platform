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
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@pilot.test")
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
            ("Open financial review", "Financial review"),
            ("Open initial assessment", "Initial Assessment"),
        ]
        for link_name, heading in checks:
            page.goto(f"{BASE_URL}{claim_href}", wait_until="networkidle")
            page.get_by_role("link", name=link_name).click()
            expect(page.get_by_role("heading", name=heading)).to_be_visible()

        page.goto(f"{BASE_URL}{claim_href}", wait_until="networkidle")
        page.get_by_role("link", name="Open AI review queue").click()
        expect(page.get_by_text("AI Review", exact=False).first).to_be_visible()

        page.screenshot(path=str(SCREENSHOT), full_page=True)
        browser.close()

    print("Design-partner browser E2E passed.")
    print(f"Screenshot: {SCREENSHOT}")


if __name__ == "__main__":
    main()
