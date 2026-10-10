"""Privacy-safe, read-only PostgreSQL lock telemetry for one synthetic Pilot CI leg.

Never print connection URLs, SQL text, query identifiers, SQL parameters, or
application data. This observer is optional diagnostic instrumentation; only
the unchanged pytest/gate result determines whether the CI run passes.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
import time
from urllib.parse import urlsplit


_MAX_ROWS = 32
_SQL = """
SELECT pid, state, wait_event_type, wait_event,
       COALESCE(EXTRACT(EPOCH FROM clock_timestamp() - xact_start)::integer, 0),
       pg_blocking_pids(pid)
FROM pg_stat_activity
WHERE datname = current_database()
  AND pid <> pg_backend_pid()
  AND backend_type = 'client backend'
ORDER BY pid
LIMIT 33
"""


def _ci_database_url() -> str:
    if (os.environ.get("APP_ENV") != "test"
            or os.environ.get("EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST") != "1"):
        raise ValueError("CI-only due-tick observer guard not satisfied")
    raw = os.environ.get("MCRI_TEST_DATABASE_URL", "")
    if raw.startswith("postgresql+psycopg://"):
        raw = "postgresql://" + raw[len("postgresql+psycopg://"):]
    parsed = urlsplit(raw)
    if (parsed.scheme != "postgresql"
            or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
            or parsed.path != "/mcri_concurrency_ci"):
        raise ValueError("Observer requires the synthetic local PostgreSQL CI database")
    return raw


def safe_summary(rows: list[tuple]) -> dict:
    """Whitelisted PostgreSQL metadata only: never accept/serialize query text."""
    sessions = []
    for pid, state, wait_type, wait_event, age, blocking in rows[:_MAX_ROWS]:
        sessions.append({
            "pid": int(pid),
            "state": state if state in ("active", "idle", "idle in transaction",
                                        "idle in transaction (aborted)") else "other",
            "wait_type": wait_type if wait_type in ("Lock", "IO", "Client", "LWLock",
                                                   "Timeout", "Activity", "IPC") else None,
            "wait_event": str(wait_event)[:64] if wait_event else None,
            "transaction_age_seconds": max(0, int(age)),
            "blocking_pids": [int(value) for value in (blocking or [])][:16],
        })
    return {
        "client_count": len(sessions),
        "blocked_count": sum(bool(s["blocking_pids"]) for s in sessions),
        "sessions": sessions,
        "truncated": len(rows) > _MAX_ROWS,
    }


def observe_once() -> dict:
    import psycopg  # locked test dependency; avoid importing it in pure unit tests

    uri = _ci_database_url()
    with psycopg.connect(
        uri,
        connect_timeout=5,
        autocommit=True,
        application_name="mcri_ci_due_tick_observer",
        options="-c statement_timeout=3000 -c lock_timeout=1000",
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(_SQL)
            return safe_summary(cursor.fetchall())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded CI-only PostgreSQL wait telemetry")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--max-samples", type=int, default=20)
    args = parser.parse_args(argv)
    if not (15 <= args.interval_seconds <= 300 and 1 <= args.max_samples <= 25):
        parser.error("interval must be 15..300s and samples 1..25")

    try:
        _ci_database_url()
    except (ValueError, TypeError):
        print(json.dumps({"event": "pg_wait_probe_disabled", "reason": "guard_failed"}), flush=True)
        return 2

    for n in range(1, args.max_samples + 1):
        time.sleep(args.interval_seconds)
        try:
            summary = observe_once()
            report = {
                "event": "pg_wait_probe",
                "sample": n,
                "observed_at_utc": datetime.now(UTC).isoformat(),
                **summary,
            }
        except Exception as exc:
            # Do not interpolate exception text: it may include URI/credentials.
            report = {"event": "pg_wait_probe_error", "sample": n,
                      "exception_type": type(exc).__name__}
        print(json.dumps(report, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
