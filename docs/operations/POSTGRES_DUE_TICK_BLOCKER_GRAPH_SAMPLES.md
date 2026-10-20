# PostgreSQL due-tick blocker graph sample — diagnostic interpretation

Follow-up to issue #766 and the merged CI stage-entry markers in PR #774.
The CI-only observer already reads whitelisted `pg_stat_activity` state,
wait-event names, transaction ages and `pg_blocking_pids(pid)` from the
ephemeral local PostgreSQL test database. This change computes **two
bounded booleans in memory** from those already-visible PID relationships:

- `observed_blocker_cycle_in_sample`: whether the sampled direct-blocker
  graph contains a cycle among *captured* sessions. This is an observed
  wait-dependency graph condition **not an independently confirmed database
  deadlock**.
- `sample_blocker_graph_complete`: whether the bounded sample contains
  every PID referenced as a direct blocker and was not truncated by
  the 32-session cap. This only describes the *captured snapshot*.
  A true value does not attest the full history or runner environment.

In the initial failed run, the captured `idle in transaction` session
blocked an `active` transaction-ID waiter. That is consistent with
one-way contention; the available sample alone does not establish a
cycle, root cause or safe timeout threshold.

A **false** cycle result cannot rule out a real deadlock, particularly
when the sample is incomplete, between samples, or when PostgreSQL has
already aborted a deadlocking transaction. A **true** cycle result is
a narrow observation for manual investigation, not an automated
claim that the PostgreSQL engine has entered an unrecoverable state.

No extra SQL queries, transaction contents, lock keys, credentials or
customer Evidence are collected. The Python unit tests mock rows and
do not connect to any database. The existing probe's fixed loopback,
`APP_ENV=test` and synthetic DB admission checks remain mandatory.

The PR does **not** modify SQLAlchemy sessions, production runtime,
concurrency test assertions, PostgreSQL statement/lock timeouts,
pytest's faulthandler threshold or branch protection. Continue comparing
Stage BEGIN/completion records with wait-graph samples on subsequent
failure and successful runs before proposing any logic or timeout fix.

```bash
python -m unittest scripts.tests.test_pilot_pg_wait_probe -v
```
