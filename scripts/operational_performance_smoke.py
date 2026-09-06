#!/usr/bin/env python3
"""Bounded live-stack performance smoke for Phase 14.2.

This harness is intentionally dependency-free and privacy-minimal. It authenticates
against the seeded design-partner environment, keeps the bearer token in memory,
and records only aggregate operational timing/status data. It never writes response
bodies, credentials, tokens, cookies, claim IDs, claim text, or evidence content.
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Scenario:
    label: str
    path: str
    authenticated: bool
    p95_budget_ms: float


@dataclass(frozen=True)
class Sample:
    ok: bool
    status_code: int | None
    duration_ms: float


def _bounded_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer") from exc
    if value < minimum or value > maximum:
        raise SystemExit(f"{name} must be between {minimum} and {maximum}")
    return value


def _bounded_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be numeric") from exc
    if value < minimum or value > maximum:
        raise SystemExit(f"{name} must be between {minimum} and {maximum}")
    return value


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil((percentile / 100.0) * len(ordered)))
    return ordered[rank - 1]


def _request(
    *,
    base_url: str,
    path: str,
    timeout_seconds: float,
    bearer_token: str | None = None,
) -> Sample:
    headers = {"Accept": "application/json", "User-Agent": "mcri-phase-14-2-performance-smoke"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    request = Request(f"{base_url}{path}", method="GET", headers=headers)
    started = perf_counter()
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - target is controlled by CI env
            response.read()
            status_code = int(response.status)
        duration_ms = (perf_counter() - started) * 1000
        return Sample(ok=200 <= status_code < 300, status_code=status_code, duration_ms=duration_ms)
    except HTTPError as exc:
        duration_ms = (perf_counter() - started) * 1000
        return Sample(ok=False, status_code=int(exc.code), duration_ms=duration_ms)
    except (URLError, TimeoutError, OSError):
        duration_ms = (perf_counter() - started) * 1000
        return Sample(ok=False, status_code=None, duration_ms=duration_ms)


def _login(*, base_url: str, timeout_seconds: float) -> str:
    organization = os.getenv("MCRI_DEMO_ORG_SLUG", "pilot").strip()
    email = os.getenv("MCRI_DEMO_EMAIL", "manager@demo.mcri.app").strip()
    password = os.getenv("MCRI_DEMO_PASSWORD", "")
    if len(password) < 12:
        raise SystemExit("MCRI_DEMO_PASSWORD must be set to the seeded 12+ character CI credential")

    body = json.dumps(
        {"organization_slug": organization, "email": email, "password": password}
    ).encode("utf-8")
    request = Request(
        f"{base_url}/auth/login",
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "mcri-phase-14-2-performance-smoke",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - target is controlled by CI env
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit("Performance smoke authentication failed") from exc

    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise SystemExit("Performance smoke authentication did not return an access token")
    return token


def _run_scenario(
    *,
    scenario: Scenario,
    base_url: str,
    bearer_token: str,
    warmup_requests: int,
    sample_requests: int,
    concurrency: int,
    timeout_seconds: float,
    max_error_ratio: float,
) -> dict[str, object]:
    token = bearer_token if scenario.authenticated else None

    for _ in range(warmup_requests):
        _request(
            base_url=base_url,
            path=scenario.path,
            timeout_seconds=timeout_seconds,
            bearer_token=token,
        )

    started = perf_counter()
    samples: list[Sample] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(
                _request,
                base_url=base_url,
                path=scenario.path,
                timeout_seconds=timeout_seconds,
                bearer_token=token,
            )
            for _ in range(sample_requests)
        ]
        for future in as_completed(futures):
            samples.append(future.result())
    elapsed_seconds = max(perf_counter() - started, 0.000001)

    durations = [sample.duration_ms for sample in samples]
    successes = sum(1 for sample in samples if sample.ok)
    failures = len(samples) - successes
    error_ratio = failures / len(samples) if samples else 1.0
    status_counts = Counter(
        str(sample.status_code) if sample.status_code is not None else "transport_error"
        for sample in samples
    )
    p95_ms = _percentile(durations, 95)
    budget_passed = error_ratio <= max_error_ratio and p95_ms <= scenario.p95_budget_ms

    return {
        "label": scenario.label,
        "request_count": len(samples),
        "success_count": successes,
        "failure_count": failures,
        "error_ratio": round(error_ratio, 6),
        "status_counts": dict(sorted(status_counts.items())),
        "latency_ms": {
            "p50": round(_percentile(durations, 50), 3),
            "p95": round(p95_ms, 3),
            "p99": round(_percentile(durations, 99), 3),
            "max": round(max(durations) if durations else 0.0, 3),
        },
        "throughput_requests_per_second": round(len(samples) / elapsed_seconds, 3),
        "ci_budget": {
            "max_error_ratio": max_error_ratio,
            "p95_ms": scenario.p95_budget_ms,
            "passed": budget_passed,
        },
    }


def main() -> int:
    base_url = os.getenv("MCRI_API_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
    output_path = Path(os.getenv("MCRI_PERF_OUTPUT", "artifacts/performance-smoke.json"))
    warmup_requests = _bounded_int("MCRI_PERF_WARMUP_REQUESTS", 3, minimum=0, maximum=20)
    sample_requests = _bounded_int("MCRI_PERF_SAMPLE_REQUESTS", 24, minimum=5, maximum=200)
    concurrency = _bounded_int("MCRI_PERF_CONCURRENCY", 4, minimum=1, maximum=32)
    timeout_seconds = _bounded_float("MCRI_PERF_TIMEOUT_SECONDS", 10.0, minimum=1.0, maximum=60.0)
    max_error_ratio = _bounded_float("MCRI_PERF_MAX_ERROR_RATIO", 0.0, minimum=0.0, maximum=1.0)

    scenarios = [
        Scenario(
            label="api_liveness",
            path="/health/live",
            authenticated=False,
            p95_budget_ms=_bounded_float(
                "MCRI_PERF_LIVENESS_P95_MS", 1000.0, minimum=10.0, maximum=30000.0
            ),
        ),
        Scenario(
            label="database_readiness",
            path="/health/ready",
            authenticated=False,
            p95_budget_ms=_bounded_float(
                "MCRI_PERF_READINESS_P95_MS", 1500.0, minimum=10.0, maximum=30000.0
            ),
        ),
        Scenario(
            label="authenticated_claim_list",
            path=f"/claims?{urlencode({'search': 'MCRI-DEMO-MT-ORION', 'limit': 20})}",
            authenticated=True,
            p95_budget_ms=_bounded_float(
                "MCRI_PERF_CLAIM_LIST_P95_MS", 2500.0, minimum=10.0, maximum=30000.0
            ),
        ),
    ]

    bearer_token = _login(base_url=base_url, timeout_seconds=timeout_seconds)
    results = [
        _run_scenario(
            scenario=scenario,
            base_url=base_url,
            bearer_token=bearer_token,
            warmup_requests=warmup_requests,
            sample_requests=sample_requests,
            concurrency=concurrency,
            timeout_seconds=timeout_seconds,
            max_error_ratio=max_error_ratio,
        )
        for scenario in scenarios
    ]
    overall_passed = all(bool(result["ci_budget"]["passed"]) for result in results)  # type: ignore[index]

    artifact = {
        "schema_version": "1.0",
        "phase": "14.2",
        "generated_at": datetime.now(UTC).isoformat(),
        "harness": {
            "warmup_requests_per_scenario": warmup_requests,
            "sample_requests_per_scenario": sample_requests,
            "concurrency": concurrency,
            "timeout_seconds": timeout_seconds,
        },
        "privacy_boundary": "aggregate_operational_metadata_only",
        "overall_passed": overall_passed,
        "scenarios": results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(artifact, indent=2, sort_keys=True))
    return 0 if overall_passed else 1


if __name__ == "__main__":
    sys.exit(main())
