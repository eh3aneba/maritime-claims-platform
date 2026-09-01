"""Browser smoke test for the synthetic MT ORION design-partner environment.

Prerequisites:
  pip install -r tests/browser/requirements.txt
  playwright install chromium
  docker compose up -d --build
  docker compose --profile demo run --rm demo-seed

Environment variables may override the defaults below.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")
SCREENSHOT = Path(os.getenv("MCRI_E2E_SCREENSHOT", "artifacts/design-partner-e2e.png"))


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    SCREENSHOT.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()

        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")
        expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()

        page.goto(f"{BASE_URL}/claims", wait_until="networkidle")
        page.get_by_placeholder("Search claim, vessel or IMO…").fill("MCRI-DEMO-MT-ORION")
        page.get_by_role("button", name="Apply filters").click()
        expect(page.get_by_text("MT ORION", exact=True)).to_be_visible()
        claim_link = page.locator('a[href^="/claims/"]').filter(has_text="MCRI-HM-").first
        expect(claim_link).to_be_visible()
        claim_href = claim_link.get_attribute("href")
        if not claim_href:
            raise AssertionError("Demo claim link did not expose an href")
        page.goto(f"{BASE_URL}{claim_href}", wait_until="networkidle")
        expect(page.get_by_role("heading", name="MT ORION")).to_be_visible()
        expect(page.get_by_text("MCRI-DEMO-MT-ORION", exact=True)).to_be_visible()

        checks = [
            ("Open Claim Q&A", "Claim Q&A"),
            ("Open Evidence Search", "Evidence Search"),
            ("Open Recovery & Time-bar", "Recovery & Time-bar Intelligence"),
            ("Open Severity & Reserve Support", "Severity & Reserve Support"),
            ("Open requirements", "Requirements & workflow"),
            ("Open chronology", "Claim chronology"),
            ("Open technical review", "Technical review matrix"),
            ("Open policy intelligence", "Policy & Contract Intelligence"),
            ("Open evidence matrix", "Evidence Matrix"),
            ("Open claim-pack exports", "Claim Pack Export"),
            ("Open financial review", "Financial review"),
            ("Open adjustment workspace", "Adjustment Workspace"),
            ("Open settlement and payment ledger", "Settlement & Payment Ledger"),
            ("Open correspondence centre", "Correspondence Centre"),
            ("Open controlled email intake", "Controlled Email Intake"),
            ("Open email adapter operations", "Email Provider Adapter Operations"),
            ("Open external collaboration portal", "External Collaboration Portal"),
            ("Open pilot operations", "Pilot Execution & Production Baseline"),
            ("Open initial assessment", "Initial Assessment"),
        ]
        for link_name, heading in checks:
            page.goto(f"{BASE_URL}{claim_href}", wait_until="networkidle")
            page.get_by_role("link", name=link_name).click()
            expect(page.get_by_role("heading", name=heading)).to_be_visible()

        page.goto(f"{BASE_URL}{claim_href}", wait_until="networkidle")
        page.get_by_role("link", name="Open Evidence Search").click()
        expect(page.get_by_role("heading", name="Evidence Search")).to_be_visible()
        expect(page.get_by_text(re.compile(r"Evidence discovery only"))).to_be_visible()
        page.get_by_label("Evidence search query").fill("turbocharger")
        with page.expect_response(
            lambda response: "/api/v1/claims/" in response.url
            and response.url.endswith("/evidence-search")
            and response.request.method == "POST"
        ) as evidence_response_info:
            page.get_by_role("button", name="Search evidence").click()
        evidence_response = evidence_response_info.value
        if not evidence_response.ok:
            raise AssertionError(f"Evidence search failed: HTTP {evidence_response.status}")
        results = page.locator('section[aria-label="Evidence search results"] article')
        expect(results.first).to_be_visible()
        expect(page.get_by_text("Current version", exact=True).first).to_be_visible()
        expect(page.get_by_role("button", name="Download source").first).to_be_visible()

        page.get_by_label("Evidence retrieval mode").select_option("hybrid")
        expect(page.get_by_text(re.compile(r"Private Hybrid is local-only"))).to_be_visible()
        page.get_by_label("Evidence search query").fill("operating hours")
        with page.expect_response(
            lambda response: "/api/v1/claims/" in response.url
            and response.url.endswith("/evidence-search")
            and response.request.method == "POST"
        ) as hybrid_response_info:
            page.get_by_role("button", name="Search evidence").click()
        hybrid_response = hybrid_response_info.value
        if not hybrid_response.ok:
            raise AssertionError(f"Private hybrid evidence search failed: HTTP {hybrid_response.status}")
        hybrid_payload = hybrid_response.json()
        if hybrid_payload.get("semantic_provider") != "local_in_process":
            raise AssertionError("Private hybrid search did not report the local semantic provider")
        if not hybrid_payload.get("semantic_used"):
            raise AssertionError("Private hybrid search did not report semantic usage")
        if not hybrid_payload.get("results"):
            raise AssertionError("Private hybrid search did not retrieve the running-hours evidence")
        expect(page.get_by_text("local_in_process", exact=True).first).to_be_visible()
        expect(page.get_by_text(re.compile(r"local semantic \d+\.\d+"), exact=True).first).to_be_visible()

        page.get_by_label("Evidence search query").fill("qzxvplmnonexistent987654321")
        with page.expect_response(
            lambda response: "/api/v1/claims/" in response.url
            and response.url.endswith("/evidence-search")
            and response.request.method == "POST"
        ) as no_evidence_response_info:
            page.get_by_role("button", name="Search evidence").click()
        no_evidence_response = no_evidence_response_info.value
        if not no_evidence_response.ok:
            raise AssertionError(f"No-evidence search failed: HTTP {no_evidence_response.status}")
        expect(page.get_by_role("heading", name="No sufficient evidence found")).to_be_visible()
        expect(page.get_by_text(re.compile(r"has not generated or inferred an answer"))).to_be_visible()

        page.goto(f"{BASE_URL}{claim_href}", wait_until="networkidle")
        page.get_by_role("link", name="Open Claim Q&A").click()
        expect(page.get_by_role("heading", name="Claim Q&A")).to_be_visible()
        expect(page.get_by_text(re.compile(r"Extractive/private only"))).to_be_visible()
        page.get_by_label("Claim Q&A retrieval mode").select_option("hybrid")
        page.get_by_label("Claim Q&A question").fill(
            "What were the turbocharger operating hours before casualty?"
        )
        with page.expect_response(
            lambda response: "/api/v1/claims/" in response.url
            and response.url.endswith("/evidence-search/qa")
            and response.request.method == "POST"
        ) as qa_response_info:
            page.get_by_role("button", name="Ask claim file").click()
        qa_response = qa_response_info.value
        if not qa_response.ok:
            raise AssertionError(f"Claim Q&A failed: HTTP {qa_response.status}")
        qa_payload = qa_response.json()
        if qa_payload.get("status") != "answered":
            raise AssertionError(f"Claim Q&A did not produce a grounded answer: {qa_payload.get('status')}")
        if qa_payload.get("semantic_provider") != "local_in_process":
            raise AssertionError("Claim Q&A did not preserve the private local semantic provider")
        if qa_payload.get("claim_facts_updated") is not False:
            raise AssertionError("Claim Q&A reported an authoritative ClaimFact mutation")
        if not qa_payload.get("statements"):
            raise AssertionError("Claim Q&A returned no source-linked statements")
        if not all(statement.get("source_refs") for statement in qa_payload["statements"]):
            raise AssertionError("Claim Q&A returned an unsupported statement without source refs")
        expect(page.get_by_role("heading", name="Source-cited answer")).to_be_visible()
        expect(page.locator('section[aria-label="Claim Q&A source statements"] article').first).to_be_visible()
        expect(page.get_by_role("button", name="Download source").first).to_be_visible()
        expect(page.get_by_text("local_in_process", exact=True).first).to_be_visible()

        page.get_by_label("Claim Q&A question").fill("qzxvplmnonexistent987654321")
        with page.expect_response(
            lambda response: "/api/v1/claims/" in response.url
            and response.url.endswith("/evidence-search/qa")
            and response.request.method == "POST"
        ) as qa_no_evidence_info:
            page.get_by_role("button", name="Ask claim file").click()
        qa_no_evidence = qa_no_evidence_info.value
        if not qa_no_evidence.ok:
            raise AssertionError(f"Claim Q&A no-evidence path failed: HTTP {qa_no_evidence.status}")
        qa_no_evidence_payload = qa_no_evidence.json()
        if qa_no_evidence_payload.get("status") != "insufficient_evidence":
            raise AssertionError("Claim Q&A no-evidence path did not fail closed")
        if qa_no_evidence_payload.get("statements"):
            raise AssertionError("Claim Q&A invented statements for the no-evidence path")
        expect(page.get_by_role("heading", name="No sufficient evidence found")).to_be_visible()

        page.goto(f"{BASE_URL}{claim_href}", wait_until="networkidle")
        page.get_by_role("link", name="Open Recovery & Time-bar").click()
        expect(page.get_by_role("heading", name="Recovery & Time-bar Intelligence")).to_be_visible()
        expect(page.get_by_text(re.compile(r"Human/legal verification required"))).to_be_visible()
        with page.expect_response(
            lambda response: "/api/v1/claims/" in response.url
            and response.url.endswith("/recovery-timebar/build")
            and response.request.method == "POST"
        ) as recovery_response_info:
            page.get_by_role("button", name=re.compile(r"Build analysis|Refresh analysis")).click()
        recovery_response = recovery_response_info.value
        if not recovery_response.ok:
            raise AssertionError(f"Recovery/time-bar analysis failed: HTTP {recovery_response.status}")
        expect(page.get_by_text("Recovery status", exact=True)).to_be_visible()
        expect(page.get_by_text("Time-bar status", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="Evaluations")).to_be_visible()
        expect(page.get_by_text("recovery", exact=True).first).to_be_visible()
        expect(page.get_by_text("timebar", exact=True).first).to_be_visible()

        page.goto(f"{BASE_URL}{claim_href}", wait_until="networkidle")
        page.get_by_role("link", name="Open Severity & Reserve Support").click()
        expect(page.get_by_role("heading", name="Severity & Reserve Support")).to_be_visible()
        expect(page.get_by_text(re.compile(r"Human reserve authority required"))).to_be_visible()
        with page.expect_response(
            lambda response: "/api/v1/claims/" in response.url
            and response.url.endswith("/severity-reserve/build")
            and response.request.method == "POST"
        ) as support_response_info:
            page.get_by_role("button", name=re.compile(r"Build support|Refresh support")).click()
        support_response = support_response_info.value
        if not support_response.ok:
            raise AssertionError(f"Severity/reserve support failed: HTTP {support_response.status}")
        expect(page.get_by_text("Handling severity", exact=True)).to_be_visible()
        expect(page.get_by_text("Candidate range", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="Evaluations")).to_be_visible()
        expect(page.get_by_text(re.compile(r"no “Set reserve automatically” action"))).to_be_visible()

        page.goto(f"{BASE_URL}{claim_href}/intelligence", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Source-linked claim intelligence")).to_be_visible()
        expect(page.get_by_text("Phase 12D · read-only adjunct", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="Severity & Reserve Support")).to_be_visible()
        expect(page.get_by_role("link", name="Open support workspace")).to_be_visible()

        page.goto(f"{BASE_URL}{claim_href}", wait_until="networkidle")
        page.get_by_role("link", name="Open requirements").click()
        expect(page.get_by_role("heading", name="Marine rule evaluations")).to_be_visible()
        with page.expect_response(
            lambda response: "/api/v1/claims/" in response.url
            and response.url.endswith("/rules/evaluate")
            and response.request.method == "POST"
        ) as rules_response_info:
            page.get_by_role("button", name="Refresh rules").click()
        rules_response = rules_response_info.value
        if not rules_response.ok:
            raise AssertionError(f"Marine rule evaluation failed: HTTP {rules_response.status}")
        expect(page.get_by_text(re.compile(r"^Registry 12B\.\d+\.\d+$"), exact=True)).to_be_visible()
        expect(page.get_by_text(re.compile(r"^triggered: \d+$"), exact=True)).to_be_visible()
        review_button = page.get_by_role("button", name=re.compile(r"Review rule|Add disposition")).first
        if review_button.count() == 0:
            details = page.locator("details").filter(has_text=re.compile(r"not-triggered / not-applicable evaluations"))
            if details.count() > 0:
                details.locator("summary").click()
                review_button = page.get_by_role("button", name=re.compile(r"Review rule|Add disposition")).first
        expect(review_button).to_be_visible()
        review_button.click()
        expect(page.get_by_text("Disposition", exact=True).first).to_be_visible()
        expect(page.get_by_text(re.compile(r"append-only and linked to this exact evaluation hash"))).to_be_visible()

        page.goto(f"{BASE_URL}{claim_href}", wait_until="networkidle")
        page.get_by_role("link", name="Open claim-pack exports").click()
        expect(page.get_by_role("heading", name="Claim Pack Export")).to_be_visible()
        page.get_by_role(
            "checkbox",
            name=re.compile(r"I understand this export is a review aid"),
        ).check()
        with page.expect_response(
            lambda response: "/api/v1/claims/" in response.url
            and "/claim-pack-exports" in response.url
            and response.request.method == "POST"
        ) as export_response_info:
            page.get_by_role("button", name="Generate PDF").click()
        export_response = export_response_info.value
        if not export_response.ok:
            raise AssertionError(
                f"Claim-pack generation failed: HTTP {export_response.status}"
            )
        expect(page.get_by_text(re.compile(r"PDF snapshot generated"))).to_be_visible()
        with page.expect_download() as download_info:
            page.get_by_role("button", name="Download").first.click()
        if not download_info.value.suggested_filename.endswith(".pdf"):
            raise AssertionError("Claim-pack download did not return a PDF filename")

        page.goto(f"{BASE_URL}{claim_href}", wait_until="networkidle")
        with page.expect_response(
            lambda response: "/api/v1/ai-review/groups?" in response.url
            and response.request.method == "GET"
        ) as review_response_info:
            page.get_by_role("link", name="Open AI review queue").click()
        review_response = review_response_info.value
        if not review_response.ok:
            raise AssertionError(
                f"AI review groups request failed: HTTP {review_response.status}"
            )
        expect(page.get_by_role("heading", name="AI Review")).to_be_visible()
        expect(page.get_by_text("Loading review queue…", exact=True)).to_be_hidden()
        expect(
            page.get_by_text(
                re.compile(r"\d+ review groups? · \d+ need attention"),
                exact=True,
            )
        ).to_be_visible()

        page.screenshot(path=str(SCREENSHOT), full_page=True)
        browser.close()

    print("Design-partner browser E2E passed.")
    print(f"Screenshot: {SCREENSHOT}")


if __name__ == "__main__":
    main()
