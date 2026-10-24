#!/usr/bin/env python3
"""Fail-closed exact-commit classifier for costly synthetic live Docker smoke.

Only a small explicit inventory of stand-alone, offline evidence-record helpers
and their unit tests may skip the live stack. Unknown, mixed, runtime, build,
infrastructure, workflow and migration changes ALWAYS require live validation.
This script never dispatches jobs; the stable operational performance gate
remains emitted for EVERY pull request.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

# Support the existing direct-script invocation from CI and operator shell:
# import only trusted, repository-local audit code, never cwd-supplied modules.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.ci_browser_offline_hm_scope import should_skip as audited_browser_skip

SHA = re.compile(r"[a-f0-9]{40}\Z")
OFFLINE_SCRIPTS = frozenset({
    "scripts/pilot_backend_execution_evidence.py",
    "scripts/pilot_ci_evidence.py",
    "scripts/pilot_rc_gate.py",
    "scripts/pilot_ruleset_evidence.py",
    "scripts/pilot_monitoring_ownership.py",
    "scripts/pilot_rollback_rehearsal.py",
    "scripts/tests/test_pilot_backend_execution_evidence.py",
    "scripts/tests/test_pilot_ci_evidence.py",
    "scripts/tests/test_pilot_rc_gate.py",
    "scripts/tests/test_pilot_ruleset_evidence.py",
    "scripts/tests/test_pilot_monitoring_ownership.py",
    "scripts/tests/test_pilot_rollback_rehearsal.py",
})
STATIC_TEXT_FILES = frozenset(("README.md", "CHANGELOG.md", "LICENSE"))

# Independent, frozen cohort: a future extension of browser/backend skip
# eligibility must NOT silently authorize bypassing live Performance validation.
AUDITED_HM_PERFORMANCE_TESTS = frozenset({
    "apps/api/tests/test_local_ai_hm_loopback_smoke.py",
    "apps/api/tests/test_local_ai_hm_fixture_matrix.py",
    "apps/api/tests/test_local_ai_hm_repeat_smoke.py",
})


def audited_hm_only(base: str, head: str, paths: list[str]) -> bool:
    """Admit only exact modified AST-audited synthetic tests, never mixed changes."""
    if (not paths or len(paths) > len(AUDITED_HM_PERFORMANCE_TESTS)
            or len(set(paths)) != len(paths)
            or any(path not in AUDITED_HM_PERFORMANCE_TESTS for path in paths)
            or not SHA.fullmatch(base) or not SHA.fullmatch(head) or base == head):
        return False
    # Browser's independently verified name-status -z classifier rejects
    # added/deleted/renamed/unknown entries and applies AST no-DB guard.
    return audited_browser_skip(base, head)



class ScopeError(ValueError):
    """Only static diagnostic messages; never disclose underlying Git output."""


def requires_live_stack(changed_paths: list[str]) -> bool:
    if not isinstance(changed_paths, list) or not changed_paths:
        # A genuinely empty diff on a purported PR is unexpected: fail closed.
        return True
    for path in changed_paths:
        if (not isinstance(path, str) or not path or path.startswith("/")
            or "\x00" in path or "\n" in path or "\r" in path
            or "/../" in path or path.startswith("../")):
            return True
        if path in OFFLINE_SCRIPTS or path in STATIC_TEXT_FILES or path.startswith("docs/"):
            continue
        # Fail CLOSED: runtime app/CI/Compose, any new script, any unknown
        # build/config path, and a mixed change all exercise the real stack.
        return True
    return False


def changed_files(base: str, head: str) -> list[str]:
    if not SHA.fullmatch(base) or not SHA.fullmatch(head) or base == head:
        raise ScopeError("missing, identical or invalid exact change SHAs")
    try:
        run = subprocess.run(
            ["git", "diff", "--name-only", "-z", "--no-renames", base, head],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ScopeError("exact-head changed-path observation unavailable") from None
    if run.returncode != 0 or not run.stdout:
        raise ScopeError("exact-head changed-path observation incomplete")
    try:
        return [p.decode("utf-8") for p in run.stdout.split(b"\x00") if p]
    except UnicodeDecodeError:
        raise ScopeError("changed-path observation contains invalid path encoding") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--output", required=True, type=Path,
                        help="GitHub Actions GITHUB_OUTPUT append-only file")
    args = parser.parse_args(argv)
    try:
        paths = changed_files(args.base, args.head)
        required = requires_live_stack(paths)
        if required and audited_hm_only(args.base, args.head, paths):
            required = False
    except ScopeError:
        # Deterministically require the real stack on ambiguous metadata,
        # including an unavailable Git diff, instead of a false cheap PASS.
        required = True
        print("::warning::Changed paths unavailable; requiring full live Docker smoke.")
    try:
        with args.output.open("a", encoding="utf-8") as stream:
            stream.write("performance_required=" + str(required).lower() + "\n")
    except OSError:
        print("::error::Cannot publish operational performance scope decision.",
              file=sys.stderr)
        return 2
    print("Operational performance live-stack required: " + str(required).lower())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
