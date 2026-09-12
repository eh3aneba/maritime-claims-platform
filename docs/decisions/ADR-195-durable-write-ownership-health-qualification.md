# ADR-195: Independent durable write-ownership health qualification

- Status: Accepted
- Date: 2026-09-12
- Phase: 17.3-AI

## Context

Phase AH can establish a durable `recovery_primary` write-routing authority on a control plane that is separate from the bounded dual-write/canary route. Local evidence remains authoritative and remains the rollback source. Before considering any later authoritative evidence-storage ownership transition, the platform needs independent evidence that the active AH route, lineage, local evidence and recovery replica remain healthy without mutating that state during the review.

## Decision

Introduce a separate Phase AI health-qualification control plane. A Phase AI request is admitted only when one exact Phase AH lease is still active, has exactly one activation receipt and no terminal receipt, and the durable route remains `recovery_primary` with the exact AH lease pointer/version.

Phase AI also re-verifies the immutable AG→AF→AE lineage, the shared `local_source` read route, the clean experimental `local_only` write route, and fresh local/recovery byte integrity. The request records the exact observed route versions, hashes and integrity proof.

Qualification requires an independent Admin+MFA actor and repeats the fresh verification. Recovery-storage unavailability remains retryable. Deterministic lineage, route or byte drift invalidates the pending qualification and produces append-only evidence.

## Observation versus action

Phase AI explicitly separates observed AH state from actions performed by AI:

- observed durable write mode: `recovery_primary`
- observed durable write ownership: active
- AI-created durable write authority: false
- AI route mutation: false
- AI read/write path switch: false
- AI storage write/delete/move/overwrite: false

This prevents a health receipt from being misread as evidence that the qualification process itself changed storage or routing authority.

## Safety boundary

Phase AI does not:

- mutate the AH durable route;
- mutate the shared read route or experimental write route;
- perform S3 PUT/COPY/DELETE;
- overwrite, move or delete local evidence;
- mutate `Document.storage_key`;
- transfer authoritative evidence-storage ownership;
- roll back or reactivate AH;
- authorize physical disposal.

Local evidence remains authoritative throughout this tranche.

## Consequences

A `qualified` Phase AI record is governance and health evidence only. It may be consumed by a later, separately authorized tranche, but it does not itself authorize authoritative storage ownership transfer, disposal, or destructive storage operations. Any such tranche requires a new explicit contract, migration/API boundary, production PR, full gates and fresh merge authorization.
