#!/usr/bin/env python3
"""Sanitized, read-only Compose configuration observation for a synthetic pilot.

The rendered Compose JSON is PRIVATE: it can contain credentials. Never log
it, print it, write it to artifacts, or treat it as actual container state.
A successful observation is not a runtime, network, OCR, or Pilot GO attestation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys

# Support the documented direct-file operator CLI as well as package imports.
# Do not depend on PYTHONPATH or installed package state on a fresh host.
if __package__:
    from .pilot_compose_readiness import EXPECTED
else:
    from pilot_compose_readiness import EXPECTED

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
SHA = re.compile(r"[a-f0-9]{40}\Z")
OPTIONAL = frozenset(("demo-seed",))
AI_SERVICES = frozenset(("api", "worker", "preflight"))
REQUIRED_AI = {
    "AI_PROVIDER": "disabled",
    "AI_MODEL": "",
    "OPENAI_API_KEY": "",
    "ALLOW_EXTERNAL_AI_RESTRICTED": "false",
}
OPTIONAL_DISABLED_FLAGS = (
    "AI_LOCAL_EXPERIMENTAL_ENABLED",
    "AI_PRODUCTION_CONTROL_PLANE_ENABLED",
    "EXTERNAL_EVIDENCE_LIVE_PROVIDER_ADAPTERS_ENABLED",
    "EXTERNAL_EVIDENCE_LIVE_SFTP_ADAPTERS_ENABLED",
)
ALLOWED_DISABLED = frozenset(("false", "0"))
SAFE_SCHEMA = "mcri-pilot-compose-feature-observation-v1"


class ComposeScopeError(ValueError):
    """Bounded code-owned error category, never an exception with raw config."""


def inspect_config(config: object, *, release_sha: str) -> dict:
    """Check explicitly declared Compose flags; unobserved runtime remains unknown."""
    if type(release_sha) is not str or SHA.fullmatch(release_sha) is None:
        raise ComposeScopeError("invalid_release_sha")
    if type(config) is not dict or type(config.get("services")) is not dict:
        raise ComposeScopeError("invalid_compose_structure")
    services = config["services"]
    errors: set[str] = set()
    if set(services) - set(EXPECTED) - OPTIONAL:
        errors.add("unexpected_service")
    if set(EXPECTED) - set(services):
        errors.add("missing_expected_service")
    for name, service in services.items():
        if type(service) is not dict:
            errors.add("malformed_service")
            continue
        env = service.get("environment")
        if env is None:
            env = {}
        if type(env) is not dict:
            errors.add("malformed_environment")
            continue
        if name in AI_SERVICES:
            for key, expected in REQUIRED_AI.items():
                if type(env.get(key)) is not str or env[key] != expected:
                    errors.add("ai_provider_or_model_not_disabled")
        elif "AI_PROVIDER" in env and env["AI_PROVIDER"] != "disabled":
            errors.add("other_service_ai_provider_enabled")
        # Reject explicitly unsafe flags on ANY container, including
        # an unexpected service. Absence is not a runtime attestation.
        for key in OPTIONAL_DISABLED_FLAGS:
            if key in env and (
                type(env[key]) is not str
                or env[key].strip().lower() not in ALLOWED_DISABLED
            ):
                errors.add("optional_ai_or_external_adapter_enabled")
        if name not in AI_SERVICES:
            if "OPENAI_API_KEY" in env and env["OPENAI_API_KEY"] != "":
                errors.add("other_service_ai_secret_configured")
        if name == "worker":
            if env.get("OCR_ENABLED") not in ("true", "false"):
                errors.add("worker_ocr_mode_unclassified")
            if not isinstance(env.get("OCR_LANGUAGES"), str):
                errors.add("worker_ocr_languages_unclassified")
        # A service with an unexpected AI model setting can be an alternate
        # execution path, even when it does not declare AI_PROVIDER.
        if name not in AI_SERVICES and name != "demo-seed":
            if "AI_MODEL" in env and env["AI_MODEL"] != "":
                errors.add("other_service_ai_model_configured")
    ai_scope_safe = not errors
    return {
        "schema": SAFE_SCHEMA,
        "operator_supplied_release_sha": release_sha,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z"),
        "compose_ai_and_adapter_config_safe": ai_scope_safe,
        "check_failures": sorted(errors),
        # These MUST remain false; composed config is not running state.
        "runtime_environment_attested": False,
        "effective_database_connector_state_attested": False,
        "network_egress_isolation_attested": False,
        "persian_critical_ocr_semantics_attested": False,
        "persian_critical_extraction_disabled_attested": False,
        "real_customer_data_authorized": False,
        "pilot_accepted": False,
    }


def observe_config(*, env_file: Path, timeout: int = 30) -> object:
    if not env_file.is_file() or not COMPOSE.is_file():
        raise ComposeScopeError("compose_input_unavailable")
    try:
        run = subprocess.run(
            [
                "docker", "compose",
                "--project-directory", str(ROOT),
                "--env-file", str(env_file),
                "-f", str(COMPOSE), "config", "--format", "json",
            ],
            capture_output=True, text=True, check=False, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ComposeScopeError("compose_observation_unavailable") from None
    if run.returncode != 0:
        raise ComposeScopeError("compose_config_rejected")
    if len(run.stdout) > 2_000_000:
        raise ComposeScopeError("compose_config_oversized")
    try:
        return json.loads(run.stdout)
    except (ValueError, TypeError):
        raise ComposeScopeError("compose_config_invalid_json") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = inspect_config(
            observe_config(env_file=args.env_file),
            release_sha=args.release_sha,
        )
        # Restrict the local evidence record even under a permissive umask.
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(args.output, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(result, out, sort_keys=True, indent=2)
            out.write("\n")
    except ComposeScopeError as exc:
        # Only static categories raised by this module; never raw Docker text.
        print("NO-GO: " + str(exc), file=sys.stderr)
        return 2
    except OSError:
        print("NO-GO: private_observation_write_failed", file=sys.stderr)
        return 2
    if not result["compose_ai_and_adapter_config_safe"]:
        print("NO-GO: Compose configuration scope flags are unsafe.")
        return 1
    print("COMPOSE CONFIG SCOPE CHECK PASS (rendered settings only).")
    print("NOT running-environment attestation, OCR accuracy, or Pilot GO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
