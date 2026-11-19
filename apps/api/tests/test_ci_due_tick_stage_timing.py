"""Offline CI-only regression for bounded, fixed-label due-tick worker timing.

These tests do not connect to PostgreSQL or process Evidence. Stage logs may
contain only pre-approved labels, canonical UTC timestamps, bounded durations
and fixed event keys.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
import json

import pytest

from tests import ci_due_tick_stage_timing as stage


def test_parallel_worker_stages_are_distinguishable_and_privacy_safe(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    log = tmp_path / "synthetic-stages.jsonl"
    monkeypatch.setattr(stage, "_LOG_PATH", str(log))
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST", "1")
    labels = (
        "same_tick_a_barrier", "same_tick_a_execute",
        "same_tick_b_barrier", "same_tick_b_execute",
        "same_tick_a_binding_lock", "same_tick_b_binding_lock",
        "same_tick_a_provider_metadata", "same_tick_b_provider_metadata",
        "same_tick_a_schedule_verify", "same_tick_b_schedule_verify",
        "same_tick_a_current_document", "same_tick_b_current_document",
        "same_tick_a_source_state", "same_tick_b_source_state",
        "same_tick_a_provider_lineage", "same_tick_b_provider_lineage",
        "same_tick_a_legacy_resolution", "same_tick_b_legacy_resolution",
        "same_tick_a_legacy_admission_integrity", "same_tick_b_legacy_admission_integrity",
        "same_tick_a_legacy_generation3_integrity", "same_tick_b_legacy_generation3_integrity",
        "same_tick_a_legacy_checkpoint", "same_tick_b_legacy_checkpoint",
        "same_tick_a_legacy_generation3_lineage", "same_tick_b_legacy_generation3_lineage",
        "same_tick_a_nested_authorization_integrity", "same_tick_b_nested_authorization_integrity",
        "same_tick_a_nested_checkpoint_integrity", "same_tick_b_nested_checkpoint_integrity",
        "same_tick_a_nested_restaging_integrity", "same_tick_b_nested_restaging_integrity",
        "same_tick_a_nested_change_integrity", "same_tick_b_nested_change_integrity",
        "same_tick_a_nested_profile_integrity", "same_tick_b_nested_profile_integrity",
        "same_tick_a_integrity", "same_tick_b_integrity",
        "same_tick_a_audit_write", "same_tick_b_audit_write",
        "same_tick_a_commit", "same_tick_b_commit",
        "same_tick_a_refresh", "same_tick_b_refresh",
        "disable_race_consume_execute", "disable_race_disable_execute",
        # Controlled cross-Session nested receipt test stages.
        "nested_receipt_freshness_checkpoint3",
        "nested_receipt_freshness_restaging",
        "nested_receipt_freshness_successor_change",
    )

    def mark(label: str) -> None:
        with stage.ci_due_tick_stage(label):
            pass

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(mark, labels))

    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(records) == len(labels) * 2
    for label in labels:
        events = [row for row in records if row["stage"] == label]
        assert len(events) == 2
        assert {row["event"] for row in events} == {
            "ci_due_tick_stage_begin", "ci_due_tick_stage",
        }
    for record in records:
        assert record["stage"] in labels
        assert set(record) <= {
            "event", "stage", "elapsed_seconds", "observed_at_utc",
        }
        timestamp = record["observed_at_utc"]
        assert isinstance(timestamp, str)
        instant = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        assert instant.tzinfo == UTC
        assert instant.strftime("%Y-%m-%dT%H:%M:%S.%fZ") == timestamp
        if record["event"] == "ci_due_tick_stage":
            assert isinstance(record["elapsed_seconds"], float)
            assert record["elapsed_seconds"] >= 0
    for label in labels:
        marks = [row for row in records if row["stage"] == label]
        begins = [row for row in marks if row["event"] == "ci_due_tick_stage_begin"]
        ends = [row for row in marks if row["event"] == "ci_due_tick_stage"]
        assert begins[0]["observed_at_utc"] <= ends[0]["observed_at_utc"]


def test_timing_is_disabled_outside_synthetic_pg_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    log = tmp_path / "must-not-exist.jsonl"
    monkeypatch.setattr(stage, "_LOG_PATH", str(log))
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST", "1")
    with stage.ci_due_tick_stage("same_tick_a_execute"):
        pass
    assert not log.exists()


def test_unapproved_stage_labels_cannot_be_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    log = tmp_path / "must-not-exist.jsonl"
    monkeypatch.setattr(stage, "_LOG_PATH", str(log))
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST", "1")
    with pytest.raises(ValueError, match="Unsupported CI timing stage"):
        with stage.ci_due_tick_stage("customer-identifier-or-SQL-text"):
            pass
    assert not log.exists()


def test_ci_sql_aggregate_records_only_fixed_counts_and_seconds(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    log = tmp_path / "sql-summary.jsonl"
    monkeypatch.setattr(stage, "_LOG_PATH", str(log))
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST", "1")
    stage.ci_due_tick_sql_aggregate("same_tick_b_legacy_admission_integrity", 27, 0.31415)
    stage.ci_due_tick_sql_aggregate("same_tick_a_legacy_generation3_lineage", 0, 0.0)
    stage.ci_due_tick_sql_aggregate("same_tick_b_nested_authorization_integrity", 4, 0.122)
    stage.ci_due_tick_sql_aggregate("same_tick_a_nested_checkpoint_integrity", 18, 0.05)
    records = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(records) == 4
    for record in records:
        assert set(record) == {
            "event", "stage", "observed_at_utc",
            "statement_count", "dbapi_execute_seconds",
        }
        assert record["event"] == "ci_due_tick_sql_aggregate"
        assert isinstance(record["statement_count"], int)
        assert isinstance(record["dbapi_execute_seconds"], float)
    assert records[0]["statement_count"] == 27
    assert records[0]["dbapi_execute_seconds"] == 0.314
    assert records[1]["statement_count"] == 0


@pytest.mark.parametrize(
    ("label", "count", "duration"),
    [
        ("claim-sensitive-token", 2, 0.1),
        ("same_tick_a_execute", 2, 0.1),
        ("same_tick_b_legacy_resolution", True, 0.1),
        ("same_tick_b_legacy_resolution", -1, 0.1),
        ("same_tick_b_legacy_resolution", 1_000_001, 0.1),
        ("same_tick_b_legacy_resolution", 2, float("nan")),
        ("same_tick_b_legacy_resolution", 2, float("inf")),
        ("same_tick_b_legacy_resolution", 2, -1.0),
    ],
)
def test_ci_sql_aggregate_rejects_invalid_inputs_without_writing(
    monkeypatch: pytest.MonkeyPatch, tmp_path, label, count, duration,
) -> None:
    log = tmp_path / "no-sensitive-sql-logging.jsonl"
    monkeypatch.setattr(stage, "_LOG_PATH", str(log))
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST", "1")
    with pytest.raises(ValueError):
        stage.ci_due_tick_sql_aggregate(label, count, duration)
    assert not log.exists()


def test_ci_sql_aggregate_disabled_outside_postgres_ci(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    log = tmp_path / "must-not-exist.jsonl"
    monkeypatch.setattr(stage, "_LOG_PATH", str(log))
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST", "1")
    stage.ci_due_tick_sql_aggregate("same_tick_a_legacy_resolution", 10, 0.05)
    assert not log.exists()
