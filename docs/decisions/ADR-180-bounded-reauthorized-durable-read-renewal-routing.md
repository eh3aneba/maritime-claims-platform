# ADR-180: Bounded reauthorized durable-read renewal routing

- **Status:** Accepted
- **Date:** 2026-09-10
- **Phase:** Enterprise Storage 17.3-S
- **Related:** #345, #344, #25

## Context

Phase 17.3-R introduced a non-routable governance reauthorization that may authorize exactly one later durable recovery read renewal after a qualified Phase Q health record. Phase R deliberately creates no live route and no write or storage-ownership authority.

The next boundary needs to consume one exact, approved, unexpired Phase R reauthorization and permit one additional bounded recovery read window without reopening or rewriting the historical Phase P renewal lease. The platform must preserve the complete Q→P→O→N→M lineage, retain local evidence as authoritative, and keep rollback deterministic.

## Decision

Phase 17.3-S introduces a separate `EvidenceRecoveryDurableReadReauthorizedRenewalLease` and append-only transition receipts. A Phase R reauthorization can back at most one Phase S lease.

Preparation is admitted only when the Phase R record is approved and unexpired, its approval receipt and full lineage remain intact, the Phase Q health qualification remains qualified and healthy, and the shared read route is still the exact clean `local_source` state pinned by Phase R. Preparation performs fresh authoritative-local and recovery-replica integrity verification and binds the resulting proof, route version, hashes and fingerprints into the Phase S lease snapshot.

Activation uses optimistic route-version concurrency and requires the shared route to remain the exact prepared local state. The activator must be a current-tenant Admin with MFA and must differ from the lease preparer, the Phase R approver, the Phase Q qualifier and the relevant prior Phase P activator. An active Phase S route is bounded to a maximum 24-hour window.

While active, document reads may resolve only through the exact Phase S recovery replica. Every recovery read revalidates the lease and Phase R lineage, source hash and size, local storage-key fingerprint, replica hash, recovery bucket and object-key fingerprints, and the remote payload SHA-256 and length. Integrity or lineage drift fails closed. Temporary object-storage unavailability returns a retryable 503 and does not silently fall back to the local source while Phase S owns the route.

Rollback or expiry reconciliation atomically restores the single shared route to exact `local_source`, clears the Phase S pointer, advances the route version and records an append-only receipt. Reconciliation is idempotent when the lease is already terminal or remains healthy and unexpired.

The shared read-route control plane gains a distinct Phase S pointer and authority kind so temporary Phase J, durable Phase M, Phase P renewal and Phase S reauthorized renewal ownership remain mutually exclusive and auditable.

## Safety boundary

Phase 17.3-S changes only the document **read route** while its bounded lease is active. It does not:

- switch or duplicate the write path;
- mutate `Document.storage_key`;
- change authoritative storage ownership;
- enable dual-write;
- overwrite, move or delete authoritative local evidence;
- issue S3 COPY, DELETE or lifecycle mutations;
- authorize disposal; or
- authorize write-path or storage-ownership migration.

Database constraints and transition logic keep `write_path_switched`, `document_storage_key_mutated`, `authoritative_storage_changed`, `destructive_action_performed`, `s3_delete_performed` and `local_delete_performed` false throughout the Phase S lifecycle.

## Consequences

A successful Phase S activation provides one additional reversible recovery-read window while preserving explicit one-time authorization consumption, actor separation, route ownership and complete audit lineage. The cost is another explicit route authority type and lease/receipt pair, which is preferred to mutating Phase P history or making renewal behavior implicit.

Any later operational-health qualification, further renewal, durable ownership promotion, write-path migration or evidence disposal remains a separate phase requiring its own review and authority boundary.
