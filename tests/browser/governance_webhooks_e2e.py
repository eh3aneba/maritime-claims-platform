"""Focused browser coverage for Phase 12I content-free signed governance integrations."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    now = datetime.now(UTC).isoformat()
    destination = {
        "id": "11111111-1111-1111-1111-111111111111",
        "organization_id": "22222222-2222-2222-2222-222222222222",
        "name": "Synthetic SIEM",
        "endpoint_url": "https://siem.example.com/mcri",
        "enabled": True,
        "event_types": ["ai_operations.claim_qa_synthesis"],
        "secret_version": 1,
        "secret_reference": "derived-hmac-sha256:synthetic:v1",
        "rotated_at": None,
        "previous_secret_valid_until": None,
        "last_tested_at": now,
        "last_test_status": "delivered",
        "created_at": now,
        "updated_at": now,
        "secret_material_persisted": False,
    }
    delivery = {
        "id": "33333333-3333-3333-3333-333333333333",
        "organization_id": destination["organization_id"],
        "destination_id": destination["id"],
        "source_workflow_type": "claim_qa_synthesis",
        "source_event_id": "44444444-4444-4444-4444-444444444444",
        "source_revision_hash": "a" * 64,
        "event_type": "ai_operations.claim_qa_synthesis",
        "envelope_version": "2026-09-01.1",
        "occurred_at": now,
        "envelope": {
            "content_free": True,
            "raw_claim_or_model_content_included": False,
            "inbound_command": False,
        },
        "payload_hash": "b" * 64,
        "secret_version": 1,
        "status": "delivered",
        "attempt_count": 1,
        "max_attempts": 6,
        "manual_retry_count": 0,
        "next_attempt_at": now,
        "last_attempt_at": now,
        "delivered_at": now,
        "last_http_status": 204,
        "last_error_code": None,
        "created_at": now,
        "updated_at": now,
        "content_free": True,
    }
    dashboard = {
        "metrics": {
            "destination_count": 1,
            "enabled_destination_count": 1,
            "queued_count": 0,
            "attempting_count": 0,
            "failed_count": 0,
            "delivered_count": 1,
            "dead_letter_count": 0,
            "delivery_success_bps": 10000,
        },
        "destinations": [destination],
        "recent_deliveries": [delivery],
        "content_free_outbound_only": True,
        "inbound_commands_enabled": False,
        "raw_claim_or_model_content_exposed": False,
    }
    issued = {
        "destination": {
            **destination,
            "id": "55555555-5555-5555-5555-555555555555",
            "name": "Primary SIEM",
        },
        "signing_secret": "ONE_TIME_SYNTHETIC_SIGNING_SECRET_1234567890",
        "secret_version": 1,
        "secret_reference": "derived-hmac-sha256:synthetic-new:v1",
        "disclosure": "Signing secret is shown once and is not persisted as raw secret material.",
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

        def route_governance(route) -> None:
            request = route.request
            path = request.url.split("?", 1)[0]
            if request.method == "GET" and path.endswith("/api/v1/governance-webhooks"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(dashboard))
                return
            if request.method == "POST" and path.endswith(
                "/api/v1/governance-webhooks/destinations"
            ):
                route.fulfill(status=201, content_type="application/json", body=json.dumps(issued))
                return
            route.continue_()

        page.route("**/api/v1/governance-webhooks**", route_governance)
        page.goto(f"{BASE_URL}/ai-integrations", wait_until="networkidle")

        expect(page.get_by_role("heading", name="AI Integrations / SIEM Webhooks")).to_be_visible()
        expect(page.get_by_text("Security boundary:", exact=False)).to_be_visible()
        expect(page.get_by_text("Synthetic SIEM", exact=True)).to_be_visible()
        expect(page.get_by_text("delivered", exact=True).first).to_be_visible()
        expect(page.get_by_text("raw claim/model content exposed: false", exact=False)).to_be_visible()
        if page.get_by_text("SUPER_SECRET_RAW_QUESTION", exact=False).count() != 0:
            raise AssertionError("AI Integrations rendered raw question content")

        page.get_by_role("button", name="Create destination").click()
        expect(page.get_by_text("One-time signing secret", exact=True)).to_be_visible()
        expect(
            page.get_by_text("ONE_TIME_SYNTHETIC_SIGNING_SECRET_1234567890", exact=True)
        ).to_be_visible()
        expect(page.get_by_text("Store this secret", exact=False)).to_be_visible()

        browser.close()

    print("Governance webhook browser E2E passed.")


if __name__ == "__main__":
    main()
