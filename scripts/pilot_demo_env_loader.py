#!/usr/bin/env python3
"""Read a deliberately restricted synthetic Pilot .env without executing shell.

This loader is only for the MT ORION design-partner preflight, not a general
Docker Compose dotenv implementation. It emits NUL-delimited KEY=VALUE records
to stdout only after validating all entries and the pre-seed safety policy.
Redirect stdout into a temporary operator-private file, never CI logs.
"""
from __future__ import annotations

from pathlib import Path
import os
import re
import sys

from pilot_demo_seed_guard import DemoSeedGuardError, check

NAME = re.compile(r"[A-Z][A-Z0-9_]*\Z")
DANGEROUS = frozenset((
    "BASH_ENV", "ENV", "IFS", "PATH", "CDPATH", "HOME", "SHELLOPTS",
    "BASHOPTS", "GLOBIGNORE", "PS4", "PROMPT_COMMAND", "TMPDIR",
    "NODE_OPTIONS", "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP",
))
DANGEROUS_PREFIXES = ("BASH_", "LD_", "PYTHON", "GIT_", "NPM_CONFIG_", "DOCKER_", "COMPOSE_")
# Explicitly limited to the documented pilot template, tracked Compose
# interpolation contract, and the synthetic-only admission flag. Even a
# syntactically valid shell variable such as MCRI_PRIVATE_TMP or ENV_FILE
# can override preflight control state if exported. Unknown application
# knobs must be reviewed rather than becoming arbitrary shell assignments.
ALLOWED_KEYS = frozenset((
    "ACCESS_TOKEN_EXPIRE_MINUTES",
    "AI_LOCAL_EXPERIMENTAL_ENABLED",
    "AI_MAX_INPUT_CHARS",
    "AI_MAX_OUTPUT_TOKENS",
    "AI_MODEL",
    "AI_PRODUCTION_CONTROL_PLANE_ENABLED",
    "AI_PROMPT_BUNDLE_VERSION",
    "AI_PROVIDER",
    "AI_SCHEMA_BUNDLE_VERSION",
    "ALLOW_EXTERNAL_AI_RESTRICTED",
    "API_V1_PREFIX",
    "APP_ENV",
    "APP_NAME",
    "AUTH_COOKIE_NAME",
    "CLAMAV_HOST",
    "CLAMAV_PORT",
    "CLAMAV_TIMEOUT_SECONDS",
    "CORS_ALLOWED_ORIGINS",
    "DATABASE_URL",
    "EXTERNAL_EVIDENCE_LIVE_PROVIDER_ADAPTERS_ENABLED",
    "EXTERNAL_EVIDENCE_LIVE_SFTP_ADAPTERS_ENABLED",
    "EXTERNAL_EVIDENCE_OBSERVER_POLL_SECONDS",
    "EXTERNAL_EVIDENCE_REVIEW_PROJECTOR_ID",
    "EXTERNAL_EVIDENCE_REVIEW_PROJECTOR_POLL_SECONDS",
    "EXTERNAL_EVIDENCE_SCHEDULER_POLL_SECONDS",
    "EXTERNAL_EVIDENCE_SERVICE_EXECUTOR_ID",
    "GOVERNANCE_WEBHOOK_MAX_ATTEMPTS",
    "GOVERNANCE_WEBHOOK_POLL_SECONDS",
    "GOVERNANCE_WEBHOOK_REPLAY_WINDOW_SECONDS",
    "GOVERNANCE_WEBHOOK_TIMEOUT_SECONDS",
    "JWT_ALGORITHM",
    "LOCAL_STORAGE_PATH",
    "MALWARE_SCAN_ENABLED",
    "MAX_UPLOAD_MB",
    "MCRI_DEMO_EMAIL",
    "MCRI_DEMO_ORG_NAME",
    "MCRI_DEMO_ORG_SLUG",
    "MCRI_DEMO_PASSWORD",
    "MCRI_SYNTHETIC_ONLY_CONFIRM",
    "NEXT_PUBLIC_API_BASE_URL",
    "OCR_ENABLED",
    "OCR_LANGUAGES",
    "OCR_MAX_PAGES",
    "OCR_TIMEOUT_SECONDS",
    "OPENAI_API_KEY",
    "POSTGRES_DB",
    "POSTGRES_PASSWORD",
    "POSTGRES_USER",
    "PROCESSING_MAX_ATTEMPTS",
    "PROCESSING_POLL_SECONDS",
    "SECRET_KEY",
    "STORAGE_BACKEND",
    "TOKEN_AUDIENCE",
    "TOKEN_ISSUER",
))
MAX_ENV_BYTES = 65536


class SyntheticEnvError(ValueError):
    """Sanitized parsing error: never copy untrusted lines or secret values."""


def parse_env(text: str) -> dict[str, str]:
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_ENV_BYTES:
        raise SyntheticEnvError("invalid or oversized synthetic environment")
    env: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SyntheticEnvError("malformed synthetic environment assignment")
        name, value = line.split("=", 1)
        if (not NAME.fullmatch(name) or name in DANGEROUS
                or name.startswith(DANGEROUS_PREFIXES)
                or name not in ALLOWED_KEYS or name in env):
            raise SyntheticEnvError("unsafe or duplicate synthetic environment key")
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0] or value[0] in value[1:-1]:
                raise SyntheticEnvError("malformed synthetic environment quote")
            value = value[1:-1]
        elif any(c.isspace() for c in value):
            raise SyntheticEnvError("unquoted whitespace in synthetic environment")
        if (any(c in value for c in ("$", "`", "\\", '"', "'"))
                or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise SyntheticEnvError("unsupported synthetic environment interpolation")
        env[name] = value
    return env


def load(path: Path) -> dict[str, str]:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ENV_BYTES:
            raise SyntheticEnvError("synthetic environment file is unsafe or unavailable")
        env = parse_env(path.read_text(encoding="utf-8"))
        check(env)
        if any("REPLACE_WITH_" in value for value in env.values()):
            raise SyntheticEnvError("synthetic environment contains placeholders")
        return env
    except (OSError, UnicodeError):
        raise SyntheticEnvError("synthetic environment unreadable") from None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 1:
        source, snapshot = Path(args[0]), None
    elif len(args) == 3 and args[1] == "--snapshot":
        source, snapshot = Path(args[0]), Path(args[2])
    else:
        print("NO-GO: one source and optional exclusive --snapshot path required",
              file=sys.stderr)
        return 2
    try:
        values = load(source)
        if snapshot is not None:
            # One parsed source, one immutable-for-this-run Compose snapshot.
            # Exclusive create + private mode: no overwrite or symlink target.
            fd = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                for key, value in values.items():
                    # Parser rejects quotes, backslashes, dollars, controls.
                    # Double-quoting all values retains literal whitespace/#.
                    stream.write(f'{key}="{value}"\n')
    except (SyntheticEnvError, DemoSeedGuardError) as exc:
        print("NO-GO: " + str(exc), file=sys.stderr)
        return 2
    except OSError:
        print("NO-GO: cannot create exclusive private Compose snapshot", file=sys.stderr)
        return 2
    # A NUL delimiter makes shell parsing non-evaluating and unambiguous.
    # stdout is secret-bearing: callers MUST NOT log or upload it.
    sys.stdout.buffer.write(b"".join(
        (key + "=" + value).encode("utf-8") + b"\0"
        for key, value in values.items()
    ))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
