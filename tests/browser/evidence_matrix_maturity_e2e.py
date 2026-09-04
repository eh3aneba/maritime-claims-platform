"""Browser acceptance for Phase 13.4C Evidence Matrix consolidation.

Uses the real MT ORION synthetic design-partner claim and production APIs. The only
DB-side fixture mutation advances one already human-approved ClaimFact version so
we can exercise the real stale-lineage reconciliation path without adding a test-only
HTTP endpoint or bypassing a human review authority control.
"""
from __future__ import annotations

import json
import os
import subprocess
import textwrap

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
API_URL = os.getenv("MCRI_API_URL", "http://127.0.0.1:8000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")
COMPOSE_ENV_FILE = os.getenv("MCRI_COMPOSE_ENV_FILE", "").strip()

STATUS_FA = {
    "missing": "مفقود",
    "requested": "درخواست‌شده",
    "received": "دریافت‌شده",
    "under_review": "در حال بازبینی",
    "accepted": "پذیرفته‌شده",
    "rejected": "ردشده",
    "superseded": "منسوخ / جایگزین‌شده",
    "not_required": "لازم نیست",
}
STATUS_EN = {
    "missing": "Missing",
    "requested": "Requested",
    "received": "Received",
    "under_review": "Under review",
    "accepted": "Accepted",
    "rejected": "Rejected",
    "superseded": "Superseded",
    "not_required": "Not required",
}


def _compose_exec_python(script: str) -> str:
    command = ["docker", "compose"]
    if COMPOSE_ENV_FILE:
        command.extend(["--env-file", COMPOSE_ENV_FILE])
    command.extend(["exec", "-T", "api", "python", "-"])
    result = subprocess.run(command, input=script, check=True, text=True, capture_output=True)
    return result.stdout.strip()


def _advance_claim_fact_version(claim_fact_id: str) -> int:
    fact_literal = json.dumps(claim_fact_id)
    script = textwrap.dedent(
        f"""
        from datetime import UTC, datetime
        from uuid import UUID

        from app.db.session import create_session
        from app.modules.claims.facts import ClaimFact

        with create_session() as db:
            fact = db.get(ClaimFact, UUID({fact_literal}))
            if fact is None:
                raise RuntimeError("Equivalent ClaimFact disappeared before stale-lineage test")
            fact.version += 1
            fact.approved_at = datetime.now(UTC)
            db.commit()
            print(fact.version)
        """
    )
    output = _compose_exec_python(script)
    return int(output.splitlines()[-1])


def _json_response(response, label: str) -> dict:
    if not response.ok:
        raise AssertionError(f"{label} failed: HTTP {response.status} {response.text()}")
    return response.json()


def _find_claim(page) -> str:
    page.goto(f"{BASE_URL}/claims", wait_until="networkidle")
    page.get_by_placeholder("Search claim, vessel or IMO…").fill("MCRI-DEMO-MT-ORION")
    page.get_by_role("button", name="Apply filters").click()
    expect(page.get_by_text("MT ORION", exact=True)).to_be_visible()
    claim_link = page.locator('a[href^="/claims/"]').filter(has_text="MCRI-HM-").first
    expect(claim_link).to_be_visible()
    href = claim_link.get_attribute("href")
    if not href:
        raise AssertionError("Expected MT ORION claim href")
    return href.rstrip("/").split("/")[-1]


def _rules(page, claim_id: str) -> dict:
    return _json_response(
        page.request.get(f"{API_URL}/api/v1/claims/{claim_id}/rules"),
        "Claim rules",
    )


def _candidate_requirement(summary: dict) -> tuple[dict, dict]:
    eligible: list[tuple[dict, dict]] = []
    for requirement in summary.get("requirements", []):
        candidates = [
            candidate
            for candidate in requirement.get("equivalent_evidence_candidates", [])
            if candidate.get("claim_fact_version")
        ]
        if not candidates or not requirement.get("state_fingerprint") or not requirement.get("state_version"):
            continue
        if requirement.get("matched_document_id"):
            # Direct evidence remains the preferred current evidence path; this test
            # intentionally exercises a requirement that genuinely relies on an
            # equivalent ClaimFact rather than displacing a usable direct document.
            continue
        eligible.append((requirement, candidates[0]))

    if not eligible:
        raise AssertionError("MT ORION has no source-linked equivalent-evidence requirement candidate")

    eligible.sort(key=lambda item: 0 if item[0].get("status") == "requested" else 1)
    return eligible[0]


def _requirement_card(page, requirement_id: str):
    card = page.locator(f'[data-requirement-id="{requirement_id}"]')
    expect(card).to_be_visible(timeout=15_000)
    return card


