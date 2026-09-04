"""End-to-end browser coverage for production-mature H&M claim intake.

Validates that deterministic classification stays advisory, a claims operator can
correct it before approval, and the reviewed type is what the source document
persists with. The test creates a minimal real DOCX without adding test-only
runtime dependencies.
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
API_URL = os.getenv("MCRI_API_URL", "http://127.0.0.1:8000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")


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


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    with tempfile.TemporaryDirectory(prefix="mcri-intake-e2e-") as directory:
        source = Path(directory) / "claim-notification.docx"
        _write_fnol_docx(source)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1280, "height": 1000})
            page = context.new_page()

            page.goto(f"{BASE_URL}/login", wait_until="networkidle")
            page.get_by_label("Organization").fill(ORG)
            page.get_by_label("Email").fill(EMAIL)
            page.get_by_label("Password").fill(PASSWORD)
            page.get_by_role("button", name="Sign in").click()
            page.wait_for_url("**/dashboard")

            page.goto(f"{BASE_URL}/claims/new", wait_until="networkidle")
            # Assert the actionable intake surface rather than coupling this maturity
            # test to unrelated page-title copy.
            expect(page.get_by_role("button", name="Upload & extract")).to_be_visible()

            page.locator('input[type="file"]').set_input_files(str(source))
            page.get_by_role("button", name="Upload & extract").click()

            type_select = page.get_by_label("Document type", exact=True)
            expect(type_select).to_be_visible(timeout=90_000)
            expect(
                page.get_by_text(re.compile(r"Suggested classification.*claim notification", re.I))
            ).to_be_visible()

            # The deterministic classifier proposes claim_notification, but the
            # human reviewer deliberately corrects the authoritative type.
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
            claim_match = re.search(r"/claims/([0-9a-f-]{36})$", page.url)
            if claim_match is None:
                raise AssertionError(f"Could not resolve created claim id from {page.url}")
            claim_id = claim_match.group(1)

            # Browser-context cookies are domain scoped rather than port scoped, so
            # the authenticated session is reused against the API service directly.
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

            browser.close()


if __name__ == "__main__":
    main()
