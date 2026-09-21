# Phase 17.5-AI — Refreshed Evidence admission authorization

## Purpose

Phase AI adds a separate human authorization boundary between a completed Phase 17.5-AH verified refresh and any later canonical N+1 Evidence admission.

AH may read exactly one approved changed remote item and stage verified bytes in governed quarantine storage. AI does not admit those bytes. It only records that one exact AH execution may proceed to the next admission phase if all authority and lineage are still current.

## Preconditions

Authorization requires:

- a completed AH execution with result_status = staged_refresh_verified;
- valid AH immutable integrity;
- active source profile and matching profile hash;
- active external Evidence-family binding;
- exact stable source-item identity match;
- exact canonical current Document ID/version/file hash matching AH;
- internally consistent AH content proof, byte count, media type, provider version-token hash and storage-key hash;
- refreshed bytes that are not already the current canonical Evidence and are not already present as non-deleted Claim Evidence.

## Human boundary

The endpoint requires an Administrator with current MFA.

The authorization snapshots the exact AH execution, source lineage, current canonical Document, staged-content proof, actor, reason and request key. Exact replay is idempotent. Altered replay conflicts.

## Hard boundaries

Phase AI performs no OAuth or provider-token acquisition, provider-client construction, remote metadata/content access, staged-storage I/O, file-signature validation, malware scanning, Document mutation, Evidence admission, processing enqueue, AI execution, Claim mutation, checkpoint advancement or background synchronization.

The raw staged storage object key is intentionally not exposed by the API schema.

## Staleness and concurrency

The exact AH execution, family binding and canonical current Document are locked/revalidated while authorization is created. A canonical version change makes the request stale. One AH execution may have at most one admission authorization, and one request key may identify only one exact authorization scope.

Historical authorization records remain immutable if the family later advances.

## Next phase

Phase 17.5-AJ will consume one valid AI authorization, revalidate current authority and AH storage integrity, perform authoritative file-signature and malware verification, and create exactly one canonical N+1 Document. AJ must not inherit processing or external-AI authority.
