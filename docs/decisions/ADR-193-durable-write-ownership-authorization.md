# ADR-193: Governance authorization for durable recovery write ownership

## Status
Accepted for Phase 17.3-AG.

## Context
Phase AF independently qualifies one completed Phase AE bounded recovery write-ownership transition after exact rollback to `local_only`. A qualified AF artifact proves that local evidence, the verified recovery replica and both routing control planes remained healthy after the temporary `recovery_primary` window.

That evidence is still not executable authority. Before any durable recovery write-ownership execution can be attempted, a separate governance step must rebind the exact AF artifact, repeat its fresh verification and obtain independent approval.

## Decision
Phase AG creates one non-executing authorization for one later durable recovery write-ownership execution window.

Admission requires an exact tenant/claim/document-scoped Phase AF health qualification with status `qualified` and `health_state=healthy`, plus exactly one matching AF qualified receipt. Phase AG freshly reloads the underlying Phase AE snapshot through the AF verifier and requires the AF snapshot to remain unchanged.

At request and approval time the evidence must still show:

- authoritative local evidence matching the source SHA-256, byte length and storage-key fingerprint;
- verified recovery replica matching the same source bytes and recovery-storage identity;
- shared read routing at exact `local_source` with no active recovery-read lease;
- dedicated write routing at exact `local_only`, with no active canary or Phase AE lease;
- no durable write authority, evidence-storage ownership transfer, destructive action or disposal authority.

The request enters `pending_second_approval` for at most ten minutes. A second Admin+MFA actor must independently repeat the fresh AF verification before approval. The approver must be independent from the AG requester, AF requester/qualifier, AE activator, AD requester/approver and the AC/AB/AA/Z/Y/X actors preserved in the lineage.

An approved authorization is valid for at most ten minutes and permits at most one later durable-write execution window. Approval does not itself create that window.

Every state transition writes an append-only, hash-bound receipt. Fresh verification drift invalidates a pending authorization. A recovery-storage outage remains retryable and does not terminalize the pending authorization.

## Safety boundary
Phase AG is authorization only. It does not:

- create or activate a write-routing lease;
- switch `local_only` to `recovery_primary` or any durable recovery mode;
- perform S3 PUT/COPY/DELETE or local overwrite/move/delete;
- create durable recovery write authority by itself;
- switch the shared read path;
- mutate `Document.storage_key`;
- transfer authoritative evidence-storage ownership;
- authorize evidence disposal or deletion.

Local evidence remains authoritative throughout Phase AG.

## Consequences
A Phase AG `approved` artifact may be consumed by one later separately reviewed execution tranche. That later tranche must define exact durable-write route semantics, rollback behavior, qualification requirements and failure handling.

Phase AG does not authorize authoritative evidence-storage ownership transfer or physical disposal. Those remain separate future decisions requiring fresh production merge authorization.
