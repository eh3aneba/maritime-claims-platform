"""Phase 13.8C real MT ORION Initial Assessment maturity acceptance."""
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


def _generate(request, claim_id: str, reason: str) -> dict:
    return _json(
        request.post(
            f"{API_URL}/api/v1/claims/{claim_id}/initial-assessment/generate",
            data={"allow_if_not_ready": True, "override_reason": reason},
        ),
        f"generate assessment: {reason}",
    )


def _review_all(request, claim_id: str, assessment: dict) -> None:
    fingerprint = assessment["source_fingerprint"]
    if not fingerprint:
        raise AssertionError("Generated assessment must be source-bound")
    for section in assessment["sections"]:
        response = request.post(
            f"{API_URL}/api/v1/claims/{claim_id}/initial-assessment/sections/{section['id']}/review",
            data={
                "action": "approve",
                "text": None,
                "expected_source_fingerprint": fingerprint,
            },
        )
        _json(response, f"review assessment section {section['section_key']}")


def _approve(request, claim_id: str, assessment: dict, note: str) -> dict:
    return _json(
        request.post(
            f"{API_URL}/api/v1/claims/{claim_id}/initial-assessment/{assessment['id']}/approve",
            data={"note": note, "expected_source_fingerprint": assessment["source_fingerprint"]},
        ),
        f"approve assessment v{assessment['version']}",
    )


