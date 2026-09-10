# ADR-179: Qualified renewal health may authorize one later bounded read renewal

## Status

Accepted for Phase 17.3-R implementation.

## Context

Phase Q produces non-routable operational-health evidence for one completed Phase P durable recovery read renewal window. A `qualified` Phase Q record proves that the exact completed window had at least one verified durable recovery read, no integrity failures, no object-storage unavailability, intact local and recovery evidence, and a shared read route returned to the exact clean `local_source` state.

That evidence must not silently create another route or become an open-ended durable-read entitlement. A new governance boundary is required before any later renewal execution can be considered.

## Decision

Phase 17.3-R introduces a separate durable-read renewal **reauthorization** record and append-only receipts.

One exact `qualified` Phase Q record may produce at most one Phase R reauthorization. Request and approval both perform fresh lineage and integrity preflight through the Phase Q snapshot, preserving the exact Phase P → Phase O → Phase N → Phase M lineage and recovery replica fingerprints.

Phase R requires:

- Phase Q status `qualified` and health state `healthy`;
- at least one verified durable recovery read in the observed Phase P window;
- zero integrity failures and zero storage-unavailable events;
- the shared route to remain exact clean `local_source`, with no active temporary, durable, or durable-renewal lease;
- fresh local authoritative-byte and recovery-candidate integrity verification;
- Admin + MFA for mutations and a second independent Admin for approval;
- the approver to differ from the Phase R requester, Phase Q qualifier, Phase P activator, Phase O approver, and prior Phase M activator;
- a 10-minute second-approval review window;
- after approval, a separate 10-minute authorization-consumption window;
- exact replay semantics and tenant-scoped reads;
- content-minimized audit receipts containing IDs, hashes, fingerprints, bounded counters, actor IDs, and timestamps rather than raw storage keys.

Transient object-storage unavailability during fresh approval preflight is retryable and leaves the pending authorization unchanged. Integrity, lineage, or route drift invalidates the pending authorization fail-closed.

## Non-routable safety boundary

Phase R is governance authorization only. It does not:

- create, switch, or extend a read route;
- bind the shared route to a new lease;
- switch or duplicate the write path;
- mutate `Document.storage_key`;
- change authoritative storage ownership;
- enable dual-write;
- overwrite, move, or delete authoritative local evidence;
- issue S3 COPY, DELETE, or lifecycle mutations;
- authorize disposal;
- authorize write-path or storage-ownership migration.

These routing, write, storage-ownership, and destructive flags are database-constrained `false` on both the authorization and receipt records.

## Consequences

A later separately reviewed execution phase may consume one exact unexpired approved Phase R authorization and create a bounded, reversible **read-only** renewal lease. That future phase must enforce one-time consumption, fresh route/integrity checks, route-version concurrency control, bounded expiry, explicit rollback/reconciliation, and the same local-authoritative/write-path safety boundary.

Phase R itself cannot make a recovery replica authoritative and cannot route a single read.

## Alternatives rejected

### Let Phase Q directly renew the route

Rejected because health evidence and routing authority would become the same capability, weakening four-eyes separation and making a qualified health record operationally active.

### Reuse or mutate the prior Phase O authorization

Rejected because Phase O was bound to the first Phase P renewal. Reusing it would blur immutable lineage, replay semantics, and one-time authorization intent.

### Issue an open-ended durable-read entitlement

Rejected because durable recovery reads remain bounded and revocable; every additional window requires fresh health evidence and governance review.

## Follow-up boundary

The next phase may implement one-time execution of an exact unexpired approved Phase R authorization. It must remain read-only and reversible and must not introduce write authority, storage ownership transfer, evidence destruction, or disposal.