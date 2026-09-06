from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HARNESS_PATH = ROOT / "scripts" / "operational_performance_smoke.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("mcri_operational_performance_smoke", HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_percentile_uses_nearest_rank_and_handles_empty_samples() -> None:
    harness = _load_harness()

    assert harness._percentile([], 95) == 0.0
    assert harness._percentile([10.0, 20.0, 30.0, 40.0], 50) == 20.0
    assert harness._percentile([10.0, 20.0, 30.0, 40.0], 95) == 40.0


def test_scenario_summary_persists_only_safe_label_and_aggregates(monkeypatch) -> None:
    harness = _load_harness()
    samples = iter(
        [
            harness.Sample(ok=True, status_code=200, duration_ms=10.0),
            harness.Sample(ok=True, status_code=200, duration_ms=20.0),
            harness.Sample(ok=False, status_code=503, duration_ms=30.0),
        ]
    )

    monkeypatch.setattr(harness, "_request", lambda **_: next(samples))
    scenario = harness.Scenario(
        label="safe_claim_read",
        path="/claims?search=must-not-be-persisted",
        authenticated=True,
        p95_budget_ms=100.0,
    )

    summary = harness._run_scenario(
        scenario=scenario,
        base_url="http://example.invalid/api/v1",
        bearer_token="must-not-be-persisted-token",
        warmup_requests=0,
        sample_requests=3,
        concurrency=1,
        timeout_seconds=1.0,
        max_error_ratio=0.5,
    )

    serialized = json.dumps(summary)
    assert summary["label"] == "safe_claim_read"
    assert summary["request_count"] == 3
    assert summary["failure_count"] == 1
    assert summary["status_counts"] == {"200": 2, "503": 1}
    assert summary["ci_budget"]["passed"] is True
    assert "must-not-be-persisted" not in serialized
    assert "example.invalid" not in serialized
