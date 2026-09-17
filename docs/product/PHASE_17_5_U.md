# Phase 17.5-U — bounded checkpoint-generation-3 advancement

Phase U advances one exact completed Phase T generation-3 quarantine candidate into one immutable generation-3 synchronization checkpoint.

## Operator action

An organization Admin with MFA calls:

`POST /api/v1/external-document-sources/profiles/{profile_id}/successor-versioned-restaging-executions/{successor_versioned_restaging_execution_id}/checkpoint-generation-3-executions`

with only:

- `request_key`
- `reason`

The caller cannot provide checkpoint generation, provider item identity, path/URL, version, content, storage key, object coordinates, credentials or tokens.

## Eligibility

The exact T execution must be:

- tenant/profile scoped;
- completed;
- `result_status=staged_candidate_verified`;
- candidate generation 3;
- integrity-valid through its full R/S/T lineage.

Its predecessor is derived only from T's persisted `checkpoint_generation_execution_id` and must be the exact completed Phase R generation-2 checkpoint.

## Result

A successful U execution records:

- predecessor checkpoint generation 2;
- candidate generation 3;
- successor checkpoint generation 3;
- immutable state/scope/request/completion hashes;
- requested/completed receipt chain;
- content SHA-256, bounded byte count, MIME/version facts;
- storage backend/purpose and storage object-key hash only.

The raw storage key is not returned.

## Zero-I/O guarantee

U performs no provider or object-storage I/O. T integrity is checked with storage verification disabled. U does not create a `Document`, admit Evidence, parse/OCR/index content, mutate a Claim, or start recurring/background synchronization.

## Replay and conflicts

Exact replay with the same actor, request key and reason returns the existing execution. Changed replay conflicts. A T candidate cannot be consumed twice, and a Phase R predecessor cannot receive two generation-3 successors in this phase.

## Read APIs

- `GET /profiles/{profile_id}/checkpoint-generation-3-executions/{execution_id}`
- `GET /profiles/{profile_id}/checkpoint-generation-3-executions/{execution_id}/receipts`

Both revalidate the full lineage and receipt/state hashes fail-closed without provider/storage I/O.

## Later phases

A later separately reviewed phase may observe the exact provider item against this generation-3 checkpoint. Human-controlled Evidence admission/current `Document` creation and recurring/background synchronization remain outside Phase U.
