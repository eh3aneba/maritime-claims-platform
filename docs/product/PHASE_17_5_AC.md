# Phase 17.5-AC — Due-tick metadata-only observation execution

Phase AC consumes one due tick from an active Phase-AB schedule into one exact-item metadata observation.

## Due selection

The server derives the earliest unconsumed tick from:
- schedule effective_at;
- cadence_minutes;
- prior completed AC ticks.

A caller cannot submit an arbitrary due time.

If five ticks are overdue, one execution consumes only the oldest outstanding tick.

## Execution

One AC execution:
1. validates tenant / Claim / profile / Y family / stable source identity;
2. validates active AB schedule authority;
3. derives and reserves one due tick;
4. performs one exact-item metadata read;
5. compares it with the current canonical Evidence source state;
6. records unchanged, changed or missing;
7. writes immutable content-free execution and receipt facts.

## No downstream side effects

AC does not:
- read file content;
- stage bytes;
- create Document N+1;
- delete canonical Evidence when remote is missing;
- enqueue OCR/indexing;
- authorize or execute AI;
- mutate Claim facts/assessments;
- advance checkpoint generations.

## Idempotency and races

- one unique execution per schedule/due_at;
- exact replay returns the existing execution;
- altered replay conflicts;
- concurrent consumers create at most one execution for the same tick;
- disable or schedule replacement racing with consume fails closed.

## Operator execution

A current-MFA Admin may trigger one due execution for testing/operator control.
The endpoint accepts only an idempotency key/reason; remote scope and due time are server-derived.

A later phase may attach a bounded internal scheduler to this same service-level authority boundary.
