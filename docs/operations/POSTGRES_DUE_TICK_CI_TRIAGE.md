# Pilot CI: PostgreSQL due-tick cancellation triage and bounded recurrence

Status: CI-only mitigation and evidence protocol for [#667](https://github.com/eh3aneba/maritime-claims-platform/issues/667). This is **not proof of an SQL deadlock**, a production fix, or a Pilot release authorization.

## Recorded incident (2026-10-10, UTC)

- On exact PR #666 head `236b56f7b8e277ffe3346697e12ee7861ebba69a`, PostgreSQL Concurrency [run 38033331274 attempt 1](https://github.com/eh3aneba/maritime-claims-platform/actions/runs/38033331274) reported the **observation-due-tick** matrix job `cancelled`. The job ran from **07:07:47 to 07:37:47 UTC**; the required due-tick test step started at **07:08:40 UTC** and had no completion timestamp. The matrix aggregator correctly failed. The original job log download returned `BlobNotFound`, with no captured SQLSTATE, stack trace, wait-event, or actionable cancellation reason.
- **Attempt 2 on that same exact SHA** succeeded. The due-tick step ran from **08:06:58 to 08:19:12 UTC**, and all **five tests passed in 727.59 seconds**. The gate succeeded; PR #666 merged after successful required checks.
- PR [#668](https://github.com/eh3aneba/maritime-claims-platform/pull/668), head `cf5b4c9cb025304e0cf45b72306bd9d5bb2b2b36`, added `pytest -vv --tb=short -o faulthandler_timeout=180 --durations=20` and `PYTHONFAULTHANDLER=1`. Its fresh PostgreSQL 18.4 due-tick step ran **08:23:33–08:30:17 UTC**, with **five passes in 395.14 seconds** and no observed timeout dump. That diagnostic change was merged to main as `503b07b7f6c35af6539e0ef2d8fbcd3903b74140`.
- No run in the above evidence reproduces an SQL deadlock. An unexplained cancellation, a Python/executor wait, a slow runner, and a blocked database session are different possible explanations. None is established as the cause of attempt 1.

## Bounded CI policy

The `observation-due-tick` PostgreSQL 18.4 matrix step retains **all five original tests**, both concurrent same-tick assertions (`one execution / one conflict`) and disable-versus-consume assertions, plus the existing job timeout and mandatory aggregate gate. The step sets `PGOPTIONS=-c lock_timeout=30000 -c statement_timeout=180000` only in its test-step environment:

- A PostgreSQL lock wait longer than **30 seconds** fails the test instead of silently waiting. A single PostgreSQL statement exceeding **180 seconds** fails; the Python 180-second faulthandler emits stack *locations* for a continuing Python hang.
- These are **client-session settings for CI test connections only**; they do not alter production defaults or PostgreSQL server configuration. They apply to psycopg/libpq clients launched by that step, including fixture connections.
- Do **not** catch timeout/OperationalError as an expected conflict or mark a timed-out matrix leg successful. Retry is diagnostic only; it is not a substitute for a passing exact-head required gate. Never skip the test or loosen the race assertions.
- Log only synthetic test data and bounded stack locations. Avoid logging SQL parameters, credential material, repository secrets, Evidence bodies, and production row content.

## Recurrence decision procedure

1. Capture the **exact PR head SHA**, workflow **run ID / attempt**, matrix **job ID**, job/step start/end UTC timestamps, conclusion, and the **aggregator conclusion** before rerunning. Preserve scrubbed job logs and any approved artifacts while still available. A GitHub `cancelled` conclusion alone does **not** establish a timeout or a deadlock.
2. Read the per-test `-vv` timestamps and `--durations=20` output to localize the slow test. Review any faulthandler stacks from the 180-second deadline. A PostgreSQL `55P03` (lock unavailable) or `57014` (statement canceled) from the CI-only limits is **positive evidence of bounded database waiting**, not proof of a cyclic deadlock.
3. If reproducible, use a **clean ephemeral PostgreSQL 18.4 service** on the **same exact SHA**. During a live failure, capture a privacy-safe summary of `pg_stat_activity`: `pid`, `state`, `wait_event_type`, `wait_event`, transaction age and `pg_blocking_pids(pid)`. Never include `query`, parameters, credentials, or Evidence content. Record whether a blocking PID exists and whether the Python thread stack points into SQL execution, synchronization, or fixture setup.
4. A genuine PostgreSQL deadlock needs a documented `40P01` or equivalent proven wait cycle. A lock timeout, executor stall, external cancellation or runner slowdown is a *different* diagnosis and needs its own fix. Do not attribute the incident to the unrelated historical Shard 20 fixture issue.
5. Keep the PostgreSQL matrix and aggregate gate mandatory for all affected diffs. Any recurrent failure must block the PR; raise a separately tracked P0/P1 investigation with the new exact-head evidence. Do not announce Pilot/Production GO on the basis of CI alone.

## Closure scope

The #667 incident can be operationally contained with tested CI diagnostics, bounded PostgreSQL waits, preserved regression assertions and an agreed recurrence procedure **even though attempt 1's root cause remains unproven**. Record this distinction in the closing comment; reopen or create a blocking follow-up upon recurrence with actionable evidence. Pilot v1 release readiness is tracked separately in #653 and related P0 issues.
