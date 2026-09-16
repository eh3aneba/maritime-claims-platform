# ADR-221 — Bounded changed-item versioned restaging

## Status

Proposed for Phase 17.5-Q / Issue #435.

## Context

Phase 17.5-P can prove that one exact provider item pinned by an immutable Phase O checkpoint is `changed`, but P deliberately has no file-body or storage authority. The platform therefore needs a separately reviewed step that can acquire the newly observed bytes without silently turning change detection into synchronization, checkpoint mutation or Evidence admission.

The current `Document` model is not a neutral pre-Evidence shell. `Document` is claim-scoped and canonical-storage-backed and existing intake paths can trigger processing. The governed email-provider path creates a `Document` only after explicit Evidence admission plus integrity/malware controls. External document integration must preserve that authority boundary.

## Decision

Phase 17.5-Q permits one explicit Admin + MFA **changed-item versioned restaging** execution for one exact integrity-valid Phase P execution whose result is `changed`.

Q derives the provider target exclusively from persisted A→P lineage, performs one bounded exact content reread, validates available version/size/MIME facts against the Phase P observation, and stages the body into a new immutable candidate quarantine generation.

The original Phase N object and Phase O checkpoint are immutable inputs and are never overwritten, deleted or advanced by Q.

### Three-stage durable lifecycle

Q persists:

1. `requested` — deterministic recovery anchor exists before provider reread or object-store write;
2. `content_verified` — bounded content proof (SHA-256, size, MIME/version facts, latency class) is committed before the first object-store write;
3. `completed` — the deterministic candidate object has been reconciled by HEAD/GET and completion/receipt hashes are committed.

This split is intentional. If the process fails after object creation but before DB completion, replay can reconcile the same deterministic object against the already committed content proof. No object delete, overwrite, copy or rename authority is needed for recovery.

## Authority boundary

Q may:

- construct the existing approved transient provider client;
- reread the exact changed item once under the existing bounded content-read policy;
- retain file bytes only transiently in memory;
- calculate a bounded content proof;
- conditionally create one deterministic generation-2 quarantine object;
- HEAD/GET only that same candidate object for integrity reconciliation;
- persist immutable execution and requested/content-verified/completed receipt lineage.

Q may not:

- list folders or discover provider items;
- write, rename, move or delete provider content;
- overwrite/delete/copy/migrate storage objects;
- mutate or advance the Phase O checkpoint;
- claim the candidate generation is synchronized/current;
- create a `Document`, admit Evidence, create Claim Facts, enqueue processing, OCR, parse, index or mutate a Claim;
- create subscriptions, webhooks, recurring polling or background synchronization.

## Eligibility and exact-target rules

Only `result_status=changed` Phase P executions are eligible. `unchanged` and `missing` are rejected before provider or storage I/O.

The caller supplies only `request_key` and `reason`. Provider item identifiers, paths, URLs, versions, cursors, ranges, content, storage keys and tokens are rejected by strict request validation.

The provider item is recovered from the immutable Phase L item referenced through Phase O/P lineage. Its identity hash must equal the Phase P observed identity hash. A fresh content result must match Phase P observed byte-size, MIME and version-token facts whenever those facts are available. Drift fails closed and requires a fresh Phase P observation.

## Storage semantics

The candidate object key is deterministic and opaque, scoped by organization, Phase P execution, generation and Phase Q execution. The raw key remains internal custody data; APIs and audit records expose only its SHA-256 hash.

Conditional create semantics prevent overwrite. Exact replay reuses the same execution and object. A second request attempting to consume the same Phase P execution conflicts.

## Consequences

The integration can now safely acquire changed bytes while keeping observation, custody, checkpoint authority and Evidence authority separate. A later phase must explicitly govern checkpoint-generation advancement to this candidate. Evidence admission / `Document` creation remains another independently reviewed human-controlled authority increase. Recurring synchronization remains later still.
