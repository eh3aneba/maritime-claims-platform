"""Runtime/deployment preflight checks for shared pilot, staging and production environments."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import create_session
from app.modules.documents.malware import MalwareScannerError, ping_clamd

DEFAULT_SECRET = "replace-with-a-long-random-secret"
DEFAULT_DB_PASSWORD_FRAGMENT = "change-me-in-local-env"


def _fail(errors: list[str], message: str) -> None:
    errors.append(message)


def run_preflight(*, require_db: bool = True) -> tuple[list[str], list[str]]:
    settings = get_settings()
    env = settings.app_env.lower().strip()
    strict = env in {"pilot", "staging", "production"}
    errors: list[str] = []
    warnings: list[str] = []

    if not settings.cors_origins:
        _fail(errors, "CORS_ALLOWED_ORIGINS must contain at least one explicit origin")
    if "*" in settings.cors_origins:
        _fail(errors, "Wildcard CORS is not allowed when credential cookies are used")

    if strict:
        if settings.secret_key == DEFAULT_SECRET or len(settings.secret_key) < 32:
            _fail(errors, "SECRET_KEY must be replaced with at least 32 random characters")
        if DEFAULT_DB_PASSWORD_FRAGMENT in settings.database_url:
            _fail(errors, "DATABASE_URL still contains the local demo password")
        if env in {"staging", "production"}:
            insecure = [origin for origin in settings.cors_origins if not origin.startswith("https://")]
            if insecure:
                _fail(errors, "Staging/production CORS origins must use HTTPS")

    if settings.ai_provider.lower() != "disabled":
        if not settings.ai_model.strip():
            _fail(errors, "AI_MODEL is required when AI_PROVIDER is enabled")
        if settings.ai_provider.lower() == "openai" and not settings.openai_api_key.strip():
            _fail(errors, "OPENAI_API_KEY is required when AI_PROVIDER=openai")
    else:
        warnings.append("AI_PROVIDER is disabled; deterministic demo data can still be used")

    if settings.storage_backend.lower() == "local":
        storage = Path(settings.local_storage_path)
        try:
            storage.mkdir(parents=True, exist_ok=True)
            probe = storage / ".mcri-write-probe"
            probe.write_text("ok")
            probe.unlink(missing_ok=True)
        except OSError as exc:
            _fail(errors, f"Local evidence storage is not writable: {exc}")
        if strict:
            warnings.append("Local evidence storage is acceptable for a private pilot but not the long-term HA target")

    if settings.malware_scan_enabled:
        try:
            ping_clamd(
                host=settings.clamav_host,
                port=settings.clamav_port,
                timeout_seconds=settings.clamav_timeout_seconds,
            )
        except MalwareScannerError as exc:
            _fail(errors, f"Malware scanner connectivity failed: {exc}")
    elif strict:
        _fail(errors, "MALWARE_SCAN_ENABLED must be true for pilot, staging and production")
    else:
        warnings.append("Malware scanning is disabled; use only synthetic or trusted development files")

    if require_db:
        try:
            with create_session() as db:
                db.execute(text("SELECT 1"))
        except Exception as exc:  # deployment diagnostic intentionally broad
            _fail(errors, f"Database connectivity failed: {type(exc).__name__}: {exc}")

    parsed = urlparse(os.getenv("NEXT_PUBLIC_API_BASE_URL", ""))
    if strict and parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", None}:
        warnings.append("NEXT_PUBLIC_API_BASE_URL uses HTTP in a shared environment; terminate TLS before external access")

    return errors, warnings


def main() -> None:
    require_db = os.getenv("MCRI_PREFLIGHT_REQUIRE_DB", "true").lower() not in {"0", "false", "no"}
    errors, warnings = run_preflight(require_db=require_db)
    for warning in warnings:
        print(f"WARNING: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    print("MCRI preflight passed.")


if __name__ == "__main__":
    main()
