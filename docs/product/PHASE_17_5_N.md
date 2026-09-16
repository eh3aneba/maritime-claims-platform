# Phase 17.5-N — Governed durable remote-content staging

Phase 17.5-N is the first Phase 17.5 step that may retain remote file bytes durably. Its authority is deliberately limited to **quarantine custody**.

## What Phase N does

For one completed, integrity-valid Phase M execution, Phase N:

1. commits a requested recovery anchor before any new remote/storage I/O;
2. binds that anchor to the exact Phase M completion/content proof and exact Phase L item lineage;
3. re-reads that same remote file under the same provider/source policy and 8 MiB limit;
4. requires the reread SHA-256 and byte count to exactly equal Phase M;
5. conditionally writes the matching body to the existing Phase 17.3 S3-compatible foundation under an application-generated quarantine key;
6. HEAD/GET verifies the stored object hash and size;
7. records only bounded custody/integrity facts and append-only receipts.

The API returns the safe hash of the storage key, never the raw key, endpoint, bucket, provider URL, object URL or credentials.

## Crash recovery

The Phase 17.3 object client intentionally has no DELETE. Phase N preserves that rule.

If the process fails after a successful object write but before DB completion, the requested anchor already exists. The next exact retry uses the same deterministic key, verifies the existing object and completes the same execution. It does not create a duplicate object and does not require destructive cleanup.

A different body at that key fails closed.

## What Phase N does not do

Phase N does **not**:

- create a local Document;
- admit Evidence or create Claim Facts;
- parse, OCR, render, classify, index or extract text;
- expose staged bytes or provide a download endpoint;
- create sync/checkpoint/subscription/background polling state;
- upload, edit, move, rename or delete provider content;
- delete/copy/migrate storage objects;
- mutate a Claim;
- make coverage, causation, liability, fraud, reserve or settlement decisions.

## Operator meaning

A completed Phase N execution proves only:

> the platform holds one quarantined durable object whose verified SHA-256 and byte count match one exact completed Phase M remote-read proof, with full upstream lineage still valid.

It does **not** mean that the object is a Document, admissible Evidence, approved evidence, processed content, synchronized source state or claim truth.

## Failure behavior

Phase N fails closed for inactive/tampered upstream lineage, disabled/invalid storage foundation, provider adapter/policy drift, changed replay, oversize content, version/media/size drift, reread digest mismatch, storage write/verification failure, or custody-object tampering.

A failed attempt after the requested anchor is committed may leave that execution in `requested` state so an exact retry can reconcile the deterministic quarantine object. The failure does not grant any broader authority.

## Next authority boundaries

Synchronization/checkpointing, local Document creation and Evidence admission remain separate later phases. Each requires its own scope, acceptance path, exact-head validation and fresh merge authorization.