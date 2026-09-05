"""Phase 13.6C real MT ORION authoritative reserve lineage acceptance."""
from __future__ import annotations

import os
import re
from decimal import Decimal

from playwright.sync_api import expect, sync_playwright

from adjustment_source_evolution_e2e import _current_invoice_amount_extractions

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
API_URL = os.getenv("MCRI_API_URL", "http://127.0.0.1:8000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")


def _json(response, label: str):
    if not response.ok:
        raise AssertionError(f"{label} failed: {response.status} {response.text()}")
    return response.json()


def _reserve_payload(*, amount: str, reason: str, key: str, history: dict, support_id: str) -> dict:
    return {
        "amount": amount,
        "reason": reason,
        "idempotency_key": key,
        "expected_reserve_version": history["current_version"],
        "expected_reserve_hash": history["current_hash"],
        "source_kind": "reserve_support",
        "source_reference_id": support_id,
    }


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

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

        request = context.request
        support_v1 = _json(
            request.post(f"{API_URL}/api/v1/claims/{claim_id}/severity-reserve/build"),
            "build current reserve support",
        )
        before = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/reserve-history"),
            "initial authoritative reserve history",
        )
        before_count = len(before["items"])
        before_version = before["current_version"]

        base_amount = Decimal(str(before["current_reserve"] or "300000.00"))
        first_amount = (base_amount + Decimal("12345.00")).quantize(Decimal("0.01"))

        page.goto(f"{BASE_URL}/claims/{claim_id}/reserve", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Authoritative Reserve")).to_be_visible()
        page.get_by_role("button", name="FA", exact=True).click()
        expect(page.locator("html")).to_have_attribute("lang", "fa")
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(page.get_by_role("heading", name="ذخیره معتبر")).to_be_visible()
        page.get_by_role("button", name="EN", exact=True).click()

        page.get_by_role("button", name="Reserve Support provenance").click()
        page.get_by_label("Authoritative reserve amount").fill(str(first_amount))
        page.get_by_label("Human reserve rationale").fill(
            "Phase 13.6C deliberate human reserve using current advisory support only as provenance."
        )
        page.get_by_role("button", name="Record authoritative reserve", exact=True).click()
        expect(page.get_by_text("Authoritative reserve recorded by human action.", exact=False)).to_be_visible(timeout=15_000)

        after_first = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/reserve-history"),
            "reserve history after first human write",
        )
        if after_first["current_version"] != before_version + 1:
            raise AssertionError("Authoritative reserve version did not advance after human write")
        if len(after_first["items"]) != before_count + 1:
            raise AssertionError("Authoritative reserve write did not append exactly one history row")
        first_row = after_first["items"][0]
        if Decimal(first_row["amount"]) != first_amount:
            raise AssertionError("Authoritative reserve amount was not the exact human-entered value")
        if first_row["source_kind"] != "reserve_support":
            raise AssertionError("Reserve Support provenance was not snapshotted")
        if first_row["source_reference_id"] != support_v1["id"]:
            raise AssertionError("Reserve history did not retain the exact support snapshot reference")
        if first_row["source_snapshot"].get("amount_inferred") is not False:
            raise AssertionError("Reserve lineage failed to record the no-inference authority boundary")
        if not first_row["reserve_hash"]:
            raise AssertionError("Authoritative reserve row is missing its lineage hash")

        support_v2 = _json(
            request.post(f"{API_URL}/api/v1/claims/{claim_id}/severity-reserve/build"),
            "refresh support after first reserve",
        )
        if support_v2["id"] == support_v1["id"]:
            raise AssertionError("Reserve-context evolution did not produce a refreshed support snapshot")

        fixture = _current_invoice_amount_extractions()
        financial = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/financial-review"),
            "current financial review",
        )
        candidates = {(row["document_id"], row["line_index"]): row for row in fixture["candidates"]}
        source_item = next(
            (
                item for item in financial["items"]
                if item["document_kind"] == "invoice"
                and (item["document_id"], item["line_index"]) in candidates
            ),
            None,
        )
        if source_item is None:
            raise AssertionError("MT ORION must expose a current reviewed invoice line for reserve source-evolution acceptance")
        extraction = candidates[(source_item["document_id"], source_item["line_index"])]
        evolved_amount = (Decimal(str(source_item["amount"])) + Decimal("77.77")).quantize(Decimal("0.01"))
        _json(
            request.post(
                f"{API_URL}/api/v1/ai-review/{extraction['extraction_id']}",
                data={
                    "action": "edit",
                    "value": {
                        "value": float(evolved_amount),
                        "currency": source_item["currency"],
                        "raw": f"{evolved_amount} {source_item['currency']}",
                    },
                    "reason": "Phase 13.6C real financial evidence evolution after authoritative reserve write",
                    "confirm_re_review": True,
                },
            ),
            "evolve reviewed invoice evidence",
        )

        second_amount = first_amount + Decimal("10000.00")
        stale_attempt = request.post(
            f"{API_URL}/api/v1/claims/{claim_id}/reserve",
            data=_reserve_payload(
                amount=str(second_amount),
                reason="This write must fail because the selected advisory source is stale.",
                key="phase-13-6c-stale-source",
                history=after_first,
                support_id=support_v2["id"],
            ),
        )
        if stale_attempt.status != 409:
            raise AssertionError(
                f"Expected stale Reserve Support provenance to return 409, got {stale_attempt.status}: {stale_attempt.text()}"
            )

        preserved = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/reserve-history"),
            "preserved history after stale source rejection",
        )
        if preserved["current_version"] != after_first["current_version"]:
            raise AssertionError("Stale source attempt mutated authoritative reserve version")
        if preserved["current_hash"] != after_first["current_hash"]:
            raise AssertionError("Stale source attempt mutated authoritative reserve hash")
        if len(preserved["items"]) != len(after_first["items"]):
            raise AssertionError("Stale source attempt appended an authoritative reserve row")
        if preserved["items"][0]["reserve_hash"] != first_row["reserve_hash"]:
            raise AssertionError("Evidence evolution rewrote historical reserve lineage")

        unchanged_support = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/severity-reserve"),
            "support after stale rejection",
        )["snapshot"]
        if unchanged_support["id"] != support_v2["id"]:
            raise AssertionError("Stale reserve validation unexpectedly mutated Reserve Support")
        support_v3 = _json(
            request.post(f"{API_URL}/api/v1/claims/{claim_id}/severity-reserve/build"),
            "explicit support refresh after evidence evolution",
        )
        if support_v3["id"] == support_v2["id"]:
            raise AssertionError("Explicit Support refresh did not bind to evolved financial evidence")

        page.goto(f"{BASE_URL}/claims/{claim_id}/reserve", wait_until="networkidle")
        page.get_by_role("button", name="Reserve Support provenance").click()
        page.get_by_label("Authoritative reserve amount").fill(str(second_amount))
        page.get_by_label("Human reserve rationale").fill(
            "Deliberate second human reserve after explicitly refreshing source-linked advisory support against evolved evidence."
        )
        page.get_by_role("button", name="Record authoritative reserve", exact=True).click()
        expect(page.get_by_text("Authoritative reserve recorded by human action.", exact=False)).to_be_visible(timeout=15_000)

        final = _json(
            request.get(f"{API_URL}/api/v1/claims/{claim_id}/reserve-history"),
            "final authoritative reserve history",
        )
        if final["current_version"] != after_first["current_version"] + 1:
            raise AssertionError("Second deliberate reserve did not append the next lineage version")
        newest = final["items"][0]
        if newest["previous_reserve_hash"] != first_row["reserve_hash"]:
            raise AssertionError("Second reserve did not preserve the append-only hash chain")
        if Decimal(newest["amount"]) != second_amount:
            raise AssertionError("Second reserve did not preserve the explicit human-entered amount")
        historical = next(row for row in final["items"] if row["id"] == first_row["id"])
        if historical["reserve_hash"] != first_row["reserve_hash"] or Decimal(historical["amount"]) != first_amount:
            raise AssertionError("Historical authoritative reserve row changed after evidence evolution")

        browser.close()


if __name__ == "__main__":
    main()
