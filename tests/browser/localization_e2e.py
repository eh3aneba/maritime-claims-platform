"""Focused browser coverage for Phase 12K bilingual UI and RTL persistence."""
from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    now = datetime.now(UTC).isoformat()
    row = {
        "claim_id": "11111111-1111-1111-1111-111111111111",
        "claim_reference": "MCRI-HM-2026-I18N-01",
        "claim_type": "hull_machinery",
        "claim_status": "investigation",
        "handler_id": "22222222-2222-2222-2222-222222222222",
        "priority": "critical",
        "rank_score": 90,
        "ranking_version": "12J.1",
        "rank_hash": "a" * 64,
        "requires_action": True,
        "nearest_due_date": "2026-09-06",
        "nearest_due_semantics": "candidate_timebar",
        "source_state_time": now,
        "factors": [{
            "source_type": "recovery_timebar",
            "source_id": "33333333-3333-3333-3333-333333333333",
            "source_hash": "b" * 64,
            "category": "candidate_timebar",
            "label": "Candidate time-bar: 2026-09-06",
            "weight": 90,
            "priority_hint": "critical",
            "due_date": "2026-09-06",
            "due_semantics": "candidate_timebar",
            "href": "/claims/11111111-1111-1111-1111-111111111111/recovery-timebar",
        }],
    }
    dashboard = {
        "metrics": {
            "claim_count": 1,
            "critical_count": 1,
            "urgent_count": 0,
            "elevated_count": 0,
            "due_soon_count": 1,
            "missing_evidence_count": 0,
            "conflict_count": 0,
            "financial_flag_count": 0,
            "pending_ai_review_count": 0,
        },
        "rows": [row],
        "ranking_version": "12J.1",
        "operational_triage_only": True,
        "claim_merits_decision": False,
    }
    workbench_methods: list[str] = []
    mutating_claim_requests: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1100})
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")

        expect(page.locator("html")).to_have_attribute("lang", "en")
        expect(page.locator("html")).to_have_attribute("dir", "ltr")
        expect(page.get_by_role("heading", name="Sign in to your claims workspace")).to_be_visible()
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")

        def observe_request(request) -> None:
            if "/api/v1/claims" in request.url and request.method not in {"GET", "HEAD", "OPTIONS"}:
                mutating_claim_requests.append(f"{request.method} {request.url}")

        page.on("request", observe_request)

        # Core portfolio surfaces use the same locale state and preserve controlled values.
        expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
        page.get_by_role("button", name="FA").click()
        expect(page.locator("html")).to_have_attribute("lang", "fa")
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(page.get_by_role("heading", name="داشبورد")).to_be_visible()
        expect(page.get_by_text("پرونده‌های اخیر", exact=True)).to_be_visible()
        dashboard_claim_ref = page.locator('a[href^="/claims/"]').filter(has_text="MCRI-HM-").first
        expect(dashboard_claim_ref).to_be_visible()
        expect(dashboard_claim_ref).to_have_attribute("dir", "ltr")
        imo_value = page.get_by_text(re.compile(r"^IMO \d{7}$")).first
        expect(imo_value).to_be_visible()
        expect(imo_value).to_have_attribute("dir", "ltr")

        page.goto(f"{BASE_URL}/claims", wait_until="networkidle")
        expect(page.locator("html")).to_have_attribute("lang", "fa")
        expect(page.get_by_role("heading", name="پرونده‌ها")).to_be_visible()
        page.get_by_placeholder("جست‌وجوی پرونده، کشتی یا IMO…").fill("MCRI-DEMO-MT-ORION")
        expect(page.get_by_role("option", name="در حال بررسی")).to_be_attached()
        expect(page.get_by_role("option", name="بحرانی")).to_be_attached()
        page.get_by_role("button", name="اعمال فیلترها").click()
        expect(page.get_by_text("MT ORION", exact=True)).to_be_visible()
        claims_claim_ref = page.locator('a[href^="/claims/"]').filter(has_text="MCRI-HM-").first
        expect(claims_claim_ref).to_have_attribute("dir", "ltr")
        claim_href = claims_claim_ref.get_attribute("href")
        assert claim_href, "Expected a claim detail href"
        expect(page.get_by_text("باز کردن هوشمندی ←", exact=True).first).to_be_visible()

        # Claim intake localizes presentation while retaining controlled source fields and LTR technical inputs.
        page.goto(f"{BASE_URL}/claims/new", wait_until="networkidle")
        expect(page.get_by_role("heading", name="ایجاد پرونده خسارت ماشین‌آلات H&M")).to_be_visible()
        expect(page.get_by_role("button", name="ورود اعلام خسارت")).to_be_visible()
        expect(page.get_by_role("button", name="ثبت دستی")).to_be_visible()
        expect(page.get_by_text("هیچ پیشنهاد استخراج‌شده‌ای به‌صورت خودکار به حقیقت پرونده تبدیل نمی‌شود.", exact=False)).to_be_visible()
        expect(page.get_by_label("تاریخ حادثه")).to_have_attribute("dir", "ltr")
        expect(page.get_by_label("ارز")).to_have_attribute("dir", "ltr")

        # Existing claim workspace is localized without changing claim state or authority.
        page.goto(f"{BASE_URL}{claim_href}", wait_until="networkidle")
        expect(page.locator("html")).to_have_attribute("lang", "fa")
        expect(page.get_by_role("heading", name="MT ORION")).to_be_visible()
        expect(page.get_by_text("نمای کلی پرونده", exact=True)).to_be_visible()
        expect(page.get_by_text("Claim Facts تأییدشده", exact=True)).to_be_visible()
        expect(page.get_by_text("ماتریس شواهد", exact=True)).to_be_visible()
        workspace_claim_ref = page.get_by_text(re.compile(r"^MCRI-HM-")).first
        expect(workspace_claim_ref).to_have_attribute("dir", "ltr")
        workspace_imo = page.get_by_text(re.compile(r"IMO \d{7}")).first
        expect(workspace_imo).to_be_visible()
        expect(workspace_imo).to_have_attribute("dir", "ltr")

        page.get_by_role("button", name="EN").click()
        expect(page.locator("html")).to_have_attribute("lang", "en")
        expect(page.locator("html")).to_have_attribute("dir", "ltr")
        expect(page.get_by_text("Claim overview", exact=True)).to_be_visible()

        def route_workbench(route) -> None:
            workbench_methods.append(route.request.method)
            if "/queue" in route.request.url:
                body = {"rows": [row], "page": 1, "page_size": 100, "total": 1, "has_more": False}
            else:
                body = dashboard
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

        page.route("**/api/v1/claim-workbench**", route_workbench)
        page.goto(f"{BASE_URL}/claims-workbench", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Claims Workbench")).to_be_visible()

        page.get_by_role("button", name="FA").click()
        expect(page.locator("html")).to_have_attribute("lang", "fa")
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(page.get_by_role("heading", name="میز کار پرونده‌ها")).to_be_visible()
        expect(page.get_by_text("تاریخ کاندید (غیرقطعی)", exact=True)).to_be_visible()
        expect(page.locator("aside")).to_have_class(re.compile(r"\bright-0\b"))

        claim_ref = page.get_by_text("MCRI-HM-2026-I18N-01", exact=True)
        expect(claim_ref).to_have_attribute("dir", "ltr")
        rank_hash = page.get_by_text("aaaaaaaaaa…aaaaaaaa", exact=True)
        expect(rank_hash).to_have_attribute("dir", "ltr")

        page.reload(wait_until="networkidle")
        expect(page.locator("html")).to_have_attribute("lang", "fa")
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(page.get_by_role("heading", name="میز کار پرونده‌ها")).to_be_visible()

        page.get_by_role("button", name="EN").click()
        expect(page.locator("html")).to_have_attribute("lang", "en")
        expect(page.locator("html")).to_have_attribute("dir", "ltr")
        expect(page.get_by_role("heading", name="Claims Workbench")).to_be_visible()
        expect(page.locator("aside")).to_have_class(re.compile(r"\bleft-0\b"))

        assert workbench_methods and set(workbench_methods) == {"GET"}, f"Localization must not mutate workbench APIs: {workbench_methods}"
        assert not mutating_claim_requests, f"Locale changes/navigation must not mutate claim APIs: {mutating_claim_requests}"
        browser.close()

    print("Bilingual RTL localization browser E2E passed.")


if __name__ == "__main__":
    main()
