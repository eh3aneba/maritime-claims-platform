# ADR-220 — Bounded exact-item remote change detection

## Status

Proposed for Phase 17.5-P.

## Context

Phase 17.5-O records one immutable generation-1 checkpoint for an exact Phase N staged remote-file snapshot. The checkpoint is deliberately control-plane only: it does not poll the provider, advance synchronization state, create a local `Document`, admit Evidence, or mutate a Claim.

The next useful authority increase is to ask whether that exact remote item still represents the same bounded metadata snapshot. This must not silently become folder synchronization or content reread.

A review of the current MCRI `Document` model also shows that `Document` creation is already an Evidence authority boundary: it is claim-scoped and canonical-storage-backed, ordinary upload starts processing, and governed email intake creates a `Document` only after explicit human Evidence admission plus integrity and malware controls. Phase P therefore must not introduce a pre-Evidence `Document` shortcut.

## Decision

Phase 17.5-P permits one explicit Admin + MFA action to observe metadata for the exact provider item pinned by one integrity-valid Phase O checkpoint.

The caller supplies only `request_key` and `reason`. Provider item identity, source boundary and endpoint are derived from persisted A→O lineage.

The provider request is an exact-item metadata GET with a fixed allowlisted projection and strict network bounds. No folder/tree listing, arbitrary provider URL, redirect following, file-body read or download is permitted.

The normalized result is classified as:

- `unchanged` — the exact item exists and all bounded comparable metadata facts match the immutable baseline;
- `changed` — the exact item exists but one or more bounded metadata/version facts differ;
- `missing` — only when the provider returns its canonical not-found/deleted condition for the exact item.

Permission errors, authorization failures, timeouts, malformed responses, oversized responses and provider failures are execution failures and are never converted into `missing`.

## Persisted facts

Phase P persists only bounded control-plane facts and hashes, including:

- Phase O checkpoint lineage and hashes;
- Phase L metadata-item lineage;
- hashes of provider item identity, display name and parent identity rather than new raw copies;
- item kind, MIME class, byte size, modified time and provider version-token hash where present;
- deterministic baseline and observed projection hashes;
- changed-dimension names;
- deterministic request, scope, completion and receipt hashes;
- explicit safety facts.

Raw provider response bodies, tokens, credentials, transient clients, arbitrary provider URLs, file content and raw storage keys are not persisted or returned.

## Safety boundary

The only new positive authority is:

1. transient provider-client construction for one exact observation;
2. one exact-item metadata read;
3. durable immutable comparison result.

Phase P explicitly grants no authority to:

- list folders or discover new items;
- read/download file content;
- write, move, rename or delete provider content;
- read/write/delete object storage;
- advance or replace the Phase O checkpoint;
- create subscriptions, recurring polling or background synchronization;
- stage a new content generation;
- create a local `Document`;
- admit Evidence or create Claim Facts;
- parse/OCR/extract/index content;
- mutate Claims or make coverage, causation, liability, fraud, reserve or settlement decisions.

DB constraints encode these negative authorities. Completed executions must show `provider_client_constructed=true`, `exact_item_metadata_read_performed=true`, and `change_detection_completed=true`, while content-read, storage, sync, subscription, Document, Evidence and Claim-mutation flags remain false.

## Integrity and replay

Every create/read operation revalidates the complete upstream A→O lineage. The Phase O checkpoint remains immutable and is locked while a new observation request is anchored.

Multiple manual observations may reference the same checkpoint, but each requires a distinct request key. Exact replay of the same request key, actor and reason returns the same execution. Changed replay conflicts.

Requested/completed receipts are append-only and hash-chained. Persisted baseline and observed projections are recomputable from bounded stored facts, so projection hashes are not opaque trust anchors.

## Consequences

Phase P provides safe change awareness without yet granting synchronization authority. A later phase may separately authorize bounded reread and versioned restaging of an item classified `changed`. Human-controlled Evidence admission / `Document` creation remains another independent authority increase.