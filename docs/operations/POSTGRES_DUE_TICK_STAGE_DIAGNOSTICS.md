# PostgreSQL due-tick CI: interrupted-stage diagnostics (#766)

The source of the intermittent `observation-due-tick` stall is **not
established**. An initial failed run on 2026-10-19 ended with pytest's
180-second faulthandler timeout and process exit 139. The PostgreSQL
wait probe showed a session idle in transaction blocking another
transaction-ID waiter, but does not prove a deadlock. Later successful
runs also spent over 100 seconds in some setup stages.

## Added observation only

`apps/api/tests/ci_due_tick_stage_timing.py` now writes a **BEGIN**
event to the existing CI-only timing file before each allowlisted
stage executes, followed by the existing completed
`ci_due_tick_stage` duration record in a `finally` block. The
GitHub Actions due-tick step already prints that local file even
when pytest exits abnormally. A BEGIN with no corresponding
completion can therefore identify the last entered *code-owned
stage* during an abrupt Python exit. Nested stages may overlap;
read the records in order rather than assuming the final BEGIN
is a definite root cause.

The two due-tick race tests also label previously unmeasured
schedule setup as `same_tick_schedule` and
`disable_race_schedule`. All executable test assertions, PostgreSQL
locking semantics, 180-second faulthandler threshold, libpq lock and
statement timeouts, full matrix selection for changed database tests,
and branch protection remain **unchanged**.

The two added events contain only fixed allowlisted stage names.
They do not contain SQL text or parameters, file contents, tenant,
claim or document IDs, database connection strings, stack variables,
or raw exception messages. The instrumentation is active only when
`APP_ENV=test` and
`EXTERNAL_EVIDENCE_DUE_TICK_POSTGRES_TEST=1`.

## Interpretation

- `ci_due_tick_stage_begin` without a matching `ci_due_tick_stage`
  means the stage did not complete normally before process termination.
  It does **not** establish whether the cause was resource contention,
  fixture lifetime, lock ownership, runner starvation or a bug.
- A clean final event means only that the stage exited; it does not
  establish race correctness. The original pytest assertions must pass.
- Compare the first failed attempt, failed-jobs rerun and later green
  full PostgreSQL runs in Issue #766 before recommending a functional
  change. Do **not** increase timeouts or skip a concurrency test to
  hide the issue.

Always-on stdlib-only policy regression:

```bash
python -m unittest scripts.tests.test_ci_due_tick_stage_entry_markers -v
```
