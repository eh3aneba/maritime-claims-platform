# ADR-163: Governed S3 recovery replication and verification

- **Status:** Accepted
- **Date:** 2026-09-09
- **Phase:** 17.3-B
- **Related:** ADR-162, Issues #25 and #310, PR #309

## Context

Phase 17.3-A introduced a bounded S3-compatible storage client as a recovery-target foundation while deliberately keeping local document storage authoritative. The platform still must prove that authoritative evidence can be replicated to a recovery target and independently read back with byte-level integrity before any later storage cutover or irreversible disposal design is considered.

A recovery copy must not silently become a second authority. It must not change a `Document.storage_key`, move or delete the authoritative local file, or create deletion authority. Existing remote objects must never be overwritten merely because a recovery operation is retried.

## Decision

### Local evidence remains authoritative

Phase 17.3-B does not change active document admission or read authority. `STORAGE_BACKEND=local` remains required for recovery replication. A recovery replica is evidence of recoverability, not the canonical document location.

The service snapshots and verifies the authoritative local bytes against the existing `Document.file_hash` and `Document.file_size_bytes` before any remote operation. The source storage key is pinned only by SHA-256 fingerprint in recovery lineage and audit metadata.

### Immutable replica lineage

Each `Document` may have one `EvidenceRecoveryReplica`. The record pins:

- tenant, claim, and document identity;
- source SHA-256 and byte length;
- source document update timestamp;
- source storage-key fingerprint;
- deterministic recovery object key;
- recovery bucket fingerprint;
- replica lineage hash and actor/time metadata.

A changed local source is not silently repinned. A new recovery lineage would require a separately reviewed future mechanism rather than mutating the existing proof.

### Append-only verification history

Each successful initial verification and every later re-verification creates a separate `EvidenceRecoveryVerification` record. Verification performs both:

1. `HEAD` validation of remote SHA-256 metadata and byte length; and
2. `GET` of the full recovery bytes with SHA-256 verification.

Verification history is append-only so a later successful check cannot erase earlier recovery evidence.

### Deterministic, non-overwriting remote creation

Recovery objects use a managed key under:

`recovery/evidence/{organization_id}/{claim_id}/{document_id}{suffix}`

Initial object creation uses conditional S3 `PUT` with `If-None-Match: *`. HTTP 412 means the key already exists; the existing object is never overwritten. Whether newly created or already present, the object must then pass exact HEAD+GET hash and size verification. A conflicting or tampered object fails closed.

### Human authority and tenant isolation

Recovery mutations require a local Admin under the tenant MFA policy. Admins and Claims Managers may read recovery lineage and verification history. Every query is tenant/claim/document scoped.

Audit events record hashes, fingerprints, outcome class, and the explicit facts that local authority remains unchanged and no destructive action occurred. Raw credentials, signed requests, and secrets are never stored in recovery records or audit values.

## Explicit non-goals

Phase 17.3-B introduces none of the following:

- S3 `DELETE` or object lifecycle policy;
- S3 copy/migration or background migration worker;
- local evidence deletion, move, or tombstone;
- `Document.storage_key` rewrite;
- dual-write document admission;
- S3 active-backend cutover;
- automatic recovery promotion;
- retention/disposal decision authority;
- physical disposal executor or destructive token.

## Consequences

The platform gains independently verifiable recovery copies without changing evidence authority. Storage failure, source drift, remote mismatch, missing objects, and tenant/MFA violations all fail closed.

Replication currently reads the full local object and performs a full remote GET verification. This is intentionally bounded by the existing upload-size regime and favors correctness over throughput at this stage.

## Follow-up

A later Phase 17.3-C may introduce governed recovery drills, replication coverage/read-shadow measurement, or restore rehearsal. Active storage cutover remains a separate decision and must not be inferred from a verified recovery replica.
