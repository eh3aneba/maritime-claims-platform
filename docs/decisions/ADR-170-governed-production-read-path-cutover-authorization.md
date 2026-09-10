# ADR-170: Governed production read-path cutover authorization

## Status
Accepted for Phase 17.3-I.

## Context
Phase 17.3-H introduced a bounded production-execution control-plane lease and proved that the exact cutover envelope can be prepared, independently activated and rolled back without changing the live document read path. A later routable cutover would cross a materially different authority boundary, so it must not be inferred from the Phase H lease or its activation.

The next safe step is therefore a separate governance contract that consumes one exact successfully rolled-back `EvidenceRecoveryCutoverExecutionLease` and records explicit human approval for a future reversible read-path cutover. The authorization itself remains non-routable.

## Decision
Introduce `EvidenceRecoveryReadPathCutoverAuthorization` and append-only authorization receipts.

An authorization request is allowed only when the bound execution lease is in `rolled_back`, has intact `activated` and `rolled_back` transition receipts, and its full cutover-admission/recovery lineage still revalidates. The request pins the exact lease, both transition receipts, the approved admission, recovery lineage, source/candidate authority fingerprints and current configuration fingerprint into an immutable hash-bound snapshot.

The authorization state machine is:

`pending_second_approval -> approved | rejected | expired | invalidated`

Approval requires a different current-tenant Admin from the requester and from the Phase H execution-lease activator. Mutations require current-tenant Admin + MFA. Admin and Claims Manager may read the authorization and receipts. The approval window is at most 10 minutes and never extends beyond the still-applicable parent admission/attestation boundary.

## Safety boundary
Phase 17.3-I does not route reads and does not create execution authority.

The database pins all of these to false:
- `routable_authority_created`
- `read_path_switched`
- `document_storage_key_mutated`
- `active_backend_changed`
- `authoritative_storage_changed`
- `destructive_action_performed`
- `s3_delete_performed`
- `local_delete_performed`

`Document.storage_key` remains authoritative and the existing document download path remains unchanged. There is no local evidence overwrite/move/delete, no S3 COPY/DELETE/lifecycle mutation, no dual-write admission and no irreversible disposal.

## Consequences
- A later separately reviewed tranche can consume one exact approved authorization as the governance prerequisite for a reversible routable read-path cutover.
- Phase H execution evidence cannot silently become live routing authority.
- Any lineage, integrity, configuration or transition-receipt drift before approval invalidates fail-closed.
- A rejected, expired or invalidated authorization is terminal and cannot be reused.
- Live evidence authority remains local until a later phase explicitly implements and governs a reversible routing switch.
