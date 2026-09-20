# Phase 17.5-AB — Recurring observation schedule authority

Phase AB is the authority layer for future background external-source synchronization.

## What it adds

A current-MFA Admin can authorize a bounded recurring exact-item observation schedule for one durable external Evidence
family.

The schedule records:
- tenant / Claim / profile;
- exact Y family binding;
- stable source-item identity hash;
- Document family;
- immutable revision number;
- cadence class;
- effective time and first due time;
- actor / reason / request key;
- integrity hashes and receipt chain.

Supported cadence classes:
- hourly;
- every 6 hours;
- every 12 hours;
- daily.

## Lifecycle

- **authorize** creates revision 1 when no active schedule exists;
- **replace** disables the active revision and creates revision N+1 atomically;
- **disable** terminates the active revision;
- exact replay is idempotent;
- altered replay conflicts.

Only one active schedule revision can exist for a family binding.

## Authority boundary

AB is deliberately side-effect free outside its own schedule/receipt records.

It does not:
- build a provider client;
- obtain tokens;
- call remote metadata/content endpoints;
- stage bytes;
- modify Documents;
- create N+1 Evidence;
- enqueue processing;
- authorize or execute AI;
- mutate Claim facts/assessments;
- advance source checkpoints;
- start a background worker.

A later phase will consume an authorized due tick into one bounded metadata-only observation execution.

## Acceptance

AB must pass backend, migrations, frontend/E2E regression, supply-chain security, operational performance,
production-policy and real PostgreSQL concurrency gates before merge.
