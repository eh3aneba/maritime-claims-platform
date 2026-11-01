"""Synthetic, GET-only browser contract test; all API responses are intercepted.

Run against a local frontend (MCRI_WEB_URL, default http://127.0.0.1:3001).
No database, real OCR, real reviewer, acceptance or workpaper-content validation.
"""
import json
import os
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def uid(n):
    return f"00000000-0000-4000-8000-{n:012d}"


def main():
    base = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3001").rstrip("/")
    if urlparse(base).hostname not in {"localhost", "127.0.0.1"}:
        raise SystemExit("This mocked test requires a loopback frontend")
    claim, document, reporter, reviewer, report, review = [uid(n) for n in range(1, 7)]
    now = "2026-11-01T12:00:00Z"
    report_row = dict(id=report, document_id=document, document_version=1,
        source_file_hash="a" * 64, extraction_text_hash="b" * 64, segment_index=0,
        locator_type="page", locator_value="1", issue_kind="negation_scope_changed",
        reported_by_id=reporter, reported_at=now, review_state="reported_unverified",
        claim_fact_approved=False)
    review_row = dict(id=review, report_id=report, document_id=document,
        source_file_hash="a" * 64, extraction_text_hash="b" * 64,
        reviewed_by_id=reviewer, reviewed_at=now, review_method="visual_original_scan",
        outcome="not_reproduced", review_workpaper_sha256="c" * 64,
        review_state="independent_observation_no_clearance", source_hold_cleared=False,
        claim_fact_approved=False)
    binding = dict(id=uid(7), report_id=report, review_id=review, document_id=document,
        workpaper_document_id=uid(8), workpaper_document_version=1,
        workpaper_file_hash="c" * 64, custody_state="managed_clean_document_record_linked",
        original_source_hold_cleared=False, claim_fact_approved=False)
    doc = dict(id=document, claim_id=claim, original_filename="invented-hm05.png",
        file_hash="a" * 64, file_size_bytes=100, version_number=1, is_current=True,
        document_type="chief_engineer_report", confidentiality_level="internal",
        malware_scan_status="clean", processing_status="processed", created_at=now)
    source = dict(document_id=document, document_version=1, source_file_hash="a" * 64,
        extraction_text_hash="b" * 64, extraction_method="tesseract:eng+fas",
        source_text_quality_state="ocr_human_source_comparison_required",
        review_disposition="machine_unverified", total_segments=1, offset=0, limit=5,
        segments=[dict(segment_index=0, locator_type="page", locator_value="1",
            text_preview="Invented incomplete machine clause", source_char_count=34,
            text_truncated=False)])
    state = {"reviews": [review_row], "binding": binding, "status": 200}
    writes = []
    review_requests = []

    def route_api(route):
        request = route.request
        if request.method != "GET":
            writes.append(request.method)
            route.abort()
            return
        path = urlparse(request.url).path
        status = 200
        if path.endswith("/auth/me"):
            body = dict(id=reviewer, full_name="Invented test reviewer", email="fiction@example.invalid", role="claims_manager")
        elif path.endswith("/workpaper-binding"):
            body = state["binding"]
        elif path.endswith("/independent-reviews"):
            review_requests.append(path)
            status = state["status"]
            body = dict(items=state["reviews"], offset=0, limit=25)
        elif path.endswith("/source-discrepancies"):
            body = dict(items=[report_row], offset=0, limit=25)
        elif path.endswith("/source-segments"):
            body = source
        elif path.endswith("/processing"):
            body = dict(operator_status="completed", processing_release_required=False,
                text_extraction=dict(source_text_quality_state=source["source_text_quality_state"], text_hash="b" * 64))
        elif path.endswith("/documents"):
            body = dict(items=[doc], quarantined_items=[])
        elif path.endswith("/facts"):
            body = dict(items=[])
        elif path.endswith("/" + claim):
            body = dict(id=claim, claim_reference="FICTION-HM-05", vessel=dict(name="SYNTHETIC VESSEL"),
                status="investigation", priority="medium", currency="USD", incident_date="2026-09-11",
                notification_date="2026-09-12", incident_description="Invented browser fixture only",
                estimated_loss=None, current_reserve=None, handler=None)
        else:
            raise AssertionError(f"Unexpected API path: {path}")
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body),
            headers={"Access-Control-Allow-Origin": base, "Access-Control-Allow-Credentials": "true"})

    with sync_playwright() as p:
        executable = os.getenv("MCRI_BROWSER_EXECUTABLE")
        browser = p.chromium.launch(headless=True, **({"executable_path": executable} if executable else {}))
        context = browser.new_context()
        context.route("**/api/v1/**", route_api)
        page = context.new_page()

        def open_source():
            page.goto(f"{base}/claims/{claim}")
            page.get_by_role("button", name="Inspect machine OCR text", exact=True).click()
            return page.get_by_test_id("ocr-independent-history")

        history = open_source()
        expect(history).to_be_visible()
        assert not review_requests, "History must be on demand"
        history.get_by_role("button", name="Independent review history", exact=True).click()
        expect(history.get_by_test_id("ocr-independent-observation")).to_have_count(1)
        expect(history.get_by_text("Not reproduced", exact=False)).to_be_visible()
        expect(history.get_by_text("Recorded observations only", exact=False)).to_be_visible()
        history.get_by_role("button", name="Managed workpaper record", exact=True).click()
        expect(history.get_by_test_id("ocr-workpaper-record")).to_contain_text("Historical metadata linkage only")

        # Mismatched binding cannot be displayed as managed evidence.
        state["binding"] = {**binding, "workpaper_file_hash": "d" * 64}
        history.get_by_role("button", name="Managed workpaper record", exact=True).click()
        history.get_by_role("button", name="Managed workpaper record", exact=True).click()
        expect(history.get_by_role("alert")).to_contain_text("No matching accessible binding")
        expect(history.get_by_test_id("ocr-workpaper-record")).to_have_count(0)

        for bad in [{**review_row, "source_hold_cleared": True},
                    {**review_row, "source_file_hash": "d" * 64}]:
            state["reviews"] = [bad]
            history.get_by_role("button", name="Independent review history", exact=True).click()
            history.get_by_role("button", name="Independent review history", exact=True).click()
            expect(history.get_by_role("alert")).to_contain_text("Review history is unavailable")
            expect(history.get_by_test_id("ocr-independent-observation")).to_have_count(0)

        state["reviews"] = []
        state["status"] = 403
        history.get_by_role("button", name="Independent review history", exact=True).click()
        history.get_by_role("button", name="Independent review history", exact=True).click()
        expect(history.get_by_role("alert")).to_contain_text("Do not interpret this as no reviews")
        state["status"] = 200
        # Historical reports must not fetch reviews for the current source.
        report_row["extraction_text_hash"] = "d" * 64
        count = len(review_requests)
        page.goto(f"{base}/claims/{claim}")
        page.get_by_role("button", name="Inspect machine OCR text", exact=True).click()
        expect(page.get_by_text("Historical source: reload", exact=False)).to_be_visible()
        expect(page.get_by_test_id("ocr-independent-history")).to_have_count(0)
        assert len(review_requests) == count
        report_row["extraction_text_hash"] = "b" * 64
        page.reload()
        history = open_source()
        history.get_by_role("button", name="Independent review history", exact=True).click()
        expect(history.get_by_text("No observations in this page", exact=False)).to_be_visible()

        # Persisted Persian locale must also present the no-clearance explanation.
        page.evaluate("localStorage.setItem('mcri.locale', 'fa')")
        page.reload()
        page.get_by_role("button", name="مشاهده متن ماشینی OCR", exact=True).click()
        history = page.get_by_test_id("ocr-independent-history")
        history.get_by_role("button", name="سوابق بازبینی مستقل", exact=True).click()
        expect(history.get_by_text("فقط مشاهدات ثبت‌شده است", exact=False)).to_be_visible()
        assert not writes, f"Read-only workspace attempted writes: {writes}"
        browser.close()
    print("PASS: synthetic bilingual readback, bounded source/binding rejection, access failure and zero API writes")


if __name__ == "__main__":
    main()
