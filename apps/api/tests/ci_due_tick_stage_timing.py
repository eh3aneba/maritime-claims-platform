"""Synthetic PostgreSQL CI-only stage timing for slow due-tick tests.

Write fixed labels, canonical UTC timestamps and elapsed seconds only.
No inputs, SQL, row contents, credentials or variable values are included.
UTC time anchors correlate each worker interval with the separate read-only
pg_stat_activity wait observer (which records UTC observation timestamps).
"""
from contextlib import contextmanager
from datetime import UTC, datetime
import json
import math
import os
from time import perf_counter

_LOG_PATH = "/tmp/mcri_due_tick_stage_timings.jsonl"


def _observed_at_utc() -> str:
    # Stable UTC representation with fixed precision, suitable for comparing
    # read-only PostgreSQL wait-probe timestamps. No input/user values.
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
_ALLOWED = frozenset({
    "same_tick_seed", "same_tick_schedule", "same_tick_workers", "same_tick_verify",
    # Distinct fixed labels per competing test thread make it possible to
    # correlate a sampled one-way PostgreSQL wait with the still-running worker.
    # These are CI-only stage names: never SQL, provider payloads or session IDs.
    "same_tick_a_session", "same_tick_a_barrier", "same_tick_a_execute",
    "same_tick_b_session", "same_tick_b_barrier", "same_tick_b_execute",
    # Test-only wrappers around the exact binding-lock acquisition and
    # bounded provider metadata read. No query, PID or claim value is logged.
    "same_tick_a_binding_lock", "same_tick_b_binding_lock",
    "same_tick_a_provider_metadata", "same_tick_b_provider_metadata",
    # Only within the synthetic two-worker PG test: isolate the main stages
    # following the binding lock. Fixed labels preserve the privacy boundary.
    "same_tick_a_schedule_verify", "same_tick_b_schedule_verify",
    "same_tick_a_current_document", "same_tick_b_current_document",
    "same_tick_a_source_state", "same_tick_b_source_state",
    "same_tick_a_provider_lineage", "same_tick_b_provider_lineage",
    # CI-only, nested breakdown of the legacy SharePoint/Drive lineage resolver.
    # Identifiers and SQL must never be interpolated into these labels.
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
    "disable_race_seed", "disable_race_schedule", "disable_race_workers",
    "disable_race_verify",
    "disable_race_consume_session", "disable_race_consume_barrier",
    "disable_race_consume_execute", "disable_race_disable_session",
    "disable_race_disable_barrier", "disable_race_disable_execute",
    "sftp_phase_s_setup", "sftp_phase_t_admit", "sftp_phase_u_bind",
    # Fixed labels for three synthetic cross-Session historical Receipt
    # tamper challenges; never derive labels from database or customer data.
    "nested_receipt_freshness_checkpoint3",
    "nested_receipt_freshness_restaging",
    "nested_receipt_freshness_successor_change",
    "sharepoint_v1_admit", "sharepoint_v1_bind",
    "sftp_phase_r_chain", "sftp_phase_s_claim", "sftp_phase_s_authorize",
    "sharepoint_v_prior_chain", "sharepoint_v_claim", "sharepoint_v_authorize",
    "sharepoint_v_execute", "sftp_q_prior_chain", "sftp_r_observe",
})


@contextmanager
def ci_due_tick_stage(label: str):
    if label not in _ALLOWED:
        raise ValueError("Unsupported CI timing stage")
    enabled = (
        os.environ.get("APP_ENV") == "test"
        and os.environ.get("EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST") == "1"
    )
    # A BEGIN marker is durable before the potentially blocked work begins.
    # On a process crash or timeout, the last unmatched BEGIN identifies
    # the interrupted code-owned stage without logging SQL or source values.
    if enabled:
        begin = {
            "event": "ci_due_tick_stage_begin",
            "stage": label,
            "observed_at_utc": _observed_at_utc(),
        }
        with open(_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(begin, sort_keys=True) + "\n")
    started = perf_counter()
    try:
        yield
    finally:
        if enabled:
            record = {
                "event": "ci_due_tick_stage",
                "stage": label,
                "observed_at_utc": _observed_at_utc(),
                "elapsed_seconds": round(perf_counter() - started, 3),
            }
            with open(_LOG_PATH, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")

# Exact allowlist: aggregate counts only within the synthetic legacy lineage
# profiler. Never use SQL text, query parameter values, DB IDs or user labels.
_SQL_AGGREGATE_STAGES = frozenset(
    f"same_tick_{worker}_{phase}"
    for worker in ("a", "b")
    for phase in (
        "legacy_resolution",
        "legacy_admission_integrity",
        "legacy_generation3_integrity",
        "legacy_checkpoint",
        "legacy_generation3_lineage",
        "nested_authorization_integrity",
        "nested_checkpoint_integrity",
        "nested_restaging_integrity",
        "nested_change_integrity",
        "nested_profile_integrity",
    )
)


def ci_due_tick_sql_aggregate(stage: str, count: int, dbapi_seconds: float) -> None:
    """Write bounded counts and DBAPI-execute time, never statement content."""
    if stage not in _SQL_AGGREGATE_STAGES:
        raise ValueError("Unsupported CI SQL-aggregate stage")
    if type(count) is not int or not 0 <= count <= 1_000_000:
        raise ValueError("Invalid CI SQL statement count")
    if type(dbapi_seconds) is not float or not math.isfinite(dbapi_seconds) or not 0 <= dbapi_seconds <= 86_400:
        raise ValueError("Invalid CI DBAPI timing duration")
    enabled = (
        os.environ.get("APP_ENV") == "test"
        and os.environ.get("EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST") == "1"
    )
    if not enabled:
        return
    record = {
        "event": "ci_due_tick_sql_aggregate",
        "stage": stage,
        "observed_at_utc": _observed_at_utc(),
        "statement_count": count,
        "dbapi_execute_seconds": round(dbapi_seconds, 3),
    }
    with open(_LOG_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
