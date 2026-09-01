"""Focused browser coverage for Phase 12J portfolio claims triage."""
from __future__ import annotations

import json
import os
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
    critical = {
        "claim_id": "11111111-1111-1111-1111-111111111111",
        "claim_reference": "MCRI-HM-2026-TRIAGE-01",
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
        "factors": [
            {
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
            }
        ],
    }
    elevated = {
        "claim_id": "44444444-4444-4444-4444-444444444444",
        "claim_reference": "MCRI-HM-2026-TRIAGE-02",
        "claim_type": "hull_machinery",
        "claim_status": "financial_review",
        "handler_id": "22222222-2222-2222-2222-222222222222",
        "priority": "elevated",
        "rank_score": 45,
        "ranking_version": "12J.1",
        "rank_hash": "c" * 64,
        "requires_action": True,
        "nearest_due_date": None,
        "nearest_due_semantics": "none",
        "source_state_time": now,
        "factors": [
            {
                "source_type": "financial_flag",
                "source_id": "55555555-5555-5555-5555-555555555555",
                "source_hash": "d" * 64,
                "category": "financial_flag",
                "label": "Open financial flag: possible duplicate",
                "weight": 45,
                "priority_hint": "urgent",
                "due_date": None,
                "due_semantics": "none",
                "href": "/claims/44444444-4444-4444-4444-444444444444/financial",
            }
        ],
    }
    dashboard = {
        "metrics": {
            "claim_count": 2,
            "critical_count": 1,
            "urgent_count": 0,
            "elevated_count": 1,
            "due_soon_count": 1,
            "missing_evidence_count": 0,
            "conflict_count": 0,
            "financial_flag_count": 1,
            "pending_ai_review_count": 0,
        },
        "rows": [critical, elevated],
        "ranking_version": "12J.1",
        "operational_triage_only": True,
        "claim_merits_decision": False,
    }

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1100})
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")

        def route_workbench(route) -> None:
            if "/queue" in route.request.url:
                body = {"rows": [critical, elevated], "page": 1, "page_size": 100, "total": 2, "has_more": False}
            else:
                body = dashboard
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

        page.route("**/api/v1/claim-workbench**", route_workbench)
        page.goto(f"{BASE_URL}/claims-workbench", wait_until="networkidle")

        expect(page.get_by_role("heading", name="Claims Workbench")).to_be_visible()
        expect(page.get_by_text("Decision boundary:", exact=False)).to_be_visible()
        rows = page.locator("tbody tr")
        expect(rows).to_have_count(2)
        expect(rows.nth(0).get_by_text("MCRI-HM-2026-TRIAGE-01", exact=True)).to_be_visible()
        expect(rows.nth(1).get_by_text("MCRI-HM-2026-TRIAGE-02", exact=True)).to_be_visible()
        expect(rows.nth(0).get_by_text("candidate date", exact=True)).to_be_visible()

        page.get_by_text("MCRI-HM-2026-TRIAGE-01", exact=True).click()
        expect(page.get_by_text("Ranking lineage", exact=True)).to_be_visible()
        expect(page.get_by_text("Candidate time-bar: 2026-09-06", exact=True).last).to_be_visible()
        source_link = page.get_by_role("link", name="Open source workflow")
        expect(source_link).to_have_attribute("href", "/claims/11111111-1111-1111-1111-111111111111/recovery-timebar")

        browser.close()

    print("Claims Workbench browser E2E passed.")


if __name__ == "__main__":
    main()
