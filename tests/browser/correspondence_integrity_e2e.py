"""Phase 13.9A real MT ORION correspondence state/review/dispatch integrity acceptance."""
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


def _expected(item: dict) -> dict:
    return {
        "expected_state_fingerprint": item["state_fingerprint"],
        "expected_state_version": item["state_version"],
    }


def _claim_id(page) -> str:
    page.goto(f"{BASE_URL}/claims", wait_until="networkidle")
    page.get_by_placeholder("Search claim, vessel or IMO…").fill("MCRI-DEMO-MT-ORION")
    page.get_by_role("button", name="Apply filters").click()
    row = page.get_by_role("row").filter(has_text="MT ORION").filter(has_text="MCRI-DEMO-MT-ORION")
    expect(row).to_have_count(1)
    link = row.locator('a[href^="/claims/"]').filter(has_text=re.compile(r"^MCRI-HM-"))
    expect(link).to_have_count(1)
    href = link.get_attribute("href")
    if not href:
        raise AssertionError("Expected MT ORION claim href")
    return href.rstrip("/").split("/")[-1]


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    suffix = uuid4().hex[:8]
    subject = f"13.9A MT ORION governed correspondence {suffix}"
    revised_body = (
        "Dear Sirs,\n\n"
        "Phase 13.9A revised factual wording after deliberate operator review. "
        "No substantive claim outcome is determined by this communication record.\n\n"
        "Kind regards,"
    )
    review_note = "Manager reviewed the exact revised wording, recipient and sensitivity for 13.9A acceptance."
    external_reference = f"MCRI-13.9A-{suffix}"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1500, "height": 1200})
        page = context.new_page()
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")

        claim_id = _claim_id(page)
        request = context.request

        created = _json(
            request.post(
                f"{API_URL}/api/v1/claims/{claim_id}/correspondence",
                data={
                    "direction": "outbound",
                    "kind": "status_update",
                    "sensitivity": "standard",
                    "recipient_label": "Owners and Lead Underwriter",
                    "subject": subject,
                    "body": "Dear Sirs,\n\nPhase 13.9A initial factual wording.\n\nKind regards,",
                },
            ),
            "create governed correspondence",
        )
        if created["state_version"] != 1 or len(created["state_fingerprint"]) != 64:
            raise AssertionError("New correspondence was not bound to initial state identity")
        stale_state = dict(created)

        revised = _json(
            request.patch(
                f"{API_URL}/api/v1/claims/{claim_id}/correspondence/{created['id']}",
                data={"body": revised_body, **_expected(created)},
            ),
            "revise governed correspondence",
        )
        if revised["state_version"] != 2 or revised["state_fingerprint"] == created["state_fingerprint"]:
            raise AssertionError("Material correspondence revision did not advance state identity")

        stale_submit = request.post(
            f"{API_URL}/api/v1/claims/{claim_id}/correspondence/{created['id']}/submit",
            data=_expected(stale_state),
        )
        if stale_submit.status != 409:
            raise AssertionError(
                f"Expected stale correspondence submit to fail 409, got {stale_submit.status}: {stale_submit.text()}"
            )

        submitted = _json(
            request.post(
                f"{API_URL}/api/v1/claims/{claim_id}/correspondence/{created['id']}/submit",
                data=_expected(revised),
            ),
            "submit current correspondence",
        )
        approved = _json(
            request.post(
                f"{API_URL}/api/v1/claims/{claim_id}/correspondence/{created['id']}/approve",
                data={"note": review_note, "confirm_re_review": False, **_expected(submitted)},
            ),
            "approve current correspondence",
        )
        if approved["review_state"] != "current" or len(approved["review_history"]) != 1:
            raise AssertionError("Expected one current append-only correspondence approval")
        approval_hash = approved["latest_review"]["review_hash"]
        if approved["latest_review"]["content_hash"] != approved["content_hash"]:
            raise AssertionError("Approved review is not bound to the approved content hash")

        replay = _json(
            request.post(
                f"{API_URL}/api/v1/claims/{claim_id}/correspondence/{created['id']}/approve",
                data={"note": review_note, "confirm_re_review": False, **_expected(submitted)},
            ),
            "replay exact correspondence approval",
        )
        if len(replay["review_history"]) != 1 or replay["latest_review"]["review_hash"] != approval_hash:
            raise AssertionError("Exact approval retry created duplicate or changed review lineage")

        wrong_dispatch = request.post(
            f"{API_URL}/api/v1/claims/{claim_id}/correspondence/{created['id']}/mark-sent",
            data={
                "confirm_sent": True,
                "channel": "email",
                "external_reference": external_reference,
                "expected_review_hash": "f" * 64,
                **_expected(approved),
            },
        )
        if wrong_dispatch.status != 409:
            raise AssertionError(
                f"Expected wrong approval hash dispatch to fail 409, got {wrong_dispatch.status}: {wrong_dispatch.text()}"
            )

        dispatch_payload = {
            "confirm_sent": True,
            "channel": "email",
            "external_reference": external_reference,
            "expected_review_hash": approval_hash,
            **_expected(approved),
        }
        sent = _json(
            request.post(
                f"{API_URL}/api/v1/claims/{claim_id}/correspondence/{created['id']}/mark-sent",
                data=dispatch_payload,
            ),
            "record exact approved external dispatch",
        )
        if sent["sent_review_hash"] != approval_hash or sent["status"] != "sent_externally":
            raise AssertionError("External dispatch was not bound to the exact approved review")

        sent_replay = _json(
            request.post(
                f"{API_URL}/api/v1/claims/{claim_id}/correspondence/{created['id']}/mark-sent",
                data=dispatch_payload,
            ),
            "replay exact external dispatch",
        )
        if sent_replay["sent_at"] != sent["sent_at"]:
            raise AssertionError("Exact dispatch replay changed the historical dispatch timestamp")

        page.goto(f"{BASE_URL}/claims/{claim_id}/correspondence", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Correspondence Centre")).to_be_visible(timeout=15_000)
        record_button = page.locator("button").filter(has_text=subject).first
        expect(record_button).to_be_visible(timeout=15_000)
        record_button.click()
        expect(page.get_by_role("heading", name=subject)).to_be_visible(timeout=15_000)
        expect(page.get_by_text(re.compile(r"state v2 .* review current"))).to_be_visible(timeout=15_000)
        expect(page.get_by_text(external_reference, exact=False)).to_be_visible(timeout=15_000)
        expect(page.get_by_text("The platform did not send this message.", exact=True)).to_be_visible(timeout=15_000)

        browser.close()


if __name__ == "__main__":
    main()
