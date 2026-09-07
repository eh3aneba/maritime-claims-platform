"""Browser regression for governed claim-domain classification and read-only playbook UX."""
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


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    catalog = {
        "catalog_version": "16.1-A.1",
        "non_authoritative": True,
        "human_classification_required": True,
        "automatic_claim_decision": False,
        "incidents": [
            {
                "code": "machinery_failure",
                "title": "Machinery Failure",
                "description": "Human-confirmed machinery casualty context; not a causation or coverage determination.",
                "component_codes": ["main_engine", "turbocharger"],
                "contextual_rule_ids": ["TECH-001"],
            },
            {
                "code": "collision",
                "title": "Collision",
                "description": "Human-confirmed collision incident context; fault and liability remain separately governed.",
                "component_codes": [],
                "contextual_rule_ids": [],
            },
        ],
        "machinery_components": [
            {"code": "main_engine", "title": "Main Engine"},
            {"code": "turbocharger", "title": "Turbocharger"},
        ],
    }
    history: list[dict] = []
    current: dict | None = None
    snapshot: dict | None = None
    build_count = 0

    def classification_row(payload: dict, number: int) -> dict:
        previous = history[0] if history else None
        hash_char = "a" if number == 1 else "b"
        return {
            "id": f"00000000-0000-0000-0000-00000000000{number}",
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
            "classification_hash": hash_char * 64,
            "created_at": datetime.now(UTC).isoformat(),
        }

    def playbook_preview(row: dict | None) -> dict:
        base = {
            "registry_version": "16.2-A.1",
            "registry_hash": "9" * 64,
            "classification_required": row is None,
            "non_authoritative": True,
            "read_only_preview": True,
            "automatic_rule_execution": False,
            "automatic_requirement_activation": False,
            "automatic_task_creation": False,
            "automatic_claim_decision": False,
            "authority_boundary": (
                "This playbook is a read-only investigation preview derived from the latest human-confirmed claim-domain "
                "classification. It does not execute rules, activate evidence requirements, create tasks or determine "
                "coverage, causation, fault, liability, recoverability, reserve, settlement, payment or closure."
            ),
            "source_ref": None,
            "classification_context": None,
            "playbook": None,
        }
        if row is None:
            return base

        machinery = row["incident_code"] == "machinery_failure"
        incident_title = "Machinery Failure" if machinery else "Collision"
        component_title = "Turbocharger" if row.get("component_code") == "turbocharger" else None
        base.update(
            {
                "classification_required": False,
                "source_ref": {
                    "kind": "claim_domain_classification",
                    "id": row["id"],
                    "catalog_version": row["catalog_version"],
                    "classification_number": row["classification_number"],
                    "classification_hash": row["classification_hash"],
                },
                "classification_context": {
                    "incident_code": row["incident_code"],
                    "incident_title": incident_title,
                    "component_code": row.get("component_code"),
                    "component_title": component_title,
                    "failure_mode": row.get("failure_mode"),
                },
                "playbook": {
                    "incident_code": row["incident_code"],
                    "title": f"{incident_title} Investigation Preview",
                    "objective": (
                        "Organize a bounded technical and adjusting investigation without deciding causation, coverage or recoverability."
                        if machinery
                        else "Organize navigation, damage and recovery evidence without determining fault, liability or apportionment."
                    ),
                    "investigation_tracks": (
                        ["Reconstruct the casualty chronology and operating condition.", "Review maintenance history and recent overhaul work."]
                        if machinery
                        else ["Reconstruct navigation, encounter geometry and collision chronology.", "Map vessel damage and emergency measures."]
                    ),
                    "evidence_prompts": (
                        ["PMS history, running-hours records, overhaul reports and maker recommendations.", "Engine log and relevant alarm/event records."]
                        if machinery
                        else ["VDR/S-VDR, AIS, ECDIS/chart data and bridge log extracts.", "Damage photographs, survey reports and repair estimates."]
                    ),
                    "review_topics": (
                        ["Technical failure mechanism and competing causation hypotheses."]
                        if machinery
                        else ["Navigation chronology and evidence preservation; no fault conclusion is implied."]
                    ),
                    "contextual_rule_ids": ["TECH-001", "AAA-D1"] if machinery else ["MARINE-EMERGENCY-001", "AAA-D1"],
                },
            }
        )
        return base

    def intelligence_snapshot(row: dict, version: int) -> dict:
        incident_title = "Machinery Failure" if row["incident_code"] == "machinery_failure" else "Collision"
        component_title = "Turbocharger" if row.get("component_code") == "turbocharger" else None
        description_parts = [incident_title]
        if component_title:
            description_parts.append(component_title)
        if row.get("failure_mode"):
            description_parts.append(row["failure_mode"])
        item_id = f"33333333-3333-3333-3333-33333333333{version}"
        snapshot_id = f"44444444-4444-4444-4444-44444444444{version}"
        return {
            "id": snapshot_id,
            "claim_id": CLAIM_ID,
            "generated_by_id": "22222222-2222-2222-2222-222222222222",
            "snapshot_version": version,
            "engine_version": "12A.1",
            "source_state_hash": ("c" if version == 1 else "d") * 64,
            "snapshot_hash": ("e" if version == 1 else "f") * 64,
            "summary": {
                "source_linked": True,
                "non_authoritative": True,
                "human_review_required": True,
                "domain_classification_present": True,
                "domain_context_count": 1,
                "domain_classification_drives_rules": False,
                "missing_evidence_count": 0,
                "open_conflict_count": 0,
                "hypothesis_count": 0,
                "financial_recovery_lead_count": 0,
                "next_action_count": 0,
            },
            "generated_at": datetime.now(UTC).isoformat(),
            "items": [
                {
                    "id": item_id,
                    "snapshot_id": snapshot_id,
                    "item_key": f"domain-classification-{row['id']}",
                    "category": "domain_context",
                    "title": f"Claim domain: {incident_title}",
                    "description": "Human-confirmed domain context: " + " — ".join(description_parts) + ".",
                    "severity": "info",
                    "urgency_score": 25,
                    "evidential_value_score": 100,
                    "rank_score": 59,
                    "rationale": "Copied from the current human-confirmed ClaimDomainClassification lineage. This is bounded incident context only.",
                    "source_refs": [
                        {
                            "kind": "claim_domain_classification",
                            "id": row["id"],
                            "catalog_version": row["catalog_version"],
                            "classification_number": row["classification_number"],
                            "classification_hash": row["classification_hash"],
                        }
                    ],
                    "action_type": None,
                    "suggested_action": None,
                    "related_entity_type": "claim_domain_classification",
                    "related_entity_id": row["id"],
                    "item_hash": ("1" if version == 1 else "2") * 64,
                    "latest_decision": None,
                }
            ],
        }

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
            nonlocal current, snapshot, build_count
            url = route.request.url
            method = route.request.method
            if url.endswith("/intelligence/domain-catalog") and method == "GET":
                route.fulfill(status=200, content_type="application/json", body=json.dumps(catalog))
                return
            if url.endswith("/intelligence/domain-playbook-preview") and method == "GET":
                route.fulfill(status=200, content_type="application/json", body=json.dumps(playbook_preview(current)))
                return
            if url.endswith("/intelligence/domain-classifications") and method == "GET":
                route.fulfill(status=200, content_type="application/json", body=json.dumps(history))
                return
            if url.endswith("/intelligence/domain-classification") and method == "GET":
                route.fulfill(status=200, content_type="application/json", body=json.dumps(current))
                return
            if url.endswith("/intelligence/domain-classification") and method == "POST":
                payload = route.request.post_data_json
                if payload.get("confirm_classification") is not True:
                    route.fulfill(status=422, content_type="application/json", body=json.dumps({"detail": "Explicit human confirmation is required"}))
                    return
                current = classification_row(payload, len(history) + 1)
                history.insert(0, current)
                route.fulfill(status=201, content_type="application/json", body=json.dumps(current))
                return
            if url.endswith("/intelligence/build") and method == "POST":
                if current is None:
                    route.fulfill(status=409, content_type="application/json", body=json.dumps({"detail": "No classification"}))
                    return
                build_count += 1
                snapshot = intelligence_snapshot(current, build_count)
                route.fulfill(status=201, content_type="application/json", body=json.dumps(snapshot))
                return
            if url.endswith("/intelligence") and method == "GET":
                dashboard = {
                    "claim_id": CLAIM_ID,
                    "snapshot": snapshot,
                    "disclaimer": "Claims Intelligence is source-linked decision support only and never determines substantive claim outcomes.",
                }
                route.fulfill(status=200, content_type="application/json", body=json.dumps(dashboard))
                return
            route.continue_()

        page.route(f"**/api/v1/claims/{CLAIM_ID}/intelligence**", route_intelligence)
        page.goto(f"{BASE_URL}/claims/{CLAIM_ID}/intelligence", wait_until="networkidle")
        classification_panel = page.locator('section[aria-label="Claim domain classification"]')
        playbook_panel = page.locator('section[aria-label="Domain investigation playbook"]')

        expect(page.get_by_role("heading", name="Source-linked claim intelligence")).to_be_visible()
        expect(page.get_by_role("heading", name="Claim domain classification")).to_be_visible()
        expect(page.get_by_role("heading", name="Domain investigation playbook")).to_be_visible()
        expect(page.get_by_text("No claim-domain classification has been recorded", exact=False)).to_be_visible()
        expect(playbook_panel.get_by_text("Human classification required.", exact=False)).to_be_visible()
        expect(playbook_panel.get_by_text("Machinery Failure Investigation Preview", exact=True)).to_have_count(0)
        expect(page.get_by_text("No intelligence snapshot yet", exact=True)).to_be_visible()

        page.get_by_label("Claim incident domain").select_option("machinery_failure")
        page.get_by_label("Machinery component").select_option("turbocharger")
        page.get_by_label("Failure mode").fill("bearing damage")
        first_note = "Handler confirms machinery failure after reviewing the controlled technical evidence."
        page.get_by_label("Human classification note").fill(first_note)
        save = page.get_by_role("button", name="Save classification")
        expect(save).to_be_disabled()
        page.get_by_label("Confirm claim domain classification").check()
        expect(save).to_be_enabled()
        save.click()

        expect(page.get_by_text("Classification v1 saved", exact=False)).to_be_visible()
        expect(page.get_by_text("was not rebuilt automatically", exact=False)).to_be_visible()
        expect(page.get_by_text("No intelligence snapshot yet", exact=True)).to_be_visible()
        expect(classification_panel).to_contain_text(first_note)
        expect(playbook_panel.get_by_text("Machinery Failure Investigation Preview", exact=True)).to_be_visible()
        expect(playbook_panel.get_by_text("PMS history", exact=False)).to_be_visible()
        expect(playbook_panel.get_by_text("TECH-001", exact=True)).to_be_visible()
        expect(playbook_panel.get_by_text("References only", exact=False)).to_be_visible()
        expect(playbook_panel).not_to_contain_text(first_note)
        expect(playbook_panel.get_by_role("button")).to_have_count(0)
        playbook_panel.get_by_text("Playbook source lineage", exact=True).click()
        expect(playbook_panel).to_contain_text("Classification sequence: v1")
        expect(playbook_panel).to_contain_text("a" * 64)

        page.get_by_role("button", name="Build intelligence").click()
        expect(page.get_by_text("Intelligence snapshot v1 is ready.", exact=True)).to_be_visible()
        domain_heading = page.get_by_role("heading", name="Governed claim domain context")
        expect(domain_heading).to_be_visible()
        domain_section = domain_heading.locator("xpath=ancestor::section[1]")
        expect(domain_section.get_by_text("Claim domain: Machinery Failure", exact=True)).to_be_visible()
        expect(domain_section).not_to_contain_text(first_note)
        expect(domain_section.get_by_text("Turbocharger", exact=False)).to_be_visible()

        page.get_by_label("Claim incident domain").select_option("collision")
        expect(page.get_by_label("Machinery component")).to_have_count(0)
        expect(page.get_by_label("Failure mode")).to_be_disabled()
        second_note = "Handler reclassifies the incident as collision after reviewing later casualty evidence."
        page.get_by_label("Human classification note").fill(second_note)
        page.get_by_label("Confirm claim domain classification").check()
        page.get_by_role("button", name="Save new classification version").click()

        expect(page.get_by_text("Classification v2 saved", exact=False)).to_be_visible()
        expect(page.get_by_text("was not rebuilt automatically", exact=False)).to_be_visible()
        expect(page.get_by_label("Claim incident domain")).to_have_value("collision")
        expect(classification_panel).to_contain_text(second_note)
        expect(page.get_by_text("Classification history · 2 versions", exact=True)).to_be_visible()
        expect(playbook_panel.get_by_text("Collision Investigation Preview", exact=True)).to_be_visible()
        expect(playbook_panel.get_by_text("VDR/S-VDR", exact=False)).to_be_visible()
        expect(playbook_panel.get_by_text("MARINE-EMERGENCY-001", exact=True)).to_be_visible()
        expect(playbook_panel).not_to_contain_text(second_note)
        expect(domain_section.get_by_text("Claim domain: Machinery Failure", exact=True)).to_be_visible()
        expect(domain_section.get_by_text("Claim domain: Collision", exact=True)).to_have_count(0)

        page.get_by_role("button", name="Refresh intelligence").click()
        expect(page.get_by_text("Intelligence snapshot v2 is ready.", exact=True)).to_be_visible()
        domain_heading = page.get_by_role("heading", name="Governed claim domain context")
        domain_section = domain_heading.locator("xpath=ancestor::section[1]")
        expect(domain_section.get_by_text("Claim domain: Collision", exact=True)).to_be_visible()
        expect(domain_section).not_to_contain_text(second_note)

        browser.close()

    print("Claim domain classification and playbook UI browser E2E passed.")


if __name__ == "__main__":
    main()
