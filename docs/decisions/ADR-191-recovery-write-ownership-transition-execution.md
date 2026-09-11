# ADR-191: Bounded reversible recovery write-ownership transition

## Status
Accepted for Phase 17.3-AE.

## Context
Phase AD authorizes one later bounded recovery write-ownership transition only after an independently qualified healthy Phase AC canary-health artifact. That authorization creates no route, storage or destructive authority by itself.

The next enterprise-storage step must prove that the dedicated write-routing control plane can temporarily select the verified recovery replica while preserving the local evidence file as the authoritative rollback source. The transition must be reversible, short-lived, source-linked and auditable, and must not change the shared read route or `Document.storage_key`.

## Decision
Phase AE consumes one exact approved, healthy and unexpired Phase AD authorization and creates at most one execution lease.

Before activation it revalidates the complete AD → AC → AB → AA → Z → Y → X lineage, confirms the completed Phase AB route is back at exact `local_only`, confirms the shared read route remains exact `local_source`, re-verifies the authoritative local evidence, and performs a fresh recovery-replica HEAD+GET with SHA-256 and byte-length verification.

Activation extends the existing dedicated write-routing control plane with one additional bounded mode:

- `local_only`: no active canary or Phase AE lease;
- `local_plus_recovery_canary`: the existing Phase AB canary state;
- `recovery_primary`: exactly one active Phase AE lease, no active canary lease.

While `recovery_primary` is active:

- `local_authoritative` remains true for evidence authority;
- `write_path_switched` is true only as a bounded routing fact;
- the shared read route remains unchanged;
- `Document.storage_key` remains unchanged;
- durable write authority remains false;
- no evidence bytes are overwritten, moved or deleted;
- no S3 PUT/COPY/DELETE/lifecycle operation is authorized by Phase AE;
- no disposal authority is created.

The lease is bounded to at most ten minutes. Explicit rollback restores exact `local_only` routing. Expiry reconciliation also restores exact `local_only` routing when the active route still matches the lease. Unsafe route drift fails closed rather than pretending rollback succeeded.

Activation and every terminal transition create append-only, hash-bound receipts. One Phase AD authorization can produce at most one Phase AE lease. Exact activation and rollback replays are idempotent.

## Governance
Mutation endpoints require the existing Admin + MFA boundary. Read endpoints use the existing recovery reader boundary and remain tenant scoped.

The Phase AE activator must be independent from the Phase AD requester and approver and from the upstream AC qualifier, AB activator, AA requester/approver, Z qualifier, Y executor and X approver.

A recovery-storage outage during activation is retryable and does not consume the Phase AD authorization. Once activated, rollback does not depend on recovery object-storage availability.

## Consequences
Phase AE proves bounded reversible write-routing ownership without transferring durable evidence-storage ownership. Local evidence remains the authoritative rollback source throughout.

This ADR does not authorize permanent recovery write ownership, evidence deletion or disposal, a shared read-route switch, or any post-transition health qualification. Those require a later separately reviewed phase and fresh merge authorization.
