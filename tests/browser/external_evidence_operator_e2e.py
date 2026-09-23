"""Phase 17.5-AK browser coverage for the separated external-Evidence operator sequence."""
from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import UTC, datetime

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")

PROFILE_ID = "11111111-1111-1111-1111-111111111111"
BINDING_ID = "22222222-2222-2222-2222-222222222222"
CLAIM_ID = "33333333-3333-3333-3333-333333333333"
FAMILY_ID = "44444444-4444-4444-4444-444444444444"
DOC_V1 = "55555555-5555-5555-5555-555555555555"
DOC_V2 = "66666666-6666-6666-6666-666666666666"
HANDOFF_ID = "77777777-7777-7777-7777-777777777777"
REFRESH_AUTH_ID = "88888888-8888-8888-8888-888888888888"
REFRESH_EXEC_ID = "99999999-9999-9999-9999-999999999999"
ADMISSION_AUTH_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ADMISSION_EXEC_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    now = datetime.now(UTC).isoformat()
    state = {
        "profiles": [
            {
                "profile_id": PROFILE_ID,
                "provider_kind": "sharepoint",
                "display_name": "AK SharePoint fixture",
                "profile_status": "active",
                "provider_health_status": "healthy",
                "provider_health_latency_class": "fast",
                "provider_health_completed_at": now,
                "active_family_count": 1,
                "pending_handoff_count": 1,
                "processing_release_required_count": 1,
                "next_due_at": now,
                "last_observation_completed_at": now,
            }
        ],
        "families": [
            {
                "binding_id": BINDING_ID,
                "claim_id": CLAIM_ID,
                "profile_id": PROFILE_ID,
                "provider_kind": "sharepoint",
                "document_family_id": FAMILY_ID,
                "current_document_id": DOC_V1,
                "current_version_number": 1,
                "version_history": [
                    {
                        "document_id": DOC_V1,
                        "version_number": 1,
                        "is_current": True,
                        "processing_status": "completed",
                        "created_at": now,
                        "superseded_at": None,
                        "processing_release_status": "active",
                        "processing_release_required": False,
                    }
                ],
                "schedule_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                "schedule_status": "active",
                "next_due_at": now,
                "last_observation_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                "last_observation_result": "changed",
                "last_observation_completed_at": now,
                "pending_handoff_id": HANDOFF_ID,
                "pending_handoff_kind": "changed",
                "pending_handoff_projected_at": now,
                "latest_decision_id": None,
                "latest_decision_kind": None,
                "latest_decision_status": None,
                "latest_decided_at": None,
                "refresh_authorization_id": None,
                "refresh_authorization_status": None,
                "refresh_execution_required": False,
                "latest_refresh_execution_id": None,
                "latest_refresh_status": None,
                "latest_refresh_completed_at": None,
                "latest_refresh_failure_code": None,
                "latest_refresh_failed_at": None,
                "latest_admission_authorization_id": None,
                "latest_admission_authorization_status": None,
                "admission_authorization_required": False,
                "latest_admission_execution_id": None,
                "admission_execution_required": False,
                "latest_admission_status": None,
                "latest_admission_executed_at": None,
                "processing_release_status": None,
                "processing_release_required": True,
            }
        ],
    }
    mutations: list[tuple[str, dict]] = []

    def family() -> dict:
        return state["families"][0]

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1800, "height": 1200})

        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")

        def route_external_evidence(route) -> None:
            request = route.request
            url = request.url
            if request.method == "GET" and url.endswith("/external-document-sources/operator-overview"):
                route.fulfill(status=200, content_type="application/json", body=json.dumps(state))
                return

            if request.method != "POST":
                route.fallback()
                return

            payload = json.loads(request.post_data or "{}")
            mutations.append((url, deepcopy(payload)))
            assert len(payload.get("reason", "")) >= 20, "Governed action must carry an explicit human reason"
            assert str(payload.get("request_key", "")).startswith("ak-"), "AK action must use a unique request key"

            row = family()
            if url.endswith(f"/observation-review-handoffs/{HANDOFF_ID}/decisions"):
                assert payload["decision_kind"] == "approve_refresh"
                row["pending_handoff_id"] = None
                row["pending_handoff_kind"] = None
                row["latest_decision_id"] = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
                row["latest_decision_kind"] = "approve_refresh"
                row["latest_decision_status"] = "refresh_authorized"
                row["latest_decided_at"] = now
                row["refresh_authorization_id"] = REFRESH_AUTH_ID
                row["refresh_authorization_status"] = "authorized"
                row["refresh_execution_required"] = True
                row["admission_authorization_required"] = False
                row["admission_execution_required"] = False
                state["profiles"][0]["pending_handoff_count"] = 0
                route.fulfill(status=201, content_type="application/json", body="{}")
                return

            if url.endswith(f"/observation-refresh-authorizations/{REFRESH_AUTH_ID}/execute"):
                row["latest_refresh_execution_id"] = REFRESH_EXEC_ID
                row["latest_refresh_status"] = "staged_refresh_verified"
                row["latest_refresh_completed_at"] = now
                row["refresh_execution_required"] = False
                row["admission_authorization_required"] = True
                route.fulfill(status=201, content_type="application/json", body="{}")
                return

            if url.endswith(f"/observation-refresh-executions/{REFRESH_EXEC_ID}/admission-authorizations"):
                row["latest_admission_authorization_id"] = ADMISSION_AUTH_ID
                row["latest_admission_authorization_status"] = "authorized"
                row["admission_authorization_required"] = False
                row["admission_execution_required"] = True
                route.fulfill(status=201, content_type="application/json", body="{}")
                return

            if url.endswith(
                f"/evidence-family-bindings/{BINDING_ID}/observation-refresh-admissions/{ADMISSION_AUTH_ID}"
            ):
                row["latest_admission_execution_id"] = ADMISSION_EXEC_ID
                row["latest_admission_status"] = "admitted"
                row["latest_admission_executed_at"] = now
                row["admission_execution_required"] = False
                row["current_document_id"] = DOC_V2
                row["current_version_number"] = 2
                row["version_history"] = [
                    {
                        "document_id": DOC_V1,
                        "version_number": 1,
                        "is_current": False,
                        "processing_status": "completed",
                        "created_at": now,
                        "superseded_at": now,
                        "processing_release_status": "active",
                        "processing_release_required": False,
                    },
                    {
                        "document_id": DOC_V2,
                        "version_number": 2,
                        "is_current": True,
                        "processing_status": "pending",
                        "created_at": now,
                        "superseded_at": None,
                        "processing_release_status": None,
                        "processing_release_required": True,
                    },
                ]
                route.fulfill(status=201, content_type="application/json", body="{}")
                return

            raise AssertionError(f"Unexpected external Evidence mutation: {request.method} {url}")

        page.route("**/api/v1/external-document-sources/**", route_external_evidence)
        page.goto(f"{BASE_URL}/external-evidence", wait_until="networkidle")

        expect(page.get_by_role("heading", name="SharePoint & Google Drive operations")).to_be_visible()
        expect(page.get_by_text("AG human decision required", exact=True)).to_be_visible()
        expect(page.get_by_text("v1 · current · released", exact=True)).to_be_visible()

        note = page.get_by_label("Human reason / audit note")
        note.fill("Human reviewer verified the exact changed source version and lineage.")

        page.get_by_role("button", name="AG · Approve refresh").click()
        expect(page.get_by_role("button", name="AH · Read & stage exact refresh")).to_be_visible()

        page.get_by_role("button", name="AH · Read & stage exact refresh").click()
        expect(page.get_by_role("button", name="AI · Authorize exact admission")).to_be_visible()
        expect(page.get_by_text("does not execute external artificial intelligence.", exact=False)).to_be_visible()

        page.get_by_role("button", name="AI · Authorize exact admission").click()
        expect(page.get_by_role("button", name="AJ · Admit canonical N+1")).to_be_visible()

        page.get_by_role("button", name="AJ · Admit canonical N+1").click()
        expect(page.get_by_text("Current v2", exact=True)).to_be_visible()
        expect(page.get_by_text("v1 · historical · released", exact=True)).to_be_visible()
        expect(page.get_by_text("v2 · current · Phase-Z required", exact=True)).to_be_visible()
        expect(page.get_by_text("Phase-Z required", exact=True).last).to_be_visible()

        assert len(mutations) == 4, f"Expected four separated governed mutations, got {mutations}"
        assert "/decisions" in mutations[0][0]
        assert "/execute" in mutations[1][0]
        assert "/admission-authorizations" in mutations[2][0]
        assert "/observation-refresh-admissions/" in mutations[3][0]

        browser.close()

    print("External Evidence operator browser E2E passed.")


if __name__ == "__main__":
    main()
