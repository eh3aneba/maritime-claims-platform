from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core import preflight
from app.core.deployment_policy import validate_production_deployment


SAFE_SECRET = "production-random-material-9f43c8071b26e55b7d8f2b1a"
SAFE_API_URL = "https://api.mcri.app/api/v1"


def test_safe_production_deployment_configuration_passes() -> None:
    assert (
        validate_production_deployment(
            secret_key=SAFE_SECRET,
            public_api_base_url=SAFE_API_URL,
        )
        == []
    )


@pytest.mark.parametrize(
    "secret",
    [
        "replace-with-a-long-random-secret",
        "ci-only-production-looking-secret-material-2026",
        "demo-secret-production-looking-secret-material-2026",
        "test-secret-production-looking-secret-material-2026",
        "replace-with-production-looking-secret-material-2026",
    ],
)
def test_production_rejects_placeholder_secret_without_echoing_it(secret: str) -> None:
    errors = validate_production_deployment(
        secret_key=secret,
        public_api_base_url=SAFE_API_URL,
    )

    assert any("SECRET_KEY" in error for error in errors)
    assert all(secret not in error for error in errors)


def test_production_rejects_short_secret_without_echoing_it() -> None:
    secret = "short-secret"
    errors = validate_production_deployment(
        secret_key=secret,
        public_api_base_url=SAFE_API_URL,
    )

    assert errors == ["SECRET_KEY must contain at least 32 characters in production"]
    assert secret not in "\n".join(errors)


@pytest.mark.parametrize(
    "public_api_base_url",
    [
        "",
        "http://api.mcri.app/api/v1",
        "https://localhost:8000/api/v1",
        "https://127.0.0.1/api/v1",
        "https://[::1]/api/v1",
        "https://example.com/api/v1",
        "https://api.example.com/api/v1",
        "https://demo.mcri.app/api/v1",
    ],
)
def test_production_rejects_unsafe_or_reserved_public_api_urls(public_api_base_url: str) -> None:
    errors = validate_production_deployment(
        secret_key=SAFE_SECRET,
        public_api_base_url=public_api_base_url,
    )

    assert any("NEXT_PUBLIC_API_BASE_URL" in error for error in errors)


def test_production_rejects_public_api_url_with_embedded_credentials() -> None:
    errors = validate_production_deployment(
        secret_key=SAFE_SECRET,
        public_api_base_url="https://user:password@api.mcri.app/api/v1",
    )

    assert errors == ["NEXT_PUBLIC_API_BASE_URL must not contain embedded credentials"]
    assert "password" not in "\n".join(errors)


def test_preflight_enforces_production_policy_without_secret_leakage(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    secret = "demo-secret-that-must-never-appear-in-preflight-output-2026"
    settings = SimpleNamespace(
        app_env="production",
        cors_origins=["https://app.mcri.app"],
        cors_allowed_origins="https://app.mcri.app",
        secret_key=secret,
        next_public_api_base_url="http://api.mcri.app/api/v1",
        database_url="postgresql+psycopg://mcri:synthetic@db:5432/mcri",
        ai_provider="disabled",
        ai_model="",
        openai_api_key="",
        allow_external_ai_restricted=False,
        ai_max_input_chars=60000,
        ai_max_output_tokens=2000,
        ai_prompt_bundle_version="2026-08-20.1",
        ai_schema_bundle_version="2026-08-20.1",
        storage_backend="local",
        local_storage_path=str(tmp_path),
        malware_scan_enabled=False,
        clamav_host="clamav",
        clamav_port=3310,
        clamav_timeout_seconds=1.0,
    )
    monkeypatch.setattr(preflight, "get_settings", lambda: settings)

    errors, _warnings = preflight.run_preflight(require_db=False)

    assert any("SECRET_KEY" in error for error in errors)
    assert any("NEXT_PUBLIC_API_BASE_URL" in error for error in errors)
    assert secret not in "\n".join(errors)
