"""Fail-closed E2E skip admission for exact audited, offline synthetic H&M tests.

Only modified, previously reviewed test modules may skip full Docker/browser
journeys. The existing required Scoped CI gate remains unchanged; the separate
Backend tests gate executes selected tests and all-backend collection.
This classifier does not authorize model calls, customer Evidence or a pilot.
"""
from __future__ import annotations

import subprocess
import sys

from scripts.ci_backend_narrow_scope import parse_git_diff
from scripts.ci_postgres_synthetic_test_scope import is_db_free_synthetic_test

# Deliberately INDEPENDENT from backend's growing AUDITED registry. Extending
# that registry must never silently increase the E2E skip set.
_ELIGIBLE = frozenset({
    "apps/api/tests/test_local_ai_hm_loopback_smoke.py",
    "apps/api/tests/test_local_ai_hm_fixture_matrix.py",
    "apps/api/tests/test_local_ai_hm_repeat_smoke.py",
})


def eligible(entries: list[tuple[str, str]]) -> bool:
    """No mixed, missing, added, deleted, renamed or unknown paths qualify."""
    if not entries or len(entries) > len(_ELIGIBLE):
        return False
    seen: set[str] = set()
    for status, path in entries:
        if (status != "M" or path not in _ELIGIBLE or path in seen
                or not is_db_free_synthetic_test(path)):
            return False
        seen.add(path)
    return True


def should_skip(base: str, head: str) -> bool:
    if any(
        type(sha) is not str or len(sha) != 40
        or any(c not in "0123456789abcdef" for c in sha)
        for sha in (base, head)
    ) or base == head:
        return False
    try:
        result = subprocess.run(
            ["git", "diff", "--name-status", "--no-renames", "-z", base, head],
            capture_output=True, check=False, timeout=20,
        )
        if result.returncode != 0:
            return False
        return eligible(parse_git_diff(result.stdout))
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError):
        return False


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    # Only the fixed token 'skip' allows the workflow to bypass the Docker
    # browser run. Errors are indistinguishable from 'full' to prevent leaks.
    allowed = len(args) == 2 and should_skip(args[0], args[1])
    print("skip" if allowed else "full")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
