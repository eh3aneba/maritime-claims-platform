"""Phase 13.7C real MT ORION recovery reporting acceptance through Claim Pack."""
from __future__ import annotations

from io import BytesIO
import json
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
        chunks = []
        for name in archive.namelist():
            if name.endswith(".xml") or name.endswith(".rels"):
                chunks.append(archive.read(name).decode("utf-8", "replace"))
    return "\n".join(chunks)


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    suffix = uuid4().hex[:8]
    counterparty_name = f"13.7C Recovery Workshop {suffix}"
    action_summary = "Human handler records preservation correspondence for governed Claim Pack reporting acceptance."

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
        counterparty = _json(
            request.post(
                f"{API_URL}/api/v1/claims/{claim_id}/recovery-timebar/counterparties",
                data={
                    "name": counterparty_name,
                    "role": "Potential workshop contractor",
                    "allegation_basis": "Human investigation hypothesis for real H&M downstream reporting acceptance only.",
                    "source_reference": "MT ORION reviewed recovery correspondence — 13.7C acceptance",
                },
            ),
            "create 13.7C recovery counterparty",
        )
        decision = _json(
            request.post(
                f"{API_URL}/api/v1/claims/{claim_id}/recovery-timebar/decisions",
                data={
                    "counterparty_id": counterparty["id"],
                    "disposition": "monitor",
                    "rationale": "Human handler keeps the recovery path under review while factual and legal work continues.",
                    "basis_reference": "MT ORION 13.7C recovery review note",
                    "next_review_date": "2026-09-30",
                },
            ),
            "record 13.7C human recovery decision",
        )
        _json(
            request.post(
                f"{API_URL}/api/v1/claims/{claim_id}/recovery-timebar/decisions/{decision['decision_key']}/actions",
                data={
                    "decision_hash": decision["decision_hash"],
                    "action_type": "correspondence",
                    "direction": "outbound",
                    "occurred_on": "2026-09-05",
                    "summary": action_summary,
                    "source_reference": "REC-13.7C-E2E-001",
                },
            ),
            "append 13.7C recovery action",
        )

        export = _json(
            request.post(
                f"{API_URL}/api/v1/claims/{claim_id}/claim-pack-exports",
                data={
                    "export_format": "xlsx",
                    "acknowledge_review_aid": True,
                    "generation_note": "Phase 13.7C real MT ORION recovery reporting acceptance",
                },
            ),
            "generate 13.7C governed Claim Pack",
        )
        if export["snapshot_schema_version"] != "1.4":
            raise AssertionError(f"Expected Claim Pack snapshot schema 1.4, got {export['snapshot_schema_version']}")

        download = request.get(
            f"{API_URL}/api/v1/claims/{claim_id}/claim-pack-exports/{export['id']}/download"
        )
        if not download.ok:
            raise AssertionError(f"Claim Pack download failed: {download.status} {download.text()}")
        if download.headers.get("x-claim-pack-snapshot-sha256") != export["snapshot_hash"]:
            raise AssertionError("Downloaded Claim Pack snapshot hash header does not match immutable export metadata")
        xml = _xlsx_xml_text(download.body())
        for expected in (
            "Recovery Review",
            "Human closure review",
            "open_recovery_paths",
            counterparty_name,
            action_summary,
            "REC-13.7C-E2E-001",
        ):
            if expected not in xml:
                raise AssertionError(f"Recovery Claim Pack XLSX is missing expected governed content: {expected}")

        page.goto(f"{BASE_URL}/claims/{claim_id}/claim-pack", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Claim Pack Export", exact=True)).to_be_visible(timeout=15_000)
        expect(page.get_by_text(export["filename"], exact=True)).to_be_visible(timeout=15_000)

        # Prove the localized operator handoff on a *mocked*, known unsupported-
        # Unicode PDF API response. The backend real 422/no-persist behavior is
        # independently covered by its database-backed regression; no invented
        # real customer PDF or human approval is involved here.
        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.locator("html")).to_have_attribute("lang", "fa")
        page.get_by_role("checkbox").check()
        export_url = f"{API_URL}/api/v1/claims/{claim_id}/claim-pack-exports"
        prior_total = _json(request.get(export_url), "pre-fallback export list")["total"]
        blocked_pdf_requests = []

        def simulate_unsupported_pdf(route) -> None:
            payload = json.loads(route.request.post_data or "{}") if route.request.method == "POST" else {}
            if payload.get("export_format") == "pdf":
                blocked_pdf_requests.append(payload)
                route.fulfill(
                    status=422,
                    content_type="application/json",
                    body=json.dumps({
                        "detail": "Cannot generate a faithful Claim Pack PDF for these characters. "
                        "Use XLSX and consult the original evidence; no PDF was saved."
                    }),
                )
            else:
                route.continue_()

        page.route("**/api/v1/claims/*/claim-pack-exports", simulate_unsupported_pdf)
        page.get_by_role("button", name="ایجاد PDF", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("فایل PDF ایجاد نشد")
        fallback = page.get_by_role("button", name="ایجاد Excel بدون تغییر متن", exact=True)
        expect(fallback).to_be_visible()
        assert len(blocked_pdf_requests) == 1
        assert _json(request.get(export_url), "unchanged export list")["total"] == prior_total

        with page.expect_response(
            lambda res: res.request.method == "POST"
            and res.url.endswith(f"/claims/{claim_id}/claim-pack-exports")
            and res.ok,
            timeout=30_000,
        ) as fallback_response:
            fallback.click()
        created_fallback = fallback_response.value.json()
        assert created_fallback["export_format"] == "xlsx"
        expect(page.get_by_text(created_fallback["filename"], exact=True).first).to_be_visible()
        assert _json(request.get(export_url), "post-fallback export list")["total"] == prior_total + 1
        page.unroute("**/api/v1/claims/*/claim-pack-exports", simulate_unsupported_pdf)

        browser.close()


if __name__ == "__main__":
    main()
