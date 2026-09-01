"""Focused browser coverage for Phase 12G governed Claim Q&A controls."""
from __future__ import annotations

import json
import os

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
        page = browser.new_page(viewport={"width": 1440, "height": 1000})

        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")

        page.goto(f"{BASE_URL}/claims", wait_until="networkidle")
        page.get_by_placeholder("Search claim, vessel or IMO…").fill("MCRI-DEMO-MT-ORION")
        page.get_by_role("button", name="Apply filters").click()
        claim_link = page.locator('a[href^="/claims/"]').filter(has_text="MCRI-HM-").first
        expect(claim_link).to_be_visible()
        claim_href = claim_link.get_attribute("href")
        if not claim_href:
            raise AssertionError("Demo claim link did not expose an href")
        claim_id = claim_href.rstrip("/").split("/")[-1]

        page.goto(f"{BASE_URL}{claim_href}", wait_until="networkidle")
        page.get_by_role("link", name="Open Claim Q&A").click()
        expect(page.get_by_role("heading", name="Claim Q&A")).to_be_visible()
        page.get_by_label("Claim Q&A answer mode").select_option("governed_synthesis")
        expect(page.get_by_text("Governed synthesis requested.", exact=False)).to_be_visible()
        page.get_by_label("Claim Q&A retrieval mode").select_option("hybrid")

        # Browser-level synthetic authorized state: backend gateway execution is separately
        # covered by API integration tests using a fake provider behind the real gateway.
        # This route verifies that the UI renders the successful governed lineage/source state
        # without introducing a test provider or test bypass into production application code.
        synth_route = "**/evidence-search/qa/synthesize"
        synthetic_source_id = "11111111-1111-1111-1111-111111111111"
        synthetic_payload = {
            "claim_id": claim_id,
            "status": "answered",
            "answer": "The engine log records 14,250 turbocharger running hours before casualty.",
            "statements": [
                {
                    "statement_number": 1,
                    "text": "The engine log records 14,250 turbocharger running hours before casualty.",
                    "source_refs": [
                        {
                            "search_unit_id": synthetic_source_id,
                            "segment_id": "22222222-2222-2222-2222-222222222222",
                            "document_id": "33333333-3333-3333-3333-333333333333",
                            "extraction_id": "44444444-4444-4444-4444-444444444444",
                            "document_family_id": "55555555-5555-5555-5555-555555555555",
                            "document_filename": "Synthetic_Engine_Log.txt",
                            "document_type": "engine_log",
                            "document_version": 1,
                            "is_current_document": True,
                            "locator_type": "page",
                            "locator_value": "9",
                            "confidentiality_level": "internal",
                            "source_file_hash": "1" * 64,
                            "extraction_text_hash": "2" * 64,
                            "normalized_text_hash": "3" * 64,
                            "search_unit_hash": "4" * 64,
                        }
                    ],
                    "statement_hash": "5" * 64,
                }
            ],
            "conflicts": [],
            "missing_evidence": [],
            "retrieval_run_id": "66666666-6666-6666-6666-666666666666",
            "retrieval_mode": "hybrid",
            "ranking_version": "12E.1",
            "question_hash": "6" * 64,
            "result_set_hash": "7" * 64,
            "semantic_used": True,
            "semantic_provider": "local_in_process",
            "semantic_model": "local semantic 1.0",
            "semantic_authorization_hash": "8" * 64,
            "answer_engine_version": "12G.1",
            "answer_hash": "9" * 64,
            "non_authoritative": True,
            "human_review_required": True,
            "claim_facts_updated": False,
            "disclaimer": "Synthetic E2E response: human review required; no authoritative claim decision.",
            "synthesis_requested": True,
            "synthesis_used": True,
            "synthesis_run_id": "77777777-7777-7777-7777-777777777777",
            "synthesis_failure_code": None,
            "fallback_used": False,
            "production_authorization_id": "88888888-8888-8888-8888-888888888888",
            "provider": "openai",
            "model": "synthetic-governed-model",
            "prompt_bundle_version": "qa-prompt-v1",
            "schema_bundle_version": "qa-schema-v1",
            "authorization_hash": "a" * 64,
            "input_hash": "b" * 64,
            "output_hash": "c" * 64,
            "synthesis_engine_version": "12G.1",
        }

        def fulfill_authorized(route) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                headers={
                    "Access-Control-Allow-Origin": BASE_URL,
                    "Access-Control-Allow-Credentials": "true",
                },
                body=json.dumps(synthetic_payload),
            )

        page.route(synth_route, fulfill_authorized)
        page.get_by_label("Claim Q&A question").fill(
            "What were the turbocharger operating hours before casualty?"
        )
        with page.expect_response(
            lambda response: response.url.endswith("/evidence-search/qa/synthesize")
            and response.request.method == "POST"
        ) as authorized_response_info:
            page.get_by_role("button", name="Ask with governed synthesis").click()
        authorized_response = authorized_response_info.value
        if not authorized_response.ok:
            raise AssertionError(f"Synthetic authorized governed Claim Q&A failed: HTTP {authorized_response.status}")
        expect(page.get_by_text("Governed synthesis verified.", exact=True)).to_be_visible()
        expect(page.get_by_text("provider openai", exact=True)).to_be_visible()
        expect(page.get_by_text("model synthetic-governed-model", exact=True)).to_be_visible()
        expect(page.locator('section[aria-label="Claim Q&A source statements"] article').first).to_be_visible()
        expect(page.get_by_text("Synthetic_Engine_Log.txt", exact=True)).to_be_visible()

        # Remove the browser mock and hit the real CI backend. AI_PROVIDER=disabled and no
        # Production-wide authorization mean the server must make zero external calls and
        # safely return the Phase 12F extractive answer.
        page.unroute(synth_route)
        page.get_by_label("Claim Q&A question").fill(
            "What were the turbocharger operating hours before casualty?"
        )
        with page.expect_response(
            lambda response: response.url.endswith("/evidence-search/qa/synthesize")
            and response.request.method == "POST"
        ) as blocked_response_info:
            page.get_by_role("button", name="Ask with governed synthesis").click()
        blocked_response = blocked_response_info.value
        if not blocked_response.ok:
            raise AssertionError(f"Governed Claim Q&A fallback failed: HTTP {blocked_response.status}")
        payload = blocked_response.json()
        if payload.get("synthesis_used") is not False:
            raise AssertionError("CI environment unexpectedly executed governed external synthesis")
        if payload.get("fallback_used") is not True:
            raise AssertionError("Governed synthesis did not preserve the safe extractive fallback")
        if payload.get("claim_facts_updated") is not False:
            raise AssertionError("Governed Q&A reported an authoritative ClaimFact mutation")
        if payload.get("provider") is not None:
            raise AssertionError("Blocked/bypassed CI synthesis unexpectedly recorded an external provider")

        expect(page.locator('section[aria-label="Governed synthesis status"]')).to_be_visible()
        expect(page.get_by_text("Governed synthesis not used — extractive fallback returned.", exact=True)).to_be_visible()
        expect(page.locator('section[aria-label="Claim Q&A source statements"] article').first).to_be_visible()

        browser.close()

    print("Governed Claim Q&A browser E2E passed.")


if __name__ == "__main__":
    main()
