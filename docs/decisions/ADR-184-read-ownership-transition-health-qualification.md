# ADR-184: Qualify bounded recovery read-ownership transition health

Status: Proposed

## Context

Phase 17.3-V permits one exact approved Phase U authorization to create a bounded, reversible recovery read-ownership transition lease. During the active window the verified recovery replica owns only the document read route. Local evidence remains intact and write/storage ownership remains unchanged.

Before considering any write-path, dual-write or authoritative storage transition, the completed Phase V operational window must be independently assessed from immutable evidence rather than from the transition's own activation decision.

## Decision

Introduce Phase 17.3-W as a separate non-routable health qualification.

A Phase W request is admitted only for one exact completed Phase V lease in `rolled_back` or `expired` state. It requires one intact activation receipt and the exact terminal receipt, a clean local shared route, fresh authoritative-local and recovery-replica integrity verification, and at least one verified Phase V recovery read.

Operational evidence is derived from immutable document-download audit events bounded by the exact activation and terminal timestamps. Verified reads, integrity/lineage failures, storage-unavailable events and route-expired attempts are counted and hash-bound. Health is deterministic: integrity failures produce `failed`, storage unavailability without integrity failure produces `degraded`, otherwise the window is `healthy`.

The request creates `pending_second_approval` evidence with a review window of at most ten minutes. Qualification requires a current-tenant Admin with MFA who differs from the requester, the Phase V activator and the Phase U approver. A healthy snapshot may become `qualified`; non-healthy evidence becomes `degraded`. Rejection, expiry and invalidation remain non-routable terminal outcomes.

## Safety boundary

Phase W creates no route, no read-ownership authority and no storage authority. It never changes the read path, write path, document storage pointer or authoritative storage semantics. It cannot enable dual-write, overwrite/move/delete authoritative local evidence, mutate object-storage lifecycle, or authorize disposal.

All authority-changing and destructive flags are database-constrained false on both the qualification artifact and append-only receipts.

## Consequences

A `qualified` healthy Phase W artifact is evidence that one bounded Phase V read-ownership window completed with verified reads and no recorded integrity or storage-unavailable failures. It is not permission to change storage ownership or write behavior.

A later separately reviewed Phase 17.3-X may consume one exact unexpired/acceptable Phase W qualification to authorize a bounded write-path or dual-write rehearsal. That later phase must define its own rollback, consistency, reconciliation and authority boundaries.
