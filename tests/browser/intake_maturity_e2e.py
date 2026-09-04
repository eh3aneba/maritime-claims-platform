"""End-to-end browser coverage for production-mature H&M claim intake.

Validates actual local EN/FA OCR using real raster PNG inputs, deterministic advisory
classification, resumable processing after refresh, explicit status recovery, a real
failure -> operator retry -> success journey, human correction/review, and persistence
of the approved source-document type.
"""
from __future__ import annotations

import html
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
API_URL = os.getenv("MCRI_API_URL", "http://127.0.0.1:8000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")
COMPOSE_ENV_FILE = os.getenv("MCRI_COMPOSE_ENV_FILE", "").strip()
RUN_RETRY_INFRA_E2E = os.getenv("MCRI_E2E_RETRY_INFRA", "").strip().lower() in {
    "1",
    "true",
    "yes",
}
ACTIVE_DRAFT_KEY = "mcri.claimIntake.activeDraftId"


def _write_fnol_docx(path: Path) -> None:
    paragraphs = [
        "Claim Notification",
        "Incident Date: 2026-08-10",
        "Notification Date: 2026-08-11",
        "Claim Reference: INTAKE-MATURITY-E2E",
        "Incident Description: Main engine turbocharger developed abnormal vibration during voyage and the vessel reduced engine load pending inspection.",
    ]
    body = "".join(
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs
    )
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    relationships = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{body}<w:sectPr/></w:body>
</w:document>"""
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", document)


def _write_raster_scan(page, path: Path, *, lines: list[str], direction: str) -> None:
    """Render a document-like page to a true PNG so the worker performs real OCR."""
    align = "right" if direction == "rtl" else "left"
    rendered = "".join(f"<p>{html.escape(line)}</p>" for line in lines)
    page.set_viewport_size({"width": 1500, "height": 900})
    page.set_content(
        f"""
        <main id="scan" dir="{direction}" style="box-sizing:border-box;width:1400px;height:800px;padding:70px 90px;background:white;color:black;font-family:'Noto Sans Arabic','Arial',sans-serif;font-size:50px;line-height:1.6;text-align:{align};">
          {rendered}
        </main>
        """
    )
    page.locator("#scan").screenshot(path=str(path))


def _compose(*args: str) -> subprocess.CompletedProcess[str]:
    if not COMPOSE_ENV_FILE:
        raise AssertionError(
            "MCRI_COMPOSE_ENV_FILE is required when the infrastructure retry E2E is enabled"
        )
    return subprocess.run(
        ["docker", "compose", "--env-file", COMPOSE_ENV_FILE, *args],
        check=True,
        text=True,
        capture_output=True,
    )


def _service_shell(service: str, command: str) -> None:
    _compose("exec", "-T", service, "sh", "-lc", command)


def _hold_intake_source(*, organization_id: str, draft_id: str, suffix: str) -> tuple[str, str]:
    source_path = f"/data/documents/_intake/{organization_id}/{draft_id}{suffix}"
    held_path = f"{source_path}.retry-e2e-hold"
    _service_shell(
        "api",
        f"test -f {shlex.quote(source_path)} && mv {shlex.quote(source_path)} {shlex.quote(held_path)}",
    )
    return source_path, held_path


def _restore_intake_source(source_path: str, held_path: str) -> None:
    _service_shell(
        "api",
        f"if test -f {shlex.quote(held_path)}; then mv {shlex.quote(held_path)} {shlex.quote(source_path)}; fi",
    )


def _exercise_real_scanned_ocr(page, fixture: Path) -> None:
    page.locator('input[type="file"]').set_input_files(str(fixture))
    page.get_by_role("button", name="Upload & extract").click()
    type_select = page.get_by_label("Document type", exact=True)
    expect(type_select).to_be_visible(timeout=90_000)
    expect(page.get_by_text(re.compile(r"Method\s+tesseract:eng\+fas", re.I))).to_be_visible()
    expect(page.get_by_text(re.compile(r"Draft reference", re.I))).to_be_visible()
    reject_button = page.get_by_role(
        "button",
        name="Reject this draft without creating a claim",
        exact=True,
    )
    expect(reject_button).to_be_visible()
    reject_button.click()
    expect(reject_button).to_be_hidden(timeout=30_000)
    if page.evaluate(f"window.sessionStorage.getItem('{ACTIVE_DRAFT_KEY}')") is not None:
        raise AssertionError("Rejected scanned OCR draft left a stale resumable pointer")


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    with tempfile.TemporaryDirectory(prefix="mcri-intake-e2e-") as directory:
        directory_path = Path(directory)
        source = directory_path / "claim-notification.docx"
        en_scan = directory_path / "claim-notification-en.png"
        fa_scan = directory_path / "claim-notification-fa.png"
        _write_fnol_docx(source)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 1000})
            fixture_page = context.new_page()
            _write_raster_scan(
                fixture_page,
                en_scan,
                direction="ltr",
                lines=[
                    "CLAIM NOTIFICATION",
                    "Vessel: MT ORION",
                    "Incident Date: 2026-08-10",
                    "Main engine turbocharger vibration and damage",
                    "Engine load reduced pending inspection",
                ],
            )
            _write_raster_scan(
                fixture_page,
                fa_scan,
                direction="rtl",
                lines=[
                    "اعلام خسارت",
                    "کشتی: MT ORION",
                    "تاریخ حادثه: 2026-08-10",
                    "خرابی و لرزش توربوشارژر موتور اصلی",
                    "توان موتور تا زمان بازرسی کاهش یافت",
                ],
            )
            fixture_page.close()

            page = context.new_page()
            page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            page.get_by_label("Organization").fill(ORG)
            page.get_by_label("Email").fill(EMAIL)
            page.get_by_label("Password").fill(PASSWORD)
            page.get_by_role("button", name="Sign in").click()
            page.wait_for_url("**/dashboard")

            page.goto(f"{BASE_URL}/claims/new", wait_until="networkidle")
            expect(page.get_by_role("button", name="Upload & extract")).to_be_visible()

            # Both true PNG raster inputs are handled by the actual worker container,
            # which contains Tesseract and the eng/fas language packs.
            _exercise_real_scanned_ocr(page, en_scan)
            _exercise_real_scanned_ocr(page, fa_scan)

            held_source: tuple[str, str] | None = None
            if RUN_RETRY_INFRA_E2E:
                _compose("stop", "worker")

            try:
                page.locator('input[type="file"]').set_input_files(str(source))
                with page.expect_response(
                    lambda response: response.request.method == "POST"
                    and "/api/v1/claim-intake/drafts" in response.url
                ) as upload_response:
                    page.get_by_role("button", name="Upload & extract").click()
                upload_payload = upload_response.value.json()
                draft_id = upload_payload.get("id")
                organization_id = upload_payload.get("organization_id")
                if not draft_id or not organization_id:
                    raise AssertionError(
                        f"Intake upload returned no draft/organization id: {upload_payload}"
                    )

                if RUN_RETRY_INFRA_E2E:
                    held_source = _hold_intake_source(
                        organization_id=organization_id,
                        draft_id=draft_id,
                        suffix=source.suffix,
                    )
                    _compose("start", "worker")

                    # The worker now performs a real attempt against a temporarily
                    # unavailable source. CI config limits this acceptance fixture to
                    # one automatic attempt, so the durable draft reaches FAILED and
                    # exposes the normal operator retry control.
                    retry_button = page.get_by_role("button", name="Retry processing")
                    expect(retry_button).to_be_visible(timeout=90_000)
                    expect(page.get_by_text("failed", exact=True)).to_be_visible()
                    if page.evaluate(
                        f"window.sessionStorage.getItem('{ACTIVE_DRAFT_KEY}')"
                    ) != draft_id:
                        raise AssertionError("Failed intake lost its resumable draft pointer")

                    # Recovery presentation must remain understandable in Persian as
                    # well as English while technical identifiers remain unchanged.
                    page.get_by_role("button", name="FA").click()
                    expect(page.locator("html")).to_have_attribute("lang", "fa")
                    expect(page.locator("html")).to_have_attribute("dir", "rtl")
                    expect(page.get_by_role("button", name="پردازش مجدد")).to_be_visible()
                    expect(page.get_by_text(draft_id, exact=True)).to_be_visible()
                    page.get_by_role("button", name="EN").click()
                    expect(page.locator("html")).to_have_attribute("lang", "en")
                    expect(page.locator("html")).to_have_attribute("dir", "ltr")

                    _restore_intake_source(*held_source)
                    held_source = None
                    with page.expect_response(
                        lambda response: response.request.method == "POST"
                        and response.url.endswith(f"/api/v1/claim-intake/drafts/{draft_id}/retry")
                    ) as retry_response:
                        page.get_by_role("button", name="Retry processing").click()
                    retry_payload = retry_response.value.json()
                    if retry_payload.get("id") != draft_id:
                        raise AssertionError("Operator retry created/referenced a different intake draft")
                    if retry_payload.get("approved_claim_id") is not None:
                        raise AssertionError("Retry created a claim before human approval")
                    if retry_payload.get("source_document_id") is not None:
                        raise AssertionError("Retry created an active source document before approval")

                type_select = page.get_by_label("Document type", exact=True)
                expect(type_select).to_be_visible(timeout=90_000)
                expect(
                    page.get_by_text(re.compile(r"Suggested classification.*claim notification", re.I))
                ).to_be_visible()
                expect(page.get_by_text(re.compile(r"Draft reference", re.I))).to_contain_text(
                    draft_id
                )
                if page.evaluate(f"window.sessionStorage.getItem('{ACTIVE_DRAFT_KEY}')") != draft_id:
                    raise AssertionError(
                        "Active intake draft id was not preserved for browser-session resume"
                    )

                durable_review = context.request.get(
                    f"{API_URL}/api/v1/claim-intake/drafts/{draft_id}"
                )
                if not durable_review.ok:
                    raise AssertionError(
                        f"Durable retry state lookup failed: {durable_review.status} {durable_review.text()}"
                    )
                durable_payload = durable_review.json()
                if durable_payload.get("id") != draft_id or durable_payload.get("status") != "pending_review":
                    raise AssertionError(f"Retry did not preserve one durable review draft: {durable_payload}")
                if durable_payload.get("approved_claim_id") is not None:
                    raise AssertionError("Retry mutated authoritative claim state before approval")
                if durable_payload.get("source_document_id") is not None:
                    raise AssertionError("Retry duplicated/promoted source evidence before approval")

                drafts_response = context.request.get(f"{API_URL}/api/v1/claim-intake/drafts")
                if not drafts_response.ok:
                    raise AssertionError(
                        f"Draft inventory lookup failed: {drafts_response.status} {drafts_response.text()}"
                    )
                same_draft = [
                    item
                    for item in (drafts_response.json().get("items") or [])
                    if item.get("id") == draft_id
                ]
                if len(same_draft) != 1:
                    raise AssertionError(
                        f"Retry should preserve exactly one intake draft, found {len(same_draft)}"
                    )

                draft_url = re.compile(
                    rf".*/api/v1/claim-intake/drafts/{re.escape(draft_id)}$"
                )

                def present_once_as_processing(route) -> None:
                    response = route.fetch()
                    payload = response.json()
                    payload["status"] = "processing"
                    route.fulfill(response=response, json=payload)

                page.route(draft_url, present_once_as_processing)
                page.reload(wait_until="networkidle")
                expect(page.get_by_text(re.compile(r"Draft reference", re.I))).to_contain_text(
                    draft_id
                )
                expect(page.get_by_role("button", name="Check status")).to_be_visible(
                    timeout=30_000
                )
                if page.evaluate(f"window.sessionStorage.getItem('{ACTIVE_DRAFT_KEY}')") != draft_id:
                    raise AssertionError("Refresh lost the resumable processing draft reference")

                page.unroute(draft_url, present_once_as_processing)
                page.get_by_role("button", name="Check status").click()
                type_select = page.get_by_label("Document type", exact=True)
                expect(type_select).to_be_visible(timeout=30_000)
                expect(
                    page.get_by_text(re.compile(r"Suggested classification.*claim notification", re.I))
                ).to_be_visible()

                type_select.select_option("survey_report")
                expect(type_select).to_have_value("survey_report")

                vessel_select = page.locator("select").filter(has=page.locator("option")).nth(1)
                if not vessel_select.input_value():
                    values = vessel_select.locator("option").evaluate_all(
                        "options => options.map(option => option.value).filter(Boolean)"
                    )
                    if not values:
                        raise AssertionError("Demo environment exposes no vessel for intake approval")
                    vessel_select.select_option(values[0])

                page.get_by_role("button", name="Approve & create claim").click()
                page.wait_for_url(re.compile(r".*/claims/[0-9a-f-]{36}$"), timeout=30_000)
                if page.evaluate(f"window.sessionStorage.getItem('{ACTIVE_DRAFT_KEY}')") is not None:
                    raise AssertionError("Completed intake left a stale resumable draft reference")
                claim_match = re.search(r"/claims/([0-9a-f-]{36})$", page.url)
                if claim_match is None:
                    raise AssertionError(f"Could not resolve created claim id from {page.url}")
                claim_id = claim_match.group(1)

                documents = context.request.get(f"{API_URL}/api/v1/claims/{claim_id}/documents")
                if not documents.ok:
                    raise AssertionError(
                        f"Created-claim document lookup failed: {documents.status} {documents.text()}"
                    )
                payload = documents.json()
                items = payload.get("items") or []
                if len(items) != 1:
                    raise AssertionError(f"Expected one intake source document, got {len(items)}")
                if items[0].get("document_type") != "survey_report":
                    raise AssertionError(
                        "Human-corrected intake document type did not persist: "
                        f"{items[0].get('document_type')!r}"
                    )
            finally:
                if RUN_RETRY_INFRA_E2E:
                    if held_source is not None:
                        _restore_intake_source(*held_source)
                    # Starting an already-running service is harmless and prevents a
                    # failed assertion from leaving the shared E2E stack degraded.
                    _compose("start", "worker")

            browser.close()


if __name__ == "__main__":
    main()
