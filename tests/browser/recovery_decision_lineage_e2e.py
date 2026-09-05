"""Phase 13.7B real MT ORION recovery decision/action lineage acceptance."""
from __future__ import annotations

import os
import re
from uuid import uuid4

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


def _claim_id(page) -> str:
    page.goto(f"{BASE_URL}/claims", wait_until="networkidle")
    page.get_by_placeholder("Search claim, vessel or IMO…").fill("MCRI-DEMO-MT-ORION")
    page.get_by_role("button", name="Apply filters").click()
    row = page.get_by_role("row").filter(has_text="MT ORION").filter(has_text="MCRI-DEMO-MT-ORION")
    expect(row).to_have_count(1)
    claim_link = row.locator('a[href^="/claims/"]').filter(has_text=re.compile(r"^MCRI-HM-"))
    expect(claim_link).to_have_count(1)
    href = claim_link.get_attribute("href")
    if not href:
        raise AssertionError("Expected MT ORION claim href")
    return href.rstrip("/").split("/")[-1]


def _control(panel, label_text: str, tag: str):
    """Resolve a nested form control from an anchored visible label prefix."""
    label = panel.locator("label").filter(
        has_text=re.compile(rf"^\s*{re.escape(label_text)}", re.IGNORECASE)
    )
    expect(label).to_have_count(1)
    control = label.locator(tag)
    expect(control).to_have_count(1)
    return control


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    suffix = uuid4().hex[:8]
    counterparty_name = f"Recovery E2E Workshop {suffix}"
    counterparty_role = "Potential workshop contractor"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1500, "height": 1600})
        page = context.new_page()

        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")

        claim_id = _claim_id(page)
        request = context.request

        # Seed one explicit human counterparty through the canonical API so this
        # acceptance remains independent from Phase 13.7A browser execution order.
        counterparty = _json(
            request.post(
                f"{API_URL}/api/v1/claims/{claim_id}/recovery-timebar/counterparties",
                data={
                    "name": counterparty_name,
                    "role": counterparty_role,
                    "allegation_basis": (
                        "Human investigation hypothesis for browser acceptance only; no platform finding of fault or liability."
                    ),
                    "source_reference": "MT ORION reviewed workshop correspondence — browser acceptance",
                },
            ),
            "create recovery counterparty",
        )

        maturity = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/recovery-timebar/maturity"),
            "recovery maturity after counterparty seed",
        )
        if not any(row["id"] == counterparty["id"] for row in maturity["counterparties"]):
            raise AssertionError("Seeded recovery counterparty is missing from the canonical maturity dashboard")

        page.goto(f"{BASE_URL}/claims/{claim_id}/recovery-timebar/maturity", wait_until="networkidle")
        decision_heading = page.get_by_role("heading", name="Recovery decision & action lineage", exact=True)
        expect(decision_heading).to_be_visible(timeout=15_000)
        panel = decision_heading.locator("xpath=ancestor::section[contains(@class,'panel')][1]")
        expect(panel).to_have_count(1)
        expect(panel.get_by_text("Human decision only.", exact=True)).to_be_visible()

        # New 13.7B surface participates in EN/FA/RTL localization.
        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.locator("html")).to_have_attribute("lang", "fa")
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(page.get_by_role("heading", name="زنجیره تصمیم و اقدامات بازیافت", exact=True)).to_be_visible()
        page.get_by_role("button", name="EN", exact=True).click()
        expect(page.locator("html")).to_have_attribute("lang", "en")
        expect(page.locator("html")).to_have_attribute("dir", "ltr")

        decision_heading = page.get_by_role("heading", name="Recovery decision & action lineage", exact=True)
        panel = decision_heading.locator("xpath=ancestor::section[contains(@class,'panel')][1]")
        expect(panel).to_have_count(1)
        counterparty_select = _control(panel, "Current counterparty version", "select")
        counterparty_option_label = f"{counterparty_name} · {counterparty_role} · v1"
        expect(counterparty_select).to_contain_text(counterparty_name, timeout=15_000)
        counterparty_select.select_option(label=counterparty_option_label)
        expect(counterparty_select).to_have_value(counterparty["id"])
        _control(panel, "Human disposition", "select").select_option("monitor")
        _control(panel, "Human rationale", "textarea").fill(
            "Human handler decision to monitor the recovery path while factual and legal review continues."
        )
        _control(panel, "Basis / source reference", "input").fill(
            "MT ORION recovery review note — browser acceptance"
        )
        _control(panel, "Next human review date (optional)", "input").fill("2026-09-30")

        decision_endpoint = f"/api/v1/claims/{claim_id}/recovery-timebar/decisions"
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(decision_endpoint),
            timeout=15_000,
        ) as save_info:
            panel.get_by_role("button", name="Record human decision", exact=True).click()
        created_decision = _json(save_info.value, "browser recovery decision save")
        if created_decision["counterparty_id"] != counterparty["id"]:
            raise AssertionError(f"Browser decision bound to unexpected counterparty: {created_decision}")

        # Verify persistence before asserting React rendering. Then locate the card
        # from its own heading rather than filtering a broad CSS collection.
        decision_dashboard = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/recovery-timebar/decisions"),
            "recovery decision dashboard",
        )
        decisions = [row for row in decision_dashboard["decisions"] if row["counterparty_name"] == counterparty_name]
        if len(decisions) != 1:
            raise AssertionError("Expected exactly one current human recovery decision for the E2E counterparty")
        decision = decisions[0]
        if decision["version"] != 1 or decision["disposition"] != "monitor":
            raise AssertionError(f"Unexpected recovery decision state: {decision}")
        if decision["context_state_status"] != "reference_only":
            raise AssertionError("Reference-only human counterparty context was not preserved on the decision")

        saved_heading = panel.get_by_role("heading", name=counterparty_name, exact=True)
        expect(saved_heading).to_be_visible(timeout=15_000)
        decision_card = saved_heading.locator("xpath=ancestor::div[contains(@class,'rounded-xl')][1]")
        expect(decision_card).to_have_count(1)
        expect(decision_card.get_by_text("monitor", exact=True)).to_be_visible()
        expect(decision_card.get_by_text("reference only", exact=True)).to_be_visible()

        # Append a real operator-entered correspondence record. The platform only
        # records this human action; it does not compose or send the correspondence.
        decision_card.get_by_role("button", name="Add action / correspondence", exact=True).click()
        action_heading = panel.get_by_text("Append-only action log", exact=True)
        expect(action_heading).to_be_visible(timeout=15_000)
        action_form = action_heading.locator("xpath=ancestor::div[contains(@class,'border-t')][1]")
        expect(action_form).to_have_count(1)
        _control(action_form, "Action type", "select").select_option("correspondence")
        _control(action_form, "Direction", "select").select_option("outbound")
        _control(action_form, "Occurred on", "input").fill("2026-09-05")
        _control(action_form, "Human-entered summary", "textarea").fill(
            "Handler records that a human-approved preservation correspondence was sent outside autonomous platform authority."
        )
        _control(action_form, "Source reference", "input").fill("Recovery correspondence REC-E2E-001")

        action_endpoint = f"/api/v1/claims/{claim_id}/recovery-timebar/decisions/{decision['decision_key']}/actions"
        with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.endswith(action_endpoint),
            timeout=15_000,
        ) as action_info:
            action_form.get_by_role("button", name="Append human action", exact=True).click()
        _json(action_info.value, "browser recovery action append")

        expect(
            decision_card.get_by_text(
                "Handler records that a human-approved preservation correspondence was sent outside autonomous platform authority.",
                exact=True,
            )
        ).to_be_visible(timeout=15_000)

        after_action = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/recovery-timebar/decisions"),
            "recovery dashboard after action",
        )
        current = next(row for row in after_action["decisions"] if row["counterparty_name"] == counterparty_name)
        if len(current["actions"]) != 1:
            raise AssertionError(f"Expected one append-only recovery action: {current['actions']}")
        action = current["actions"][0]
        if action["action_number"] != 1 or action["action_type"] != "correspondence":
            raise AssertionError(f"Unexpected action lineage: {action}")
        if action["previous_action_hash"] is not None:
            raise AssertionError("First recovery action unexpectedly has a previous action hash")

        browser.close()


if __name__ == "__main__":
    main()