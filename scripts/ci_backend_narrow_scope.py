"""Fail-closed Backend CI classifier: a fixed, audited synthetic-only cohort."""
from __future__ import annotations

import subprocess
import sys
from scripts.ci_postgres_synthetic_test_scope import is_db_free_synthetic_test

AUDITED = frozenset((
    "apps/api/tests/test_local_ai_hm_loopback_smoke.py",
    "apps/api/tests/test_local_ai_hm_fixture_matrix.py",
))
PG_ONLY = frozenset((
    "apps/api/tests/test_external_document_source_recurring_observation_schedule_concurrency_postgres.py",
    "apps/api/tests/test_external_document_source_due_tick_dispatch_concurrency_postgres.py",
    "apps/api/tests/test_external_document_source_due_tick_observation_concurrency_postgres.py",
    "apps/api/tests/test_external_document_source_observation_refresh_execution_concurrency_postgres.py",
    "apps/api/tests/test_external_document_source_observation_review_handoff_concurrency_postgres.py",
    "apps/api/tests/test_external_document_source_observation_review_decision_concurrency_postgres.py",
    "apps/api/tests/test_external_document_source_due_tick_service_executor_concurrency_postgres.py",
    "apps/api/tests/test_external_document_source_observation_refresh_admission_authorization_concurrency_postgres.py",
    "apps/api/tests/test_external_document_source_family_version_concurrency_postgres.py",
    "apps/api/tests/test_processing_lease_postgres.py",
    "apps/api/tests/test_payment_settlement_concurrency_postgres.py",
    "apps/api/tests/test_external_document_source_observation_refresh_admission_execution_concurrency_postgres.py",
    "apps/api/tests/test_external_document_source_sftp_handshake_execution_concurrency_postgres.py",
))
PG_WORKFLOW = ".github/workflows/postgres-concurrency-regressions.yml"


def parse_git_diff(data: bytes) -> list[tuple[str, str]]:
    if not data or not data.endswith(b"\0"):
        raise ValueError("missing_exact_head_diff")
    parts = data[:-1].split(b"\0")
    if len(parts) % 2:
        raise ValueError("invalid_git_diff")
    return [(parts[i].decode("ascii"), parts[i+1].decode("utf-8"))
            for i in range(0, len(parts), 2)]


def classify(entries: list[tuple[str, str]]) -> tuple[str, tuple[str, ...]]:
    """Return full, narrow or none; never infer narrow from unknown changes."""
    if not entries:
        return "full", ()
    eligible = []
    saw_other = False
    for status, path in entries:
        if not path or status not in ("M", "A", "D"):
            return "full", ()
        if path in AUDITED:
            if status != "M" or not is_db_free_synthetic_test(path) or path in eligible:
                return "full", ()
            eligible.append(path)
        else:
            saw_other = True
            if path in PG_ONLY or path == PG_WORKFLOW:
                continue
            if (path.startswith("apps/api/") or path in (
                ".github/workflows/backend-premerge.yml",
                "scripts/ci_backend_narrow_scope.py",
                "scripts/ci_postgres_synthetic_test_scope.py",
                "scripts/backend_shard_selector.py",
            )):
                return "full", ()
    if eligible:
        if saw_other:
            return "full", ()
        return "narrow", tuple("tests/" + p.rsplit("/", 1)[1] for p in sorted(eligible))
    return "none", ()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    mode, paths = "full", ()
    try:
        if len(args) != 2 or any(
            len(s) != 40 or any(c not in "0123456789abcdef" for c in s)
            for s in args
        ):
            raise ValueError("invalid_exact_head_sha")
        diff = subprocess.run(
            ["git", "diff", "--name-status", "--no-renames", "-z", *args],
            capture_output=True, check=False, timeout=20,
        )
        if diff.returncode != 0:
            raise ValueError("git_diff_failed")
        mode, paths = classify(parse_git_diff(diff.stdout))
    except (ValueError, OSError, UnicodeError, subprocess.SubprocessError):
        pass
    print(f"backend_required={str(mode == 'full').lower()}")
    print(f"narrow_required={str(mode == 'narrow').lower()}")
    print("narrow_tests=" + " ".join(paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
