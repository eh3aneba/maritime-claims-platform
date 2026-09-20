# Phase 17.5-AD — bounded recurring observation scheduler dispatch

AD adds a DB-only scheduler queue in front of AC.

## One scheduler iteration

1. finds active schedules whose initial due time is not in the future;
2. locks the Y family binding using the same lifecycle lock order as AB/AC;
3. revalidates the exact active schedule and family;
4. locks the canonical current Document;
5. derives the earliest unconsumed AC tick;
6. skips a tick that is not due, already completed by AC, or already dispatched;
7. creates one immutable dispatch + receipt.

## Safety boundary

AD never:
- constructs a provider client;
- acquires tokens;
- reads remote metadata or content;
- writes remote state;
- reads/writes evidence storage;
- mutates Documents;
- admits Evidence;
- enqueues processing;
- executes AI;
- mutates Claim facts;
- advances checkpoints;
- impersonates a human User.

Only a hash of the scheduler worker identifier is persisted.

## Worker

`python -m app.workers.external_evidence_scheduler_worker --once`
creates at most one dispatch and exits.

Without `--once`, the worker polls using `EXTERNAL_EVIDENCE_SCHEDULER_POLL_SECONDS`.

## Next boundary

AD dispatch is not provider execution authority. A later phase must introduce a distinct internal service-executor identity
and consume one exact dispatch through the existing AC authority checks.
