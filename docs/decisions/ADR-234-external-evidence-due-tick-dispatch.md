# ADR-234: DB-only scheduler dispatch before internal provider execution

## Status

Proposed by Phase 17.5-AD.

## Context

Phase AB authorizes recurring observation schedules and Phase AC can consume one deterministic due tick,
but AC's current operator execution receipt is explicitly bound to a human application User.

A background scheduler must not fabricate, borrow or replay a human identity merely to trigger AC.

## Decision

AD introduces a separate DB-only dispatch boundary.

One scheduler iteration may:
- inspect active AB schedules;
- derive the exact earliest unconsumed AC due tick;
- validate schedule/family/current-Document state;
- create one immutable dispatch for the exact schedule/tick;
- record only a hash of the internal worker identifier.

AD performs no provider, token, content, storage, Document, processing, AI, Claim or checkpoint action.

The unique `(schedule_id, due_at)` boundary prevents duplicate dispatch.

## Identity

No User row is created or reused for scheduler execution.
The ordinary audit event has `user_id = NULL` and stores only the non-secret worker-id hash in content-free details.

## Consequences

The scheduling mechanism can run continuously without widening provider authority or weakening application identity semantics.
A later phase must define an explicit internal service-executor identity before a dispatch may be consumed into AC provider I/O.
