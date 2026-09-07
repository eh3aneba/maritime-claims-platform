"""Browser regression for Phase 16.2-D explicit human Investigation Plan activation."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")
CLAIM_ID = "11111111-1111-1111-1111-111111111111"


def _plan(number: int, *, incident: str) -> dict:
    machinery = incident == "machinery_failure"
    return {
        "id": f"60000000-0000-0000-0000-00000000000{number}",
        "claim_id": CLAIM_ID,
        "plan_number": number,
        "classification_id": f"10000000-0000-0000-0000-00000000000{number}",
        "catalog_version": "16.1-A.1",
        "classification_number": number,
        "classification_hash": ("a" if number == 1 else "b") * 64,
        "registry_version": "16.2-A.1",
        "registry_hash": "9" * 64,
        "incident_code": incident,
        "component_code": "turbocharger" if machinery else None,
        "failure_mode": "bearing damage" if machinery else None,
        "investigation_tracks": [
            "Review machinery casualty chronology and immediate response."
            if machinery
            else "Reconstruct navigation and collision chronology."
        ],
        "evidence_prompts": [
            "Review PMS history and running-hours records."
            if machinery
            else "Review VDR, AIS and bridge-log evidence."
        ],
        "review_topics": [
            "Review competing technical failure hypotheses."
            if machinery
            else "Review navigation evidence without a fault conclusion."
        ],
        "contextual_rule_ids": ["TECH-001"] if machinery else ["MARINE-EMERGENCY-001"],
        "adoption_note": "Human-adopted governed investigation plan used only for explicit activation testing.",
        "adopted_by_id": "22222222-2222-2222-2222-222222222222",
        "supersedes_plan_id": None if number == 1 else "60000000-0000-0000-0000-000000000001",
        "previous_plan_hash": None if number == 1 else "e" * 64,
        "adoption_key_hash": ("c" if number == 1 else "d") * 64,
        "plan_hash": ("e" if number == 1 else "f") * 64,
        "adopted_at": datetime.now(UTC).isoformat(),
        "source_current": True,
        "non_authoritative": True,
        "automatic_rule_execution": False,
        "automatic_requirement_activation": False,
        "automatic_task_creation": False,
        "automatic_claim_decision": False,
    }


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    current_plan = _plan(1, incident="machinery_failure")
    activation_history: list[dict] = []

    def activation_with_freshness(row: dict | None) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        result["plan_current"] = bool(
            current_plan.get("source_current")
            and result["plan_id"] == current_plan["id"]
            and result["plan_hash"] == current_plan["plan_hash"]
        )
        return result

    def create_activation(payload: dict) -> dict:
        number = len(activation_history) + 1
        catalog = [
            {"key": "track:0", "kind": "investigation_track", "text": current_plan["investigation_tracks"][0]},
            {"key": "evidence:0", "kind": "evidence_prompt", "text": current_plan["evidence_prompts"][0]},
            {"key": "review:0", "kind": "review_topic", "text": current_plan["review_topics"][0]},
        ]
        requested = set(payload["item_keys"])
        selected = [item for item in catalog if item["key"] in requested]
        work_items = []
        for index, item in enumerate(selected, 1):
            prefix = "Review — " if item["kind"] == "review_topic" else (
                "Evidence follow-up — " if item["kind"] == "evidence_prompt" else "Investigate — "
            )
            work_items.append(
                {
                    **item,
                    "task_id": f"70000000-0000-0000-0000-{number:04d}{index:08d}",
                    "task_title": prefix + item["text"],
                    "task_status": "open",
                    "task_type": "review" if item["kind"] == "review_topic" else "follow_up",
                }
            )
        previous = activation_history[0] if activation_history else None
        row = {
            "id": f"80000000-0000-0000-0000-00000000000{number}",
            "claim_id": CLAIM_ID,
            "activation_number": number,
            "plan_id": current_plan["id"],
            "plan_number": current_plan["plan_number"],
            "plan_hash": current_plan["plan_hash"],
            "selected_items": selected,
            "activation_note": payload["note"],
            "activated_by_id": "22222222-2222-2222-2222-222222222222",
            "assignee_id": "22222222-2222-2222-2222-222222222222",
            "due_date": payload.get("due_date"),
            "previous_activation_hash": previous["activation_hash"] if previous else None,
            "activation_key_hash": ("1" if number == 1 else "2") * 64,
            "activation_hash": ("3" if number == 1 else "4") * 64,
            "activated_at": datetime.now(UTC).isoformat(),
            "plan_current": True,
            "work_items": work_items,
            "automatic_rule_execution": False,
            "automatic_requirement_activation": False,
            "automatic_document_request": False,
            "automatic_intelligence_build": False,
            "automatic_claim_decision": False,
        }
        activation_history.insert(0, row)
        return row

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1200})
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")

        def route_activation(route) -> None:
            url = route.request.url
            method = route.request.method
            if url.endswith("/intelligence/investigation-plan-activations") and method == "GET":
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps([activation_with_freshness(row) for row in activation_history]),
                )
                return
            if url.endswith("/intelligence/investigation-plan-activation") and method == "GET":
                row = activation_history[0] if activation_history else None
                route.fulfill(status=200, content_type="application/json", body=json.dumps(activation_with_freshness(row)))
                return
            if url.endswith("/intelligence/investigation-plan-activation") and method == "POST":
                payload = route.request.post_data_json
                if payload.get("confirm_activation") is not True:
                    route.fulfill(status=409, content_type="application/json", body=json.dumps({"detail": "Explicit confirmation required"}))
                    return
                if payload.get("plan_id") != current_plan["id"] or payload.get("plan_hash") != current_plan["plan_hash"] or not current_plan.get("source_current"):
                    route.fulfill(status=409, content_type="application/json", body=json.dumps({"detail": "Investigation Plan changed"}))
                    return
                row = create_activation(payload)
                route.fulfill(status=201, content_type="application/json", body=json.dumps(row))
                return
            if url.endswith("/intelligence/investigation-plan") and method == "GET":
                route.fulfill(status=200, content_type="application/json", body=json.dumps(current_plan))
                return
            route.continue_()

        page.route(f"**/api/v1/claims/{CLAIM_ID}/intelligence**", route_activation)
        page.goto(f"{BASE_URL}/claims/{CLAIM_ID}/intelligence", wait_until="networkidle")

        panel = page.locator('section[aria-label="Investigation plan activation"]')
        expect(panel.get_by_role("heading", name="Activate investigation work items")).to_be_visible()
        expect(panel.get_by_text("Activate from Plan v1", exact=True)).to_be_visible()

        track = current_plan["investigation_tracks"][0]
        review = current_plan["review_topics"][0]
        panel.get_by_label(f"Activate Investigation track: {track}").check()
        panel.get_by_label(f"Activate Review topic: {review}").check()
        panel.get_by_label("Investigation activation note").fill(
            "Handler explicitly activates two bounded plan items as human-owned investigation work only."
        )
        activate = panel.get_by_role("button", name="Activate selected work items")
        expect(activate).to_be_disabled()
        panel.get_by_label("Confirm investigation work activation").check()
        expect(activate).to_be_enabled()
        activate.click()

        expect(panel.get_by_text("Activation v1 created 2 human work items", exact=False)).to_be_visible()
        expect(panel.get_by_text("Latest activation v1 · Plan v1", exact=True)).to_be_visible()
        expect(panel.get_by_text("Investigate —", exact=False)).to_be_visible()
        expect(panel.get_by_text("Review —", exact=False)).to_be_visible()
        expect(panel.get_by_text("Activation history · 1 record", exact=True)).to_be_visible()
        for forbidden in ("Apply rules", "Request documents", "Build intelligence"):
            expect(panel.get_by_role("button", name=forbidden, exact=True)).to_have_count(0)

        current_plan["source_current"] = False
        page.evaluate(
            "(claimId) => window.dispatchEvent(new CustomEvent('claim-domain-classification-updated', {detail: {claimId}}))",
            CLAIM_ID,
        )
        expect(panel.get_by_text("Current plan is stale.", exact=False)).to_be_visible()
        expect(panel.get_by_text("Stale plan source", exact=True)).to_be_visible()
        expect(panel.get_by_role("button", name="Activate selected work items")).to_have_count(0)
        assert len(activation_history) == 1

        current_plan = _plan(2, incident="collision")
        page.evaluate(
            "(claimId) => window.dispatchEvent(new CustomEvent('claim-investigation-plan-updated', {detail: {claimId}}))",
            CLAIM_ID,
        )
        expect(panel.get_by_text("Activate from Plan v2", exact=True)).to_be_visible()
        expect(panel.get_by_text("Stale plan source", exact=True)).to_be_visible()
        assert len(activation_history) == 1

        collision_track = current_plan["investigation_tracks"][0]
        panel.get_by_label(f"Activate Investigation track: {collision_track}").check()
        panel.get_by_label("Investigation activation note").fill(
            "Handler explicitly activates the new current collision plan item after reviewing the re-adopted plan."
        )
        panel.get_by_label("Confirm investigation work activation").check()
        panel.get_by_role("button", name="Activate selected work items").click()

        expect(panel.get_by_text("Activation v2 created 1 human work item", exact=False)).to_be_visible()
        expect(panel.get_by_text("Latest activation v2 · Plan v2", exact=True)).to_be_visible()
        expect(panel.get_by_text("Activation history · 2 records", exact=True)).to_be_visible()
        assert len(activation_history) == 2
        assert activation_history[1]["plan_number"] == 1
        assert activation_history[0]["plan_number"] == 2

        browser.close()

    print("Explicit Investigation Plan activation UI browser E2E passed.")


if __name__ == "__main__":
    main()
