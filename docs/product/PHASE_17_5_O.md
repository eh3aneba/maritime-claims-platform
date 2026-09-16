# Phase 17.5-O — Bounded initial synchronization checkpoint custody

Phase 17.5-O creates the first durable synchronization checkpoint for SharePoint / Google Drive document integration.

## What Phase O does

For one exact completed Phase N durable-staging execution, an organization Admin with MFA may record one immutable initial checkpoint describing the already-staged snapshot.

The checkpoint records only bounded non-secret facts:

- exact source/profile/provider lineage;
- exact Phase N staging, Phase M read and Phase L item/listing lineage;
- staged content SHA-256 and byte count;
- bounded media type and provider version-token hash where available;
- sanitized storage backend/purpose and storage-object-key hash;
- checkpoint kind `initial_remote_file_snapshot_v1`;
- checkpoint generation `1`;
- deterministic integrity hashes and requested/completed receipt chain.

This creates a comparison baseline for a future separately authorized change-detection phase.

## What Phase O does not do

Phase O does **not** contact SharePoint or Google Drive. It does not list a folder, read a file, acquire a token, construct a provider client or advance any provider cursor.

Phase O also does **not** read or mutate object storage. No PUT, HEAD, GET, DELETE, copy, migration or lifecycle operation is part of checkpoint creation or checkpoint inspection.

It does not:

- run recurring or background synchronization;
- create subscriptions, webhooks or scheduled polling;
- synchronize a second file or folder tree;
- create a local Document;
- admit Evidence or create Claim Facts;
- parse, OCR, render, index or extract staged content;
- expose file bytes, raw storage keys, signed URLs, credentials or tokens;
- write, move, rename or delete provider content;
- mutate claims or make coverage, causation, liability, fraud, reserve or settlement decisions.

`checkpoint_created=true` means only that the immutable initial control-plane baseline was recorded. `sync_executed` remains false.

## Replay behavior

An exact replay of the same completed request returns the existing checkpoint and creates no additional checkpoint, provider call or storage operation. A changed replay or a second request attempting to consume the same Phase N staging execution fails closed.

## Integrity behavior

Every checkpoint read revalidates its own hashes and receipts and the persisted Phase N lineage. If upstream source/profile/credential or A→N integrity becomes invalid, the checkpoint read fails closed.

Phase O intentionally does not perform a fresh storage-body verification; Phase N remains the authority for durable content custody.

## Next authority boundary

Phase O does not make the integration a recurring sync system. A later phase must separately authorize bounded change detection or incremental synchronization against this baseline. Local Document creation and Evidence admission remain later independent authority increases.
