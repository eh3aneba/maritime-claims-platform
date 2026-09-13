# ADR-203: Controlled physical evidence disposal execution

## Status
Accepted for implementation in Phase 17.4-B.

## Context
Phase 17.2 established retention/disposal governance and Phase 17.3 established durable recovery-storage authority. Phase 17.4-A added a short-lived, single-use, four-eyes admission credential, but deliberately performed no deletion. The remaining boundary is the first irreversible removal of legacy local evidence bytes.

A database transaction cannot roll back a filesystem unlink. The executor therefore cannot pretend that physical deletion and relational state are atomic. It must remain reconstructable after a process crash, retry only exact targets, and preserve the durable recovery copy and its audit lineage.

## Decision
Phase 17.4-B consumes exactly one valid Phase 17.4-A credential and deletes only the manifest-bound local legacy copy represented by the existing `Document.storage_key` fingerprint. It never deletes the recovery object, never deletes the `Document` row, and never mutates `Document.storage_key`.

Execution is two-stage:

1. Freshly revalidate the approved release review, quarantine stage, execution manifest, every AO qualification and receipt, the Phase 17.4-A authorization and receipt chain, actor separation, and an active Phase V recovery read-ownership path. Verify local bytes and recovery bytes against the exact binding.
2. Persist and commit an immutable execution intent and per-document target hashes before any unlink.
3. Delete each exact local target. Persist deletion evidence after each item. A retry finding a missing local target under the same prepared execution reconciles that crash window rather than issuing a second deletion.
4. Re-read the recovery object directly and verify its bound hash and size after each local deletion.
5. Only after every item is verified, atomically terminalize the Phase 17.4-A credential as `consumed` with `execution_count=1`, finalize the Phase 17.4-B execution, and append a success receipt.

A conflicting replay fails closed. A recovery-store outage before any unlink is retryable without consuming authority. An outage after an unlink leaves a durable partial execution that can only be reconciled by the same exact request.

## Read-path consequence
After successful lawful local disposal, recovery is the only surviving evidence copy. The Phase V recovery read path therefore treats a successful, verified Phase 17.4-B execution item as retirement of the local fallback: reads verify the recovery object directly rather than requiring the deleted local bytes. The old local metadata remains immutable audit lineage.

Rollback or reconciliation to a deleted local source is not a valid state. Phase 17.4-B must fail closed around any operation that would restore local read ownership after a verified disposal.

## Actor separation
The destructive executor must be a retention Admin with MFA and must differ from all material retention/disposal actors, the Phase 17.4-A approver, and the actor lineage embedded in the bound AO health qualifications.

## Safety invariants
- no S3/recovery-object delete;
- no wildcard or prefix deletion;
- no unrelated claim/document deletion;
- no `Document` row deletion;
- no `Document.storage_key` mutation;
- no legal-hold bypass;
- exact manifest/document/AO binding required;
- one admission credential can succeed once only;
- append-only hash-chained execution receipts;
- tenant isolation on every lookup;
- recovery bytes must verify before and after local deletion.

## Consequences
Physical disposal becomes intentionally explicit and auditable. The retained `Document` row becomes historical metadata for evidence whose authoritative bytes live in durable recovery storage. Any future storage-provider deletion or destruction of the durable recovery copy requires a separately governed boundary and is not authorized by this ADR.
