# ADR-165: Governed recovery promotion dry-run and cutover attestation

## Status
Accepted for Phase 17.3-D implementation.

## Context
Phase 17.3-B established immutable recovery replicas and Phase 17.3-C proved that a verified replica can be restored into an isolated local staging namespace. That proves recoverability but deliberately grants no authority to promote restored bytes into the live evidence path.

A later disaster-recovery cutover would be a materially higher-risk action because it could change which storage object is authoritative for a claim document. Before any executor exists, the platform needs a separately governed artifact that proves exactly what would be promoted, who reviewed it, and whether source/replica/restore state remained unchanged between request and second approval.

## Decision
Introduce `EvidenceRecoveryPromotionAttestation` as a tenant/claim/document-scoped, four-eyes, non-cutover approval artifact.

The attestation binds:
- exact `EvidenceRecoveryReplica` id and replica hash;
- exact `EvidenceRecoveryRestoreRehearsal` id and rehearsal hash;
- the latest restore verification id and verification hash at request time;
- authoritative source hash, byte length, document-update timestamp and storage-key fingerprint;
- recovery bucket and recovery object-key fingerprints;
- restore staging-key fingerprint;
- a configuration fingerprint;
- an immutable dry-run promotion plan and plan hash.

The approval lifecycle is:
- `pending_second_approval`
- `approved`
- `rejected`
- `expired`
- `invalidated`

The review window is one hour. The requester and approver must be different local Admin users and both mutations require current-tenant MFA under the existing retention governance dependency.

Request and second approval each freshly revalidate the current local authoritative source, recovery replica, remote object integrity, restore rehearsal lineage, restore staging integrity and latest restore verification. Any semantic drift invalidates the pending attestation instead of permitting approval.

## Dry-run plan
The plan is content-only governance evidence. It contains action classes, object ids, hashes and fingerprints, with every action marked `execute=false`.

It may describe a future authority-switch placeholder, but it performs no authority switch and cannot be interpreted as an execution token.

## Hard safety boundary
Phase 17.3-D does **not**:
- rewrite `Document.storage_key`;
- change the active document storage backend;
- move, overwrite, archive or delete the authoritative local file;
- issue S3 COPY, DELETE or lifecycle mutations;
- create dual-write admission;
- promote the restore staging artifact;
- create a recovery cutover worker or executor;
- create a destructive token.

Database constraints require both `cutover_performed=false` and `authoritative_storage_changed=false` for every attestation row.

Audit payloads contain hashes/fingerprints only and explicitly record that cutover, authority change and destructive actions were not performed.

## Consequences
A future recovery executor cannot legitimately rely on a restore rehearsal alone. It must be designed as a separate phase and must require a still-valid, freshly revalidated approved attestation or a successor authorization artifact.

Even an `approved` Phase 17.3-D attestation remains evidence of review only. It is not execution authority.

## Future work
A subsequent phase may design a reversible recovery activation rehearsal or a separately governed cutover execution contract. That work must define atomicity, rollback, idempotency, partial-failure handling, read/write authority, race protection and explicit operator ceremony before any live authority mutation is introduced.
