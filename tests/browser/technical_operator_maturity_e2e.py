"""Phase 13.5B browser acceptance for controlled technical investigation review."""
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

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1200})
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
        claim_href = claim_link.get_attribute("href")
        assert claim_href, "Expected MT ORION claim href"
        claim_id = claim_href.rstrip("/").split("/")[-1]

        topic_key = "workshop_opinion_aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        reviewer_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"
        evidence_item = {
            "extraction_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "field_path": "workshop.suspected_cause_opinions[0]",
            "value": "Lubrication deficiency",
            "document_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "source_quote": "Workshop suspects lubrication deficiency as a possible contributor.",
            "source_locator_type": "page",
            "source_locator_value": "7",
            "source_verified": True,
        }

        review = {
            "maintenance_facts": {
                "maintenance.running_hours_since_overhaul": {"value": 14800.0, "unit": "hours", "raw": "14,800 hours"},
                "maintenance.recommended_overhaul_interval": {"value": 12000.0, "unit": "hours", "raw": "12,000 hours"},
            },
            "workshop_findings": [],
            "workshop_repair_options": [],
            "workshop_cause_opinions": [evidence_item],
            "matrix": [
                {
                    "key": topic_key,
                    "topic_kind": "workshop_opinion",
                    "title": "Workshop cause opinion: Lubrication deficiency",
                    "severity": "medium",
                    "status": "under_review",
                    "evidence_for": [evidence_item],
                    "evidence_against": [{"lube_oil_pressure": "Normal immediately before shutdown"}],
                    "unknown_or_missing": ["Lubricating-oil analysis / condition evidence"],
                    "recommended_follow_up": ["Review lube-oil analysis, filter inspection, pump condition and alarm history."],
                    "explanation": "This is a human-reviewed source opinion, not a confirmed cause. It must be tested against independent technical evidence.",
                    "state_fingerprint": "a" * 64,
                    "state_version": 1,
                    "decision_state": "none",
                    "latest_decision": None,
                }
            ],
            "generated_at": "2026-09-04T18:00:00Z",
        }
        history: list[dict] = []
        post_payloads: list[dict] = []
        force_stale_once = {"value": False}

        def decision(number: int, action: str, note: str) -> dict:
            previous = history[-1]["decision_hash"] if history else None
            row = review["matrix"][0]
            return {
                "id": f"eeeeeeee-eeee-eeee-eeee-{number:012d}",
                "topic_key": topic_key,
                "topic_kind": "workshop_opinion",
                "state_fingerprint": row["state_fingerprint"],
                "state_version": row["state_version"],
                "decision_number": number,
                "action": action,
                "note": note,
                "decided_by_id": reviewer_id,
                "decided_at": f"2026-09-04T18:0{number}:00Z",
                "previous_decision_hash": previous,
                "decision_hash": str(number) * 64,
            }

        def route_technical(route) -> None:
            request = route.request
            url = request.url.rstrip("/")
            row = review["matrix"][0]
            history_suffix = f"/claims/{claim_id}/technical-review/topics/{topic_key}/decisions"

            if request.method == "GET" and url.endswith(f"/claims/{claim_id}/technical-review"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(review))
                return

            if request.method == "GET" and url.endswith(history_suffix):
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        "topic_key": topic_key,
                        "current_state_fingerprint": row["state_fingerprint"],
                        "current_state_version": row["state_version"],
                        "decision_state": row["decision_state"],
                        "items": history,
                    }),
                )
                return

            if request.method == "POST" and url.endswith(history_suffix):
                payload = json.loads(request.post_data or "{}")
                post_payloads.append(payload)

                if force_stale_once["value"]:
                    force_stale_once["value"] = False
                    row["state_fingerprint"] = "b" * 64
                    row["state_version"] = 2
                    row["decision_state"] = "stale"
                    route.fulfill(
                        status=409,
                        content_type="application/json",
                        body=json.dumps({"detail": "Technical evidence changed. Refresh the current topic before recording a decision."}),
                    )
                    return

                assert payload["expected_state_fingerprint"] == row["state_fingerprint"]
                assert payload["expected_state_version"] == row["state_version"]
                item = decision(len(history) + 1, payload["action"], payload["note"])
                history.append(item)
                row["latest_decision"] = item
                row["decision_state"] = "current"
                route.fulfill(status=200, content_type="application/json", body=json.dumps(item))
                return

            route.continue_()

        page.route(f"**/api/v1/claims/{claim_id}/technical-review**", route_technical)
        page.goto(f"{BASE_URL}/claims/{claim_id}/technical", wait_until="networkidle")

        # Evidence, unknowns, follow-up and current human state are visible together.
        expect(page.get_by_text("Workshop cause opinion: Lubrication deficiency", exact=True)).to_be_visible()
        expect(page.get_by_text("No human disposition", exact=True)).to_be_visible()
        expect(page.get_by_text("Lubricating-oil analysis / condition evidence", exact=False)).to_be_visible()
        expect(page.get_by_role("link", name="Open source context").first).to_be_visible()
        expect(page.get_by_text("Workshop suspects lubrication deficiency", exact=False).first).to_be_visible()

        note_box = page.get_by_placeholder("Explain what the current evidence supports, does not support, or still requires.")
        note_box.fill("Keep this as a working hypothesis pending independent lubricating-oil evidence.")
        page.get_by_role("button", name="Needs more evidence", exact=True).click()
        expect(page.get_by_text("Current human disposition", exact=True)).to_be_visible()
        expect(page.get_by_text("Decision history (1)", exact=True)).to_be_visible()
        assert post_payloads[0]["expected_state_fingerprint"] == "a" * 64
        assert post_payloads[0]["expected_state_version"] == 1
        assert post_payloads[0]["confirm_re_review"] is False

        # A stale write fails closed, does not auto-replay, and preserves the human draft.
        page.get_by_role("button", name="Start deliberate re-review", exact=True).click()
        expect(page.get_by_text("A new decision will be appended", exact=False)).to_be_visible()
        note_box = page.get_by_placeholder("Explain what the current evidence supports, does not support, or still requires.")
        stale_note = "Preserve this draft while updated workshop evidence is loaded."
        note_box.fill(stale_note)
        force_stale_once["value"] = True
        request_count_before = len(post_payloads)
        page.get_by_role("button", name="Keep investigation open", exact=True).click()
        expect(page.get_by_text("Technical evidence changed while you were reviewing it", exact=False)).to_be_visible()
        expect(note_box).to_have_value(stale_note)
        expect(page.get_by_role("button", name="Refresh current evidence state", exact=True)).to_be_visible()
        assert len(post_payloads) == request_count_before + 1, "409 must not auto-resubmit the technical decision"

        page.get_by_role("button", name="Refresh current evidence state", exact=True).click()
        expect(page.get_by_text("Prior disposition is stale", exact=True)).to_be_visible()
        note_box = page.get_by_placeholder("Explain what the current evidence supports, does not support, or still requires.")
        expect(note_box).to_have_value(stale_note)
        note_box.fill("Re-reviewed against the updated evidence state; keep open pending oil analysis.")
        page.get_by_role("button", name="Keep investigation open", exact=True).click()
        expect(page.get_by_text("Decision history (2)", exact=True)).to_be_visible()
        assert post_payloads[-1]["expected_state_fingerprint"] == "b" * 64
        assert post_payloads[-1]["expected_state_version"] == 2
        assert post_payloads[-1]["confirm_re_review"] is True

        # Persian keeps the same controlled workflow under RTL.
        page.get_by_role("button", name="FA").click()
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(page.get_by_text("تصمیم انسانی فعلی", exact=True)).to_be_visible()
        expect(page.get_by_text("تاریخچه تصمیم (2)", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="شروع بازبینی مجدد آگاهانه", exact=True)).to_be_visible()

        browser.close()


if __name__ == "__main__":
    main()
