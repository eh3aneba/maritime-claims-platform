# ADR-187: Authorization-only gate for one bounded routable dual-write canary

## Status
Accepted for Phase 17.3-AA implementation.

## Context
Phase X authorized one isolated write rehearsal, Phase Y executed exactly one non-routable recovery-storage write, and Phase Z independently qualified that rehearsal as healthy. Those phases intentionally did not create a live write path, durable write authority, storage ownership transfer, or destructive authority.

A healthy rehearsal is necessary but not sufficient to activate even a bounded routable dual-write canary. The first operational write-side routing change needs a separate governance artifact with fresh evidence verification and independent approval.

## Decision
Phase AA creates an authorization-only artifact for **at most one future bounded routable dual-write canary window**. It consumes exactly one `qualified` / `healthy` Phase Z artifact and its exact qualified receipt, preserves the Z → Y → X → W → V → U → T → replica lineage, and invokes the Phase Z fresh verification path again at request and approval time.

The authorization has:
- a 10-minute independent review window;
- Four-Eyes approval;
- approver separation from the AA requester, Phase Z qualifier, Phase Y executor, and Phase X approver;
- a 10-minute approved authorization lifetime;
- `max_canary_windows = 1`;
- one Phase Z qualification → at most one Phase AA authorization;
- append-only hash-bound requested/approved/rejected/expired/invalidated receipts.

Recovery-storage outage is retryable and does not consume a pending authorization. Route, lineage, key, local-evidence, rehearsal-object, or integrity drift fails closed and invalidates a pending authorization during second approval.

## Explicit non-authority
Phase AA does **not** execute a canary and does not itself create operational write authority. Database constraints pin the following false on both authorization and receipts:
- storage write performed;
- canary executed;
- routable dual-write active;
- durable write authority created;
- rehearsal object routable;
- read path switched;
- write path switched;
- `Document.storage_key` mutated;
- authoritative storage changed;
- destructive action performed;
- S3 COPY performed;
- S3 DELETE performed;
- local authoritative delete performed.

Phase AA also does not authorize disposal, overwrite/move authoritative local evidence, or make recovery storage authoritative.

## Consequence
A later Phase AB may consume one exact approved and unexpired Phase AA authorization to implement a separately reviewed bounded canary execution. Phase AB must define atomic write/routing behavior, deterministic rollback, idempotency, failure semantics, and post-window qualification before any permanent or durable write ownership can be considered.
