# ADR-169: Bounded recovery cutover execution lease

## Status
Accepted for Phase 17.3-H.

## Context
Phase 17.3-G produced governed approval evidence for a future reversible cutover executor. The next safe step is to model one bounded production-execution control-plane lease without connecting that lease to the live document read path or mutating authoritative evidence.

## Decision
Introduce `EvidenceRecoveryCutoverExecutionLease` and append-only transition receipts.

A lease can be prepared only from one exact approved `EvidenceRecoveryCutoverAdmission` whose approval receipt and full recovery lineage still validate. The lease is tenant/claim/document scoped, hash-bound, one-time and expires no later than 10 minutes after preparation or the earlier parent admission/attestation boundary.

The state machine is `prepared -> activated -> rolled_back`, with `expired` and `invalidated` terminal states for fail-closed activation failures. Activation requires a different Admin from both the lease preparer and the cutover-admission approver. Rollback is risk-reducing and remains available after lease expiry once activation has occurred.

## Safety boundary
Phase 17.3-H remains deliberately non-routable. `activated` means only that the execution control-plane lease is active; it does not switch reads or storage authority.

The database pins all of these to false:
- `read_path_switched`
- `document_storage_key_mutated`
- `active_backend_changed`
- `authoritative_storage_changed`
- `destructive_action_performed`
- `s3_delete_performed`
- `local_delete_performed`

There is no local evidence delete/move/overwrite, no S3 COPY/DELETE/lifecycle operation, no dual-write admission, no production storage pointer update and no irreversible disposal.

## Consequences
- A later phase can consume a verified rolled-back execution lease as evidence that the organization rehearsed the exact production execution control plane under a short-lived lease.
- Rollback proof is explicit and append-only.
- Any lineage or integrity drift before activation invalidates fail-closed.
- Live evidence authority remains local until a separately governed phase explicitly changes that boundary.
