"""Synthetic PostgreSQL CI-only stage timing for slow due-tick tests.

Write fixed labels, canonical UTC timestamps and elapsed seconds only.
No inputs, SQL, row contents, credentials or variable values are included.
UTC time anchors correlate each worker interval with the separate read-only
pg_stat_activity wait observer (which records UTC observation timestamps).
"""
from contextlib import contextmanager
from datetime import UTC, datetime
import json
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
    "disable_race_seed", "disable_race_schedule", "disable_race_workers",
    "disable_race_verify",
    "disable_race_consume_session", "disable_race_consume_barrier",
    "disable_race_consume_execute", "disable_race_disable_session",
    "disable_race_disable_barrier", "disable_race_disable_execute",
    "sftp_phase_s_setup", "sftp_phase_t_admit", "sftp_phase_u_bind",
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
