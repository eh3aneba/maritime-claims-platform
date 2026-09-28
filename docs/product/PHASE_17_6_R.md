# Phase 17.6-R — SFTP generation-3 exact-file observation

Phase R observes the exact SFTP file represented by one completed generation-3 checkpoint and records whether its bounded metadata is unchanged, changed, or canonically missing.

## Operator flow

1. Select one completed Phase Q generation-3 checkpoint.
2. Provide only a request key and human reason.
3. The service revalidates Q → P → O and deeper SFTP custody lineage.
4. The service derives the exact remote file and governed credential reference internally.
5. One exact metadata/stat call is performed.
6. The result is compared with the generation-3 baseline and an immutable execution/receipt chain is recorded.

## Generation-3 baseline

The baseline comes from the exact metadata accepted into P/Q:
- content byte count from Q/P;
- modified time and metadata identity from P/O;
- deterministic projection hash from those generation-3 facts.

The prior generation-2 checkpoint is not the comparison state.

## Safety

R performs no directory listing, file-content read, object-storage operation, provider mutation, checkpoint advancement, Document/Evidence creation, processing, AI, Claim mutation, or background sync.

Caller-controlled connection/path/credential/storage/content fields are rejected by the strict request schema.

## Result semantics

- `unchanged`: bounded metadata still matches the generation-3 baseline.
- `changed`: one or more bounded comparison dimensions changed.
- `missing`: only canonical exact-item not-found.
- all other provider/transport/authentication failures: fail closed, no successful observation.

## Next phase

The next separately reviewed boundary may create a human Evidence-admission authorization from one latest integrity-valid R `unchanged` observation.
