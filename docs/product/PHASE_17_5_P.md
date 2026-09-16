# Phase 17.5-P — Exact-item remote change detection

Phase 17.5-P lets an authorized operator compare one exact SharePoint or Google Drive item against the immutable Phase O checkpoint baseline.

## What it does

For one completed, integrity-valid Phase O checkpoint, an organization Admin with MFA can trigger one manual metadata-only observation of the same exact provider item.

The system returns one of three results:

- **unchanged** — the exact item still exists and its bounded normalized metadata matches the checkpoint baseline;
- **changed** — the exact item still exists but one or more bounded comparison dimensions differ;
- **missing** — the provider explicitly reports the exact item as not found/deleted.

A missing permission, expired authorization, timeout, malformed provider response or other provider error is not reported as `missing`. Those remain execution failures.

## What is compared

The comparison is derived from persisted checkpoint/metadata lineage and a fresh exact-item projection. Bounded comparison dimensions include:

- item kind;
- display-name hash;
- parent-item hash;
- MIME type class;
- byte size;
- modified timestamp;
- provider version-token hash where available.

Raw provider item IDs are not newly copied into the Phase P tables or API; bounded hashes are persisted instead.

## What Phase P does not do

Phase P does not:

- list a folder or discover new items;
- download/read file bytes;
- touch object storage;
- replace or advance the Phase O checkpoint;
- stage a new file generation;
- create a `Document`;
- admit Evidence;
- start OCR, parsing, extraction or indexing;
- create a subscription or recurring/background sync;
- write/delete/move/rename provider content;
- mutate a Claim.

## Operator workflow

1. Complete the governed A→O chain for one remote file.
2. Select the Phase O checkpoint.
3. Run one explicit change-detection action with a reason and request key.
4. Review `unchanged`, `changed` or `missing` plus the changed dimensions.
5. If the item is `changed`, a later separately authorized phase may reread and stage a new immutable generation. Phase P itself does not do that.

## Audit and replay

Each successful observation has deterministic lineage/request/completion hashes and a requested/completed receipt chain. Replaying the same request key with the same actor and reason returns the original execution; attempting to repurpose the key conflicts.

All later reads revalidate the upstream A→O lineage and fail closed if the source profile, credential binding, checkpoint or upstream integrity becomes invalid.