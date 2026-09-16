# Phase 17.5-R — bounded checkpoint-generation advancement

Phase 17.5-R turns one exact, already-verified Phase Q generation-2 candidate into an immutable **successor synchronization checkpoint record**. It is an explicit administrative control-plane action, not synchronization and not Evidence admission.

## Preconditions

The operator must be an organization Admin with MFA and must target one exact Phase Q versioned-restaging execution through the path-bound execution ID.

The Phase Q execution must be:

- tenant/profile scoped correctly;
- completed;
- `staged_candidate_verified`;
- candidate generation `2`;
- fully integrity-valid through its persisted A→Q lineage.

The Phase O predecessor referenced by Q must still be a valid generation-1 checkpoint.

The request body contains only:

- `request_key`
- `reason`

Provider IDs, generation overrides, paths, URLs, content, storage keys and tokens are rejected.

## What R records

R creates a new immutable checkpoint-generation execution with:

- predecessor Phase O checkpoint ID, generation, state hash and completion hash;
- Phase Q candidate execution and integrity hashes;
- exact listing/metadata lineage IDs inherited from Q;
- generation-2 content SHA-256 and byte count;
- media type and provider version-token hash when available;
- storage backend/purpose and the **hash** of the candidate storage key;
- successor checkpoint kind `remote_file_snapshot_successor_v1`;
- successor checkpoint generation `2`;
- deterministic successor checkpoint state, request and completion hashes;
- requested/completed append-only receipts.

On completion the safety facts record:

- `checkpoint_created=true`
- `checkpoint_advanced=true`
- `checkpoint_generation_advance_completed=true`

## What R does not do

R performs no provider or object-storage I/O. There is no metadata request, file download, folder listing, storage HEAD/GET/PUT/COPY/DELETE, or storage migration.

It also does not:

- mutate the generation-1 Phase O checkpoint;
- mutate the Phase Q candidate row or object;
- make change detection consume the new checkpoint;
- stage a new object;
- create a `Document`;
- admit Evidence or Claim Facts;
- run OCR, parsing, extraction, rendering or indexing;
- enqueue document processing;
- mutate a Claim;
- create subscriptions, cursors, webhooks or background synchronization.

## Immutability and replay

A Phase Q candidate can be consumed once. A Phase O generation-1 predecessor can have only one generation-2 successor in this phase.

Repeating the exact same request with the same actor, request key and reason returns the same execution. Changing the request after consumption conflicts. A second candidate attempting to create a competing generation-2 successor from the same predecessor also conflicts.

## Fail-closed behavior

Every later read of an R execution or its receipts revalidates the predecessor and candidate lineage. Tampered hashes/receipts, invalidated profile or credential lineage, missing upstream facts, or other integrity drift return a conflict rather than silently trusting the successor record.

The raw candidate storage key, provider URL, provider response body, content bytes and credentials are never returned or written to the R audit payload.

## API

Execute:

`POST /api/v1/external-document-sources/profiles/{profile_id}/versioned-restaging-executions/{versioned_restaging_execution_id}/checkpoint-generation-executions`

Read execution:

`GET /api/v1/external-document-sources/profiles/{profile_id}/checkpoint-generation-executions/{execution_id}`

Read receipts:

`GET /api/v1/external-document-sources/profiles/{profile_id}/checkpoint-generation-executions/{execution_id}/receipts`

## Next authority boundaries

Phase R only records the successor checkpoint. A later phase must explicitly decide how subsequent exact-item observations consume successor checkpoint generations.

Human-controlled Evidence admission and claim-scoped `Document` creation remain separate. Recurring/background synchronization remains later still.
