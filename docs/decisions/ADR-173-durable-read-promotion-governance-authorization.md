# ADR-173: Durable recovery read promotion governance authorization

## Status
Accepted for Phase 17.3-L implementation.

## Context
Phase 17.3-J demonstrated the first bounded reversible production read-path cutover to a verified recovery replica. Phase 17.3-K then required two independently authorized J cutover/rollback cycles and converted those repeated successful rehearsals into non-routable qualification evidence.

Repeated cutover evidence alone must not silently become durable routing authority. Before any long-lived read promotion is considered, the current source bytes, recovery candidate, route state and Phase K lineage must be revalidated under a new four-eyes approval boundary.

## Decision
Phase 17.3-L introduces `EvidenceRecoveryDurableReadPromotionAuthorization`, a tenant/claim/document-scoped governance record that may be requested only from one exact Phase K record in `qualified` state.

Request and approval both require fresh checks that:

- the Phase K qualification and its `qualified` receipt remain intact and hash-bound;
- the exact two qualifying Phase J cycles still revalidate through Phase K;
- the live read route remains `local_source`, with no active lease or replica and with the same route version and authority/configuration fingerprints pinned by Phase K;
- the authoritative local bytes still match `Document` metadata and the pinned recovery replica;
- the recovery object still passes HEAD/GET SHA-256 and content-length verification;
- no read/write/storage-authority/destructive boundary has been crossed.

The authorization window is at most ten minutes. Approval requires an Admin with MFA who differs from the requester, the Phase K qualifier, and both Phase J cutover activators. Exact request/approval/rejection replays are idempotent; mismatched replays conflict. Snapshot drift invalidates a pending record fail-closed. A temporary recovery-storage availability failure remains fail-closed but retryable and therefore does not itself create approval or routing authority.

## Authority boundary
An `approved` Phase L record is governance evidence only. It is not a durable read route, temporary route, execution token, write authority, storage-ownership change, or disposal authorization.

All authorization and receipt rows constrain the following to false:

- `routable_authority_created`
- `durable_read_route_created`
- `read_path_switched`
- `write_path_switched`
- `document_storage_key_mutated`
- `authoritative_storage_changed`
- `destructive_action_performed`
- `s3_delete_performed`
- `local_delete_performed`

Phase L performs read-only integrity checks against the existing local source and recovery candidate. It does not rewrite `Document.storage_key`, overwrite/move/delete local evidence, issue S3 COPY/DELETE/lifecycle mutations, enable dual-write, or change storage ownership.

## Consequences
A later separately reviewed tranche may consume one exact unexpired approved Phase L authorization to introduce a reversible durable read-routing promotion with its own activation, rollback, reconciliation, expiry and operational safeguards.

That later tranche must remain read-only with respect to evidence content unless an additional separately governed write/storage-authority phase is approved. Phase L does not authorize durable routing, write-path migration, destructive migration, or evidence disposal.
