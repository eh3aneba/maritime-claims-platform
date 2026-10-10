"""Synthetic PostgreSQL CI-only stage durations for slow due-tick tests.

Write fixed stage labels and elapsed seconds only. No inputs, SQL, row
contents, credentials or variable values are ever included.
"""
from contextlib import contextmanager
import json
import os
from time import perf_counter

_LOG_PATH = "/tmp/mcri_due_tick_stage_timings.jsonl"
_ALLOWED = frozenset({
    "same_tick_seed", "same_tick_schedule", "same_tick_workers", "same_tick_verify",
    "disable_race_seed", "disable_race_schedule", "disable_race_workers",
    "disable_race_verify",
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
    started = perf_counter()
    try:
        yield
    finally:
        if (os.environ.get("APP_ENV") == "test"
                and os.environ.get("EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST") == "1"):
            record = {"event": "ci_due_tick_stage", "stage": label,
                      "elapsed_seconds": round(perf_counter() - started, 3)}
            with open(_LOG_PATH, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
