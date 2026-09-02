"""Phase 12K browser coverage for Correspondence and Claim Pack localization."""
from __future__ import annotations

import os
import re

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")


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
            tracked = "/correspondence" in request.url or "/claim-pack-exports" in request.url
            if tracked and request.method not in {"GET", "HEAD", "OPTIONS"}:
                mutations.append(f"{request.method} {request.url}")

        page.on("request", record_request)

        page.goto(f"{BASE_URL}/claims", wait_until="networkidle")
        page.get_by_placeholder("Search claim, vessel or IMO…").fill("MCRI-DEMO-MT-ORION")
        page.get_by_role("button", name="Apply filters").click()
        expect(page.get_by_text("MT ORION", exact=True)).to_be_visible()
        claim_link = page.locator('a[href^="/claims/"]').filter(has_text=re.compile(r"^MCRI-HM-")).first
        expect(claim_link).to_be_visible()
        claim_href = claim_link.get_attribute("href")
        assert claim_href, "Expected MT ORION claim href"
        claim_id = claim_href.rstrip("/").split("/")[-1]

        # Correspondence: the UI localizes, while draft/source content is not rewritten.
        page.goto(f"{BASE_URL}/claims/{claim_id}/correspondence", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Correspondence Centre")).to_be_visible()
        expect(page.locator("html")).to_have_attribute("dir", "ltr")
        claim_ref = page.locator("p.eyebrow")
        expect(claim_ref).to_have_attribute("dir", "ltr")
        body_en = page.get_by_label("Body")
        expect(body_en).to_have_attribute("dir", "auto")
        original_body = body_en.input_value()
        assert original_body.startswith("Dear Sirs,"), "Default correspondence content unexpectedly changed"

        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.get_by_role("heading", name="مرکز مکاتبات")).to_be_visible()
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        body_fa = page.get_by_label("متن مکاتبه")
        expect(body_fa).to_have_attribute("dir", "auto")
        assert body_fa.input_value() == original_body, "Locale switch translated or rewrote correspondence content"
        recipient = page.get_by_label("گیرنده").first
        assert recipient.input_value() == "Shipowner / Assured", "Locale switch rewrote recipient content"
        assert mutations == [], f"Correspondence locale switch caused mutation: {mutations}"

        # Claim Pack: control shell localizes; immutable export metadata stays directionally isolated.
        page.goto(f"{BASE_URL}/claims/{claim_id}/claim-pack", wait_until="networkidle")
        expect(page.get_by_role("heading", name="خروجی بسته پرونده")).to_be_visible()
        expect(page.get_by_text("ابزار بازبینی — نه تصمیم پرونده", exact=True)).to_be_visible()
        expect(page.get_by_label("یادداشت ایجاد خروجی (اختیاری)")).to_have_attribute("dir", "auto")
        expect(page.locator("html")).to_have_attribute("dir", "rtl")

        filenames = page.locator("tbody tr td:nth-child(3) p").first
        if filenames.count():
            expect(filenames).to_have_attribute("dir", "ltr")
        hashes = page.locator("tbody code").first
        if hashes.count():
            expect(hashes).to_have_attribute("dir", "ltr")

        page.get_by_role("button", name="EN", exact=True).click()
        expect(page.get_by_role("heading", name="Claim Pack Export")).to_be_visible()
        expect(page.get_by_text("Review aid — not a claim decision", exact=True)).to_be_visible()
        expect(page.locator("html")).to_have_attribute("dir", "ltr")
        assert mutations == [], f"Claim Pack locale switch caused mutation: {mutations}"

        browser.close()


if __name__ == "__main__":
    main()
