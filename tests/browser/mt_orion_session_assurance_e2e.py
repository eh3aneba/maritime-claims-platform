"""Browser E2E for MT ORION design-partner login, session assurance, and logout."""
from __future__ import annotations

import os

from playwright.sync_api import sync_playwright

BASE_URL = os.getenv("MCRI_WEB_URL", "http://127.0.0.1:3000").rstrip("/")
ORG = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot")
EMAIL = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app")
PASSWORD = os.getenv("MCRI_DEMO_PASSWORD", "")


def main() -> None:
    if len(PASSWORD) < 12:
        raise SystemExit("Set MCRI_DEMO_PASSWORD (12+ characters) before running browser E2E")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})

        page.goto(f"{BASE_URL}/login", wait_until="networkidle")
        page.get_by_label("Organization").fill(ORG)
        page.get_by_label("Email").fill(EMAIL)
        page.get_by_label("Password").fill(PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/dashboard")

        session_result = page.evaluate(
            """async () => {
                const response = await fetch('/api/v1/auth/session', {credentials: 'include'});
                return {status: response.status, body: await response.json()};
            }"""
        )
        assert session_result["status"] == 200
        assert session_result["body"]["identity_source"] == "local"
        assert session_result["body"]["auth_method"] == "password"
        assert session_result["body"]["id"]
        serialized = str(session_result["body"]).lower()
        for forbidden in (
            "access_token",
            "password_hash",
            "assertion",
            "client_secret",
            "mfa_secret",
        ):
            assert forbidden not in serialized

        logout_status = page.evaluate(
            """async () => {
                const response = await fetch('/api/v1/auth/logout', {
                    method: 'POST',
                    credentials: 'include'
                });
                return response.status;
            }"""
        )
        assert logout_status == 204

        replay_status = page.evaluate(
            """async () => {
                const response = await fetch('/api/v1/auth/me', {credentials: 'include'});
                return response.status;
            }"""
        )
        assert replay_status == 401

        browser.close()

    print("MT ORION session assurance browser E2E passed.")


if __name__ == "__main__":
    main()
