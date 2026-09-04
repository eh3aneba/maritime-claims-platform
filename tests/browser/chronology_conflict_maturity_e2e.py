"""Phase 13.3B browser acceptance for state-aware chronology conflict review."""
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
        claim_href = claim_link.get_attribute("href")
        assert claim_href, "Expected MT ORION claim href"
        claim_id = claim_href.rstrip("/").split("/")[-1]

        event_a = "11111111-1111-1111-1111-111111111111"
        event_b = "22222222-2222-2222-2222-222222222222"
        extraction_a = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        extraction_b = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        conflict_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        reviewer_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"

        def evidence(extraction_id: str, document_id: str, document_name: str, quote: str, locator: str) -> dict:
            return {
                "extraction_id": extraction_id,
                "document_id": document_id,
                "document_name": document_name,
                "document_type": "engine_log" if "engine" in document_name else "chief_engineer_report",
                "field_path": "events.shutdown_time",
                "value": "14:05" if extraction_id == extraction_a else "14:12",
                "source_quote": quote,
                "source_locator_type": "page",
                "source_locator_value": locator,
                "source_verified": True,
                "evidence_role": "primary",
            }

        chronology = {
            "events": [
                {
                    "id": event_a,
                    "event_type": "shutdown",
                    "title": "Engine Log shutdown",
                    "description": "Engine Log records the main-engine shutdown.",
                    "occurred_on": "2026-08-31",
                    "occurred_time": "14:05:00",
                    "timezone_label": "UTC+04",
                    "materiality": "high",
                    "evidence": [evidence(extraction_a, "aaaaaaaa-1111-1111-1111-111111111111", "engine-log.pdf", "14:05 ME stopped.", "12")],
                    "created_at": "2026-09-01T08:00:00Z",
                    "updated_at": "2026-09-01T08:00:00Z",
                },
                {
                    "id": event_b,
                    "event_type": "shutdown",
                    "title": "Chief Engineer report shutdown",
                    "description": "Chief Engineer report records a later shutdown time.",
                    "occurred_on": "2026-08-31",
                    "occurred_time": "14:12:00",
                    "timezone_label": "UTC+04",
                    "materiality": "high",
                    "evidence": [evidence(extraction_b, "bbbbbbbb-2222-2222-2222-222222222222", "chief-engineer-report.pdf", "Main engine stopped at 14:12.", "3")],
                    "created_at": "2026-09-01T08:00:00Z",
                    "updated_at": "2026-09-01T08:00:00Z",
                },
            ],
            "conflicts": [
                {
                    "id": conflict_id,
                    "conflict_type": "timestamp_difference",
                    "topic": "Shutdown time discrepancy",
                    "description": "Two reviewed sources record different shutdown times.",
                    "value_a": {"date": "2026-08-31", "time": "14:05", "timezone": "UTC+04"},
                    "value_b": {"date": "2026-08-31", "time": "14:12", "timezone": "UTC+04"},
                    "difference_minutes": "7",
                    "materiality": "medium",
                    "state_fingerprint": "a" * 64,
                    "state_version": 1,
                    "decision_state": "none",
                    "decision_history": [],
                    "status": "open",
                    "resolution_note": None,
                    "event_a_id": event_a,
                    "event_b_id": event_b,
                    "evidence_a_extraction_id": extraction_a,
                    "evidence_b_extraction_id": extraction_b,
                    "resolved_by_id": None,
                    "resolved_at": None,
                    "created_at": "2026-09-01T08:00:00Z",
                    "updated_at": "2026-09-01T08:00:00Z",
                }
            ],
            "event_count": 2,
            "open_conflict_count": 1,
        }
        post_payloads: list[dict] = []
        force_stale_once = {"value": False}

        def decision(number: int, status: str, note: str) -> dict:
            previous = chronology["conflicts"][0]["decision_history"][-1]["decision_hash"] if chronology["conflicts"][0]["decision_history"] else None
            return {
                "id": f"eeeeeeee-eeee-eeee-eeee-{number:012d}",
                "state_fingerprint": chronology["conflicts"][0]["state_fingerprint"],
                "state_version": chronology["conflicts"][0]["state_version"],
                "decision_number": number,
                "status": status,
                "note": note,
                "decided_by_id": reviewer_id,
                "decided_at": f"2026-09-04T10:0{number}:00Z",
                "previous_decision_hash": previous,
                "decision_hash": str(number) * 64,
                "created_at": f"2026-09-04T10:0{number}:00Z",
            }

        def route_chronology(route) -> None:
            request = route.request
            url = request.url.rstrip("/")
            if request.method == "GET" and url.endswith(f"/claims/{claim_id}/chronology"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(chronology))
                return
            if request.method == "POST" and url.endswith(f"/claims/{claim_id}/chronology/conflicts/{conflict_id}/resolve"):
                payload = json.loads(request.post_data or "{}")
                post_payloads.append(payload)
                conflict = chronology["conflicts"][0]

                if force_stale_once["value"]:
                    force_stale_once["value"] = False
                    conflict["state_fingerprint"] = "b" * 64
                    conflict["state_version"] = 2
                    conflict["decision_state"] = "stale"
                    conflict["status"] = "open"
                    conflict["resolution_note"] = None
                    chronology["open_conflict_count"] = 1
                    route.fulfill(status=409, content_type="application/json", body=json.dumps({"detail": "Conflict state changed; refresh required."}))
                    return

                assert payload["expected_state_fingerprint"] == conflict["state_fingerprint"]
                assert payload["expected_state_version"] == conflict["state_version"]
                number = len(conflict["decision_history"]) + 1
                row = decision(number, payload["status"], payload["note"])
                conflict["decision_history"].append(row)
                conflict["decision_state"] = "current"
                conflict["status"] = payload["status"]
                conflict["resolution_note"] = payload["note"]
                conflict["resolved_by_id"] = reviewer_id
                conflict["resolved_at"] = row["decided_at"]
                chronology["open_conflict_count"] = 0
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        "id": conflict_id,
                        "status": payload["status"],
                        "resolution_note": payload["note"],
                        "resolved_by_id": reviewer_id,
                        "resolved_at": row["decided_at"],
                        "state_fingerprint": conflict["state_fingerprint"],
                        "state_version": conflict["state_version"],
                        "decision_number": number,
                        "decision_hash": row["decision_hash"],
                        "replayed": False,
                    }),
                )
                return
            route.continue_()

        page.route(f"**/api/v1/claims/{claim_id}/chronology**", route_chronology)
        page.goto(f"{BASE_URL}/claims/{claim_id}/chronology", wait_until="networkidle")

        # Source evidence is adjacent to the conflict before a decision is made.
        expect(page.get_by_text("Source A", exact=True)).to_be_visible()
        expect(page.get_by_text("engine-log.pdf", exact=False).first).to_be_visible()
        expect(page.get_by_text("Source B", exact=True)).to_be_visible()
        expect(page.get_by_text("chief-engineer-report.pdf", exact=False).first).to_be_visible()
        expect(page.get_by_text("No decision", exact=True)).to_be_visible()

        note_box = page.get_by_placeholder("Explain how this difference should be understood…")
        note_box.fill("Engine Log treated as the operational timestamp; discrepancy retained for review.")
        page.get_by_role("button", name="Explain", exact=True).click()
        expect(page.get_by_text("Decision current", exact=True)).to_be_visible()
        expect(page.get_by_text("Decision history (1)", exact=True)).to_be_visible()
        assert post_payloads[0]["expected_state_fingerprint"] == "a" * 64
        assert post_payloads[0]["expected_state_version"] == 1
        assert post_payloads[0]["confirm_re_review"] is False

        page.get_by_role("button", name="Begin deliberate re-review", exact=True).click()
        expect(page.get_by_text("append a new human decision", exact=False)).to_be_visible()
        note_box = page.get_by_placeholder("Explain how this difference should be understood…")
        note_box.fill("Second human review accepts the difference as operationally explainable.")
        page.get_by_role("button", name="Accept difference", exact=True).click()
        expect(page.get_by_text("Decision history (2)", exact=True)).to_be_visible()
        assert post_payloads[1]["confirm_re_review"] is True
        assert post_payloads[1]["expected_state_version"] == 1

        # A stale response fails closed. No automatic replay occurs and the draft remains visible.
        page.get_by_role("button", name="Begin deliberate re-review", exact=True).click()
        note_box = page.get_by_placeholder("Explain how this difference should be understood…")
        stale_note = "Keep this draft while the evidence state is refreshed."
        note_box.fill(stale_note)
        force_stale_once["value"] = True
        request_count_before = len(post_payloads)
        page.get_by_role("button", name="Resolve", exact=True).click()
        expect(page.get_by_text("This conflict changed after you loaded it", exact=False)).to_be_visible()
        expect(note_box).to_have_value(stale_note)
        expect(page.get_by_role("button", name="Refresh current state", exact=True)).to_be_visible()
        assert len(post_payloads) == request_count_before + 1, "409 must not auto-resubmit the decision"

        page.get_by_role("button", name="Refresh current state", exact=True).click()
        expect(page.get_by_text("Prior decision stale", exact=True)).to_be_visible()
        note_box = page.get_by_placeholder("Explain how this difference should be understood…")
        expect(note_box).to_have_value(stale_note)
        note_box.fill("Reviewed again after refresh against state version 2.")
        page.get_by_role("button", name="Explain", exact=True).click()
        expect(page.get_by_text("Decision history (3)", exact=True)).to_be_visible()
        assert post_payloads[-1]["expected_state_fingerprint"] == "b" * 64
        assert post_payloads[-1]["expected_state_version"] == 2
        assert post_payloads[-1]["confirm_re_review"] is True

        page.get_by_role("button", name="FA").click()
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(page.get_by_text("تصمیم فعلی است", exact=True)).to_be_visible()
        expect(page.get_by_text("تاریخچه تصمیم‌ها (3)", exact=True)).to_be_visible()

        browser.close()


if __name__ == "__main__":
    main()
