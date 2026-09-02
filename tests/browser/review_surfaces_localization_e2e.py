"""Focused browser coverage for Phase 12K review-support localization."""
from __future__ import annotations

import os
import re

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")

TRACKED = ("/technical", "/financial", "/severity-reserve", "/recovery-timebar")


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    mutations: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1100})

        def record_request(request) -> None:
            if request.method not in {"GET", "HEAD", "OPTIONS"} and any(part in request.url for part in TRACKED):
                mutations.append(f"{request.method} {request.url}")

        page.on("request", record_request)

        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")

        page.goto(f"{BASE_URL}/claims", wait_until="networkidle")
        page.get_by_placeholder("Search claim, vessel or IMO…").fill("MCRI-DEMO-MT-ORION")
        page.get_by_role("button", name="Apply filters").click()
        expect(page.get_by_text("MT ORION", exact=True)).to_be_visible()
        claim_link = page.locator('a[href^="/claims/"]').filter(has_text=re.compile(r"^MCRI-HM-")).first
        expect(claim_link).to_be_visible()
        claim_href = claim_link.get_attribute("href")
        assert claim_href, "Expected MT ORION claim href"
        claim_id = claim_href.rstrip("/").split("/")[-1]

        # Technical: English -> Persian. Locale switching must not reload or mutate technical review state.
        page.goto(f"{BASE_URL}/claims/{claim_id}/technical", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Technical review matrix")).to_be_visible()
        expect(page.locator("html")).to_have_attribute("dir", "ltr")
        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.get_by_role("heading", name="ماتریس بازبینی فنی")).to_be_visible()
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        assert mutations == [], f"Technical locale switch caused mutation: {mutations}"

        # Financial: Persian -> English. Currency/amount content remains data, while labels switch language.
        page.goto(f"{BASE_URL}/claims/{claim_id}/financial", wait_until="networkidle")
        expect(page.get_by_role("heading", name="بازبینی مالی")).to_be_visible()
        expect(page.get_by_text("ذخیره فعلی", exact=True)).to_be_visible()
        page.get_by_role("button", name="EN", exact=True).click()
        expect(page.get_by_role("heading", name="Financial review")).to_be_visible()
        expect(page.get_by_text("Current reserve", exact=True)).to_be_visible()
        assert mutations == [], f"Financial locale switch caused mutation: {mutations}"

        # Severity & reserve support: do not click build/refresh/decision controls.
        page.goto(f"{BASE_URL}/claims/{claim_id}/severity-reserve", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Severity & Reserve Support")).to_be_visible()
        expect(page.get_by_text("Human reserve authority required.", exact=False)).to_be_visible()
        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.get_by_role("heading", name="پشتیبانی شدت و ذخیره")).to_be_visible()
        expect(page.get_by_text("اختیار انسانی برای ذخیره الزامی است.", exact=False)).to_be_visible()
        assert mutations == [], f"Severity/reserve locale switch caused mutation: {mutations}"

        # Recovery & time-bar: candidate dates remain non-authoritative and no decision/build runs on locale switch.
        page.goto(f"{BASE_URL}/claims/{claim_id}/recovery-timebar", wait_until="networkidle")
        expect(page.get_by_role("heading", name="هوشمندی بازیافت و مهلت زمانی")).to_be_visible()
        expect(page.get_by_text("تأیید انسانی/حقوقی الزامی است.", exact=False)).to_be_visible()
        page.get_by_role("button", name="EN", exact=True).click()
        expect(page.get_by_role("heading", name="Recovery & Time-bar Intelligence")).to_be_visible()
        expect(page.get_by_text("Human/legal verification required.", exact=False)).to_be_visible()
        assert mutations == [], f"Recovery/time-bar locale switch caused mutation: {mutations}"

        browser.close()


if __name__ == "__main__":
    main()
