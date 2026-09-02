"""Final Phase 12K mobile, RTL and accessibility browser coverage."""
from __future__ import annotations

import os
import re

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    mutating_requests: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")

        def observe_request(request) -> None:
            watched_paths = (
                "/api/v1/claims",
                "/api/v1/claim-workbench",
                "/api/v1/ai-",
                "/api/v1/governance-",
            )
            if any(path in request.url for path in watched_paths) and request.method not in {"GET", "HEAD", "OPTIONS"}:
                mutating_requests.append(f"{request.method} {request.url}")

        page.on("request", observe_request)

        expect(page.locator("html")).to_have_attribute("lang", "en")
        expect(page.locator("html")).to_have_attribute("dir", "ltr")
        expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()

        skip_link = page.locator(".skip-link")
        expect(skip_link).to_have_attribute("href", "#main-content")
        skip_link.focus()
        expect(skip_link).to_be_visible()
        expect(page.locator("main#main-content")).to_have_attribute("tabindex", "-1")

        menu_button = page.get_by_role("button", name="Open navigation")
        expect(menu_button).to_be_visible()
        expect(menu_button).to_have_attribute("aria-expanded", "false")
        menu_button.click()
        expect(menu_button).to_have_attribute("aria-expanded", "true")

        drawer = page.locator("#mobile-navigation")
        expect(drawer).to_be_visible()
        expect(drawer).to_have_attribute("role", "dialog")
        expect(drawer).to_have_attribute("aria-modal", "true")
        expect(drawer).to_have_class(re.compile(r"\bleft-0\b"))
        current_dashboard = drawer.locator('a[aria-current="page"]')
        expect(current_dashboard).to_have_count(1)
        expect(current_dashboard).to_have_attribute("href", "/dashboard")

        page.keyboard.press("Escape")
        expect(drawer).to_have_count(0)
        expect(menu_button).to_be_focused()
        expect(menu_button).to_have_attribute("aria-expanded", "false")

        page.get_by_role("button", name="FA").click()
        expect(page.locator("html")).to_have_attribute("lang", "fa")
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(page.get_by_role("heading", name="داشبورد")).to_be_visible()

        claim_reference = page.get_by_text(re.compile(r"^MCRI-HM-")).first
        expect(claim_reference).to_be_visible()
        expect(claim_reference).to_have_attribute("dir", "ltr")
        imo_value = page.get_by_text(re.compile(r"^IMO \d{7}$")).first
        expect(imo_value).to_be_visible()
        expect(imo_value).to_have_attribute("dir", "ltr")

        rtl_menu_button = page.get_by_role("button", name="باز کردن منو")
        rtl_menu_button.click()
        rtl_drawer = page.locator("#mobile-navigation")
        expect(rtl_drawer).to_be_visible()
        expect(rtl_drawer).to_have_class(re.compile(r"\bright-0\b"))
        expect(rtl_drawer.locator('a[aria-current="page"]')).to_have_count(1)
        expect(rtl_drawer.get_by_role("button", name="خروج")).to_be_visible()

        rtl_drawer.locator('a[href="/claims"]').click()
        page.wait_for_url("**/claims")
        expect(page.locator("html")).to_have_attribute("dir", "rtl")
        expect(page.get_by_role("heading", name="پرونده‌ها")).to_be_visible()
        expect(page.locator("#mobile-navigation")).to_have_count(0)

        page.get_by_role("button", name="EN").click()
        expect(page.locator("html")).to_have_attribute("lang", "en")
        expect(page.locator("html")).to_have_attribute("dir", "ltr")
        expect(page.get_by_role("heading", name="Claims")).to_be_visible()

        assert not mutating_requests, f"Locale/mobile navigation must not mutate claim or AI/governance APIs: {mutating_requests}"
        browser.close()

    print("Final localization / RTL / accessibility browser E2E passed.")


if __name__ == "__main__":
    main()
