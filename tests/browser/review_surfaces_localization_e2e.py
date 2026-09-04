"""Focused browser coverage for localized review surfaces and AI review maturity."""
from __future__ import annotations

import json
import os
import re
import subprocess
import textwrap

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
API_URL = os.getenv("MCRI_API_URL", "http://127.0.0.1:8000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")
COMPOSE_ENV_FILE = os.getenv("MCRI_COMPOSE_ENV_FILE", "").strip()

TRACKED = ("/technical", "/financial", "/severity-reserve", "/recovery-timebar")


def _seed_ai_review_supersession_fixture() -> dict[str, str]:
    """Create one synthetic intake fact plus a pending AI proposal in the CI database.

    This uses the already-running API container and real application models. It is
    test-fixture setup only: no production/test-only HTTP endpoint or authority bypass
    is introduced.
    """

    email_literal = json.dumps(EMAIL)
    script = textwrap.dedent(
        f"""
        import json
        from datetime import UTC, datetime
        from decimal import Decimal
        from sqlalchemy import select

        from app.db.session import create_session
        from app.demo.seed_mt_orion import DEMO_EXTERNAL_REFERENCE
        from app.modules.claims.facts import ClaimFact
        from app.modules.claims.models import Claim
        from app.modules.intelligence.models import AISemanticKind, AIReviewStatus, AIRun, DocumentExtraction
        from app.modules.processing.models import DocumentTextExtraction, DocumentTextSegment
        from app.modules.users.models import User

        FIELD_PATH = "claim.incident_description"
        INTAKE_VALUE = "Main engine turbocharger No.2 failure with abnormal vibration."
        AI_VALUE = "Main engine turbocharger No.2 failure with abnormal vibration, load reduction and subsequent shutdown."

        with create_session() as db:
            claim = db.scalar(select(Claim).where(Claim.external_reference == DEMO_EXTERNAL_REFERENCE))
            if claim is None:
                raise RuntimeError("MT ORION demo claim is unavailable")
            reviewer = db.scalar(
                select(User).where(
                    User.organization_id == claim.organization_id,
                    User.email == {email_literal},
                )
            )
            seed_extraction = db.scalar(
                select(DocumentExtraction)
                .where(DocumentExtraction.claim_id == claim.id)
                .order_by(DocumentExtraction.created_at.asc())
                .limit(1)
            )
            if reviewer is None or seed_extraction is None:
                raise RuntimeError("Demo reviewer/source extraction is unavailable")
            run = db.get(AIRun, seed_extraction.ai_run_id)
            text_extraction = db.scalar(
                select(DocumentTextExtraction).where(
                    DocumentTextExtraction.document_id == seed_extraction.document_id
                )
            )
            segment = db.scalar(
                select(DocumentTextSegment)
                .where(DocumentTextSegment.document_id == seed_extraction.document_id)
                .order_by(DocumentTextSegment.segment_index.asc())
                .limit(1)
            )
            if run is None or text_extraction is None or segment is None:
                raise RuntimeError("Demo source lineage is incomplete")
            existing_fact = db.scalar(
                select(ClaimFact).where(
                    ClaimFact.organization_id == claim.organization_id,
                    ClaimFact.claim_id == claim.id,
                    ClaimFact.field_path == FIELD_PATH,
                )
            )
            existing_candidate = db.scalar(
                select(DocumentExtraction).where(
                    DocumentExtraction.organization_id == claim.organization_id,
                    DocumentExtraction.claim_id == claim.id,
                    DocumentExtraction.field_path == FIELD_PATH,
                )
            )
            if existing_fact is not None or existing_candidate is not None:
                raise RuntimeError("AI review operator fixture already exists; start from a clean demo volume")

            fact = ClaimFact(
                organization_id=claim.organization_id,
                claim_id=claim.id,
                field_path=FIELD_PATH,
                value=INTAKE_VALUE,
                provenance_kind="intake_review",
                source_extraction_id=None,
                source_text_extraction_id=text_extraction.id,
                source_document_id=seed_extraction.document_id,
                source_segment_id=segment.id,
                approved_by_id=reviewer.id,
                approved_at=datetime.now(UTC),
                version=1,
            )
            candidate = DocumentExtraction(
                organization_id=claim.organization_id,
                claim_id=claim.id,
                document_id=seed_extraction.document_id,
                ai_run_id=run.id,
                source_segment_id=segment.id,
                field_path=FIELD_PATH,
                semantic_kind=AISemanticKind.FACT,
                raw_value=AI_VALUE,
                normalized_value=AI_VALUE,
                confidence=Decimal("0.970"),
                source_locator_type=segment.locator_type,
                source_locator_value=segment.locator_value,
                source_quote=segment.text[:500],
                source_verified=True,
                human_status=AIReviewStatus.PENDING,
            )
            db.add_all([fact, candidate])
            db.commit()
            print(json.dumps({{
                "claim_id": str(claim.id),
                "candidate_id": str(candidate.id),
                "intake_value": INTAKE_VALUE,
                "ai_value": AI_VALUE,
            }}))
        """
    )
    command = ["docker", "compose"]
    if COMPOSE_ENV_FILE:
        command.extend(["--env-file", COMPOSE_ENV_FILE])
    command.extend(["exec", "-T", "api", "python", "-"])
    result = subprocess.run(command, input=script, check=True, text=True, capture_output=True)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise AssertionError("AI review fixture setup returned no result")
    return json.loads(lines[-1])


