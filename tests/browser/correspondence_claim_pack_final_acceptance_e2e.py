"""Phase 13.9C final MT ORION Correspondence -> Claim Pack maturity acceptance."""
from __future__ import annotations

from io import BytesIO
import os
import re
import zipfile
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
    link = row.locator('a[href^="/claims/"]').filter(has_text=re.compile(r"^MCRI-HM-"))
    expect(link).to_have_count(1)
    href = link.get_attribute("href")
    if not href:
        raise AssertionError("Expected MT ORION claim href")
    return href.rstrip("/").split("/")[-1]


def _xlsx_xml_text(payload: bytes) -> str:
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        return "\n".join(
            archive.read(name).decode("utf-8", "replace")
            for name in archive.namelist()
            if name.endswith(".xml") or name.endswith(".rels")
        )


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    suffix = uuid4().hex[:8]
    subject = f"13.9C MT ORION final correspondence {suffix}"
    initial_body = f"Dear Sirs,\n\n13.9C initial governed MT ORION wording {suffix}.\n\nKind regards,"
    competing_body = f"Dear Sirs,\n\n13.9C competing server revision {suffix}.\n\nKind regards,"
    final_marker = f"13.9C final governed MT ORION wording {suffix}"
    final_body = f"Dear Sirs,\n\n{final_marker}.\n\nKind regards,"
    external_reference = f"MCRI-13.9C-{suffix}"
    mutations: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1500, "height": 1250})
        page = context.new_page()
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")

        claim_id = _claim_id(page)
        request = context.request
        page.goto(f"{BASE_URL}/claims/{claim_id}/correspondence", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Correspondence Centre")).to_be_visible(timeout=15_000)

        # 1) Create the real operator draft through the browser.
        page.get_by_label("Subject").first.fill(subject)
        page.get_by_label("Body").fill(initial_body)
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith(f"/claims/{claim_id}/correspondence")
        ) as created_info:
            page.get_by_role("button", name="Create draft").click()
        created = created_info.value.json()
        correspondence_id = created["id"]
        expect(page.get_by_role("heading", name=subject)).to_be_visible(timeout=15_000)
        expect(page.get_by_label("Draft body")).to_have_value(initial_body)

        def record_mutation(req) -> None:
            governed = "/correspondence" in req.url or "/claim-pack-exports" in req.url
            if governed and req.method not in {"GET", "HEAD", "OPTIONS"}:
                mutations.append(f"{req.method} {req.url}")

        page.on("request", record_mutation)

        # 2) Locale switching changes only the shell, never authored correspondence content.
        mutations.clear()
        selected_subject_en = page.get_by_label("Subject").last.input_value()
        selected_body_en = page.get_by_label("Draft body").input_value()
        selected_recipient_en = page.get_by_label("Recipient").last.input_value()
        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.locator("html")).to_have_attribute("lang", "fa")
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        assert page.get_by_label("موضوع").last.input_value() == selected_subject_en
        assert page.get_by_label("متن پیش‌نویس").input_value() == selected_body_en
        assert page.get_by_label("گیرنده").last.input_value() == selected_recipient_en
        page.get_by_role("button", name="EN", exact=True).click()
        expect(page.locator("html")).to_have_attribute("lang", "en")
        expect(page.locator("html")).to_have_attribute("dir", "ltr")
        assert mutations == [], f"Locale switch caused correspondence mutation: {mutations}"

        # 3) Submit and record the first exact human approval through the operator UI.
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith(f"/correspondence/{correspondence_id}/submit")
        ):
            page.get_by_role("button", name="Submit for manager review").click()
        expect(page.get_by_text("Manager decision", exact=True)).to_be_visible(timeout=15_000)
        page.get_by_placeholder("Record the factual, recipient and sensitivity review.").fill(
            "13.9C manager approval of the exact initial wording and recipient."
        )
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith(f"/correspondence/{correspondence_id}/approve")
        ) as first_approval_info:
            page.get_by_role("button", name="Approve wording").click()
        first_approved = first_approval_info.value.json()
        first_review_hash = first_approved["latest_review"]["review_hash"]
        expect(page.get_by_test_id("correspondence-review-lineage")).to_contain_text("Review #1")
        expect(page.get_by_text("Review matches current state", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Revise before dispatch")).to_be_visible()

        # 4) Create a real competing actor change while the browser still holds approved state v1.
        reopened = _json(
            request.post(
                f"{API_URL}/api/v1/claims/{claim_id}/correspondence/{correspondence_id}/revise",
                data={
                    "expected_state_fingerprint": first_approved["state_fingerprint"],
                    "expected_state_version": first_approved["state_version"],
                },
            ),
            "reopen approved correspondence from competing actor",
        )
        competing = _json(
            request.patch(
                f"{API_URL}/api/v1/claims/{claim_id}/correspondence/{correspondence_id}",
                data={
                    "body": competing_body,
                    "expected_state_fingerprint": reopened["state_fingerprint"],
                    "expected_state_version": reopened["state_version"],
                },
            ),
            "material competing correspondence revision",
        )
        if competing["state_version"] <= first_approved["state_version"]:
            raise AssertionError("Competing material revision did not advance correspondence state")

        # The stale browser action must fail closed, then the UI reloads current server state.
        page.get_by_role("button", name="Revise before dispatch").click()
        expect(page.get_by_text(re.compile(r"This view was stale or the governed state changed"))).to_be_visible(timeout=15_000)
        expect(page.get_by_label("Draft body")).to_have_value(competing_body, timeout=15_000)
        expect(page.get_by_text("Historical review — current state needs review", exact=True)).to_be_visible()
        expect(page.get_by_test_id("correspondence-review-lineage")).to_contain_text("Review #1")

        # 5) Deliberately revise the recovered current state and append an explicit re-review.
        page.get_by_label("Draft body").fill(final_body)
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith(f"/correspondence/{correspondence_id}/submit")
        ):
            page.get_by_role("button", name="Submit revised state for re-review").click()
        expect(page.get_by_text("Manager re-review decision", exact=True)).to_be_visible(timeout=15_000)
        page.get_by_placeholder("Record the factual, recipient and sensitivity review.").fill(
            "13.9C explicit manager re-review of the recovered final wording."
        )
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith(f"/correspondence/{correspondence_id}/approve")
        ) as second_approval_info:
            page.get_by_role("button", name="Approve wording").click()
        second_approved = second_approval_info.value.json()
        if len(second_approved["review_history"]) != 2:
            raise AssertionError("Expected two append-only correspondence reviews after deliberate re-review")
        if second_approved["latest_review"]["previous_review_hash"] != first_review_hash:
            raise AssertionError("Second correspondence review did not chain to the historical approval")
        if second_approved["latest_review"]["correspondence_state_fingerprint"] != second_approved["state_fingerprint"]:
            raise AssertionError("Second approval is not bound to the exact final correspondence state")
        expect(page.get_by_test_id("correspondence-review-lineage")).to_contain_text("Review #2")
        expect(page.get_by_text("Review matches current state", exact=True)).to_be_visible()

        # 6) Record only the exact approved external dispatch; the platform itself does not send.
        page.get_by_label("External reference").fill(external_reference)
        page.get_by_label("I confirm this exact approved correspondence was sent outside the platform.").check()
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith(f"/correspondence/{correspondence_id}/mark-sent")
        ) as sent_info:
            page.get_by_role("button", name="Mark Sent Externally").click()
        sent = sent_info.value.json()
        latest_review_hash = sent["latest_review"]["review_hash"]
        if sent["sent_review_hash"] != latest_review_hash:
            raise AssertionError("External dispatch record is not bound to the exact final approved review")
        expect(page.get_by_text("The platform did not send this message.", exact=False)).to_be_visible(timeout=15_000)
        expect(page.get_by_text(external_reference, exact=False)).to_be_visible()

        # Locale switching after dispatch must not alter the authored or dispatch record.
        mutations.clear()
        body_before_locale = page.locator("div.whitespace-pre-wrap").filter(has_text=final_marker).text_content()
        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(page.get_by_text(external_reference, exact=False)).to_be_visible()
        body_fa = page.locator("div.whitespace-pre-wrap").filter(has_text=final_marker).text_content()
        assert body_fa == body_before_locale
        page.get_by_role("button", name="EN", exact=True).click()
        expect(page.locator("html")).to_have_attribute("dir", "ltr")
        assert mutations == [], f"Locale switch after dispatch caused governed mutation: {mutations}"

        # 7) Claim Pack shell also localizes without mutation, then creates one immutable Excel snapshot.
        page.goto(f"{BASE_URL}/claims/{claim_id}/claim-pack", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Claim Pack Export", exact=True)).to_be_visible(timeout=15_000)
        mutations.clear()
        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.get_by_role("heading", name="خروجی بسته پرونده", exact=True)).to_be_visible()
        page.get_by_role("button", name="EN", exact=True).click()
        expect(page.get_by_role("heading", name="Claim Pack Export", exact=True)).to_be_visible()
        assert mutations == [], f"Claim Pack locale switch caused mutation: {mutations}"

        page.get_by_label("I understand this export is a review aid and may contain open or unresolved items.").check()
        page.get_by_label("Generation note (optional)").fill(
            f"13.9C final MT ORION correspondence handoff {suffix}"
        )
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith(f"/claims/{claim_id}/claim-pack-exports")
        ) as export_info:
            page.get_by_role("button", name="Generate Excel").click()
        export = export_info.value.json()
        if export["snapshot_schema_version"] != "1.4":
            raise AssertionError(f"Expected Claim Pack schema 1.4, got {export['snapshot_schema_version']}")
        expect(page.get_by_text(export["filename"], exact=True)).to_be_visible(timeout=15_000)
        expect(page.get_by_text(re.compile(r"Excel snapshot generated"))).to_be_visible()

        download_url = f"{API_URL}/api/v1/claims/{claim_id}/claim-pack-exports/{export['id']}/download"
        first_download = request.get(download_url)
        if not first_download.ok:
            raise AssertionError(f"Claim Pack download failed: {first_download.status} {first_download.text()}")
        if first_download.headers.get("x-claim-pack-snapshot-sha256") != export["snapshot_hash"]:
            raise AssertionError("Downloaded Claim Pack snapshot hash does not match immutable export metadata")
        if first_download.headers.get("x-claim-pack-file-sha256") != export["file_hash"]:
            raise AssertionError("Downloaded Claim Pack file hash does not match immutable export metadata")

        xml = _xlsx_xml_text(first_download.body())
        for expected in (subject, final_marker, external_reference, latest_review_hash):
            if expected not in xml:
                raise AssertionError(f"Final Claim Pack is missing governed correspondence content: {expected}")
        if first_review_hash == latest_review_hash:
            raise AssertionError("Final approval unexpectedly reused the historical approval hash")

        second_download = request.get(download_url)
        if not second_download.ok:
            raise AssertionError(f"Repeated Claim Pack download failed: {second_download.status} {second_download.text()}")
        if second_download.body() != first_download.body():
            raise AssertionError("Immutable Claim Pack bytes changed across repeated downloads")
        if second_download.headers.get("x-claim-pack-snapshot-sha256") != export["snapshot_hash"]:
            raise AssertionError("Repeated Claim Pack download changed snapshot identity")

        browser.close()


if __name__ == "__main__":
    main()
