# ADR-192: Independent health qualification for bounded recovery write-ownership transition

## Status
Accepted for Phase 17.3-AF.

## Context
Phase AE proves that the dedicated write-routing control plane can temporarily select `recovery_primary` under one approved Phase AD authorization and then restore exact `local_only` routing without changing the shared read route, `Document.storage_key`, durable evidence authority or evidence bytes.

A successful route transition is not by itself sufficient evidence for a later durable recovery write-ownership decision. The completed window must be independently re-verified after terminal restoration, using fresh local and recovery evidence checks and exact route-state validation.

## Decision
Phase AF creates one independent health-qualification artifact for one completed Phase AE transition lease.

Admission requires the Phase AE lease to be terminal `rolled_back` or `expired`; `invalidated` windows are never healthy candidates. The lease must have exactly one activation receipt and one matching terminal receipt. The activation must prove `local_only -> recovery_primary`; the terminal receipt must prove `recovery_primary -> local_only` with the expected route-version progression.

At request time Phase AF freshly verifies:

- the exact Phase AD authorization and approval lineage consumed by Phase AE;
- the shared read route is still exact `local_source`, with no active recovery-read lease;
- the dedicated write route is exact `local_only`, with no active canary or Phase AE lease;
- the authoritative local evidence still matches the source SHA-256, byte length and storage-key fingerprint;
- the recovery replica lineage still matches the Phase AE evidence;
- a fresh recovery-object HEAD+GET matches the source SHA-256 and byte length and, when available, the Phase AE-observed ETag;
- no evidence-storage ownership, destructive or disposal flag has changed.

The request enters `pending_second_approval` for at most ten minutes. A second Admin+MFA actor must independently repeat the fresh verification before setting the artifact to `qualified`. The qualifier must be independent from the AF requester, the Phase AE activator, the Phase AD requester/approver and the upstream AC/AB/AA/Z/Y/X governance actors preserved by the Phase AD authorization.

Fresh verification drift invalidates the pending AF artifact. A recovery-storage outage remains retryable and does not consume a new AF request before persistence. Explicit rejection and review-window expiry are terminal outcomes.

Every state transition writes an append-only, hash-bound receipt.

## Safety boundary
Phase AF is observation and qualification only. It does not:

- create or activate a write-route lease;
- reactivate `recovery_primary`;
- perform S3 PUT/COPY/DELETE or local overwrite/move/delete;
- create durable recovery write authority;
- switch the shared read path;
- mutate `Document.storage_key`;
- transfer authoritative evidence-storage ownership;
- authorize evidence disposal or deletion.

Local evidence remains authoritative throughout Phase AF.

## Consequences
A `qualified` Phase AF artifact is stronger evidence that one bounded Phase AE transition completed cleanly and remained healthy after rollback. It may be consumed by a later separately reviewed authorization phase, but Phase AF itself grants no durable write or storage authority.

Any later durable recovery write-ownership authorization or execution requires a separate tranche, a new ADR and fresh production merge authorization.
