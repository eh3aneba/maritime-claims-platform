# ADR-183: Bounded recovery read-ownership transition

## Status

Proposed for Enterprise Storage Phase 17.3-V.

## Context

Phase 17.3-U creates a short-lived, non-routable governance authorization from one exact healthy and qualified Phase T record. That authorization is intentionally not execution authority. The next transition must remain reversible and read-only while establishing a stronger operational proof that the verified recovery replica can own the document read path for a bounded window.

The platform already supports temporary, durable, renewal and reauthorized-renewal recovery read leases. Phase V must not reinterpret those historical leases or silently widen them into storage ownership. It needs its own independently attributable state and receipts, must consume one exact unexpired approved Phase U authorization once, and must preserve the authoritative local evidence and write path.

## Decision

Introduce a separate Phase 17.3-V recovery read-ownership transition lease.

The lease may be prepared only from one exact approved and unexpired Phase U authorization. Preparation revalidates the Phase U snapshot, local authoritative bytes, recovery replica bytes, and the clean shared route. Activation requires a different current-tenant Admin with MFA and fresh revalidation.

While activated, the shared document read route is bound to the verified recovery replica under a distinct `read_ownership_transition` authority. This authority owns only read routing for the bounded lease window. It does not own the evidence object, write path, document storage pointer, retention/disposal lifecycle, or authoritative storage semantics.

The active window is capped at 72 hours. Explicit rollback is always risk-reducing and remains available after expiry. Reconciliation restores the exact clean local route after expiry. Integrity/lineage drift fails closed. Object-storage unavailability while the transition owns reads returns a retryable unavailable response without silent local fallback.

One Phase U authorization may back at most one Phase V lease. Activation must be separated from the preparer and from the Phase U approver. All transition receipts are append-only and hash-bound.

## Safety boundary

Phase V may change only the document read route while its bounded lease is active.

It MUST NOT:

- switch or duplicate the write path;
- mutate `Document.storage_key`;
- change authoritative storage ownership;
- enable dual-write;
- overwrite, move or delete authoritative local evidence;
- issue S3 COPY, DELETE or lifecycle mutations;
- authorize disposal;
- create write-path or storage-ownership migration authority.

Local evidence remains intact as the rollback source throughout the lease.

## Failure and rollback semantics

- Preparation and activation require the shared route to be exact clean `local_source` at the Phase U pinned route version.
- Activation uses route-version concurrency control and increments the shared route version exactly once.
- Every recovery read freshly verifies the active lease, Phase U authorization lineage, replica identity, source/candidate authority fingerprints, configuration fingerprint, object metadata, SHA-256 and byte length.
- Integrity or lineage drift fails closed and does not silently fall back to local reads.
- Transient object-storage unavailability returns retryable service unavailability while the transition owns reads.
- Explicit rollback atomically restores `local_source`, clears the Phase V pointer and increments route version.
- Expiry reconciliation restores the same clean local state.

## Governance

- Mutations: current-tenant Admin + MFA.
- Reads: Admin and Claims Manager.
- Tenant isolation: cross-tenant resources resolve as not found.
- Prepare and activation are four-eyes; the activator differs from the preparer and Phase U approver.
- Exact replay is idempotent. Mutating replay with changed reason or actor conflicts.
- Audit payloads contain IDs, hashes, fingerprints, counters and timestamps only; raw storage identifiers are excluded.

## Consequences

Phase V provides stronger, independently attributable evidence that recovery can own the read path for a materially longer bounded window while preserving immediate rollback and all local authoritative bytes. It still does not justify write-path migration, dual-write or authoritative storage transfer.

A later Phase 17.3-W should qualify the operational health of one exact completed Phase V window before any write/storage authority transition is considered.
