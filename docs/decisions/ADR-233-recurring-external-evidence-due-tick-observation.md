# ADR-233: Deterministic due-tick exact-item observation execution

## Status

Proposed by Phase 17.5-AC.

## Context

Phase AB authorizes bounded recurring exact-item observation schedules but performs no provider I/O.
The next step is to consume schedule authority into one metadata-only observation without silently
granting broader provider, content, Evidence, processing or AI authority.

## Decision

Each AC execution consumes exactly one deterministic due tick from one active AB schedule revision.

The due tick is server-derived from:
- schedule effective time;
- cadence minutes;
- prior completed AC executions.

The schedule row remains immutable. AC stores execution rows instead.

A database uniqueness boundary on `(schedule_id, due_at)` prevents duplicate consumption under concurrency.

If multiple ticks are overdue, one invocation consumes only the earliest unconsumed tick. No silent skipping occurs.

## Observation scope

AC may perform exactly one exact-item metadata read for the stable source item already bound by Phase Y.
It may resolve/use the existing governed provider-client lineage needed for that read.

AC must not perform:
- broad list/folder crawl;
- remote content read;
- remote write/delete;
- storage read/write/delete;
- staging;
- Document mutation;
- processing enqueue;
- AI;
- Claim mutation;
- checkpoint advancement;
- automatic Evidence admission.

## Canonical comparison baseline

For current family version 1, compare the fresh remote projection with the immutable Phase-Y source projection/version lineage.

For current family version N > 1, compare with the latest successful Phase-AA admission execution associated with the exact current Document.

Result is one of:
- unchanged;
- changed;
- missing.

Only content-free metadata facts and hashes are persisted.

## Concurrency

The active schedule revision is locked and integrity-checked before due selection.
Disable/replace racing with consume fails closed.
The execution row reserves the exact due tick before provider I/O, and duplicate consumers cannot create a second execution.

## Consequences

Recurring metadata observation becomes bounded, deterministic and auditable while keeping downstream content,
Evidence admission, processing and AI authority separate.
