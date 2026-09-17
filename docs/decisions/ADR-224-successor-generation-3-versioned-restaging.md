# ADR-224 — Successor generation-3 versioned restaging

## Status

Accepted for Phase 17.5-T implementation review.

## Context

Phase 17.5-S observes one exact remote item against the immutable Phase R generation-2 successor checkpoint. A `changed` result proves that the current bounded metadata projection differs from the generation-2 baseline, but S intentionally has no file-body or object-storage authority.

The next required capability is to reread the exact changed file body and place it into immutable quarantine custody as candidate generation 3. Combining this with checkpoint advancement or Evidence admission would collapse distinct authority boundaries and make recovery/tamper semantics harder to prove.

## Decision

Phase T consumes only one exact completed integrity-valid S execution with `result_status=changed`.

It creates a separate successor-restaging execution with immutable lineage to S, R, Q, P and the earlier governed source lineage. Candidate generation is fixed to `3` by application and database constraints.

The provider target is never supplied by the caller. The exact provider item comes from the original governed metadata item and must hash to the Phase S observed provider identity.

Phase T reuses the existing bounded remote file-content read policy and adapter registry. The transient content result is reconciled against Phase S observed byte size, MIME class and version token when those values exist.

## Durable lifecycle

The lifecycle is:

`requested → content_verified → completed`

The `requested` anchor is committed before provider or storage I/O.

The content proof—SHA-256, byte count, MIME class, version token, latency class and proof hash—is committed before the first object-store PUT.

The storage key is deterministic and internal:

`external-remote-content-versioned-quarantine/{organization_id}/{phase_s_execution_id}/generation-3/{phase_t_execution_id}`

Only `storage_object_key_hash` is exposed through API/audit surfaces.

Storage uses conditional put-if-absent. No overwrite or delete authority exists.

If execution fails after PUT but before completion, replay from `content_verified` first HEAD/GET-verifies the deterministic object. A matching existing object completes the execution without provider reread or another PUT. If the object is absent, the provider may be reread once and must exactly match the already-committed content proof before conditional PUT.

## Authority boundary

Phase T may:

- construct the already-governed transient provider client path;
- perform one exact file-body reread;
- transiently observe content;
- commit a bounded content proof;
- write one immutable generation-3 quarantine object;
- read that exact object for verification;
- persist immutable execution and receipt hashes.

Phase T may not:

- relist/discover folders or items;
- mutate O/P/Q/R/S;
- overwrite/delete/migrate storage objects;
- create or advance a checkpoint;
- create `Document` or Evidence/Claim Facts;
- parse/OCR/render/index/extract content;
- enqueue document processing;
- create webhooks/subscriptions/cursors/background sync;
- provider write/edit/move/rename/delete;
- mutate Claims or make claim decisions.

## Consequences

Generation-3 content gains durable, crash-recoverable quarantine custody without changing the authoritative checkpoint. The next checkpoint-generation advancement remains a separate human-reviewed production phase.

Evidence admission/current `Document` creation remains a later separate authority boundary, and recurring/background synchronization remains later still.
