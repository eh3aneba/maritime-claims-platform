"""Phase 13.7A real MT ORION Recovery / Time-bar maturity acceptance."""
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


def _control_by_label(scope, label_text: str, selector: str):
    """Resolve a form control from the real label container, not ARIA heuristics."""
    label = scope.locator("label").filter(has_text=label_text).first
    expect(label).to_be_visible(timeout=15_000)
    control = label.locator(selector)
    expect(control).to_have_count(1)
    expect(control).to_be_visible()
    return control


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


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1500, "height": 1400})
        page = context.new_page()

        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")

        claim_id = _claim_id(page)
        request = context.request

        # Discoverability: the mature workflow must be reachable from the real claim overview.
        page.goto(f"{BASE_URL}/claims/{claim_id}", wait_until="networkidle")
        maturity_link = page.get_by_role("link", name="Recovery scenarios", exact=True)
        expect(maturity_link).to_be_visible()
        maturity_link.click()
        page.wait_for_url(f"**/claims/{claim_id}/recovery-timebar/maturity")
        expect(page.get_by_role("heading", name="Recovery counterparties & time-bar scenarios")).to_be_visible()
        expect(page.get_by_text("No automated legal conclusion.", exact=True)).to_be_visible()

        # EN/FA/RTL acceptance on the new production surface.
        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.locator("html")).to_have_attribute("lang", "fa")
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(page.get_by_role("heading", name="طرف‌های احتمالی بازیافت و سناریوهای مهلت زمانی")).to_be_visible()
        page.get_by_role("button", name="EN", exact=True).click()
        expect(page.locator("html")).to_have_attribute("lang", "en")
        expect(page.locator("html")).to_have_attribute("dir", "ltr")

        counterparty_section = page.locator("section").filter(
            has=page.get_by_role("heading", name="Potential counterparties", exact=True)
        )
        expect(counterparty_section).to_have_count(1)
        counterparty_section.get_by_label("Name", exact=True).fill("TurboMaker GmbH")
        counterparty_section.get_by_label("Human-assigned role", exact=True).fill("Workshop overhaul contractor")
        counterparty_section.get_by_label("Allegation / investigation basis", exact=True).fill(
            "Human investigation hypothesis following the recent turbocharger overhaul; no platform finding of fault."
        )
        counterparty_section.get_by_label("Source reference", exact=True).fill(
            "Reviewed workshop correspondence and overhaul contract file"
        )
        counterparty_section.get_by_role("button", name="Save human context", exact=True).click()
        expect(counterparty_section.get_by_text("Workshop overhaul contractor · v1", exact=True)).to_be_visible(timeout=15_000)

        first_dashboard = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/recovery-timebar/maturity"),
            "maturity after counterparty creation",
        )
        counterparties = [row for row in first_dashboard["counterparties"] if row["name"] == "TurboMaker GmbH"]
        if len(counterparties) != 1:
            raise AssertionError("Expected one current human-created recovery counterparty")
        first_counterparty = counterparties[0]
        if first_counterparty["version"] != 1 or first_counterparty["source_state_status"] != "reference_only":
            raise AssertionError("Initial counterparty did not preserve version/reference-only provenance")

        # Explicit counterparty revision: prior version remains immutable history.
        counterparty_card = counterparty_section.locator("div.rounded-xl.border.border-slate-200").filter(
            has=page.get_by_role("heading", name="TurboMaker GmbH", exact=True)
        ).first
        counterparty_card.get_by_role("button", name="Create revised version", exact=True).click()
        counterparty_section.get_by_label("Human-assigned role", exact=True).fill(
            "Workshop contractor / overhaul provider"
        )
        counterparty_section.get_by_role("button", name="Save human context", exact=True).click()
        # React click completion does not await the async API handler. Wait for the
        # reloaded immutable v2 card rather than racing the following API assertion.
        expect(
            counterparty_section.get_by_text("Workshop contractor / overhaul provider · v2", exact=True)
        ).to_be_visible(timeout=15_000)

        revised_dashboard = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/recovery-timebar/maturity"),
            "maturity after counterparty revision",
        )
        current_counterparty = next(row for row in revised_dashboard["counterparties"] if row["name"] == "TurboMaker GmbH")
        if current_counterparty["version"] != 2:
            raise AssertionError(
                f"Counterparty revision did not create immutable version 2: {current_counterparty}"
            )
        counterparty_history = _json(
            request.get(
                f"{API_URL}/api/v1/claims/{claim_id}/recovery-timebar/counterparties/{current_counterparty['counterparty_key']}/history"
            ),
            "counterparty history",
        )
        if [row["version"] for row in counterparty_history] != [2, 1]:
            raise AssertionError("Counterparty history did not preserve both immutable versions")
        if counterparty_history[0]["supersedes_id"] != counterparty_history[1]["id"]:
            raise AssertionError("Counterparty version lineage is broken")

        # Re-enter the persisted workspace after the write. This avoids testing a
        # transient React tree and proves that the immutable v2 context is what a
        # fresh operator view exposes to the scenario form.
        page.reload(wait_until="networkidle")
        expect(page.get_by_role("heading", name="Recovery counterparties & time-bar scenarios")).to_be_visible()
        scenario_heading = page.get_by_role("heading", name="Create alternative time-bar scenario", exact=True)
        expect(scenario_heading).to_be_visible(timeout=15_000)
        scenario_form = page.locator("section").filter(has=scenario_heading)
        expect(scenario_form).to_have_count(1)
        counterparty_label = scenario_form.locator("label").filter(
            has_text="Potential counterparty (optional)"
        ).first
        expect(counterparty_label).to_be_visible()
        counterparty_select = counterparty_label.locator("select")
        expect(counterparty_select).to_have_count(1)
        expect(counterparty_select).to_be_visible()
        expect(counterparty_select.locator(f'option[value="{current_counterparty["id"]}"]')).to_have_text(
            "TurboMaker GmbH · v2"
        )

        # Scenario A: six-month contractual notice hypothesis.
        scenario_form.get_by_label("Scenario title", exact=True).fill("Workshop contractual notice scenario")
        counterparty_select.select_option(current_counterparty["id"])
        scenario_form.get_by_label("Human-entered legal/factual basis", exact=True).fill(
            "Human hypothesis based on the workshop contract notice wording; governing law and enforceability remain for legal review."
        )
        scenario_form.get_by_label("Source reference", exact=True).fill("Workshop Contract clause 12 — human reviewed reference")
        scenario_form.get_by_label("Human-selected anchor date", exact=True).fill("2026-07-10")
        scenario_form.get_by_label("Period", exact=True).fill("6")
        period_unit_label = scenario_form.locator("label").filter(has_text="Unit").nth(0)
        expect(period_unit_label).to_be_visible()
        period_unit_select = period_unit_label.locator("select")
        expect(period_unit_select).to_have_count(1)
        period_unit_select.select_option("months")
        _control_by_label(scenario_form, "Assumptions and uncertainty", "textarea").fill(
            "Assume solely for comparison that 10 July 2026 is the contractual trigger; no legal conclusion is made."
        )
        scenario_form.get_by_role("button", name="Compute candidate & save", exact=True).click()
        scenarios_section = page.locator("section").filter(
            has=page.get_by_role("heading", name="Alternative time-bar scenarios", exact=True)
        )
        scenario_a_card = scenarios_section.locator("div.rounded-xl.border.border-slate-200").filter(
            has=page.get_by_role("heading", name="Workshop contractual notice scenario", exact=True)
        ).first
        expect(scenario_a_card.get_by_text("v1 · 6 months", exact=True)).to_be_visible(timeout=15_000)

        dashboard_a = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/recovery-timebar/maturity"),
            "maturity after first scenario",
        )
        scenario_a = next(row for row in dashboard_a["scenarios"] if row["title"] == "Workshop contractual notice scenario")
        if scenario_a["candidate_deadline"] != "2027-01-10":
            raise AssertionError(f"Unexpected six-month candidate date: {scenario_a['candidate_deadline']}")
        if scenario_a["latest_review"] is not None:
            raise AssertionError("Candidate arithmetic unexpectedly created an authoritative review")
        if scenario_a["source_state_status"] != "reference_only":
            raise AssertionError("Reference-only scenario provenance was not explicit")

        # Deliberate revision of Scenario A using optimistic scenario lineage.
        scenario_a_card.get_by_role("button", name="Create revised version", exact=True).click()
        revised_heading = page.get_by_role("heading", name="Revise time-bar scenario", exact=True)
        expect(revised_heading).to_be_visible(timeout=15_000)
        revised_form = page.locator("section").filter(has=revised_heading)
        expect(revised_form).to_have_count(1)
        revised_assumption = (
            "Revised human assumption after contract review: anchor remains comparative only and requires legal verification."
        )
        _control_by_label(revised_form, "Assumptions and uncertainty", "textarea").fill(revised_assumption)
        revised_form.get_by_role("button", name="Create new immutable version", exact=True).click()
        # The title already existed at v1, so wait for content that can only be
        # rendered from the completed v2 reload.
        expect(scenarios_section.get_by_text(revised_assumption, exact=True)).to_be_visible(timeout=15_000)
        scenario_a_card = scenarios_section.locator("div.rounded-xl.border.border-slate-200").filter(
            has=page.get_by_role("heading", name="Workshop contractual notice scenario", exact=True)
        ).first
        expect(scenario_a_card.get_by_text("v2 · 6 months", exact=True)).to_be_visible(timeout=15_000)

        dashboard_v2 = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/recovery-timebar/maturity"),
            "maturity after scenario revision",
        )
        scenario_a_v2 = next(row for row in dashboard_v2["scenarios"] if row["title"] == "Workshop contractual notice scenario")
        if scenario_a_v2["version"] != 2 or scenario_a_v2["candidate_deadline"] != "2027-01-10":
            raise AssertionError("Scenario revision did not preserve deterministic candidate arithmetic/versioning")
        scenario_history = _json(
            request.get(
                f"{API_URL}/api/v1/claims/{claim_id}/recovery-timebar/scenarios/{scenario_a_v2['scenario_key']}/history"
            ),
            "scenario history",
        )
        if [row["version"] for row in scenario_history] != [2, 1]:
            raise AssertionError("Scenario revision did not preserve immutable history")
        if scenario_history[0]["supersedes_id"] != scenario_history[1]["id"]:
            raise AssertionError("Scenario version lineage is broken")

        # Scenario B: alternative one-year hypothesis. Both must coexist.
        create_heading = page.get_by_role("heading", name="Create alternative time-bar scenario", exact=True)
        expect(create_heading).to_be_visible(timeout=15_000)
        create_form = page.locator("section").filter(has=create_heading)
        expect(create_form).to_have_count(1)
        create_form.get_by_label("Scenario title", exact=True).fill("Alternative annual limitation scenario")
        create_form.get_by_label("Human-entered legal/factual basis", exact=True).fill(
            "Alternative human hypothesis for comparison only; legal applicability has not been determined."
        )
        create_form.get_by_label("Source reference", exact=True).fill("Alternative legal review note — human supplied")
        create_form.get_by_label("Human-selected anchor date", exact=True).fill("2026-07-10")
        create_form.get_by_label("Period", exact=True).fill("1")
        create_period_unit_label = create_form.locator("label").filter(has_text="Unit").nth(0)
        expect(create_period_unit_label).to_be_visible()
        create_period_unit_select = create_period_unit_label.locator("select")
        expect(create_period_unit_select).to_have_count(1)
        create_period_unit_select.select_option("years")
        _control_by_label(create_form, "Assumptions and uncertainty", "textarea").fill(
            "Compare a one-year period without treating it as selected governing law or an authoritative time bar."
        )
        create_form.get_by_role("button", name="Compute candidate & save", exact=True).click()
        scenario_b_card = scenarios_section.locator("div.rounded-xl.border.border-slate-200").filter(
            has=page.get_by_role("heading", name="Alternative annual limitation scenario", exact=True)
        ).first
        expect(scenario_b_card.get_by_text("v1 · 1 years", exact=True)).to_be_visible(timeout=15_000)

        alternatives = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/recovery-timebar/maturity"),
            "maturity with alternative scenarios",
        )
        current = {row["title"]: row for row in alternatives["scenarios"]}
        required_titles = {"Workshop contractual notice scenario", "Alternative annual limitation scenario"}
        if not required_titles.issubset(current):
            raise AssertionError(f"Expected both alternative scenarios, got {set(current)}")
        if current["Alternative annual limitation scenario"]["candidate_deadline"] != "2027-07-10":
            raise AssertionError("Alternative one-year candidate date was not deterministic")

        # Manager/Admin review is a separate explicit authority step.
        reviewed_card = scenarios_section.locator("div.rounded-xl.border.border-slate-200").filter(
            has=page.get_by_role("heading", name="Workshop contractual notice scenario", exact=True)
        ).first
        reviewed_card.get_by_role("button", name="Human/legal review", exact=True).click()
        review_marker = page.get_by_text("Manager/Admin human/legal review", exact=True)
        expect(review_marker).to_be_visible(timeout=15_000)
        review_section = page.locator("section").filter(
            has=page.get_by_role("heading", name="Workshop contractual notice scenario", exact=True)
        ).filter(has=review_marker)
        expect(review_section).to_have_count(1)
        _control_by_label(review_section, "Review action", "select").select_option("confirm")
        _control_by_label(review_section, "Human/legal review note", "textarea").fill(
            "Manager reviewed the human inputs and source reference; confirming only this scenario's computed candidate for controlled diary use."
        )
        review_section.get_by_role("button", name="Record append-only human review", exact=True).click()
        # Wait for the scenario card to render the separately persisted review.
        expect(reviewed_card.get_by_text("Latest human/legal review", exact=True)).to_be_visible(timeout=15_000)
        expect(reviewed_card).to_contain_text("#1 · confirm")

        final = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/recovery-timebar/maturity"),
            "final recovery maturity dashboard",
        )
        confirmed = next(row for row in final["scenarios"] if row["title"] == "Workshop contractual notice scenario")
        if confirmed["latest_review"] is None:
            raise AssertionError("Human/legal confirmation was not recorded")
        if confirmed["latest_review"]["action"] != "confirm":
            raise AssertionError("Unexpected human/legal review action")
        if confirmed["latest_review"]["confirmed_deadline"] != confirmed["candidate_deadline"]:
            raise AssertionError("Confirm did not bind exactly to the immutable candidate date")
        if not confirmed["latest_review"]["review_hash"]:
            raise AssertionError("Human/legal review is missing its append-only hash")

        browser.close()


if __name__ == "__main__":
    main()
