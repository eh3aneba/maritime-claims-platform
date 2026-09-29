# Phase 17.6-W — Provider-neutral recurring-observation lineage

Phase W removes the remaining provider-specific lineage assumption from the generic recurring-observation engine.

## What changes

- due-tick observation lineage can represent either legacy SharePoint/Google Drive generation-3 lineage or SFTP R/Q lineage;
- due-tick dispatch persistence recognizes SFTP;
- a shared resolver validates provider-specific lineage and exposes one normalized metadata-only observation contract;
- existing legacy scope hashes retain their historical shape.

## SFTP resolver

For SFTP, the resolver revalidates:

1. provider-neutral U family binding;
2. Phase-T admission execution;
3. Phase-S human authorization;
4. latest trusted Phase-R generation-3 observation;
5. exact Phase-Q generation-3 checkpoint;
6. Phase-P restaging and predecessor custody lineage;
7. active governed SFTP credential/profile facts.

The stable source identity must match the trusted profile plus relative-path hash.

## Metadata observation

The SFTP reader performs exactly one bounded stat operation using the existing adapter.

It normalizes:

- unchanged;
- changed;
- missing.

No directory listing, content read, object-storage access, Document mutation, Claim mutation, processing enqueue, checkpoint advance or AI is performed.

## Migration boundary

Migration 0215 makes due-tick lineage provider-aware while preserving all historical SharePoint/Google Drive rows. Downgrade fails closed if any SFTP due-tick or dispatch rows have been created.

## Authority remains closed

Phase W does not allow an SFTP family to create a recurring schedule.

A schedule request for `provider_kind=sftp` fails explicitly until Phase 17.6-X. This keeps infrastructure refactor separate from authority expansion.

## Next

Phase X opens one human-controlled recurring SFTP schedule lifecycle against this provider-neutral lineage contract.
