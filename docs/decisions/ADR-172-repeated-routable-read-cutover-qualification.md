# ADR-172: Repeated routable read cutover qualification

## Status
Accepted for Phase 17.3-K implementation.

## Context
Phase 17.3-J introduced the first bounded production read-path switch to a verified recovery replica. Each J cutover is deliberately short-lived, independently authorized and terminal after rollback. A single successful cutover is not enough evidence to justify durable promotion or any later write-path migration.

The next bounded step therefore needs to prove repeated successful cutover/rollback behavior without weakening the J control plane and without creating new routing authority.

## Decision
Phase 17.3-K introduces `EvidenceRecoveryRoutableReadQualification`, a tenant/claim/document-scoped governance record that can be requested only from exactly two distinct Phase J cutover leases that:

- belong to the same document and exact recovery replica lineage;
- were independently authorized;
- each reached `rolled_back` after an intact `local_source -> recovery_replica -> local_source` transition sequence;
- have exactly one activation and one rollback receipt with matching actors, timestamps, hashes and route versions;
- carry no write-path, storage-authority or destructive flags;
- leave the live read route in a clean `local_source` state with no active lease or replica.

The two cycles are hash-bound into a qualification bundle and a request snapshot. Qualification requires a second Admin with MFA who is different from the requester and from both cutover activators. Fresh receipt, lineage and live-route verification is performed at qualification time. Drift invalidates the pending record fail-closed.

## Authority boundary
A `qualified` Phase K record is **governance evidence only**. It is not a routing record, execution token, storage promotion, write authority or disposal authorization.

All Phase K rows and receipts are constrained to keep the following false:

- `routable_authority_created`
- `read_path_switched`
- `write_path_switched`
- `document_storage_key_mutated`
- `authoritative_storage_changed`
- `destructive_action_performed`
- `s3_delete_performed`
- `local_delete_performed`

Phase K does not modify `Document.storage_key`, local evidence bytes, S3 object bytes, lifecycle configuration, dual-write behavior or storage ownership.

## Consequences
A later separately reviewed phase may consume a valid Phase K qualification as one prerequisite for durable **read** promotion governance. That later phase must still perform fresh integrity and lineage checks and must define its own rollback and approval boundary.

Phase K does not authorize durable read routing, write-path migration, destructive migration or evidence disposal.