def _evolve_claim(request, claim_id: str, marker: str) -> dict:
    claim = _json(request.get(f"{API_URL}/api/v1/claims/{claim_id}"), "read MT ORION claim")
    description = str(claim["incident_description"])
    return _json(
        request.patch(
            f"{API_URL}/api/v1/claims/{claim_id}",
            data={"incident_description": f"{description} | {marker}"},
        ),
        f"evolve MT ORION source state: {marker}",
    )


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

        # 1) Human-review and approve one exact source-bound version.
        first = _generate(request, claim_id, f"13.8C first approved source-bound version {suffix}")
        _review_all(request, claim_id, first)
        approved_first = _approve(request, claim_id, first, "13.8C human-approved historical baseline")
        first_digest = approved_first.get("approved_content_hash")
        if not first_digest or len(first_digest) != 64:
            raise AssertionError("Approved baseline assessment must carry a deterministic content digest")

        # 2) Evolve authoritative upstream claim state. The approved record remains immutable but becomes stale.
        _evolve_claim(request, claim_id, f"13.8C evidence evolution A {suffix}")
        historical = _json(
            request.get(
                f"{API_URL}/api/v1/claims/{claim_id}/initial-assessment/versions/{approved_first['id']}"
            ),
            "retrieve historical approved assessment",
        )
        if historical["source_state"] != "stale":
            raise AssertionError(f"Expected historical approved assessment to become stale, got {historical['source_state']}")
        if historical["approved_content_hash"] != first_digest:
            raise AssertionError("Source evolution must not rewrite the historical approved-content digest")

        # 3) Prove a browser/session-bound stale write is rejected on an open draft.
        stale_draft = _generate(request, claim_id, f"13.8C deliberate draft before second evolution {suffix}")
        _evolve_claim(request, claim_id, f"13.8C evidence evolution B {suffix}")
        stale_section = stale_draft["sections"][0]
        stale_write = request.post(
            f"{API_URL}/api/v1/claims/{claim_id}/initial-assessment/sections/{stale_section['id']}/review",
            data={
                "action": "approve",
                "text": None,
                "expected_source_fingerprint": stale_draft["source_fingerprint"],
            },
        )
        if stale_write.status != 409:
            raise AssertionError(f"Expected stale assessment write to fail closed with 409, got {stale_write.status}")

        # 4) Deliberately generate, human-review and approve the new current version.
        current = _generate(request, claim_id, f"13.8C deliberate recovery version {suffix}")
        _review_all(request, claim_id, current)
        approved_current = _approve(request, claim_id, current, "13.8C current source-bound human approval")
        current_digest = approved_current.get("approved_content_hash")
        if not current_digest or len(current_digest) != 64 or current_digest == first_digest:
            raise AssertionError("Current approved assessment must have its own deterministic digest")

        history = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/initial-assessment/history"),
            "read assessment version history",
        )
        by_id = {item["id"]: item for item in history["items"]}
        if by_id[approved_first["id"]]["source_state"] != "stale":
            raise AssertionError("Historical approved version must be shown as stale in history")
        if not by_id[approved_current["id"]]["is_latest"]:
            raise AssertionError("Deliberately regenerated approved version must be latest")

        # 5) Real operator workspace: latest/current, exact historical navigation, then FA/RTL state.
        page.goto(f"{BASE_URL}/claims/{claim_id}/assessment", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Initial Assessment", exact=True)).to_be_visible(timeout=15_000)
        expect(page.get_by_role("heading", name="Version history", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="Current canonical claim context", exact=True)).to_be_visible()
        expect(page.get_by_text(current_digest, exact=False)).to_be_visible()

        historical_button = page.get_by_role("button").filter(has_text=re.compile(rf"v{approved_first['version']}\b"))
        expect(historical_button).to_have_count(1)
        historical_button.click()
        expect(page.get_by_role("heading", name="Historical assessment version", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="Source state changed — this assessment is historical", exact=True)).to_be_visible()
        expect(page.get_by_text(first_digest, exact=False)).to_be_visible()

        page.get_by_role("button", name="FA").click()
        expect(page.locator("html")).to_have_attribute("lang", "fa")
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(page.get_by_role("heading", name="ارزیابی اولیه", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="تاریخچه نسخه‌ها", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="نسخه تاریخی ارزیابی", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="وضعیت منابع تغییر کرده — این ارزیابی تاریخی است", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="ایجاد نسخه جدید").first).to_be_visible()

        page.get_by_role("button", name="EN").click()
        expect(page.locator("html")).to_have_attribute("lang", "en")
        expect(page.locator("html")).to_have_attribute("dir", "ltr")
        current_button = page.get_by_role("button").filter(has_text=re.compile(rf"v{approved_current['version']}\b"))
        expect(current_button).to_have_count(1)
        current_button.click()
        expect(page.get_by_text(current_digest, exact=False)).to_be_visible()

        # 6) Immutable downstream audit/export handoff uses exactly the digest-bound approved assessment.
        export = _json(
            request.post(
                f"{API_URL}/api/v1/claims/{claim_id}/claim-pack-exports",
                data={
                    "export_format": "xlsx",
                    "acknowledge_review_aid": True,
                    "generation_note": "Phase 13.8C approved assessment digest handoff acceptance",
                },
            ),
            "generate 13.8C Claim Pack",
        )
        if export["snapshot_schema_version"] != "1.3":
            raise AssertionError(f"Expected Claim Pack schema 1.3, got {export['snapshot_schema_version']}")
        download = request.get(
            f"{API_URL}/api/v1/claims/{claim_id}/claim-pack-exports/{export['id']}/download"
        )
        if not download.ok:
            raise AssertionError(f"Claim Pack download failed: {download.status} {download.text()}")
        if download.headers.get("x-claim-pack-snapshot-sha256") != export["snapshot_hash"]:
            raise AssertionError("Downloaded Claim Pack snapshot hash header does not match immutable export metadata")
        xml = _xlsx_xml_text(download.body())
        for expected in (
            "Approved Assessment",
            "Digest-bound approved assessment handoff only",
            "Approved content digest",
            current_digest,
            f"v{approved_current['version']}",
            "Source state at export",
            "current",
        ):
            if expected not in xml:
                raise AssertionError(f"13.8C Claim Pack is missing approved assessment handoff content: {expected}")
        if first_digest in xml:
            raise AssertionError("Claim Pack must consume the latest eligible approved assessment, not an older approved digest")

        browser.close()


if __name__ == "__main__":
    main()
