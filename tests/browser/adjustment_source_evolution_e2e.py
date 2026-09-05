"""Phase 13.6B real MT ORION Adjustment source-evolution acceptance."""
from __future__ import annotations

import json
import os
import re
import subprocess
import textwrap
from decimal import Decimal

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
API_URL = os.getenv("MCRI_API_URL", "http://127.0.0.1:8000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")
COMPOSE_ENV_FILE = os.getenv("MCRI_COMPOSE_ENV_FILE", "").strip()


def _json(response, label: str):
    if not response.ok:
        raise AssertionError(f"{label} failed: {response.status} {response.text()}")
    return response.json()


def _current_invoice_amount_extractions() -> dict:
    """Resolve real current reviewed invoice amount extractions from the running demo stack."""

    script = textwrap.dedent(
        """
        import json
        import re
        from sqlalchemy import select

        from app.db.session import create_session
        from app.demo.seed_mt_orion import DEMO_EXTERNAL_REFERENCE
        from app.modules.claims.models import Claim
        from app.modules.financial.service import _latest_completed_runs, _reviewed_rows
        from app.modules.intelligence.service import TASK_INVOICE

        with create_session() as db:
            claim = db.scalar(select(Claim).where(Claim.external_reference == DEMO_EXTERNAL_REFERENCE))
            if claim is None:
                raise RuntimeError("MT ORION demo claim is unavailable")
            candidates = []
            for run, _document in _latest_completed_runs(db, claim, [TASK_INVOICE]):
                rows = _reviewed_rows(db, run)
                for field_path, extraction in rows.items():
                    match = re.fullmatch(r"invoice\.line_items\[(\d+)\]\.amount", field_path)
                    if not match:
                        continue
                    candidates.append({
                        "document_id": str(run.document_id),
                        "ai_run_id": str(run.id),
                        "line_index": int(match.group(1)),
                        "extraction_id": str(extraction.id),
                    })
            print(json.dumps({"claim_id": str(claim.id), "candidates": candidates}))
        """
    )
    command = ["docker", "compose"]
    if COMPOSE_ENV_FILE:
        command.extend(["--env-file", COMPOSE_ENV_FILE])
    command.extend(["exec", "-T", "api", "python", "-"])
    result = subprocess.run(command, input=script, check=True, text=True, capture_output=True)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise AssertionError("Financial source fixture lookup returned no result")
    return json.loads(lines[-1])


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    fixture = _current_invoice_amount_extractions()
    if not fixture["candidates"]:
        raise AssertionError("MT ORION must expose at least one current reviewed invoice amount extraction")

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

        page.goto(f"{BASE_URL}/claims", wait_until="networkidle")
        page.get_by_placeholder("Search claim, vessel or IMO…").fill("MCRI-DEMO-MT-ORION")
        page.get_by_role("button", name="Apply filters").click()
        row = page.get_by_role("row").filter(has_text="MT ORION").filter(has_text="MCRI-DEMO-MT-ORION")
        expect(row).to_have_count(1)
        claim_link = row.locator('a[href^="/claims/"]').filter(has_text=re.compile(r"^MCRI-HM-"))
        expect(claim_link).to_have_count(1)
        claim_href = claim_link.get_attribute("href")
        if not claim_href:
            raise AssertionError("Expected MT ORION claim href")
        claim_id = claim_href.rstrip("/").split("/")[-1]
        if claim_id != fixture["claim_id"]:
            raise AssertionError("Browser MT ORION claim does not match the live financial source fixture")

        request = context.request
        claim = _json(request.get(f"{API_URL}/api/v1/claims/{claim_id}"), "claim detail")
        target_currency = claim["currency"]
        financial = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/financial-review"),
            "financial review",
        )
        candidate_map = {
            (row["document_id"], row["line_index"]): row
            for row in fixture["candidates"]
        }
        source_item = next(
            (
                item for item in financial["items"]
                if item["document_kind"] == "invoice"
                and item["currency"] == target_currency
                and (item["document_id"], item["line_index"]) in candidate_map
            ),
            None,
        )
        if source_item is None:
            raise AssertionError(
                f"MT ORION must expose a {target_currency} invoice line linked to a current reviewed amount extraction"
            )
        candidate = candidate_map[(source_item["document_id"], source_item["line_index"])]

        created = _json(
            request.post(
                f"{API_URL}/api/v1/claims/{claim_id}/adjustments",
                data={"currency": target_currency, "title": "Phase 13.6B real source-evolution acceptance"},
            ),
            "create current adjustment",
        )
        if created["source_state_status"] != "current":
            raise AssertionError("New Adjustment was not bound to the current Financial Review state")
        old_statement_id = created["id"]
        old_version = created["version"]
        old_gross = created["gross_claimed"]
        line = next((row for row in created["lines"] if row["cost_item_id"] == source_item["id"]), None)
        if line is None:
            raise AssertionError("Current financial source item was not materialized into the Adjustment")

        treated = _json(
            request.patch(
                f"{API_URL}/api/v1/claims/{claim_id}/adjustments/{old_statement_id}/lines/{line['id']}",
                data={
                    "treatment": "included",
                    "basis": "particular_average",
                    "claimed_amount": line["claimed_amount"],
                    "considered_amount": line["claimed_amount"],
                    "note": "Phase 13.6B human treatment before evidence evolution.",
                },
            ),
            "record human line treatment",
        )
        treated_line = next(row for row in treated["lines"] if row["id"] == line["id"])
        if treated_line["treatment"] != "included":
            raise AssertionError("Human Adjustment line treatment was not recorded")

        evolved_amount = (Decimal(str(source_item["amount"])) + Decimal("123.45")).quantize(Decimal("0.01"))
        _json(
            request.post(
                f"{API_URL}/api/v1/ai-review/{candidate['extraction_id']}",
                data={
                    "action": "edit",
                    "value": {
                        "value": float(evolved_amount),
                        "currency": target_currency,
                        "raw": f"{evolved_amount} {target_currency}",
                    },
                    "reason": "Phase 13.6B real invoice evidence-evolution acceptance",
                    "confirm_re_review": True,
                },
            ),
            "edit reviewed invoice amount",
        )

        listing = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/adjustments"),
            "stale adjustment listing",
        )
        stale = next(row for row in listing["items"] if row["id"] == old_statement_id)
        if stale["source_state_status"] != "stale":
            raise AssertionError(f"Expected stale Adjustment, got {stale['source_state_status']!r}")
        if stale["source_change_summary"]["changed_count"] < 1:
            raise AssertionError("Invoice evidence evolution was not reflected in the Adjustment source change summary")
        if stale["gross_claimed"] != old_gross:
            raise AssertionError("Historical Adjustment values changed after live evidence evolution")

        page.goto(f"{BASE_URL}/claims/{claim_id}/adjustment", wait_until="networkidle")
        expect(page.get_by_text("Evidence changed — re-review required", exact=True).first).to_be_visible()
        expect(page.get_by_role("button", name="Rebase to current evidence", exact=True)).to_be_visible()

        page.get_by_role("button", name="FA").click()
        expect(page.locator("html")).to_have_attribute("lang", "fa")
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(page.get_by_text("شواهد تغییر کرده‌اند — بازبینی مجدد لازم است", exact=True).first).to_be_visible()
        expect(page.get_by_role("button", name="Rebase به شواهد جاری", exact=True)).to_be_visible()

        page.get_by_role("button", name="EN").click()
        note = page.get_by_placeholder("Why are you rebasing to current evidence?")
        note.fill("Deliberate rebase after the reviewed invoice amount changed; changed lines require fresh human review.")
        page.get_by_role("button", name="Rebase to current evidence", exact=True).click()
        expect(page.get_by_text("Current evidence state", exact=True).first).to_be_visible(timeout=15_000)

        final_listing = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/adjustments"),
            "rebased adjustment listing",
        )
        newest = max(final_listing["items"], key=lambda row: row["version"])
        if newest["version"] != old_version + 1:
            raise AssertionError("Explicit rebase did not create the next Adjustment version")
        if newest["rebased_from_statement_id"] != old_statement_id:
            raise AssertionError("Rebased Adjustment lost historical version linkage")
        if newest["source_state_status"] != "current":
            raise AssertionError("Rebased Adjustment is not current against evolved financial evidence")
        changed_line = next(row for row in newest["lines"] if row["source_snapshot"]["item_key"] == source_item["item_key"])
        if changed_line["treatment"] != "pending" or Decimal(changed_line["considered_amount"]) != 0:
            raise AssertionError("Changed source line incorrectly carried its prior human Adjustment judgment")
        historical = next(row for row in final_listing["items"] if row["id"] == old_statement_id)
        if historical["gross_claimed"] != old_gross or historical["source_state_status"] != "stale":
            raise AssertionError("Historical Adjustment was not preserved after explicit rebase")

        browser.close()


if __name__ == "__main__":
    main()
