# ADR-168: Governed recovery cutover admission contract

## Status
Accepted for Phase 17.3-G.

## Context
Phase 17.3-F proved that a recovery candidate can enter and leave a virtual authority state without changing production evidence authority. A future real cutover must not be reachable directly from that rehearsal. We need a separate, short-lived governance artifact that proves the exact rehearsal completed activation and rollback, pins all recovery lineage, and requires an independent human approval before any future execution capability can even be designed.

## Decision
Introduce `EvidenceRecoveryCutoverAdmission` and append-only `EvidenceRecoveryCutoverAdmissionReceipt` records.

An admission can be requested only when the bound `EvidenceRecoveryAuthoritySwitchRehearsal` is `rolled_back`, its virtual authority has returned to the pinned authoritative-source fingerprint, and the exact activation and rollback receipts are present and consistent. Request and approval both perform fresh recovery-lineage and integrity revalidation across source evidence, S3 replica, restore staging, shadow promotion, latest verification lineage, configuration fingerprint, and promotion attestation.

The admission window is at most 15 minutes and cannot outlive the parent promotion attestation. Approval requires a different local Admin with current-tenant MFA. Drift or expiry fails closed.

## Safety boundary
`approved` is governance evidence only. It does not create executable authority.

This phase does **not**:
- rewrite `Document.storage_key`;
- change the active document storage backend or read path;
- overwrite, move, archive, tombstone, or delete authoritative evidence;
- perform S3 COPY, DELETE, or lifecycle mutation;
- enable dual-write admission;
- create a production cutover token, executor job, or execution credential;
- authorize irreversible disposal.

Database constraints pin `cutover_performed`, `authoritative_storage_changed`, `document_storage_key_mutated`, `active_backend_changed`, `production_execution_token_created`, and `execution_authority_created` to `false`.

## Consequences
A future reversible cutover executor must be introduced in a separate phase and must bind an exact, approved, unexpired admission. It must define atomic authority switching, rollback, partial-failure reconciliation, read-path behavior and operator controls before any production authority changes are possible.
