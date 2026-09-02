"""Focused browser coverage for Phase 12K Chronology localization."""
from __future__ import annotations

import json
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

    chronology_mutations: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1100})
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

        chronology_payload = {
            "events": [
                {
                    "id": "99999999-9999-9999-9999-999999999991",
                    "title": "Main engine shutdown",
                    "description": "Turbocharger vibration increased; Chief Engineer stopped the main engine; RPM: 72",
                    "event_type": "shutdown",
                    "occurred_on": "2026-08-31",
                    "occurred_time": "14:05:00",
                    "timezone_label": "UTC+04",
                    "materiality": "high",
                    "evidence": [
                        {
                            "extraction_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1",
                            "document_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1",
                            "document_name": "engine-log-2026-08-31.pdf",
                            "field_path": "events[3].rpm",
                            "value": {"value": 72, "unit": "rpm", "raw": "72 rpm"},
                            "source_verified": True,
                            "source_quote": "14:05 ME stopped after abnormal TC vibration.",
                        },
                        {
                            "extraction_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2",
                            "document_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1",
                            "document_name": "engine-log-2026-08-31.pdf",
                            "field_path": "events[3].engine_load",
                            "value": {"value": 48, "unit": "%", "raw": "48%"},
                            "source_verified": False,
                            "source_quote": None,
                        },
                    ],
                }
            ],
            "conflicts": [
                {
                    "id": "cccccccc-cccc-cccc-cccc-ccccccccccc1",
                    "topic": "Shutdown time discrepancy",
                    "conflict_type": "timestamp_difference",
                    "status": "open",
                    "materiality": "medium",
                    "description": "Engine Log records 14:05 while the Chief Engineer report records 14:12.",
                    "value_a": {"date": "2026-08-31", "time": "14:05", "timezone": "UTC+04"},
                    "value_b": {"date": "2026-08-31", "time": "14:12", "timezone": "UTC+04"},
                    "difference_minutes": 7,
                    "resolution_note": None,
                }
            ],
            "event_count": 1,
            "open_conflict_count": 1,
        }

        def route_chronology(route) -> None:
            request = route.request
            if request.method == "GET" and request.url.rstrip("/").endswith(f"/claims/{claim_id}/chronology"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(chronology_payload))
                return
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                chronology_mutations.append(f"{request.method} {request.url}")
                route.fulfill(status=200, content_type="application/json", body="{}")
                return
            route.continue_()

        page.route(f"**/api/v1/claims/{claim_id}/chronology**", route_chronology)
        page.goto(f"{BASE_URL}/claims/{claim_id}/chronology", wait_until="networkidle")

        expect(page.locator("html")).to_have_attribute("lang", "en")
        expect(page.locator("html")).to_have_attribute("dir", "ltr")
        expect(page.get_by_role("heading", name="Claim chronology")).to_be_visible()
        expect(page.get_by_text("Conflicts are review flags only", exact=False)).to_be_visible()
        expect(page.get_by_text("Event importance: High", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="Evidence conflicts")).to_be_visible()
        expect(page.get_by_text("Conflict severity: Medium", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Build / refresh chronology")).to_be_visible()
        expect(page.get_by_placeholder("Explain how this difference should be understood…")).to_be_visible()
        expect(page.get_by_role("button", name="Accept difference")).to_be_visible()

        source_title = page.get_by_role("heading", name="Main engine shutdown")
        expect(source_title).to_be_visible()
        page.get_by_text("Sources (1) · Evidence fields (2)", exact=True).click()
        source_filename = page.get_by_text("engine-log-2026-08-31.pdf", exact=True).first
        expect(source_filename).to_have_attribute("dir", "ltr")
        source_quote = page.get_by_text("14:05 ME stopped after abnormal TC vibration.", exact=True)
        expect(source_quote).to_be_visible()
        timeline_time = page.get_by_text("14:05", exact=True).first
        expect(timeline_time).to_have_attribute("dir", "ltr")

        assert chronology_mutations == [], f"Unexpected chronology mutation before locale switch: {chronology_mutations}"

        page.get_by_role("button", name="FA").click()
        expect(page.locator("html")).to_have_attribute("lang", "fa")
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(page.get_by_role("heading", name="خط زمانی پرونده")).to_be_visible()
        expect(page.get_by_text("تعارض‌ها فقط پرچم بازبینی هستند", exact=False)).to_be_visible()
        expect(page.get_by_text("رویدادهای خط زمانی", exact=True)).to_be_visible()
        expect(page.get_by_text("اهمیت رویداد: زیاد", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="تعارض‌های شواهد")).to_be_visible()
        expect(page.get_by_text("اختلاف زمان · باز", exact=True)).to_be_visible()
        expect(page.get_by_text("شدت تعارض: متوسط", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="ساخت / به‌روزرسانی خط زمانی")).to_be_visible()
        expect(page.get_by_placeholder("توضیح دهید این اختلاف چگونه باید درک شود…")).to_be_visible()
        expect(page.get_by_role("button", name="پذیرش اختلاف")).to_be_visible()
        expect(page.get_by_role("button", name="حل تعارض")).to_be_visible()

        # Source/extracted content remains unchanged and is not auto-translated.
        expect(page.get_by_role("heading", name="Main engine shutdown")).to_be_visible()
        expect(page.get_by_text("14:05 ME stopped after abnormal TC vibration.", exact=True)).to_be_visible()
        expect(source_filename).to_have_attribute("dir", "ltr")
        rpm_value = page.locator('p[dir="ltr"]').filter(has_text=re.compile(r"^72 rpm$"))
        expect(rpm_value).to_have_attribute("dir", "ltr")
        expect(page.get_by_text(re.compile(r"2026-08-31.*14:05.*UTC\+04"))).to_be_visible()

        assert chronology_mutations == [], f"Locale switch/navigation caused chronology mutation: {chronology_mutations}"

        page.get_by_role("button", name="EN").click()
        expect(page.locator("html")).to_have_attribute("lang", "en")
        expect(page.locator("html")).to_have_attribute("dir", "ltr")
        expect(page.get_by_role("heading", name="Claim chronology")).to_be_visible()
        assert chronology_mutations == [], f"Switching back to English caused chronology mutation: {chronology_mutations}"

        browser.close()


if __name__ == "__main__":
    main()
