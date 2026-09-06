"""Fail-closed, content-free validation for production deployment configuration."""
from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlparse

DEFAULT_SECRET = "replace-with-a-long-random-secret"

_SECRET_PLACEHOLDER_MARKERS = (
    "replace-with",
    "replace_with",
    "replace-me",
    "replace_me",
    "change-me",
    "change_me",
    "changeme",
    "placeholder",
    "example-secret",
    "demo-secret",
    "test-secret",
    "ci-only",
)
_RESERVED_PUBLIC_HOSTS = {
    "localhost",
    "demo.mcri.app",
    "example.com",
    "example.org",
    "example.net",
}
_RESERVED_PUBLIC_SUFFIXES = (
    ".localhost",
    ".example.com",
    ".example.org",
    ".example.net",
    ".invalid",
)


def secret_key_is_placeholder(value: str) -> bool:
    """Return whether a secret is recognizably a deployment placeholder.

    This intentionally uses a narrow deny-list rather than guessing secret entropy.
    Callers must never log or interpolate the supplied value.
    """

    normalized = value.strip().lower()
    if not normalized:
        return True
    if normalized == DEFAULT_SECRET:
        return True
    return any(marker in normalized for marker in _SECRET_PLACEHOLDER_MARKERS)


def _is_loopback_hostname(hostname: str) -> bool:
    if hostname == "localhost" or hostname.endswith(".localhost"):
        return True
    try:
        return ip_address(hostname).is_loopback
    except ValueError:
        return False


def validate_production_deployment(
    *,
    secret_key: str,
    public_api_base_url: str,
) -> list[str]:
    """Validate production-only configuration without returning sensitive values."""

    errors: list[str] = []

    if len(secret_key) < 32:
        errors.append("SECRET_KEY must contain at least 32 characters in production")
    elif secret_key_is_placeholder(secret_key):
        errors.append("SECRET_KEY must not use a placeholder, demo, test, or CI-only value in production")

    raw_url = public_api_base_url.strip()
    if not raw_url:
        errors.append("NEXT_PUBLIC_API_BASE_URL must be explicitly set in production")
        return errors

    parsed = urlparse(raw_url)
    if parsed.scheme.lower() != "https" or not parsed.netloc or not parsed.hostname:
        errors.append("NEXT_PUBLIC_API_BASE_URL must be an absolute HTTPS URL in production")
        return errors

    if parsed.username is not None or parsed.password is not None:
        errors.append("NEXT_PUBLIC_API_BASE_URL must not contain embedded credentials")

    hostname = parsed.hostname.lower().rstrip(".")
    if _is_loopback_hostname(hostname):
        errors.append("NEXT_PUBLIC_API_BASE_URL must not target localhost or a loopback address in production")
    elif hostname in _RESERVED_PUBLIC_HOSTS or hostname.endswith(_RESERVED_PUBLIC_SUFFIXES):
        errors.append("NEXT_PUBLIC_API_BASE_URL must not use a demo, example, or reserved deployment hostname")

    return errors


def main() -> None:
    # Import lazily so the validation helpers remain dependency-light and easy to test.
    from app.core.config import get_settings

    settings = get_settings()
    if settings.app_env.lower().strip() != "production":
        print("ERROR: production deployment policy requires APP_ENV=production")
        raise SystemExit(1)

    errors = validate_production_deployment(
        secret_key=settings.secret_key,
        public_api_base_url=settings.next_public_api_base_url,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)
    print("MCRI production deployment policy passed.")


if __name__ == "__main__":
    main()
