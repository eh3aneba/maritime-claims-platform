# ADR-164 — Governed Recovery Restore Rehearsal

- Status: Proposed
- Date: 2026-09-09
- Phase: 17.3-C
- Related: #25, #308, #309, #310, #311, #312

## Context

Phase 17.3-A established a bounded S3-compatible evidence-storage foundation without activating it for document admission. Phase 17.3-B added verified recovery replicas while keeping local evidence authoritative.

A verified replica is not sufficient proof that recovery operations are safe. The platform must also prove that replica bytes can be downloaded and restored into local storage without overwriting authoritative evidence, changing `Document.storage_key`, or silently adopting an ungoverned staging artifact.

## Decision

Add a **recovery restore rehearsal** that restores a verified recovery replica into an isolated local staging namespace only.

The rehearsal is evidence of recoverability. It is not evidence authority, cutover authority, retention authority, or disposal authority.

### Authority boundary

1. Local `Document.storage_key` remains authoritative and immutable in this phase.
2. Existing authoritative local evidence is never overwritten, moved, deleted, archived, or replaced.
3. S3 recovery objects are never deleted, copied, lifecycle-mutated, or promoted.
4. Rehearsal bytes may be written only under the managed `recovery-restore-staging/` namespace.
5. No route or service in this phase can promote staged bytes into the authoritative namespace.
6. No active S3 backend cutover, dual-write admission, destructive worker, or disposal token is introduced.

### Restore preflight

Every rehearsal or re-verification must freshly validate:

- the tenant/claim/document scope;
- the authoritative local source SHA-256 and byte length against `Document` metadata;
- the immutable `EvidenceRecoveryReplica` lineage against the current source snapshot;
- the configured recovery bucket fingerprint against the pinned replica;
- remote HEAD metadata against the pinned hash and byte length;
- a full remote GET against the pinned SHA-256;
- staged bytes against the same pinned SHA-256 and byte length.

Any drift fails closed.

### Staging publication

A new rehearsal uses a deterministic managed staging key derived only from organization, claim, document, and replica IDs.

The staged file is created through an isolated temporary file, flushed, integrity-checked, and then atomically published inside the staging namespace with no-overwrite semantics. If a target already exists without an immutable rehearsal record, the platform refuses to adopt or overwrite it.

Temporary staging artifacts may be cleaned up. This cleanup authority does not extend to authoritative evidence or recovery replicas.

### Rehearsal lineage

`EvidenceRecoveryRestoreRehearsal` is immutable service-level lineage for one replica. Exact replay re-verifies the same rehearsal instead of writing a new staged target.

`EvidenceRecoveryRestoreVerification` is append-only and records each fresh remote + staged integrity verification.

Audit output contains storage-key fingerprints, never raw authoritative or staging paths.

### Access control

- Mutations: local Admin with current tenant MFA assurance.
- Reads: Admin and Claims Manager.
- Cross-tenant access fails as not found.

## Consequences

### Positive

- Recovery becomes empirically rehearsed rather than assumed.
- A verified S3 replica can be independently restored without evidence-authority changes.
- Unknown/preexisting staging artifacts cannot be silently trusted.
- Restore verification history is append-only and auditable.
- The next cutover-readiness phase can build on demonstrated recoverability.

### Costs and limitations

- Staging artifacts consume local disk space and are not automatically garbage-collected in this phase.
- File-system and database commits are not one distributed transaction; orphaned staging artifacts therefore fail closed and require governed reconciliation rather than automatic adoption.
- This phase does not make S3 authoritative and does not provide a promotion path.

## Explicit non-goals

This ADR does not authorize or implement:

- S3 DELETE or COPY;
- object lifecycle rules;
- local authoritative file deletion/move/overwrite;
- `Document.storage_key` mutation;
- restore promotion;
- admission dual-write;
- active storage cutover;
- irreversible disposal.

A future cutover or promotion phase requires a separate ADR, tests, production gates, and fresh explicit approval.
