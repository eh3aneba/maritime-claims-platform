#!/usr/bin/env python3
"""Host-only synthetic fail-and-recover signal checks after first-manual rollback.

Actual Docker service failures and readback, NOT a real customer alert channel.
Does not send notifications, modify the DB, delete Evidence, or grant Pilot GO.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

import pilot_compose_readiness as readiness
import pilot_demo_docker_target as docker_target
import pilot_ci_first_manual_rollback as rollback
from pilot_ci_first_manual_recovery import ENV_FILE, admitted_source
from pilot_running_image_identity import _service_ids, inspect_image_ids

SHA = re.compile(r"[0-9a-f]{40}\Z")
ROOT = Path(__file__).resolve().parents[1]
PROOF = Path("artifacts/first-manual-ci/fault-detection.json")
PRIOR_PROOF = Path("artifacts/first-manual-ci/rollback.json")
API_HEALTH = "http://127.0.0.1:8000/api/v1/health/ready"
SIGNALS = (
    ("api", "api_liveness_and_readiness"),
    ("worker", "document_worker_and_queue"),
)


class FaultProbeError(RuntimeError):
    """Fixed safe categories only; no raw Docker or request output."""


def demand(test: bool, reason: str) -> None:
    if not test:
        raise FaultProbeError(reason)


def run(command: list[str], phase: str, *, timeout: int = 120) -> str:
    try:
        process = subprocess.run(command, capture_output=True, text=True,
                                 timeout=timeout, check=False, cwd=ROOT)
    except (OSError, subprocess.TimeoutExpired):
        raise FaultProbeError(phase + "_unavailable") from None
    demand(process.returncode == 0, phase + "_failed")
    return process.stdout.strip()


def compose(*args: str, timeout: int = 120) -> None:
    run(["docker", "compose", "--project-directory", str(ROOT),
         "--env-file", str(ROOT / ENV_FILE), "-f", str(ROOT / "docker-compose.yml"),
         *args], "synthetic_compose_operation", timeout=timeout)


def http_ready() -> bool:
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(API_HEALTH, timeout=3) as response:
            body = response.read(8192)
            if response.status != 200:
                return False
            payload = json.loads(body)
            return payload.get("status") == "ready" and payload.get("check") == "readiness"
    except (OSError, URLError, ValueError, TypeError):
        return False


def status(sha: str) -> tuple[list[dict], dict]:
    items = readiness.observe(env_file=ENV_FILE)
    return items, readiness.evaluate(items, release_sha=sha)


def validate_scope(env: dict[str, str]) -> str:
    demand(env.get("MCRI_CI_FIRST_MANUAL_FAULT_PROBE") == "1"
           and admitted_source(ENV_FILE, env), "not_an_admitted_hosted_synthetic_pilot")
    actual = run(["git", "rev-parse", "HEAD"], "current_checkout")
    demand(SHA.fullmatch(actual) is not None, "invalid_candidate_sha")
    # A prior CI step genuinely exercised the bounded six-backend rollback.
    # A marker file is evidence of the expected step, not operator attestation.
    demand(PRIOR_PROOF.is_file() and not PRIOR_PROOF.is_symlink()
           and PRIOR_PROOF.stat().st_size <= 8192, "rollback_stage_missing")
    try:
        prior = json.loads(PRIOR_PROOF.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise FaultProbeError("rollback_stage_invalid") from None
    demand(prior.get("schema") == "mcri-first-manual-synthetic-backend-rollback-v1"
           and prior.get("from_sha") == actual
           and prior.get("app_env") == "pilot"
           and prior.get("pilot_authorized") is False
           and prior.get("backend_services_recreated_and_image_ids_matched") == 6,
           "rollback_stage_not_verified")
    return actual


def detect(service: str, sha: str) -> None:
    demand(service in dict(SIGNALS), "unapproved_fault_service")
    _, evidence = status(sha)
    demand(not evidence["compose_status_complete"], "outage_not_detected")
    selected = evidence["services"][service]
    demand(selected["observed"] and selected["status"] == "exited"
           and not selected["pass"], "target_outage_not_observed")
    # Unexpected other failures are not a successful scoped test.
    demand(all(row["pass"] for key, row in evidence["services"].items()
               if key != service), "unrelated_service_unhealthy")
    if service == "api":
        demand(not http_ready(), "api_readiness_ignored_failure")


def healthy(sha: str) -> bool:
    try:
        _, evidence = status(sha)
        return evidence["compose_status_complete"] and http_ready()
    except readiness.ReadinessError:
        return False


def recover(service: str, sha: str, *, attempts: int = 25) -> None:
    compose("start", service, timeout=90)
    for n in range(attempts):
        if healthy(sha):
            return
        if n + 1 < attempts:
            time.sleep(3)
    raise FaultProbeError("restarted_stack_not_healthy")


def exercise_once(service: str, sha: str) -> None:
    demand(service in dict(SIGNALS), "unapproved_fault_service")
    stopped = False
    recovered = False
    try:
        compose("stop", service, timeout=90)
        stopped = True
        detect(service, sha)
        recover(service, sha)
        recovered = True
    finally:
        if stopped and not recovered:
            # Best-effort recovery on failed assertion, but the test remains
            # a hard failure. Never touch a service we did not stop.
            try:
                compose("start", service, timeout=90)
            except FaultProbeError:
                pass


def observe(env: dict[str, str]) -> dict:
    sha = validate_scope(env)
    docker_target.observe()
    demand(healthy(sha), "unhealthy_initial_synthetic_stack")
    initial, _ = status(sha)
    initial_ids = inspect_image_ids(initial)
    source, audit, revision = rollback.snapshot()
    original_bytes = rollback.read_originals(env)

    for service, _ in SIGNALS:
        exercise_once(service, sha)

    demand(healthy(sha), "unhealthy_recovered_synthetic_stack")
    final, _ = status(sha)
    demand(inspect_image_ids(final) == initial_ids,
           "unexpected_runtime_image_change")
    demand(_service_ids(final) == _service_ids(initial),
           "unexpected_container_recreation")
    demand(rollback.read_originals(env) == original_bytes,
           "synthetic_original_document_changed")
    after, later_audit, after_revision = rollback.snapshot()
    demand(after == source and after_revision == revision,
           "synthetic_lineage_or_schema_changed")
    demand(all(later_audit.get(k) == v for k, v in audit.items()),
           "prior_synthetic_audit_changed")

    return {
        "schema": "mcri-first-manual-hosted-fault-probe-v1",
        "candidate_sha": sha,
        "observed_at_utc": datetime.now(timezone.utc)
            .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "app_env": "pilot",
        "signals_tested": [label for _, label in SIGNALS],
        "real_compose_outage_detected_count": len(SIGNALS),
        "api_http_outage_detected": True,
        "service_restarts_and_readiness_passed": True,
        "runtime_image_ids_and_container_identities_unchanged": True,
        "originals_and_business_lineage_preserved": True,
        "prior_audit_rows_preserved": True,
        "postgres_migration_unchanged": True,
        "external_alert_delivered_and_acknowledged": False,
        "independent_monitoring_owner_approved": False,
        "real_host_monitoring_verified": False,
        "customer_data_used": False,
        "pilot_authorized": False,
    }


def main() -> int:
    try:
        report = observe(dict(os.environ))
        with PROOF.open("x", encoding="utf-8") as output:
            json.dump(report, output, indent=2, sort_keys=True)
            output.write("\n")
    except (FaultProbeError, OSError, ValueError, RuntimeError):
        print("NO-GO: bounded hosted synthetic fault probe rejected", file=sys.stderr)
        return 2
    print("PASS: hosted synthetic API and worker outage detection/recovery; no real alert delivery or Pilot GO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
