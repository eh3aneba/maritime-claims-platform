# ADR-181: Reauthorized durable-read renewal health qualification

## Status
Accepted for Phase 17.3-T implementation.

## Context
Phase 17.3-S introduced a second bounded, reversible recovery read-routing window after one exact Phase R reauthorization. Phase S remains read-only: local evidence stays authoritative, `Document.storage_key` stays unchanged, write routing does not move, and rollback or expiry reconciliation restores the shared read route to `local_source`.

A successful activation alone is not enough evidence for a later storage-authority decision. Before any stronger read/storage ownership transition can be considered, the platform needs an immutable, independently reviewed record of what actually happened during the exact Phase S operational window.

## Decision
Phase 17.3-T adds a separate, non-routable health qualification bound to one exact completed Phase S lease.

A qualification request is admitted only when all of the following remain true:

- the Phase S lease completed as `rolled_back` or `expired` after a real activation;
- exactly one activation receipt and one matching terminal receipt prove the route changed from local to the pinned recovery replica and back to local;
- the shared read route is currently exact `local_source`, with no active temporary, durable-promotion, Phase P renewal or Phase S reauthorized-renewal pointer;
- the Phase S lease still matches its exact Phase R reauthorization, Phase Q qualified health record and prior Phase P lease, which preserve the underlying O→N→M lineage;
- local authoritative bytes still match the pinned source hash, length and storage-key fingerprint;
- the recovery replica still matches the pinned replica hash, bucket/key fingerprints and verified object SHA-256/length;
- at least one successful document read during the exact Phase S window is attributable to that exact Phase S lease in the audit stream.

Phase T derives bounded operational evidence only from audit events attributed to the exact Phase S lease and window. It records successful verified recovery reads, integrity/lineage failures, storage-unavailable outcomes and route-expired attempts. Integrity failures classify the window as `failed`; storage unavailability without integrity failure classifies it as `degraded`; otherwise the window is `healthy`. Only `healthy` evidence may become `qualified`.

The request enters `pending_second_approval` for a short review window. Qualification requires a current-tenant Admin with MFA who is independent from the requester, the Phase S activator, Phase R approver, Phase Q qualifier and prior Phase P activator. Fresh lineage and byte-integrity checks run again at qualification time. Object-storage unavailability is retryable and does not silently terminalize the pending governance record; lineage or integrity drift invalidates fail-closed.

Qualification and transition receipts are append-only and hash-bound. Audit payloads contain IDs, hashes, fingerprints, bounded counters and timestamps only; raw local or remote storage keys are excluded.

## Safety boundary
Phase T is governance evidence only. It does not:

- create, extend or switch a read route;
- switch or duplicate the write path;
- mutate `Document.storage_key`;
- change authoritative storage ownership;
- enable dual-write;
- overwrite, move or delete authoritative local evidence;
- issue S3 COPY, DELETE or lifecycle mutations;
- authorize disposal;
- authorize write-path or storage-ownership migration.

Database constraints keep all routing, write, ownership and destructive authority flags false on both the qualification and its receipts.

## Consequences
A qualified Phase T record demonstrates that the platform has completed repeated bounded recovery-read operation through M→N→O→P→Q→R→S and returned cleanly to local authority with independently reviewed operational evidence. It is still not an execution token and grants no storage authority.

Any later move toward durable read ownership, write-path migration, dual-write, local evidence retirement or disposal requires a new separately reviewed phase with its own explicit authority boundary and fresh user merge approval.

## References
- Issue #347
- Phase S Issue #345 / PR #346
- Phase R Issue #343 / PR #344
- Phase Q Issue #341 / PR #342
- Roadmap #25
