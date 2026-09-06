"""Phase 14.4 browser acceptance for historical AI surface retirement."""
from __future__ import annotations

import os
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")

CANONICAL_AI_ROUTES = (
    "/ai-review",
    "/ai-governance",
    "/ai-evaluation",
    "/ai-operations",
    "/ai-integrations",
)

LEGACY_REDIRECTS = {
    "/ai-private-pilot": "/ai-operations",
    "/ai-limited-production": "/ai-operations",
    "/ai-scale-up": "/ai-operations",
    "/ai-broader-production": "/ai-operations",
    "/ai-high-coverage": "/ai-operations",
    "/ai-final-production": "/ai-operations",
    "/ai-near-universal-production": "/ai-operations",
    "/ai-bounded-full-production": "/ai-operations",
    "/ai-production-wide": "/ai-operations",
    "/ai-pilot-outcomes": "/ai-evaluation",
    "/ai-limited-production-outcomes": "/ai-evaluation",
    "/ai-scale-up-outcomes": "/ai-evaluation",
    "/ai-broader-production-outcomes": "/ai-evaluation",
    "/ai-high-coverage-outcomes": "/ai-evaluation",
    "/ai-final-production-readiness": "/ai-evaluation",
    "/ai-final-production-outcomes": "/ai-evaluation",
    "/ai-near-universal-outcomes": "/ai-evaluation",
    "/ai-bounded-full-production-outcomes": "/ai-evaluation",
}


def current_path(page) -> str:
    return urlparse(page.url).path.rstrip("/") or "/"


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    mutating_requests: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")
        expect(page.locator("main#main-content")).to_be_visible()

        def observe_request(request) -> None:
            if "/api/v1/" in request.url and request.method not in {"GET", "HEAD", "OPTIONS"}:
                mutating_requests.append(f"{request.method} {request.url}")

        page.on("request", observe_request)

        primary_nav = page.get_by_role("navigation", name="Primary navigation").first
        expect(primary_nav).to_be_visible()

        for canonical_route in CANONICAL_AI_ROUTES:
            expect(primary_nav.locator(f'a[href="{canonical_route}"]')).to_have_count(1)

        for legacy_route in LEGACY_REDIRECTS:
            expect(primary_nav.locator(f'a[href="{legacy_route}"]')).to_have_count(0)

        # Canonical operator surfaces remain directly reachable and are not rewritten.
        for canonical_route in CANONICAL_AI_ROUTES:
            response = page.goto(f"{BASE_URL}{canonical_route}", wait_until="domcontentloaded")
            if response is None or response.status >= 400:
                raise AssertionError(f"Canonical AI surface failed to load: {canonical_route}")
            page.wait_for_url(f"**{canonical_route}")
            assert current_path(page) == canonical_route
            expect(page.locator("main#main-content")).to_be_visible()

        # Historical rollout/readiness URLs remain backward-compatible but resolve to
        # the durable Operations or Evaluation product surface before legacy UI renders.
        for legacy_route, destination in LEGACY_REDIRECTS.items():
            response = page.goto(f"{BASE_URL}{legacy_route}", wait_until="domcontentloaded")
            if response is None or response.status >= 400:
                raise AssertionError(f"Legacy AI route failed to redirect safely: {legacy_route}")
            page.wait_for_url(f"**{destination}")
            assert current_path(page) == destination, (
                f"Expected {legacy_route} to resolve to {destination}, got {current_path(page)}"
            )
            expect(page.locator("main#main-content")).to_be_visible()

        assert not mutating_requests, (
            "AI navigation/retirement redirects must not mutate API state: "
            f"{mutating_requests}"
        )
        browser.close()

    print("Phase 14.4 AI surface consolidation browser E2E passed.")


if __name__ == "__main__":
    main()
