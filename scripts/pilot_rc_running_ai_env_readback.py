#!/usr/bin/env python3
"""Read-only, privacy-safe observation of effective Docker container AI flags.

This inspects actual container Config.Env arrays for the *selected* Compose
project and never emits or persists their values. A green observation is a
bounded runtime configuration check, NOT evidence of DB connector state,
host/network isolation, Persian OCR semantic accuracy, or Pilot GO.
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

# Support direct-file operator CLI and package/module CI tests alike.
if __package__:
    from .pilot_compose_readiness import EXPECTED, ReadinessError, evaluate, observe
    from .pilot_rc_compose_feature_observation import (
        AI_SERVICES, REQUIRED_AI, OPTIONAL_DISABLED_FLAGS, ALLOWED_DISABLED,
    )
else:
    from pilot_compose_readiness import EXPECTED, ReadinessError, evaluate, observe
    from pilot_rc_compose_feature_observation import (
        AI_SERVICES, REQUIRED_AI, OPTIONAL_DISABLED_FLAGS, ALLOWED_DISABLED,
    )

SHA = re.compile(r"[0-9a-f]{40}\Z")
CONTAINER_ID = re.compile(r"[0-9a-f]{12,64}\Z")
_SCHEMA = "mcri-pilot-running-ai-config-v1"


class RuntimeScopeError(ValueError):
    """Only fixed, code-owned failure codes; never surface Docker content."""


def _observed_ids(items: list[dict]) -> dict[str, str]:
    """Strict 11-service identity validation; include optional demo."""
    if type(items) is not list:
        raise RuntimeScopeError("container_service_identity_invalid")
    identities: dict[str, str] = {}
    for item in items:
        if type(item) is not dict:
            raise RuntimeScopeError("container_service_identity_invalid")
        service = item.get("Service")
        if service == "demo-seed":
            continue
        cid = item.get("ID")
        if (service not in EXPECTED or service in identities
                or type(cid) is not str or CONTAINER_ID.fullmatch(cid) is None):
            raise RuntimeScopeError("container_service_identity_invalid")
        identities[service] = cid
    if set(identities) != set(EXPECTED) or len(set(identities.values())) != len(EXPECTED):
        raise RuntimeScopeError("container_service_identity_invalid")
    demos = [item for item in items if item.get("Service") == "demo-seed"]
    if len(demos) > 1:
        raise RuntimeScopeError("duplicate_demo_container")
    if demos:
        cid = demos[0].get("ID")
        if type(cid) is not str or CONTAINER_ID.fullmatch(cid) is None:
            raise RuntimeScopeError("demo_container_identity_invalid")
        if cid in identities.values():
            raise RuntimeScopeError("container_identity_reused")
        identities["demo-seed"] = cid
    return identities


def _read_config_env(container_id: str) -> list[str]:
    if type(container_id) is not str or CONTAINER_ID.fullmatch(container_id) is None:
        raise RuntimeScopeError("invalid_container_identity")
    try:
        run = subprocess.run(
            ["docker", "inspect", "--type", "container", container_id],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeScopeError("docker_inspect_unavailable") from None
    if run.returncode != 0 or len(run.stdout) > 2_000_000:
        raise RuntimeScopeError("docker_inspect_rejected")
    try:
        parsed = json.loads(run.stdout)
    except ValueError:
        raise RuntimeScopeError("docker_inspect_malformed") from None
    if (type(parsed) is not list or len(parsed) != 1
            or type(parsed[0]) is not dict
            or type(parsed[0].get("Id")) is not str
            or not parsed[0]["Id"].startswith(container_id)):
        raise RuntimeScopeError("docker_inspect_identity_mismatch")
    config = parsed[0].get("Config")
    if type(config) is not dict or type(config.get("Env")) is not list:
        raise RuntimeScopeError("docker_inspect_env_unavailable")
    return config["Env"]


def _check_service(service: str, entries: object) -> set[str]:
    """Evaluate exact expected runtime flags without returning any raw values."""
    if type(entries) is not list or len(entries) > 512:
        return {"invalid_runtime_environment"}
    env: dict[str, str] = {}
    for item in entries:
        if type(item) is not str or "=" not in item:
            return {"invalid_runtime_environment"}
        key, value = item.split("=", 1)
        if not key or key in env or len(key) > 150 or len(value) > 100_000:
            return {"duplicate_or_oversized_runtime_environment"}
        env[key] = value

    failures: set[str] = set()
    if service in AI_SERVICES:
        for key, expected in REQUIRED_AI.items():
            if env.get(key) != expected:
                failures.add("runtime_ai_not_disabled")
    else:
        if "AI_PROVIDER" in env and env["AI_PROVIDER"] != "disabled":
            failures.add("runtime_other_ai_provider_enabled")
        if env.get("AI_MODEL", "") != "":
            failures.add("runtime_other_ai_model_configured")
        if env.get("OPENAI_API_KEY", "") != "":
            failures.add("runtime_other_ai_key_configured")
    for key in OPTIONAL_DISABLED_FLAGS:
        if key in env and env[key].strip().lower() not in ALLOWED_DISABLED:
            failures.add("runtime_external_or_ai_adapter_enabled")
    if service not in AI_SERVICES and (
        "ALLOW_EXTERNAL_AI_RESTRICTED" in env
        and env["ALLOW_EXTERNAL_AI_RESTRICTED"] != "false"
    ):
        failures.add("runtime_other_external_ai_restriction_enabled")
    if service == "worker":
        if env.get("OCR_ENABLED") not in ("true", "false"):
            failures.add("runtime_worker_ocr_mode_unclassified")
        if not env.get("OCR_LANGUAGES"):
            failures.add("runtime_worker_ocr_languages_unclassified")
    return failures


def summarize(*, before: list[dict], after: list[dict],
              environment_by_service: dict[str, list[str]], release_sha: str) -> dict:
    if type(release_sha) is not str or SHA.fullmatch(release_sha) is None:
        raise RuntimeScopeError("invalid_release_sha")
    try:
        b = evaluate(before, release_sha=release_sha)
        a = evaluate(after, release_sha=release_sha)
    except (ReadinessError, TypeError, ValueError):
        raise RuntimeScopeError("compose_status_invalid") from None
    if not b["compose_status_complete"] or not a["compose_status_complete"]:
        raise RuntimeScopeError("compose_status_unready")
    before_ids = _observed_ids(before)
    after_ids = _observed_ids(after)
    if before_ids != after_ids:
        raise RuntimeScopeError("container_ids_changed_during_readback")
    if type(environment_by_service) is not dict or set(environment_by_service) != set(before_ids):
        raise RuntimeScopeError("incomplete_runtime_environment_census")
    faults = set()
    for service, entries in environment_by_service.items():
        faults.update(_check_service(service, entries))
    return {
        "schema": _SCHEMA,
        "operator_supplied_release_sha": release_sha,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z"),
        "expected_service_count": len(EXPECTED),
        "inspected_service_count": len(before_ids),
        "container_identity_stable": True,
        "runtime_ai_config_disabled_observed": not faults,
        "check_failures": sorted(faults),
        # This check does not authenticate provider binaries, block egress
        # or validate database-stored integrations or critical Persian claims.
        "actual_egress_isolation_attested": False,
        "database_connector_state_attested": False,
        "persian_critical_extraction_disabled_attested": False,
        "persian_ocr_semantics_attested": False,
        "source_sha_to_image_verified": False,
        "independent_operator_verified": False,
        "real_customer_data_authorized": False,
        "pilot_accepted": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if SHA.fullmatch(args.release_sha) is None:
            raise RuntimeScopeError("invalid_release_sha")
        before = observe(env_file=args.env_file)
        ids = _observed_ids(before)
        environment = {
            name: _read_config_env(cid) for name, cid in ids.items()
        }
        after = observe(env_file=args.env_file)
        result = summarize(
            before=before, after=after, environment_by_service=environment,
            release_sha=args.release_sha,
        )
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(args.output, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except (RuntimeScopeError, ReadinessError, ValueError, TypeError):
        print("NO-GO: runtime AI configuration observation rejected", file=sys.stderr)
        return 2
    except OSError:
        print("NO-GO: private runtime evidence cannot be written", file=sys.stderr)
        return 2
    if not result["runtime_ai_config_disabled_observed"]:
        print("NO-GO: effective container AI configuration unsafe")
        return 1
    print("RUNNING-CONTAINER AI FLAG OBSERVATION PASS (bounded flags only).")
    print("NOT egress, DB connector, Persian OCR fidelity or Pilot GO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
