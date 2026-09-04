"""Phase 13.5C real MT ORION technical acceptance against the live local API."""
from __future__ import annotations

import os
import re

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
API_URL = os.getenv("MCRI_API_URL", "http://127.0.0.1:8000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")


def _json(response, label: str):
    if not response.ok:
        raise AssertionError(f"{label} failed: {response.status} {response.text()}")
    return response.json()


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1500, "height": 1200})
        page = context.new_page()

        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")

        page.goto(f"{BASE_URL}/claims", wait_until="networkidle")
        page.get_by_placeholder("Search claim, vessel or IMO…").fill("MCRI-DEMO-MT-ORION")
        page.get_by_role("button", name="Apply filters").click()
        mt_orion_row = page.get_by_role("row").filter(has_text="MT ORION").filter(
            has_text="MCRI-DEMO-MT-ORION"
        )
        expect(mt_orion_row).to_have_count(1)
        expect(mt_orion_row).to_contain_text("MT ORION")
        claim_link = mt_orion_row.locator('a[href^="/claims/"]').filter(
            has_text=re.compile(r"^MCRI-HM-")
        )
        expect(claim_link).to_have_count(1)
        claim_href = claim_link.get_attribute("href")
        if not claim_href:
            raise AssertionError("Expected MT ORION claim href")
        claim_id = claim_href.rstrip("/").split("/")[-1]

        request = context.request
        review = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/technical-review"),
            "initial technical review",
        )
        candidates = [
            row for row in review.get("matrix", [])
            if row.get("topic_kind") == "workshop_opinion"
            and row.get("decision_state") == "none"
            and row.get("evidence_for")
            and row["evidence_for"][0].get("extraction_id")
        ]
        if not candidates:
            raise AssertionError(
                "MT ORION must expose an unreviewed source-linked workshop opinion for real Phase 13.5C acceptance"
            )
        topic = candidates[0]
        topic_key = topic["key"]
        extraction_id = topic["evidence_for"][0]["extraction_id"]
        original_value = str(topic["evidence_for"][0].get("value") or "Workshop technical opinion")

        first = _json(
            request.post(
                f"{API_URL}/api/v1/claims/{claim_id}/technical-review/topics/{topic_key}/decisions",
                data={
                    "action": "needs_more_evidence",
                    "note": "Phase 13.5C: keep this workshop opinion under investigation pending independent evidence.",
                    "expected_state_fingerprint": topic["state_fingerprint"],
                    "expected_state_version": topic["state_version"],
                    "confirm_re_review": False,
                },
            ),
            "first technical disposition",
        )

        evolved_value = (
            f"{original_value} — updated reviewed wording for Phase 13.5C evidence-evolution acceptance"
        )
        _json(
            request.post(
                f"{API_URL}/api/v1/ai-review/{extraction_id}",
                data={
                    "action": "edit",
                    "value": evolved_value,
                    "reason": "Phase 13.5C real technical evidence evolution acceptance",
                },
            ),
            "workshop opinion edit",
        )

        evolved = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/technical-review"),
            "evolved technical review",
        )
        evolved_topic = next(row for row in evolved["matrix"] if row["key"] == topic_key)
        if evolved_topic["decision_state"] != "stale":
            raise AssertionError(f"Expected stale technical disposition, got {evolved_topic['decision_state']!r}")
        if evolved_topic["state_version"] != topic["state_version"] + 1:
            raise AssertionError("Technical evidence evolution did not advance the state version")
        if evolved_topic["state_fingerprint"] == topic["state_fingerprint"]:
            raise AssertionError("Technical evidence evolution did not change the state fingerprint")
        if evolved_topic["latest_decision"]["decision_hash"] != first["decision_hash"]:
            raise AssertionError("Stale state lost the prior human technical decision lineage")

        page.goto(f"{BASE_URL}/claims/{claim_id}/technical", wait_until="networkidle")
        expect(page.get_by_text("Prior disposition is stale", exact=True)).to_be_visible()
        page.get_by_role("button", name="Start deliberate re-review", exact=True).click()
        note_box = page.get_by_placeholder(
            "Explain what the current evidence supports, does not support, or still requires."
        )
        note_box.fill(
            "Re-reviewed after the workshop opinion changed; keep investigation open pending independent evidence."
        )
        page.get_by_role("button", name="Keep investigation open", exact=True).click()
        expect(page.get_by_text("Current human disposition", exact=True)).to_be_visible()
        expect(page.get_by_text("Decision history (2)", exact=True)).to_be_visible()

        history = _json(
            request.get(
                f"{API_URL}/api/v1/claims/{claim_id}/technical-review/topics/{topic_key}/decisions"
            ),
            "technical decision history",
        )
        if len(history["items"]) != 2:
            raise AssertionError(f"Expected two append-only technical decisions, got {len(history['items'])}")
        if history["items"][1]["previous_decision_hash"] != history["items"][0]["decision_hash"]:
            raise AssertionError("Technical re-review did not preserve the append-only hash chain")
        if history["decision_state"] != "current":
            raise AssertionError("Explicit re-review did not restore current technical disposition state")

        # Existing downstream surfaces remain distinct claim-workspace authorities.
        surface_checks = [
            ("evidence-matrix", "Evidence Matrix"),
            ("chronology", "Chronology"),
            ("assessment", "Initial Assessment"),
            ("claim-pack", "Claim Pack"),
        ]
        for suffix, marker in surface_checks:
            page.goto(f"{BASE_URL}/claims/{claim_id}/{suffix}", wait_until="networkidle")
            expect(page.locator("body")).to_contain_text(marker)

        browser.close()


if __name__ == "__main__":
    main()
