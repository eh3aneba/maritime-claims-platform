# ADR-159: Governed disposal dry-run ceremony and attestation

- Status: Proposed
- Date: 2026-09-09
- Decision owners: MCRI enterprise retention governance
- Related: #25, #298, #299, #300, #301, #302, ADR-154, ADR-155, ADR-156, ADR-157, ADR-158

## Context

Phase 17.2-D introduced a four-eyes `DisposalAuthorization`, and Phase 17.2-E introduced an immutable, short-lived `DisposalExecutionManifest` that inventories the exact claim/document/storage metadata a future disposal executor would need to verify. Neither phase performs deletion or storage mutation.

The next governance gap is operational rehearsal: before any destructive capability is even considered, MCRI needs a way to prove that a live manifest can be reproduced, reviewed by a separate human, and attested without converting that rehearsal into execution authority.

## Decision

Introduce a tenant- and claim-scoped `DisposalDryRunCeremony` as a **non-destructive rehearsal record**.

### 1. Ceremony source

A ceremony may only be opened from a `ready`, unexpired `DisposalExecutionManifest`. Opening the ceremony performs a fresh manifest revalidation first.

Any active legal hold, pending legal-hold proposal, retention-policy drift, claim/evidence/storage drift, authorization expiry, manifest expiry, or stored-integrity failure prevents a ceremony from becoming pending for attestation.

### 2. Human separation

Opening and attesting a ceremony require a local Admin with current tenant MFA assurance.

The ceremony creator may not attest their own ceremony. This creates a new human checkpoint beyond the prior disposal-authorization and manifest-preflight controls.

No AI subsystem, external signal, webhook, rule, worker, service account, or timer is allowed to attest.

### 3. Dry-run plan

The plan is derived only from the stored manifest inventory and contains:

- stable object identifiers;
- row fingerprints;
- file hashes where applicable;
- storage-key fingerprints, never raw storage keys;
- byte counts and bounded version metadata;
- an explicit `dry_run_only` mode and simulated action label.

The plan contains no file content, no executable credentials, no raw storage locations, and no API/job payload capable of deleting or mutating data.

The canonical plan is SHA-256 hashed. The ceremony hash binds the plan hash to the exact manifest, authorization lineage, policy lineage, creator, opening reason, opening time, and expiry.

### 4. Short validity

A ceremony is valid for at most 30 minutes and never beyond the parent manifest expiry.

The lifecycle is:

`pending_attestation | attested | blocked | invalidated | expired | cancelled`

Terminal states never revive.

### 5. Independent attestation

Attestation performs another live manifest revalidation. It then verifies:

- stored ceremony integrity;
- exact manifest hash and inventory hash;
- exact authorization and retention-policy lineage;
- document count and total bytes;
- exact regenerated dry-run plan and plan hash.

If any state changes, the ceremony fails closed as blocked, invalidated, or expired.

A successful attestation records the human attester, attestation time, reason, and a canonical attestation hash.

### 6. No execution authority

An `attested` ceremony is evidence that a rehearsal succeeded. It is **not** an execution token, capability, job, command, credential, approval for deletion, or permission to mutate storage.

Audit records explicitly include:

- `execution_authority_created=false`
- `destructive_action_performed=false`
- `storage_identifiers_raw_logged=false`

### 7. No destructive runtime path

Phase 17.2-F adds:

- no DELETE endpoint;
- no claim/document `deleted_at` mutation;
- no object-store delete/move/archive/lifecycle mutation;
- no tombstone or quarantine mutation;
- no destructive worker;
- no timer-driven execution;
- no automatic follow-on action.

## Consequences

### Positive

- A future destructive capability cannot claim operational readiness merely because an authorization and manifest exist.
- The system proves that a second human can independently reproduce and attest the exact dry-run plan.
- Storage identifiers remain minimized while still allowing drift detection.
- The audit chain records a clear non-destructive ceremony boundary.

### Trade-offs

- Organizations need at least two eligible local Admin actors to complete a ceremony.
- Short-lived ceremonies may expire and require a fresh authorization/manifest chain before another rehearsal.
- This adds governance overhead before any irreversible execution is considered.

## Follow-up

A later phase may consider a **reversible quarantine or tombstone staging design**, but only as a separately reviewed authority boundary. Any physical deletion or irreversible object-store/database mutation remains explicitly out of scope until recovery, hold precedence, idempotency, incident rollback, and human execution controls are independently designed and approved.
