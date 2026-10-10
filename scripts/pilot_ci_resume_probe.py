#!/usr/bin/env python3
"""CI-only synthetic recovery -> controlled Compose resume -> authenticated read.

Run ONLY after pilot_ci_restore_probe.py has verified a synthetic DB/Evidence
clone and stopped all Compose application writers. This is NOT deployment,
fresh-host restore, rollback, operator authorization or a production SLA.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import http.cookiejar
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import pilot_compose_readiness as readiness

SHA_RE = re.compile(r"[a-f0-9]{40}\Z")
TEST_DB = "mcri_performance"
TEST_USER = "mcri_performance"
DEMO_CLAIM = "MCRI-DEMO-MT-ORION"
RESTART_SERVICES = (
    "api", "web", "worker", "governance-webhook-worker",
    "external-evidence-scheduler-worker",
    "external-evidence-observation-worker",
    "external-evidence-review-projector-worker",
)
RUNNING_BEFORE = frozenset(("db", "clamav"))
HEALTH_URL = "http://127.0.0.1:8000/api/v1/health/ready"
LOGIN_URL = "http://127.0.0.1:8000/api/v1/auth/login"
CLAIMS_URL = "http://127.0.0.1:8000/api/v1/claims?search=MCRI-DEMO-MT-ORION"
MAX_HTTP_BYTES = 128 * 1024


class ResumeError(RuntimeError):
    """Only bounded failure categories, never Docker output or auth secrets."""


def validate_guard(*, env_file: str, env: dict[str, str],
                   release_sha: str) -> None:
    if (env_file != ".env.performance"
        or env.get("MCRI_CI_RESUME_PROBE") != "1"
        or env.get("APP_ENV") != "test"
        or env.get("POSTGRES_DB") != TEST_DB
        or env.get("POSTGRES_USER") != TEST_USER
        or not SHA_RE.fullmatch(release_sha)
        or not isinstance(env.get("MCRI_DEMO_PASSWORD"), str)
        or len(env["MCRI_DEMO_PASSWORD"]) < 12):
        raise ResumeError("synthetic CI resume environment guard failed")


def _compose(env_file: str, *args: str) -> list[str]:
    return ["docker", "compose", "--env-file", env_file, *args]


def _run(cmd: list[str], *, timeout: int = 90) -> str:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ResumeError("synthetic Compose resume operation unavailable") from None
    if result.returncode != 0:
        raise ResumeError("synthetic Compose resume operation failed")
    return result.stdout.strip()


def _json(response) -> dict:
    try:
        raw = response.read(MAX_HTTP_BYTES + 1)
        if len(raw) > MAX_HTTP_BYTES or response.status != 200:
            raise ResumeError("synthetic HTTP acceptance response invalid")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ResumeError("synthetic HTTP acceptance response invalid")
    except (OSError, ValueError):
        raise ResumeError("synthetic HTTP acceptance response unavailable") from None
    return parsed


def _get_health() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=4) as response:
            parsed = _json(response)
        return (parsed.get("status") == "ready"
                and parsed.get("check") == "readiness"
                and isinstance(parsed.get("dependencies"), dict)
                and parsed["dependencies"].get("database") == "ok"
                and parsed["dependencies"].get("sftp_runtime") != "unavailable")
    except (OSError, ValueError, ResumeError):
        return False


def _authenticated_claim_read(env: dict[str, str]) -> bool:
    # Authentication is intentionally through the real HTTP route, not DB SQL.
    # No response body, email, username, cookie, session, password, claim id,
    # vessel or Evidence data is logged or retained in the output artifact.
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    body = json.dumps({
        "organization_slug": env.get("MCRI_DEMO_ORG_SLUG", "pilot"),
        "email": env.get("MCRI_DEMO_EMAIL", "manager@demo.mcri.app"),
        "password": env["MCRI_DEMO_PASSWORD"],
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            LOGIN_URL, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with opener.open(req, timeout=8) as response:
            _json(response)
        with opener.open(CLAIMS_URL, timeout=8) as response:
            parsed = _json(response)
        return (
            parsed.get("total") == 1
            and isinstance(parsed.get("items"), list)
            and len(parsed["items"]) == 1
            and parsed["items"][0].get("external_reference") == DEMO_CLAIM
        )
    except (OSError, ValueError, ResumeError, KeyError, TypeError):
        return False


def observe(*, env_file: str, env: dict[str, str], release_sha: str,
            max_attempts: int = 24) -> dict:
    validate_guard(env_file=env_file, env=env, release_sha=release_sha)
    # Guard against the previous probe failing/being skipped: the only
    # running services MUST be db+clamav before any restart mutation.
    original = _run(_compose(env_file, "ps", "--status", "running", "--services"))
    names = original.splitlines()
    if len(names) != len(set(names)) or set(names) != RUNNING_BEFORE:
        raise ResumeError("synthetic Compose writer-stop baseline not verified")

    _run(_compose(env_file, "start", *RESTART_SERVICES), timeout=120)

    ready = False
    # A bounded check for the ACTUAL containers, not a fabricated health flag.
    for attempt in range(max_attempts):
        try:
            status = readiness.evaluate(readiness.observe(env_file=env_file),
                                        release_sha=release_sha)
            if status["compose_status_complete"] and _get_health():
                ready = True
                break
        except readiness.ReadinessError:
            pass
        if attempt + 1 < max_attempts:
            time.sleep(3)
    if not ready:
        raise ResumeError("synthetic resumed stack not healthy before timeout")

    if not _authenticated_claim_read(env):
        raise ResumeError("synthetic authenticated claim read after resume failed")

    return {
        "schema": "mcri-synthetic-ci-post-recovery-resume-v1",
        "observed_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z"),
        "operator_supplied_release_sha": release_sha,
        "environment": "ephemeral_ci_synthetic_only",
        "writers_observed_stopped_before_restart": True,
        "writers_started": len(RESTART_SERVICES),
        "compose_services_healthy_after_restart": True,
        "real_http_api_readiness_after_restart": True,
        "synthetic_authenticated_claim_read_after_restart": True,
        "real_customer_evidence_verified": False,
        "fresh_host_restore_verified": False,
        "rollback_to_previous_release_verified": False,
        "independent_operator_approved": False,
        "pilot_authorized": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = observe(env_file=args.env_file, env=dict(os.environ),
                         release_sha=args.release_sha)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2, sort_keys=True)
            stream.write("\n")
    except ResumeError as exc:
        print("NO-GO: " + str(exc), file=sys.stderr)
        return 2
    except OSError:
        print("NO-GO: cannot create exclusive synthetic resume record",
              file=sys.stderr)
        return 2
    print("SYNTHETIC POST-RECOVERY STACK RESUME + AUTHENTICATED READ PASS.")
    print("This is NOT a real-host restore, version rollback, or Pilot GO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
