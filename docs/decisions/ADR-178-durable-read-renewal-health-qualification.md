# ADR-178: Durable read renewal health qualification

## Status
Accepted for Phase 17.3-Q implementation; production merge remains subject to fresh explicit approval after all gates are green.

## Context
Phase 17.3-P can execute one independently controlled, bounded durable recovery-read renewal window after Phase O authorization. A successful renewal must not become evidence for another renewal merely because the route eventually returned to local. The platform needs an immutable, independently reviewed record of what actually happened during that exact Phase P window.

## Decision
Phase Q introduces a **non-routable renewal-health qualification** for one exact completed Phase P lease.

A qualification can be requested only after Phase P has activated and terminally returned the shared route to `local_source` through rollback or active-window expiry reconciliation. Phase Q binds the request to the exact Phase P activation and terminal receipts, Phase O authorization, Phase N health qualification, prior Phase M durable lease, recovery replica, source fingerprints, route version and audited operational window.

At request and again before second approval, the service verifies:

- the Phase P lease and append-only transition receipts are internally consistent;
- the Phase O authorization remains approved and exactly matches Phase P;
- the Phase N record remains a qualified healthy source for Phase O/P;
- the prior Phase M lease remains terminal and matches the pinned lineage;
- the shared route is clean local with no temporary, durable-promotion or durable-renewal pointer;
- local authoritative bytes and the recovery candidate still match the pinned hash, size and lineage;
- at least one verified `recovery-replica-durable-renewal` read occurred inside the exact Phase P operational window;
- integrity, storage-unavailable and route-expiry failures are derived from audit evidence attributable to that exact renewal lease.

Health is classified as `healthy`, `degraded` or `failed`. Only a healthy snapshot can become `qualified`; non-healthy evidence becomes `degraded`. The qualification review window is ten minutes. An expired review becomes terminal `expired` rather than being silently extended.

Second approval is four-eyes controlled. The qualifier must differ from the requestor, Phase P renewal activator, Phase O authorization approver and prior Phase M activator. Mutations require Admin+MFA; Admin and Claims Manager may read tenant-scoped qualification evidence.

Object-storage unavailability during the fresh approval preflight is retryable and fails closed with no state transition. Integrity or lineage drift invalidates the pending qualification. Receipts are append-only and audit payloads contain identifiers, hashes, fingerprints and bounded counters rather than raw storage keys.

## Safety boundary
Phase Q is governance evidence only. It does **not** create or extend routable authority. It does not switch a read path, switch or duplicate a write path, mutate `Document.storage_key`, change authoritative storage ownership, enable dual-write, overwrite/move/delete local evidence, issue S3 COPY/DELETE/lifecycle mutations, or authorize evidence disposal.

The qualification and receipt tables database-constrain all routing, write, storage-ownership and destructive flags to `false`.

## Consequences
A later separately reviewed phase may consume one exact unexpired/acceptable **qualified Phase Q record** as evidence when deciding whether to authorize another bounded renewal. That later phase must perform fresh integrity/lineage checks and independent approval. Phase Q itself is never an authorization and never changes the live route.

This preserves a deliberate sequence: execute a bounded renewal, return to local, independently qualify the observed window, then separately consider any future renewal.
