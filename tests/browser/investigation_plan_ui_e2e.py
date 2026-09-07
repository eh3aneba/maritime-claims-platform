"""Browser regression for Phase 16.2-C governed investigation-plan adoption."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from playwright.sync_api import expect, sync_playwright

from investigation_plan_activation_ui_e2e import main as investigation_activation_main

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")
CLAIM_ID = "11111111-1111-1111-1111-111111111111"
REGISTRY_VERSION = "16.2-A.1"
REGISTRY_HASH = "9" * 64

CATALOG = {
    "catalog_version": "16.1-A.1",
    "non_authoritative": True,
    "human_classification_required": True,
    "automatic_claim_decision": False,
    "incidents": [
        {
            "code": "machinery_failure",
            "title": "Machinery Failure",
            "description": "Human-confirmed machinery casualty context.",
            "component_codes": ["turbocharger"],
            "contextual_rule_ids": ["TECH-001"],
        },
        {
            "code": "collision",
            "title": "Collision",
            "description": "Human-confirmed collision context.",
            "component_codes": [],
            "contextual_rule_ids": [],
        },
    ],
    "machinery_components": [{"code": "turbocharger", "title": "Turbocharger"}],
}

PLAYBOOKS = {
    "machinery_failure": {
        "incident_code": "machinery_failure",
        "title": "Machinery Failure Investigation Preview",
        "objective": "Organize a bounded machinery investigation without deciding causation or coverage.",
        "investigation_tracks": ["Review machinery casualty chronology and immediate response."],
        "evidence_prompts": ["Review PMS history and running-hours records."],
        "review_topics": ["Review competing technical failure hypotheses."],
        "contextual_rule_ids": ["TECH-001", "AAA-D1"],
    },
    "collision": {
        "incident_code": "collision",
        "title": "Collision Investigation Preview",
        "objective": "Organize collision evidence without determining fault or liability.",
        "investigation_tracks": ["Reconstruct navigation and collision chronology."],
        "evidence_prompts": ["Review VDR, AIS and bridge-log evidence."],
        "review_topics": ["Review navigation evidence without a fault conclusion."],
        "contextual_rule_ids": ["MARINE-EMERGENCY-001"],
    },
}


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    history: list[dict] = []
    current_classification: dict | None = None
    plan_history: list[dict] = []
    current_plan: dict | None = None
    build_count = 0

    def classification(payload: dict, number: int) -> dict:
        previous = history[0] if history else None
        return {
            "id": f"10000000-0000-0000-0000-00000000000{number}",
            "claim_id": CLAIM_ID,
            "catalog_version": "16.1-A.1",
            "classification_number": number,
            "incident_code": payload["incident_code"],
            "component_code": payload.get("component_code"),
            "failure_mode": payload.get("failure_mode"),
            "classification_note": payload["note"],
            "classified_by_id": "22222222-2222-2222-2222-222222222222",
            "supersedes_classification_id": previous["id"] if previous else None,
            "previous_classification_hash": previous["classification_hash"] if previous else None,
            "classification_hash": ("a" if number == 1 else "b") * 64,
            "created_at": datetime.now(UTC).isoformat(),
        }

    def preview() -> dict:
        if current_classification is None:
            return {
                "registry_version": REGISTRY_VERSION,
                "registry_hash": REGISTRY_HASH,
                "classification_required": True,
                "non_authoritative": True,
                "read_only_preview": True,
                "automatic_rule_execution": False,
                "automatic_requirement_activation": False,
                "automatic_task_creation": False,
                "automatic_claim_decision": False,
                "authority_boundary": "Read-only preview only.",
                "source_ref": None,
                "classification_context": None,
                "playbook": None,
            }
        code = current_classification["incident_code"]
        incident = next(item for item in CATALOG["incidents"] if item["code"] == code)
        component_title = "Turbocharger" if current_classification.get("component_code") == "turbocharger" else None
        return {
            "registry_version": REGISTRY_VERSION,
            "registry_hash": REGISTRY_HASH,
            "classification_required": False,
            "non_authoritative": True,
            "read_only_preview": True,
            "automatic_rule_execution": False,
            "automatic_requirement_activation": False,
            "automatic_task_creation": False,
            "automatic_claim_decision": False,
            "authority_boundary": "Read-only preview only.",
            "source_ref": {
                "kind": "claim_domain_classification",
                "id": current_classification["id"],
                "catalog_version": current_classification["catalog_version"],
                "classification_number": current_classification["classification_number"],
                "classification_hash": current_classification["classification_hash"],
            },
            "classification_context": {
                "incident_code": code,
                "incident_title": incident["title"],
                "component_code": current_classification.get("component_code"),
                "component_title": component_title,
                "failure_mode": current_classification.get("failure_mode"),
            },
            "playbook": PLAYBOOKS[code],
        }

    def plan_with_freshness(row: dict | None) -> dict | None:
        if row is None:
            return None
        result = dict(row)
        result["source_current"] = bool(
            current_classification
            and row["classification_id"] == current_classification["id"]
            and row["classification_hash"] == current_classification["classification_hash"]
        )
        return result

    def adopt_plan(payload: dict) -> dict:
        live = preview()
        number = len(plan_history) + 1
        previous = plan_history[0] if plan_history else None
        code = live["classification_context"]["incident_code"]
        row = {
            "id": f"30000000-0000-0000-0000-00000000000{number}",
            "claim_id": CLAIM_ID,
            "plan_number": number,
            "classification_id": live["source_ref"]["id"],
            "catalog_version": live["source_ref"]["catalog_version"],
            "classification_number": live["source_ref"]["classification_number"],
            "classification_hash": live["source_ref"]["classification_hash"],
            "registry_version": REGISTRY_VERSION,
            "registry_hash": REGISTRY_HASH,
            "incident_code": code,
            "component_code": live["classification_context"]["component_code"],
            "failure_mode": live["classification_context"]["failure_mode"],
            "investigation_tracks": payload["investigation_tracks"],
            "evidence_prompts": payload["evidence_prompts"],
            "review_topics": payload["review_topics"],
            "contextual_rule_ids": PLAYBOOKS[code]["contextual_rule_ids"],
            "adoption_note": payload["note"],
            "adopted_by_id": "22222222-2222-2222-2222-222222222222",
            "supersedes_plan_id": previous["id"] if previous else None,
            "previous_plan_hash": previous["plan_hash"] if previous else None,
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
        plan_history.insert(0, row)
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

        def route_intelligence(route) -> None:
            nonlocal current_classification, current_plan, build_count
            url = route.request.url
            method = route.request.method
            if url.endswith("/intelligence/domain-catalog") and method == "GET":
                route.fulfill(status=200, content_type="application/json", body=json.dumps(CATALOG)); return
            if url.endswith("/intelligence/domain-classifications") and method == "GET":
                route.fulfill(status=200, content_type="application/json", body=json.dumps(history)); return
            if url.endswith("/intelligence/domain-classification") and method == "GET":
                route.fulfill(status=200, content_type="application/json", body=json.dumps(current_classification)); return
            if url.endswith("/intelligence/domain-classification") and method == "POST":
                payload = route.request.post_data_json
                current_classification = classification(payload, len(history) + 1)
                history.insert(0, current_classification)
                route.fulfill(status=201, content_type="application/json", body=json.dumps(current_classification)); return
            if url.endswith("/intelligence/domain-playbook-preview") and method == "GET":
                route.fulfill(status=200, content_type="application/json", body=json.dumps(preview())); return
            if url.endswith("/intelligence/investigation-plans") and method == "GET":
                route.fulfill(status=200, content_type="application/json", body=json.dumps([plan_with_freshness(row) for row in plan_history])); return
            if url.endswith("/intelligence/investigation-plan") and method == "GET":
                route.fulfill(status=200, content_type="application/json", body=json.dumps(plan_with_freshness(current_plan))); return
            if url.endswith("/intelligence/investigation-plan") and method == "POST":
                payload = route.request.post_data_json
                live = preview()
                if payload.get("confirm_adoption") is not True or payload.get("classification_id") != live["source_ref"]["id"]:
                    route.fulfill(status=409, content_type="application/json", body=json.dumps({"detail": "Stale or unconfirmed plan"})); return
                current_plan = adopt_plan(payload)
                route.fulfill(status=201, content_type="application/json", body=json.dumps(current_plan)); return
            if url.endswith("/intelligence/build") and method == "POST":
                build_count += 1
                route.fulfill(status=409, content_type="application/json", body=json.dumps({"detail": "Not expected in this regression"})); return
            if url.endswith("/intelligence") and method == "GET":
                route.fulfill(status=200, content_type="application/json", body=json.dumps({
                    "claim_id": CLAIM_ID,
                    "snapshot": None,
                    "disclaimer": "Source-linked decision support only.",
                })); return
            route.continue_()

        page.route(f"**/api/v1/claims/{CLAIM_ID}/intelligence**", route_intelligence)
        page.goto(f"{BASE_URL}/claims/{CLAIM_ID}/intelligence", wait_until="networkidle")

        plan_panel = page.locator('section[aria-label="Governed investigation plan"]')
        expect(plan_panel.get_by_role("heading", name="Governed investigation plan")).to_be_visible()
        expect(plan_panel.get_by_text("Human classification required", exact=False)).to_be_visible()
        expect(plan_panel.get_by_role("button", name="Adopt investigation plan")).to_have_count(0)

        page.get_by_label("Claim incident domain").select_option("machinery_failure")
        page.get_by_label("Machinery component").select_option("turbocharger")
        page.get_by_label("Failure mode").fill("bearing damage")
        page.get_by_label("Human classification note").fill("Handler records machinery failure after reviewing the controlled casualty evidence package.")
        page.get_by_label("Confirm claim domain classification").check()
        page.get_by_role("button", name="Save classification").click()

        expect(plan_panel.get_by_text("No investigation plan has been adopted", exact=False)).to_be_visible()
        machinery_track = PLAYBOOKS["machinery_failure"]["investigation_tracks"][0]
        machinery_evidence = PLAYBOOKS["machinery_failure"]["evidence_prompts"][0]
        plan_panel.get_by_label(f"Investigation tracks: {machinery_track}").check()
        plan_panel.get_by_label(f"Evidence prompts: {machinery_evidence}").check()
        plan_panel.get_by_label("Investigation plan adoption note").fill("Handler adopts the machinery investigation scope after reviewing the live governed playbook.")
        adopt = plan_panel.get_by_role("button", name="Adopt investigation plan")
        expect(adopt).to_be_disabled()
        plan_panel.get_by_label("Confirm investigation plan adoption").check()
        expect(adopt).to_be_enabled()
        adopt.click()

        expect(plan_panel.get_by_text("Investigation plan v1 adopted", exact=False)).to_be_visible()
        expect(plan_panel.get_by_text("Plan v1", exact=False).first).to_be_visible()
        expect(plan_panel.get_by_text("Current source", exact=False).first).to_be_visible()
        expect(page.get_by_text("No intelligence snapshot yet", exact=True)).to_be_visible()
        assert build_count == 0

        page.get_by_label("Claim incident domain").select_option("collision")
        page.get_by_label("Human classification note").fill("Handler reclassifies the casualty as collision after reviewing later navigation evidence.")
        page.get_by_label("Confirm claim domain classification").check()
        page.get_by_role("button", name="Save new classification version").click()

        expect(plan_panel.get_by_text("Stale source", exact=False).first).to_be_visible()
        expect(page.get_by_role("heading", name="Collision Investigation Preview")).to_be_visible()
        assert build_count == 0

        collision_track = PLAYBOOKS["collision"]["investigation_tracks"][0]
        plan_panel.get_by_label(f"Investigation tracks: {collision_track}").check()
        plan_panel.get_by_label("Investigation plan adoption note").fill("Handler adopts a new collision investigation plan after reviewing the reclassified live playbook.")
        plan_panel.get_by_label("Confirm investigation plan adoption").check()
        plan_panel.get_by_role("button", name="Adopt new investigation plan version").click()

        expect(plan_panel.get_by_text("Investigation plan v2 adopted", exact=False)).to_be_visible()
        expect(plan_panel.get_by_text("Investigation plan history · 2 versions", exact=True)).to_be_visible()
        expect(plan_panel.get_by_text("Plan v2", exact=False).first).to_be_visible()
        expect(page.get_by_text("No intelligence snapshot yet", exact=True)).to_be_visible()
        assert build_count == 0
        assert len(plan_history) == 2
        assert plan_history[1]["incident_code"] == "machinery_failure"
        assert plan_history[0]["incident_code"] == "collision"

        forbidden = ["Apply rules", "Activate rules", "Create task", "Request document"]
        for label in forbidden:
            expect(plan_panel.get_by_role("button", name=label, exact=True)).to_have_count(0)

        browser.close()

    print("Governed investigation plan UI browser E2E passed.")
    investigation_activation_main()


if __name__ == "__main__":
    main()
