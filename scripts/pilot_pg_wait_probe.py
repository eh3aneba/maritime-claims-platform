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


def _observed_blocker_graph(sessions: list[dict], *, truncated: bool) -> dict:
    """Detect a cycle only among PIDs visible in this *one bounded sample*.

    A missing cycle does NOT exclude a real PostgreSQL deadlock: blockers
    may be outside the row cap or relationships may change between probes.
    Never inspect SQL text, lock keys, transaction IDs or application data.
    """
    ids = {session["pid"] for session in sessions}
    graph = {
        session["pid"]: [
            pid for pid in session["blocking_pids"] if pid in ids
        ]
        for session in sessions
    }
    complete = not truncated and all(
        pid in ids
        for session in sessions
        for pid in session["blocking_pids"]
    )
    seen: set[int] = set()
    path: set[int] = set()

    def visit(pid: int) -> bool:
        if pid in path:
            return True
        if pid in seen:
            return False
        path.add(pid)
        for blocker in graph[pid]:
            if visit(blocker):
                return True
        path.remove(pid)
        seen.add(pid)
        return False

    detected = any(visit(pid) for pid in graph if pid not in seen)
    return {
        "observed_blocker_cycle_in_sample": detected,
        "sample_blocker_graph_complete": complete,
    }


def safe_summary(rows: list[tuple]) -> dict:
    """Whitelisted PostgreSQL metadata only: never accept/serialize query text."""
    sessions = []
    truncated_blocker_lists = False
    for pid, state, wait_type, wait_event, age, blocking in rows[:_MAX_ROWS]:
        # The output stays bounded at 16 blocker PIDs per session, but a
        # clipped list cannot support a claim of complete graph coverage.
        blocker_ids = list(blocking or [])
        if len(blocker_ids) > 16:
            truncated_blocker_lists = True
        sessions.append({
            "pid": int(pid),
            "state": state if state in ("active", "idle", "idle in transaction",
                                        "idle in transaction (aborted)") else "other",
            "wait_type": wait_type if wait_type in ("Lock", "IO", "Client", "LWLock",
                                                   "Timeout", "Activity", "IPC") else None,
            "wait_event": str(wait_event)[:64] if wait_event else None,
            "transaction_age_seconds": max(0, int(age)),
            "blocking_pids": [int(value) for value in blocker_ids[:16]],
        })
    truncated = len(rows) > _MAX_ROWS
    return {
        "client_count": len(sessions),
        "blocked_count": sum(bool(s["blocking_pids"]) for s in sessions),
        "sessions": sessions,
        "truncated": truncated,
        "blocker_pid_lists_truncated": truncated_blocker_lists,
        **_observed_blocker_graph(
            sessions, truncated=truncated or truncated_blocker_lists
        ),
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


# Kernel-owned counters and statvfs for fixed runner mounts only. Never read
# /proc/<pid>, command lines, environment, SQL or private Evidence paths.
_MAX_RESOURCE_VALUE = (1 << 63) - 1


def _bounded_kernel_integer(path: str) -> int | None:
    try:
        with open(path, "r", encoding="ascii") as handle:
            raw = handle.read(64)
    except (OSError, UnicodeError):
        return None
    value = raw.strip()
    if not value or not value.isascii() or not value.isdecimal():
        return None
    number = int(value)
    return number if 0 <= number <= _MAX_RESOURCE_VALUE else None


def _cgroup_memory_events() -> dict[str, int | None]:
    result = {"oom": None, "oom_kill": None}
    try:
        with open("/sys/fs/cgroup/memory.events", "r", encoding="ascii") as handle:
            raw = handle.read(1024)
    except (OSError, UnicodeError):
        return result
    if len(raw) >= 1024:
        return result
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) != 2 or parts[0] not in result:
            continue
        if parts[1].isascii() and parts[1].isdecimal():
            value = int(parts[1])
            if 0 <= value <= _MAX_RESOURCE_VALUE:
                result[parts[0]] = value
    return result


def _fixed_mount_available(path: str) -> int | None:
    try:
        info = os.statvfs(path)
    except OSError:
        return None
    value = info.f_bavail * info.f_frsize
    return value if 0 <= value <= _MAX_RESOURCE_VALUE else None


def safe_ci_runner_resources() -> dict[str, int | None]:
    """Aggregate CI runner resource counters, never identities or paths.

    Missing cgroup-v2 or mount support stays null. These observations cannot
    diagnose the root cause of SIGBUS without independent reproduction.
    """
    _ci_database_url()  # Same strict synthetic local-only guard as PG observer.
    events = _cgroup_memory_events()
    return {
        "cgroup_memory_current_bytes": _bounded_kernel_integer(
            "/sys/fs/cgroup/memory.current"
        ),
        "cgroup_memory_peak_bytes": _bounded_kernel_integer(
            "/sys/fs/cgroup/memory.peak"
        ),
        "cgroup_memory_limit_bytes": _bounded_kernel_integer(
            "/sys/fs/cgroup/memory.max"
        ),
        "cgroup_oom_events": events["oom"],
        "cgroup_oom_kill_events": events["oom_kill"],
        "tmp_available_bytes": _fixed_mount_available("/tmp"),
        "shm_available_bytes": _fixed_mount_available("/dev/shm"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded CI-only PostgreSQL wait telemetry")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--max-samples", type=int, default=20)
    args = parser.parse_args(argv)
    if not (15 <= args.interval_seconds <= 300 and 1 <= args.max_samples <= 45
            and args.interval_seconds * args.max_samples <= 1440):
        parser.error("bounded probe requires 15..300s, 1..45 samples, max 24m")

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
        # Sample independently of SQL success; capture resource pressure at
        # the last interval before a native crash without logging process data.
        try:
            report["runner_resources"] = safe_ci_runner_resources()
        except Exception:
            report["runner_resources"] = None
        print(json.dumps(report, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
