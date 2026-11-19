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

## 2026-11-19 — SIGBUS/135 resource-pressure diagnostics (CI only)

The protected PostgreSQL observation-due-tick job for PR #958 experienced a
**native pytest SIGBUS / exit 135** on its first attempt before the new
nested receipt test; a second identical-head attempt passed all 8 real
PostgreSQL tests in 846 seconds. This is not proof of root cause or a
production DB issue. No native core dump was preserved or interpreted.

The existing `scripts/pilot_pg_wait_probe.py` now records a bounded
`runner_resources` object alongside each 30-second sampled lock-wait
observation. It contains only cgroup v2 memory current/peak/limit and
OOM/OOM-kill counts plus **available bytes** for the fixed runner mounts
`/tmp` and `/dev/shm`. Missing kernel counters are explicitly `null`.
There is no PID memory inspection, process command-line, environment,
SQL, credential, customer path, exception message or Evidence bytes.
The strict synthetic PostgreSQL loopback/CI environment guard remains
mandatory; tests prove only fixed keys, bounded numeric values and
no production/remote access. Capturing an OOM count or low mount space
does not prove it caused SIGBUS, and null is not a clean-resource result.

The observer is extended from 25 to **45 samples** at the same 30-second
interval, covering up to 22.5 minutes of the existing 25-minute job;
the CLI rejects intervals/sample combinations exceeding 24 minutes.
Cleanup still kills the observer after pytest. Its output is
diagnostic-only: original pytest exit status, the 180-second faulthandler
threshold, 25-minute job timeout, PostgreSQL lock ordering, all
concurrency tests and the protected gate are unchanged.

If a crash repeats, compare **the last preceding resource snapshot**
and fixed timing/lock markers against the next successful same-head
attempt. Only then consider an isolated native/runner investigation;
never label a native crash `flaky` or disable the test without evidence.
Issue #766 stays OPEN; customer Pilot remains NO-GO.
