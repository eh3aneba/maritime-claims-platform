# #766 — narrow PostgreSQL CI scope for offline synthetic AI tests

The PostgreSQL concurrency gate remains a **required** status. This
optimization makes **only two exact paths** eligible to avoid launching
the expensive 17-group database matrix:

- `apps/api/tests/test_local_ai_hm_loopback_smoke.py`
- `apps/api/tests/test_local_ai_hm_fixture_matrix.py`

For every changed file matching these two paths, the classifier runs
`python3 scripts/ci_postgres_synthetic_test_scope.py <exact-path>` and
skips the matrix **only if** the candidate still passes the fixed
standard-library AST review (approved imports and no database, dynamic
execution, or persistence operations). Anything unfamiliar, unreadable,
invalid, imported from a new module or otherwise ambiguous **fails
closed to all groups**. All other `apps/api/*` changes continue to
trigger the normal classifier.

Changes to this guard script or the PostgreSQL workflow itself also
trigger **all groups**, so nobody can relax the guard while silently
skipping the DB matrix. Existing PostgreSQL-specific test paths retain
the original group selection and genuinely DB-affecting runtime changes
still execute the broad tests.

This is a narrowly scoped CI heuristic, not an executable sandbox or
formal proof of database independence. Imported helper source is
subject to normal code review and separate AI policy guards. The
normal backend and synthetic test jobs continue to execute; the
protected `PostgreSQL concurrency gate` still runs and confirms that
the classifier succeeded and the selected jobs had the right outcomes.

Focused CI policy regression:

```bash
python -m unittest scripts.tests.test_ci_postgres_synthetic_test_scope -v
python scripts/ci_postgres_synthetic_test_scope.py apps/api/tests/test_local_ai_hm_loopback_smoke.py
python scripts/ci_postgres_synthetic_test_scope.py apps/api/tests/test_local_ai_hm_fixture_matrix.py
```

Acceptance includes demonstrating the exact AI-only diff skips the
matrix but preserves a passing gate, while a DB-related diff and any
guard/workflow change do run the full validation. Also separately
investigate the intermittent `observation-due-tick` timeout recorded
in #766; CI optimization is **not** a fix for that potential issue.
