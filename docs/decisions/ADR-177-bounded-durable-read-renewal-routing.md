# ADR-177: Bounded durable recovery read renewal routing

## Status

Proposed for Phase 17.3-P.

## Context

Phase 17.3-M proved that a recovery replica can temporarily serve a bounded durable read route while the authoritative local evidence, write path, and storage ownership remain unchanged. Phase 17.3-N then independently qualified the completed operational window, and Phase 17.3-O introduced a short-lived, non-routable governance authorization that may be issued only from an exact healthy Phase N record.

A later durable-read window must not be implemented by reopening or rewriting the historical Phase M lease. Doing so would weaken transition provenance and make it difficult to distinguish the first production-like read window from a later renewal. A renewal must therefore consume one exact Phase O authorization and create new immutable lease/receipt evidence while continuing to use the single shared read-route control plane.

## Decision

Phase 17.3-P introduces a separate `EvidenceRecoveryDurableReadRenewalLease` and append-only transition receipts. One exact Phase O authorization may back at most one Phase P lease.

Preparation is permitted only when the Phase O authorization is still approved and inside its bounded activation window. The service reconstructs the exact Phase O snapshot, validates its single approval receipt, verifies the qualified healthy Phase N evidence, verifies the completed prior Phase M lease, requires the shared read route to remain in the exact pinned clean-local state, and performs fresh local-source and recovery-candidate integrity verification.

Activation repeats the fresh validation under row locks. The activator must differ from the Phase P preparer, the Phase O approver, and the prior Phase M activator. A transient recovery-object-store outage is retryable: the request returns unavailable and the database transaction is rolled back, leaving the lease prepared. Integrity, lineage, or route drift invalidates the prepared lease fail-closed.

An activated Phase P lease owns a distinct route pointer, `active_durable_renewal_lease_id`, and the route authority kind is `durable_renewal`. The original Phase M durable lease pointer remains clear. This preserves historical Phase M immutability while making the active renewal owner explicit.

The maximum renewal routing window is 24 hours. During the active window every document download revalidates Phase O, healthy Phase N evidence, terminal Phase M lineage, current local source metadata, recovery replica lineage, and recovery bytes. Integrity or lineage failure returns a conflict. Recovery storage unavailability returns unavailable. Neither condition silently falls back to the local file while the renewal route is active.

Explicit rollback or expiry reconciliation restores the single shared route to `local_source`, clears the active renewal lease and replica pointers, increments the route version, and records an append-only receipt.

## Safety boundary

Phase P is read-routing only. It does not:

- switch or duplicate the write path;
- mutate `Document.storage_key`;
- change authoritative storage ownership;
- overwrite, move, or delete the authoritative local evidence;
- issue S3 COPY, DELETE, or lifecycle mutations;
- enable dual-write;
- authorize evidence disposal; or
- authorize write-path or storage-ownership migration.

The lease, receipt, and shared route models keep write, storage-key, authoritative-storage, and destructive-action flags database constrained false. Audit events contain only identifiers, hashes, fingerprints, route state, and bounded safety flags; raw local or recovery storage keys are excluded.

## Consequences

A second durable read window is independently attributable and reversible rather than being represented as a mutation of historical Phase M evidence. The additional route pointer slightly expands the shared control-plane schema, but prevents ambiguous ownership between original promotion and renewal leases.

Repeated renewal is deliberately not recursive in this phase. Phase P consumes only one Phase O authorization derived from the completed Phase M window. Another future renewal must first obtain separately reviewed operational-health evidence for the exact completed Phase P window and pass a new bounded governance decision; historic healthy evidence cannot be reused indefinitely.

## Next boundary

A separately reviewed tranche may introduce **post-renewal operational health qualification** for one exact completed Phase P lease. It should measure verified renewal reads, integrity failures, storage-unavailability events, route-expiry attempts, and exact activation/terminal receipt lineage while remaining non-routable. It must not introduce write migration, dual-write, storage ownership transfer, destruction, or disposal authority.
