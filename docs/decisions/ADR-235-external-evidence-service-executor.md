# ADR-235 — Internal service-executor identity for due-tick observation

## Decision

Phase 17.5-AE consumes an immutable Phase-AD dispatch without creating or borrowing an application User.

A due-tick observation actor is exactly one of:
- human: existing `users.id`;
- service: SHA-256 of a normalized, non-secret configured service-executor identifier.

Existing human observation hashes remain backward compatible. Service rows extend the actor hash only when `actor_kind = service`.

Each AD dispatch may have at most one immutable AE consumption. If the exact tick was already completed through human AC, AE links the dispatch to that observation and performs no second provider read.

## Safety boundary

AE permits only the existing exact-item metadata observation. It does not list remote containers, read file content, mutate remote state, touch canonical/staging storage, mutate Documents, admit Evidence, enqueue processing, run AI, mutate Claim facts/assessments, or advance checkpoints.

## Concurrency

The Y family binding remains the serialization authority for schedule/current-Document observation state. The AD dispatch is independently locked for consumption. The existing unique observation boundary on `(schedule_id, due_at)` remains the cross-human/service exactly-once boundary.

## Follow-up

Later phases may act on a `changed` observation only through separately governed Evidence-admission authority. AE itself does not admit N+1.
