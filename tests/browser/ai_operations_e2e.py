"""Focused browser coverage for Phase 12H content-free AI Operations."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")


def _event(event_id: str, workflow: str, *, status: str, failure_code=None, attention=False, review_state="not_applicable") -> dict:
    return {
        "id": event_id,
        "workflow_type": workflow,
        "event_time": datetime.now(UTC).isoformat(),
        "claim_id": "11111111-1111-1111-1111-111111111111",
        "document_id": "22222222-2222-2222-2222-222222222222" if workflow == "document_processing" else None,
        "document_type": "chief_engineer_report" if workflow == "document_processing" else None,
        "authorization_id": "33333333-3333-3333-3333-333333333333",
        "authorization_hash": "a" * 64,
        "eligibility_decision_id": "44444444-4444-4444-4444-444444444444" if workflow == "document_processing" else None,
        "eligibility_policy_hash": "b" * 64,
        "eligibility_decision_hash": "c" * 64 if workflow == "document_processing" else None,
        "status": status,
        "failure_code": failure_code,
        "fallback_used": workflow == "claim_qa_synthesis" and attention,
        "provider_call_made": workflow == "claim_qa_synthesis" or review_state == "completed",
        "provider": "openai" if workflow == "claim_qa_synthesis" else None,
        "model": "synthetic-governed-model",
        "prompt_bundle_version": "prompt-v1",
        "schema_bundle_version": "schema-v1",
        "human_review_state": review_state,
        "human_review_action": None,
        "requested_by_id": "55555555-5555-5555-5555-555555555555",
        "reviewed_by_id": None,
        "run_hash": "d" * 64 if workflow == "document_processing" else None,
        "review_hash": None,
        "retrieval_run_id": "66666666-6666-6666-6666-666666666666" if workflow == "claim_qa_synthesis" else None,
        "question_hash": "e" * 64 if workflow == "claim_qa_synthesis" else None,
        "result_set_hash": "f" * 64 if workflow == "claim_qa_synthesis" else None,
        "input_hash": "1" * 64 if workflow == "claim_qa_synthesis" else None,
        "output_hash": "2" * 64 if workflow == "claim_qa_synthesis" else None,
        "answer_hash": "3" * 64 if workflow == "claim_qa_synthesis" else None,
        "source_count": 3 if workflow == "claim_qa_synthesis" else None,
        "output_candidate_count": None,
        "human_edit_count": None,
        "unsupported_output_count": None,
        "source_grounded_output_count": None,
        "source_grounding_total_count": None,
        "input_chars": 600 if workflow == "claim_qa_synthesis" else None,
        "input_tokens": 100 if workflow == "claim_qa_synthesis" else None,
        "output_tokens": 20 if workflow == "claim_qa_synthesis" else None,
        "total_tokens": 120 if workflow == "claim_qa_synthesis" else None,
        "latency_ms": 1100,
        "observed_provider_cost_microusd": None,
        "requires_attention": attention,
        "attention_reasons": [failure_code or "pending_different_human_review"] if attention else [],
        "content_free": True,
    }


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    document_event = _event(
        "77777777-7777-7777-7777-777777777777",
        "document_processing",
        status="queued",
        attention=True,
        review_state="pending",
    )
    synthesis_event = _event(
        "88888888-8888-8888-8888-888888888888",
        "claim_qa_synthesis",
        status="verification_failed",
        failure_code="grounding_verification_failed",
        attention=True,
    )
    all_events = [synthesis_event, document_event]
    dashboard = {
        "metrics": {
            "event_count": 2,
            "document_processing_count": 1,
            "claim_qa_synthesis_count": 1,
            "provider_run_count": 1,
            "blocked_or_fallback_count": 1,
            "verification_failure_count": 1,
            "authorization_or_policy_block_count": 0,
            "pending_human_review_count": 1,
            "approve_count": 0,
            "edit_count": 0,
            "reject_count": 0,
            "unsupported_output_count": 0,
            "source_grounding_validity_bps": None,
            "total_tokens": 120,
            "total_observed_provider_cost_microusd": 0,
            "mean_latency_ms": 1100,
            "p95_latency_ms": 1100,
            "requires_attention_count": 2,
            "failures_by_workflow": {"claim_qa_synthesis": 1},
            "failures_by_model": {"synthetic-governed-model": 1},
        },
        "recent_attention": all_events,
        "content_free_governance_plane": True,
        "raw_claim_or_model_content_exposed": False,
    }

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1100})
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")

        def fulfill_dashboard(route) -> None:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(dashboard))

        def fulfill_events(route) -> None:
            query = parse_qs(urlparse(route.request.url).query)
            workflow = query.get("workflow_type", [None])[0]
            attention_only = query.get("requires_attention", [None])[0] == "true"
            rows = [item for item in all_events if not workflow or item["workflow_type"] == workflow]
            if attention_only:
                rows = [item for item in rows if item["requires_attention"]]
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "events": rows, "page": 1, "page_size": 50, "total": len(rows), "has_more": False,
            }))

        def fulfill_queue(route) -> None:
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "events": [document_event], "page": 1, "page_size": 20, "total": 1, "has_more": False,
            }))

        # Scope mocks to the API origin/path only. A broad **/ai-operations matcher also
        # intercepts the Next.js page navigation itself and replaces the HTML document with JSON.
        page.route("**/api/v1/ai-operations", fulfill_dashboard)
        page.route("**/api/v1/ai-operations/events?*", fulfill_events)
        page.route("**/api/v1/ai-operations/review-queue?*", fulfill_queue)
        page.goto(f"{BASE_URL}/ai-operations", wait_until="networkidle")

        expect(page.get_by_role("heading", name="AI Decision Log / AI Operations")).to_be_visible()
        expect(page.get_by_text("Content-free governance boundary:", exact=False)).to_be_visible()
        expect(page.get_by_text("grounding verification failed", exact=False)).to_be_visible()
        expect(page.get_by_text("Different-human review queue", exact=True)).to_be_visible()

        page.get_by_text("claim qa synthesis", exact=True).first.click()
        expect(page.get_by_text("Lineage drill-down", exact=True)).to_be_visible()
        expect(page.get_by_text("synthetic-governed-model", exact=True).first).to_be_visible()
        expect(page.get_by_text("Input hash", exact=True)).to_be_visible()
        expect(page.get_by_text("Output hash", exact=True)).to_be_visible()
        if page.get_by_text("SUPER_SECRET_RAW_QUESTION", exact=False).count() != 0:
            raise AssertionError("AI Operations rendered raw question content")

        page.get_by_text("chief engineer report", exact=True).first.click()
        expect(page.get_by_text("Complete existing different-human review", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="approve", exact=True)).to_be_visible()

        page.get_by_label("Workflow").select_option("claim_qa_synthesis")
        event_table = page.locator("table")
        expect(event_table.get_by_text("claim qa synthesis", exact=True)).to_be_visible()
        expect(event_table.get_by_text("chief engineer report", exact=True)).to_have_count(0)

        browser.close()

    print("AI Operations browser E2E passed.")


if __name__ == "__main__":
    main()
