# ADR-204: Independent post-disposal closure health qualification

## Status

Accepted for Phase 17.4-C implementation.

## Context

Phase 17.4-A creates a bounded, four-eyes credential for physical disposal. Phase 17.4-B consumes that credential and may remove the exact manifest-bound local evidence bytes after durable recovery authority has been independently established and freshly reverified.

A successful destructive execution is necessary but is not, by itself, sufficient closure evidence. After deletion, the system still needs an independently reviewable proof that:

- the exact local target remains absent;
- the authoritative recovery object still exists and contains the exact source bytes;
- recovery storage remains the durable authoritative-storage route;
- the Phase 17.4-B execution, per-document outcomes and append-only receipt chain have not been altered;
- the `Document` row and historical `Document.storage_key` remain preserved;
- no new legal hold, retention-policy drift or material governance drift invalidates closure; and
- the closure ceremony itself performs no storage, routing or destructive mutation.

Without this step, Enterprise Disposal would end at the destructive action rather than at independently qualified evidence that the destructive action left the intended durable-recovery state healthy.

## Decision

Introduce Phase 17.4-C as an observation-only, four-eyes post-disposal closure qualification.

### Admission source

One Phase 17.4-C qualification is bound to exactly one tenant/claim-scoped Phase 17.4-B execution. The execution must be `succeeded`, must retain its exact Phase 17.4-A authorization hashes and document-binding hash, and must still satisfy all Phase 17.4-B terminal safety invariants.

The linked Phase 17.4-A authorization must remain `consumed`, with `execution_count = 1` and the original authorization/approval evidence intact.

### Fresh closure observation

Both request and qualification perform a fresh observation of the post-disposal state. For every execution item the service requires:

- `status = verified`;
- the stored outcome hash recomputes exactly;
- local deletion and post-delete absence are recorded;
- the local target is freshly observed as absent;
- recovery was verified before and after deletion;
- `Document.deleted_at` remains null;
- `Document.file_hash`, size and storage-key fingerprint remain bound to the execution item;
- the linked Phase AO qualification and qualified receipt remain intact;
- the current authoritative-storage route remains `recovery_storage / durable_recovery` and points to the same durable Phase AN ratification;
- the ratification and replica remain bound to the same source hash and byte length; and
- a fresh recovery read recomputes the expected SHA-256 and byte length.

The final Phase 17.4-B execution hash and every Phase 17.4-B receipt hash are recomputed. Historical receipt hashes are recomputed from each receipt's stored `status_after` and event facts; the current terminal execution status is never substituted into historical receipt events.

### Governance separation

The closure requester and second qualifier are local Admin + MFA actors. They are independent from the material prior actor set, including the Phase 17.4-B executor, Phase 17.4-A requester/approver, release/quarantine/manifest/dry-run/source-authorization actors and actors captured in the linked Phase AO lineage.

The exact material actor set is canonicalized and hash-bound to the closure qualification.

### Lifecycle evidence

A closure qualification starts as `pending_second_approval` and may become `qualified`, `rejected`, `expired` or `invalidated`.

Lifecycle transitions emit append-only, SHA-256 hash-chained receipts. A qualified artifact binds:

- Phase 17.4-B execution hash;
- Phase 17.4-B receipt-chain hash;
- per-item outcome-hash aggregate;
- fresh verification snapshot hash;
- material actor-set hash;
- requester, qualifier and decision evidence.

Recovery-store unavailability is retryable. It must not falsely qualify or terminalize a pending artifact.

### Safety boundary

Phase 17.4-C is strictly observation-only. Database constraints keep all of the following false on qualification and receipt rows:

- storage writes;
- route or ownership mutation;
- read/write path switching;
- document storage-key mutation;
- destructive action;
- new physical-disposal authority;
- S3 PUT/COPY/DELETE;
- local overwrite/move/delete.

Phase 17.4-C never recreates a missing local copy and never deletes a reappeared local copy. Local-target reappearance is a fail-closed closure condition, not a cleanup instruction.

## Consequences

A `qualified` Phase 17.4-C artifact becomes the evidence gate for considering Enterprise Disposal 17.4 closed. It creates no additional deletion authority and cannot be used as an executor credential.

Operationally, the system can distinguish "destructive execution completed" from "destructive execution independently verified and closed." This preserves auditability around irreversible evidence handling while keeping the durable recovery copy authoritative.

## Alternatives rejected

### Treat Phase 17.4-B success as final closure

Rejected because the destructive executor would be self-certifying its own terminal state without an independent fresh observation.

### Re-run deletion when local evidence reappears

Rejected because closure verification must not broaden or renew destructive authority. A reappeared target requires new governance, not opportunistic cleanup.

### Require historical temporary read leases to remain active

Rejected because durable authoritative storage is established by the Phase AN/AO lineage. Temporary read/cutover leases may legitimately have been retired before physical disposal.

## Verification

Phase 17.4-C is released only after real-chain coverage proves independent qualification, receipt-chain integrity, fresh local absence, fresh recovery-byte verification, metadata preservation, actor separation, idempotent qualification replay, retryable recovery outage, fail-closed local reappearance, tamper rejection and zero storage/routing/destructive mutation.

References: #400, #399, #397, #396, #395, #394, #393.
