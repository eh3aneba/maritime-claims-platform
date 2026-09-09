"""Runtime/deployment preflight checks for shared pilot, staging and production environments."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import text

from app.core.config import get_settings
from app.core.deployment_policy import DEFAULT_SECRET, validate_production_deployment
from app.db.session import create_session
from app.modules.documents.malware import MalwareScannerError, ping_clamd
from app.modules.documents.object_storage import (
    ObjectStorageError,
    S3CompatibleEvidenceStore,
    S3ObjectStoreConfig,
)

DEFAULT_DB_PASSWORD_FRAGMENT = "change-me-in-local-env"


def _fail(errors: list[str], message: str) -> None:
    errors.append(message)


def _build_s3_foundation_store(settings, *, require_https: bool) -> S3CompatibleEvidenceStore:
    config = S3ObjectStoreConfig(
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        bucket=settings.s3_bucket,
        access_key_id=settings.s3_access_key_id,
        secret_access_key=settings.s3_secret_access_key.get_secret_value(),
        session_token=settings.s3_session_token.get_secret_value(),
        request_timeout_seconds=settings.s3_request_timeout_seconds,
        max_attempts=settings.s3_max_attempts,
        tls_verify=settings.s3_tls_verify,
    )
    config.validate(require_https=require_https)
    if require_https and not config.tls_verify:
        raise ObjectStorageError("S3 TLS verification must be enabled in staging/production")
    return S3CompatibleEvidenceStore(config)


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
        if env == "production":
            errors.extend(
                validate_production_deployment(
                    secret_key=settings.secret_key,
                    public_api_base_url=settings.next_public_api_base_url,
                )
            )
        elif settings.secret_key == DEFAULT_SECRET or len(settings.secret_key) < 32:
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
        if settings.ai_provider.lower() == "openai":
            if not settings.openai_api_key.strip():
                _fail(errors, "OPENAI_API_KEY is required when AI_PROVIDER=openai")
            if env != "staging":
                _fail(errors, "Sprint 11A permits AI_PROVIDER=openai only in staging")
            if settings.allow_external_ai_restricted:
                _fail(errors, "Restricted documents cannot be enabled for external AI in Sprint 11A")
            if not 1000 <= settings.ai_max_input_chars <= 60000:
                _fail(errors, "AI_MAX_INPUT_CHARS must be between 1000 and 60000")
            if not 128 <= settings.ai_max_output_tokens <= 4096:
                _fail(errors, "AI_MAX_OUTPUT_TOKENS must be between 128 and 4096")
            if not settings.ai_prompt_bundle_version.strip():
                _fail(errors, "AI_PROMPT_BUNDLE_VERSION is required for external AI")
            if not settings.ai_schema_bundle_version.strip():
                _fail(errors, "AI_SCHEMA_BUNDLE_VERSION is required for external AI")
    else:
        warnings.append("AI_PROVIDER is disabled; deterministic demo data can still be used")

    storage_backend = settings.storage_backend.lower().strip()
    if storage_backend == "local":
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
    elif storage_backend == "s3":
        _fail(
            errors,
            "STORAGE_BACKEND=s3 is foundation-only in Phase 17.3-A and cannot yet be selected for active evidence admission",
        )
    else:
        _fail(errors, f"Unsupported STORAGE_BACKEND: {storage_backend or '<empty>'}")

    # Some existing deployment-policy tests intentionally use lightweight settings
    # stubs. Missing foundation-only configuration must preserve the historical
    # default (disabled), while real Settings objects still validate strictly when
    # S3_FOUNDATION_ENABLED is explicitly true.
    if getattr(settings, "s3_foundation_enabled", False):
        try:
            s3_store = _build_s3_foundation_store(
                settings,
                require_https=env in {"staging", "production"},
            )
            health = s3_store.probe_bucket()
            if health.status != "ok":
                _fail(errors, "S3-compatible evidence storage foundation target is not ready")
            else:
                warnings.append(
                    "S3-compatible evidence storage foundation target is reachable but is not active for document admission"
                )
        except ObjectStorageError as exc:
            _fail(errors, f"S3-compatible evidence storage foundation check failed: {exc}")

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

    parsed = urlparse(settings.next_public_api_base_url)
    if (
        strict
        and env != "production"
        and parsed.scheme == "http"
        and parsed.hostname not in {"localhost", "127.0.0.1", None}
    ):
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
