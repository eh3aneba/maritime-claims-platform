#!/usr/bin/env python3
"""Read-only Pilot v1 Compose service-status evidence (NOT release approval).

Inspects existing Docker Compose containers, without starting/stopping them,
executing into containers, reading their environment, or logging raw Docker
output. A status snapshot does not prove host security, storage restore,
image/release SHA identity, operator review or production readiness.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

SHA = re.compile(r"[a-f0-9]{40}\Z")
HEALTHY = frozenset(("db", "clamav", "api", "web"))
RUNNING = frozenset((
    "worker",
    "governance-webhook-worker",
    "external-evidence-scheduler-worker",
    "external-evidence-observation-worker",
    "external-evidence-review-projector-worker",
))
ONESHOT = frozenset(("migrate", "preflight"))
EXPECTED = tuple(sorted(HEALTHY | RUNNING | ONESHOT))
OPTIONAL = frozenset(("demo-seed",))
SAFE_STATES = frozenset(("running", "exited", "created", "restarting", "paused", "dead"))
SAFE_HEALTH = frozenset(("healthy", "unhealthy", "starting", "none"))


class ReadinessError(RuntimeError):
    """Bounded failure string; no raw Docker stderr, paths or credentials."""


def parse_ps(raw: str) -> list[dict]:
    if not isinstance(raw, str) or not raw.strip():
        raise ReadinessError("empty Docker Compose service-status response")
    try:
        parsed = json.loads(raw)
    except ValueError:
        try:
            parsed = [json.loads(line) for line in raw.splitlines() if line.strip()]
        except ValueError:
            raise ReadinessError("malformed Docker Compose JSON service-status response") from None
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list) or not all(isinstance(x, dict) for x in parsed):
        raise ReadinessError("unexpected Docker Compose service-status structure")
    return parsed


def evaluate(items: list[dict], *, release_sha: str) -> dict:
    if not SHA.fullmatch(release_sha):
        raise ReadinessError("full lowercase candidate SHA required")
    if not isinstance(items, list):
        raise ReadinessError("invalid service-status collection")
    found: dict[str, dict] = {}
    unknown = 0
    duplicates = 0
    for item in items:
        if not isinstance(item, dict):
            raise ReadinessError("malformed Compose service entry")
        name = item.get("Service")
        if not isinstance(name, str):
            raise ReadinessError("Compose service label missing")
        if name not in EXPECTED and name not in OPTIONAL:
            unknown += 1
            continue
        if name in found:
            duplicates += 1
            continue
        found[name] = item

    statuses: dict[str, dict] = {}
    for service in EXPECTED:
        item = found.get(service)
        if item is None:
            statuses[service] = {"observed": False, "status": "missing",
                                 "health": "none", "exit_code_ok": False, "pass": False}
            continue
        state = item.get("State")
        health = item.get("Health")
        state = state if state in SAFE_STATES else "unknown"
        health = health.lower() if isinstance(health, str) else "none"
        health = health if health in SAFE_HEALTH else "unknown"
        exit_code = item.get("ExitCode")
        exit_ok = type(exit_code) is int and exit_code == 0
        if service in HEALTHY:
            passed = state == "running" and health == "healthy"
        elif service in RUNNING:
            passed = state == "running" and health not in ("unhealthy", "unknown")
        else:
            passed = state == "exited" and exit_ok
        statuses[service] = {"observed": True, "status": state, "health": health,
                             "exit_code_ok": exit_ok if service in ONESHOT else False,
                             "pass": passed}

    optional = found.get("demo-seed")
    optional_ok = optional is None or (
        optional.get("State") == "exited"
        and type(optional.get("ExitCode")) is int
        and optional["ExitCode"] == 0
    )
    complete = all(x["pass"] for x in statuses.values()) and not unknown and not duplicates and optional_ok
    return {
        "schema": "mcri-pilot-compose-readiness-v1",
        "operator_supplied_release_sha": release_sha,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z"),
        "service_count_expected": len(EXPECTED),
        "service_count_passing": sum(x["pass"] for x in statuses.values()),
        "unknown_service_count": unknown,
        "duplicate_service_count": duplicates,
        "optional_demo_seed_safe": optional_ok,
        "services": statuses,
        "compose_status_complete": complete,
        "image_digest_verified": False,
        "deployed_release_identity_verified": False,
        "fresh_host_verified": False,
        "independent_operator_verified": False,
        "pilot_authorized": False,
    }


def observe(*, env_file: str, timeout: int = 20) -> list[dict]:
    try:
        result = subprocess.run(
            ["docker", "compose", "--env-file", env_file, "ps", "--all", "--format", "json"],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ReadinessError("Docker Compose status observation unavailable") from None
    if result.returncode != 0:
        # Raw Docker output may contain sensitive configuration, never include.
        raise ReadinessError("Docker Compose status observation failed") from None
    return parse_ps(result.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, help="Local private Pilot env file")
    parser.add_argument("--release-sha", required=True, help="Operator-supplied exact candidate SHA")
    parser.add_argument("--output", required=True, type=Path, help="Exclusive new JSON evidence path")
    args = parser.parse_args(argv)
    try:
        if not SHA.fullmatch(args.release_sha):
            raise ReadinessError("full lowercase candidate SHA required")
        evidence = evaluate(observe(env_file=args.env_file), release_sha=args.release_sha)
        with args.output.open("x", encoding="utf-8") as out:
            json.dump(evidence, out, sort_keys=True, indent=2)
            out.write("\n")
    except ReadinessError as exc:
        print(f"NO-GO: {exc}", file=sys.stderr)
        return 2
    except OSError:
        print("NO-GO: cannot exclusively write status evidence", file=sys.stderr)
        return 2
    if not evidence["compose_status_complete"]:
        print("NO-GO: Compose service status/readiness incomplete; see private JSON record.")
        return 1
    print("COMPOSE STATUS COMPLETE: identity, host, recovery and operator proof still required.")
    print("This is NOT Pilot GO or release authorization.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
