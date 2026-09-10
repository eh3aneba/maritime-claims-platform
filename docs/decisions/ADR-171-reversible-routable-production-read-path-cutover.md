# ADR-171: Reversible routable production read-path cutover

## Status
Accepted for Phase 17.3-J.

## Context
Phases 17.3-A through 17.3-I progressively proved recovery replication, restore rehearsal, promotion evidence, shadow verification, authority-switch rehearsal, cutover admission, bounded execution control and explicit read-path cutover authorization while keeping the production document read path local.

Phase 17.3-J is the first tranche allowed to alter live read routing. That authority must remain narrower than evidence ownership: the local `Document.storage_key` and local evidence bytes remain authoritative and intact, while a short-lived route record may direct reads to one exact verified recovery replica.

## Decision
Introduce three bounded records:

- `EvidenceRecoveryReadPathCutoverLease`: immutable/hash-bound admission for one exact approved Phase I authorization and one exact verified recovery replica.
- `EvidenceRecoveryReadPathRoute`: one mutable, tenant/claim/document-scoped routing pointer whose only states are `local_source` and `recovery_replica`.
- `EvidenceRecoveryReadPathCutoverReceipt`: append-only transition evidence for prepare, activate, rollback, expiry and invalidation.

The lease state machine is:

`prepared -> activated -> rolled_back`

with fail-closed terminal states `expired` and `invalidated` before activation.

Activation requires a fresh full-lineage preflight, independent Admin activation and a verified remote GET. It changes only the dedicated route record from `local_source` to `recovery_replica`. The route is bound to the exact active lease and exact replica.

The document download endpoint consults the route. Without an active recovery route it uses the existing local `Document.storage_key`. With an active recovery route it revalidates the exact lease, authorization, recovery lineage, local source lineage, configuration and remote SHA-256 integrity before returning recovery bytes. Any inconsistency fails closed instead of silently falling back to another source.

Rollback is risk-reducing and returns the route to `local_source` without changing or deleting evidence bytes.

## Safety boundary
Phase 17.3-J changes read routing only. It does not promote recovery storage to authoritative evidence storage and does not change the write path.

The following remain false by database constraint throughout the tranche:

- `write_path_switched`
- `document_storage_key_mutated`
- `authoritative_storage_changed`
- `destructive_action_performed`
- `s3_delete_performed`
- `local_delete_performed`

Local evidence remains present as the immediate rollback source. There is no S3 COPY/DELETE/lifecycle mutation, local overwrite/move/delete, dual-write admission, evidence disposal or irreversible migration.

## Operational consequences
- Operators can prove a real production read from the verified recovery replica without changing evidence ownership.
- The route is explicit and observable rather than inferred from an authorization or lease.
- An expired or drifted active route fails closed and requires explicit rollback; it never silently falls back while claiming recovery routing remained active.
- Every transition is hash-bound and auditable without exposing raw recovery object keys.
- Repeated successful activation/rollback evidence is required before any later durable promotion or write-path migration can be considered.

## Next boundary
A later separately reviewed tranche may consider durable read promotion or a write-path migration only after repeated successful routable cutovers and rollbacks. Phase 17.3-J authorizes neither destructive migration nor evidence disposal.
