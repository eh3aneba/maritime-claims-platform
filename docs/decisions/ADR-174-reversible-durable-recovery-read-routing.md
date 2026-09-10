# ADR-174: Reversible durable recovery read routing

## Status
Accepted for Phase 17.3-M implementation.

## Context
Phase 17.3-J proved short-lived reversible production reads from a verified recovery replica. Phase 17.3-K required two independent J cutover/rollback cycles, and Phase 17.3-L converted that evidence into a fresh, non-routable durable-read promotion authorization. An approved L record is deliberately insufficient by itself to change routing.

The next bounded step may exercise longer-lived recovery reads, but it must not confuse a read source with evidence ownership, create a second competing routing pointer, or weaken rollback guarantees.

## Decision
Phase 17.3-M introduces `EvidenceRecoveryDurableReadPromotionLease`, bound to one exact unexpired approved Phase L authorization and its approval receipt, Phase K lineage and verified recovery replica.

Preparation requires fresh Phase L snapshot verification while the shared `EvidenceRecoveryReadPathRoute` remains in the exact local state pinned by L. Activation has its own deadline bounded by the Phase L authorization expiry and requires an Admin with MFA different from both the lease preparer and the Phase L approver.

The existing single read-route record is extended rather than duplicated. It has exactly three valid structural states:

- local: local source, no active temporary or durable lease;
- temporary recovery: one active Phase J lease and no durable lease;
- durable recovery: one active Phase M lease and no Phase J lease.

The first durable route window is capped at 24 hours from activation. While active, every recovery read revalidates the durable lease, the exact Phase L authorization and approval receipt, the Phase K qualification, route fingerprints/version, local evidence bytes, recovery replica identity, remote HEAD/GET integrity, SHA-256 and content length. Drift fails closed. A temporary recovery-storage outage returns a retryable availability error and never silently falls back to local while durable recovery authority is active.

Explicit rollback remains available after route expiry and restores the shared route record to local source atomically. Reconciliation is an operational safeguard: an expired active route is returned to local and terminalized as `expired`; a healthy unexpired route is a no-op after fresh validation.

## Authority boundary
Phase M changes read routing only while the durable lease is active. It does not change evidence ownership or write authority.

Throughout Phase M:

- `Document.storage_key` is unchanged;
- local evidence bytes remain intact;
- `write_path_switched = false`;
- `document_storage_key_mutated = false`;
- `authoritative_storage_changed = false`;
- `destructive_action_performed = false`;
- `s3_delete_performed = false`;
- `local_delete_performed = false`.

No local overwrite/move/delete, S3 COPY/DELETE/lifecycle mutation, dual-write admission, destructive migration or disposal is authorized.

## Consequences
Phase M provides bounded operational evidence for sustained recovery reads while preserving immediate return to local authority. A later separately reviewed tranche may evaluate renewal/health qualification or a future read-authority ownership promotion.

Any write-path change, storage-ownership transfer, destructive migration or evidence disposal remains outside this decision and requires a separate governance boundary and explicit production approval.