def _accept_equivalent(page, claim_id: str, requirement: dict, candidate: dict, *, note: str, re_review: bool) -> dict:
    response = page.request.post(
        f"{API_URL}/api/v1/claims/{claim_id}/rules/requirements/{requirement['id']}/accept-equivalent",
        data={
            "claim_fact_id": candidate["claim_fact_id"],
            "claim_fact_version": candidate["claim_fact_version"],
            "expected_state_fingerprint": requirement["state_fingerprint"],
            "expected_state_version": requirement["state_version"],
            "note": note,
            "re_review": re_review,
        },
    )
    return _json_response(response, "Equivalent evidence review")


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

        claim_id = _find_claim(page)
        initial_summary = _rules(page, claim_id)
        requirement, candidate = _candidate_requirement(initial_summary)
        initial_status = requirement["status"]

        # The consolidated matrix exposes readiness and active requirement lifecycle
        # beside ClaimFact/source/conflict provenance, without adding a write surface.
        page.goto(f"{BASE_URL}/claims/{claim_id}/evidence-matrix", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Evidence Matrix")).to_be_visible()
        expect(page.get_by_role("heading", name="Requirements & readiness")).to_be_visible()
        expect(page.get_by_text("Readiness", exact=True)).to_be_visible()
        card = _requirement_card(page, requirement["id"])
        expect(card.get_by_text(STATUS_EN[initial_status], exact=True)).to_be_visible()
        expect(page.get_by_role("link", name="Review / request evidence")).to_have_attribute(
            "href", f"/claims/{claim_id}/rules"
        )

        # Locale switching is presentation-only and preserves the same requirement
        # identity/readiness state while flipping directionality.
        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(page.get_by_role("heading", name="ماتریس شواهد")).to_be_visible()
        expect(page.get_by_role("heading", name="نیازها و آمادگی شواهد")).to_be_visible()
        card = _requirement_card(page, requirement["id"])
        expect(card.get_by_text(STATUS_FA[initial_status], exact=True)).to_be_visible()
        page.get_by_role("button", name="EN", exact=True).click()
        expect(page.locator("html")).to_have_attribute("dir", "ltr")

        # Use the production human-review endpoint with the exact evidence-state and
        # ClaimFact versions returned to the operator. This creates append-only lineage.
        first_note = "MT ORION browser acceptance: equivalent evidence reviewed and accepted."
        first_result = _accept_equivalent(
            page,
            claim_id,
            requirement,
            candidate,
            note=first_note,
            re_review=False,
        )
        if first_result["requirement"]["status"] != "accepted":
            raise AssertionError("Equivalent review did not move the requirement to accepted")

        page.reload(wait_until="networkidle")
        card = _requirement_card(page, requirement["id"])
        expect(card.get_by_text("Accepted", exact=True)).to_be_visible()
        expect(card.get_by_text("Equivalent evidence", exact=True)).to_be_visible()
        expect(card.get_by_text(first_note, exact=True)).to_be_visible()
        card.get_by_role("button", name="View decision lineage", exact=True).click()
        expect(card.get_by_text(first_note, exact=True)).to_be_visible()
        expect(card.get_by_text("#1 · Accept Equivalent", exact=True)).to_be_visible()

        # Advance the exact canonical ClaimFact version that was reviewed, then invoke
        # the normal deterministic rules refresh. The prior acceptance must become stale
        # rather than silently transferring to the changed fact.
        next_fact_version = _advance_claim_fact_version(candidate["claim_fact_id"])
        evaluate_response = page.request.post(f"{API_URL}/api/v1/claims/{claim_id}/rules/evaluate")
        _json_response(evaluate_response, "Rules refresh after ClaimFact evolution")

        page.reload(wait_until="networkidle")
        card = _requirement_card(page, requirement["id"])
        expect(card.get_by_text("Superseded", exact=True)).to_be_visible()
        expect(card.get_by_text("explicit human re-review is required", exact=False)).to_be_visible()

        # Refresh the operator contract and explicitly re-review the changed evidence.
        refreshed_summary = _rules(page, claim_id)
        refreshed_requirement = next(
            item for item in refreshed_summary["requirements"] if item["id"] == requirement["id"]
        )
        refreshed_candidate = next(
            item
            for item in refreshed_requirement["equivalent_evidence_candidates"]
            if item["claim_fact_id"] == candidate["claim_fact_id"]
        )
        if refreshed_candidate["claim_fact_version"] != next_fact_version:
            raise AssertionError("Refreshed requirement did not expose the current ClaimFact version")

        second_note = "MT ORION browser acceptance: changed equivalent evidence explicitly re-reviewed."
        second_result = _accept_equivalent(
            page,
            claim_id,
            refreshed_requirement,
            refreshed_candidate,
            note=second_note,
            re_review=True,
        )
        if second_result["requirement"]["status"] != "accepted":
            raise AssertionError("Explicit re-review did not restore accepted requirement state")

        page.reload(wait_until="networkidle")
        card = _requirement_card(page, requirement["id"])
        expect(card.get_by_text("Accepted", exact=True)).to_be_visible()
        card.get_by_role("button", name="View decision lineage", exact=True).click()
        expect(card.get_by_text(first_note, exact=True)).to_be_visible()
        expect(card.get_by_text(second_note, exact=True)).to_be_visible()
        expect(card.get_by_text("#1 · Accept Equivalent", exact=True)).to_be_visible()
        expect(card.get_by_text("#2 · Accept Equivalent", exact=True)).to_be_visible()

        # The same post-re-review state must remain readable in Persian/RTL; locale
        # switching cannot create another decision or alter canonical evidence state.
        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(page.get_by_role("heading", name="ماتریس شواهد")).to_be_visible()
        card = _requirement_card(page, requirement["id"])
        expect(card.get_by_text("پذیرفته‌شده", exact=True)).to_be_visible()
        expect(card.get_by_text(first_note, exact=True)).to_be_visible()
        expect(card.get_by_text(second_note, exact=True)).to_be_visible()

        history_response = page.request.get(
            f"{API_URL}/api/v1/claims/{claim_id}/rules/requirements/{requirement['id']}/decisions"
        )
        history = _json_response(history_response, "Requirement decision history")
        if len(history["items"]) != 2:
            raise AssertionError(f"Expected exactly two append-only decisions, got {len(history['items'])}")
        if history["items"][1]["previous_decision_hash"] != history["items"][0]["decision_hash"]:
            raise AssertionError("Requirement decision lineage is not hash chained")

        browser.close()


if __name__ == "__main__":
    main()