def _api_detail(page, candidate_id: str) -> dict:
    response = page.request.get(f"{API_URL}/api/v1/ai-review/{candidate_id}")
    if not response.ok:
        raise AssertionError(f"AI review detail failed: HTTP {response.status}")
    return response.json()


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    fixture = _seed_ai_review_supersession_fixture()
    mutations: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1500, "height": 1100})

        def record_request(request) -> None:
            if request.method not in {"GET", "HEAD", "OPTIONS"} and any(part in request.url for part in TRACKED):
                mutations.append(f"{request.method} {request.url}")

        page.on("request", record_request)

        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")

        # Primary navigation keeps operator tasks and hides historical rollout stages.
        expect(page.locator('aside nav a[href="/ai-review"]').first).to_be_visible()
        expect(page.locator('aside nav a[href="/ai-governance"]').first).to_be_visible()
        expect(page.locator('aside nav a[href="/ai-evaluation"]').first).to_be_visible()
        expect(page.locator('aside nav a[href="/ai-operations"]').first).to_be_visible()
        expect(page.locator('aside nav a[href="/ai-integrations"]').first).to_be_visible()
        expect(page.locator('aside nav a[href="/ai-private-pilot"]').first).to_be_hidden()
        expect(page.locator('aside nav a[href="/ai-production-wide"]').first).to_be_hidden()
        legacy_response = page.goto(f"{BASE_URL}/ai-private-pilot", wait_until="networkidle")
        if legacy_response is None or not legacy_response.ok:
            raise AssertionError("Historical AI rollout route was hidden from navigation but no longer routable")

        page.goto(f"{BASE_URL}/claims", wait_until="networkidle")
        page.get_by_placeholder("Search claim, vessel or IMO…").fill("MCRI-DEMO-MT-ORION")
        page.get_by_role("button", name="Apply filters").click()
        expect(page.get_by_text("MT ORION", exact=True)).to_be_visible()
        claim_link = page.locator('a[href^="/claims/"]').filter(has_text=re.compile(r"^MCRI-HM-")).first
        expect(claim_link).to_be_visible()
        claim_href = claim_link.get_attribute("href")
        assert claim_href, "Expected MT ORION claim href"
        claim_id = claim_href.rstrip("/").split("/")[-1]
        assert claim_id == fixture["claim_id"]

        # Technical: English -> Persian. Locale switching must not reload or mutate technical review state.
        page.goto(f"{BASE_URL}/claims/{claim_id}/technical", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Technical review matrix")).to_be_visible()
        expect(page.locator("html")).to_have_attribute("dir", "ltr")
        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.get_by_role("heading", name="ماتریس بازبینی فنی")).to_be_visible()
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        assert mutations == [], f"Technical locale switch caused mutation: {mutations}"

        # Financial: Persian -> English. Currency/amount content remains data, while labels switch language.
        page.goto(f"{BASE_URL}/claims/{claim_id}/financial", wait_until="networkidle")
        expect(page.get_by_role("heading", name="بازبینی مالی")).to_be_visible()
        expect(page.get_by_text("ذخیره فعلی", exact=True)).to_be_visible()
        page.get_by_role("button", name="EN", exact=True).click()
        expect(page.get_by_role("heading", name="Financial review")).to_be_visible()
        expect(page.get_by_text("Current reserve", exact=True)).to_be_visible()
        assert mutations == [], f"Financial locale switch caused mutation: {mutations}"

        # Severity & reserve support: do not click build/refresh/decision controls.
        page.goto(f"{BASE_URL}/claims/{claim_id}/severity-reserve", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Severity & Reserve Support")).to_be_visible()
        expect(page.get_by_text("Human reserve authority required.", exact=False)).to_be_visible()
        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.get_by_role("heading", name="پشتیبانی شدت و ذخیره")).to_be_visible()
        expect(page.get_by_text("اختیار انسانی برای ذخیره الزامی است.", exact=False)).to_be_visible()
        assert mutations == [], f"Severity/reserve locale switch caused mutation: {mutations}"

        # Recovery & time-bar: candidate dates remain non-authoritative and no decision/build runs on locale switch.
        page.goto(f"{BASE_URL}/claims/{claim_id}/recovery-timebar", wait_until="networkidle")
        expect(page.get_by_role("heading", name="هوشمندی بازیافت و مهلت زمانی")).to_be_visible()
        expect(page.get_by_text("تأیید انسانی/حقوقی الزامی است.", exact=False)).to_be_visible()
        page.get_by_role("button", name="EN", exact=True).click()
        expect(page.get_by_role("heading", name="Recovery & Time-bar Intelligence")).to_be_visible()
        expect(page.get_by_text("Human/legal verification required.", exact=False)).to_be_visible()
        assert mutations == [], f"Recovery/time-bar locale switch caused mutation: {mutations}"

        # AI Review: an intake-reviewed canonical fact must not be silently replaced.
        page.goto(f"{BASE_URL}/ai-review?claim_id={claim_id}", wait_until="networkidle")
        expect(page.get_by_role("heading", name="AI Review")).to_be_visible()
        page.get_by_label("Review view").select_option("fields")
        candidate = page.locator("article").filter(has_text="claim.incident_description").first
        expect(candidate).to_be_visible()
        candidate.get_by_role("button", name="Approve", exact=True).click()
        warning = page.locator('div[role="alert"]:not(#__next-route-announcer__)').first
        expect(warning).to_contain_text("Canonical Claim Fact replacement requires confirmation")
        expect(warning).to_contain_text("Human-reviewed intake")
        expect(warning).to_contain_text("version 1")

        # Locale change changes presentation only; replacement is still pending explicit human confirmation.
        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(warning).to_contain_text("جایگزینی واقعیت معتبر پرونده نیازمند تأیید است")
        detail_before_confirm = _api_detail(page, fixture["candidate_id"])
        assert detail_before_confirm["current_claim_fact"]["provenance_kind"] == "intake_review"
        assert detail_before_confirm["current_claim_fact"]["version"] == 1
        assert detail_before_confirm["item"]["human_status"] == "pending"

        page.get_by_role("button", name="تأیید جایگزینی", exact=True).click()
        page.get_by_role("button", name="EN", exact=True).click()
        detail_after_approve = _api_detail(page, fixture["candidate_id"])
        assert detail_after_approve["current_claim_fact"]["provenance_kind"] == "ai_review"
        assert detail_after_approve["current_claim_fact"]["version"] == 2
        assert detail_after_approve["current_claim_fact"]["value"] == fixture["ai_value"]
        assert [row["version"] for row in detail_after_approve["claim_fact_revisions"][:2]] == [2, 1]

        with page.expect_response(
            lambda response: "/api/v1/ai-review?" in response.url
            and "review_status=approved" in response.url
            and response.request.method == "GET"
        ) as approved_queue_info:
            page.get_by_label("Review status").select_option("approved")
        approved_queue = approved_queue_info.value
        if not approved_queue.ok:
            raise AssertionError(f"Approved AI review queue failed: HTTP {approved_queue.status}")
        approved_payload = approved_queue.json()
        if fixture["candidate_id"] not in {
            item.get("extraction_id") for item in approved_payload.get("items", [])
        }:
            raise AssertionError("Approved AI review queue did not return the replaced candidate")
        approved_candidate = page.locator("article").filter(has_text="claim.incident_description").first
        expect(approved_candidate).to_be_visible(timeout=15_000)
        approved_candidate.get_by_role("button", name="Provenance & history", exact=True).click()
        expect(approved_candidate).to_contain_text("Human-approved AI review")
        expect(approved_candidate).to_contain_text("Version 2")

        # Reviewed items expose an explicit two-step re-review entry point. Locale
        # switching changes copy/direction only and must not itself record a decision.
        expect(approved_candidate.get_by_role("button", name="Reject on re-review", exact=True)).to_be_hidden()
        approved_candidate.get_by_role("button", name="Re-review decision", exact=True).click()
        expect(approved_candidate).to_contain_text("Deliberate re-review")
        detail_before_re_review = _api_detail(page, fixture["candidate_id"])
        assert detail_before_re_review["item"]["human_status"] == "approved"
        assert detail_before_re_review["current_claim_fact"]["version"] == 2

        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(approved_candidate).to_contain_text("بازبینی مجدد آگاهانه")
        detail_after_locale_switch = _api_detail(page, fixture["candidate_id"])
        assert detail_after_locale_switch["item"]["human_status"] == "approved"
        assert detail_after_locale_switch["current_claim_fact"]["version"] == 2
        page.get_by_role("button", name="EN", exact=True).click()

        with page.expect_request(
            lambda request: request.url.endswith(f"/api/v1/ai-review/{fixture['candidate_id']}")
            and request.method == "POST"
        ) as re_review_request_info:
            approved_candidate.get_by_role("button", name="Reject on re-review", exact=True).click()
        re_review_payload = re_review_request_info.value.post_data_json
        if not re_review_payload or re_review_payload.get("confirm_re_review") is not True:
            raise AssertionError("Deliberate re-review did not send explicit confirmation intent")

        detail_after_reject = _api_detail(page, fixture["candidate_id"])
        assert detail_after_reject["item"]["human_status"] == "rejected"
        assert detail_after_reject["current_claim_fact"]["provenance_kind"] == "intake_review"
        assert detail_after_reject["current_claim_fact"]["version"] == 3
        assert detail_after_reject["current_claim_fact"]["value"] == fixture["intake_value"]
        assert [row["version"] for row in detail_after_reject["claim_fact_revisions"][:3]] == [3, 2, 1]

        with page.expect_response(
            lambda response: "/api/v1/ai-review?" in response.url
            and "review_status=rejected" in response.url
            and response.request.method == "GET"
        ) as rejected_queue_info:
            page.get_by_label("Review status").select_option("rejected")
        rejected_queue = rejected_queue_info.value
        if not rejected_queue.ok:
            raise AssertionError(f"Rejected AI review queue failed: HTTP {rejected_queue.status}")
        rejected_payload = rejected_queue.json()
        if fixture["candidate_id"] not in {
            item.get("extraction_id") for item in rejected_payload.get("items", [])
        }:
            raise AssertionError("Rejected AI review queue did not return the restored candidate")
        rejected_candidate = page.locator("article").filter(has_text="claim.incident_description").first
        expect(rejected_candidate).to_be_visible(timeout=15_000)
        rejected_candidate.get_by_role("button", name="Provenance & history", exact=True).click()
        expect(rejected_candidate).to_contain_text("Human-reviewed intake")
        expect(rejected_candidate).to_contain_text("Version 3")
        expect(rejected_candidate).to_contain_text(fixture["intake_value"])

        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(rejected_candidate).to_contain_text("ورودی بازبینی‌شده توسط انسان")

        browser.close()


if __name__ == "__main__":
    main()
