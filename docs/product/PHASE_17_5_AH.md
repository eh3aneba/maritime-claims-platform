# Phase 17.5-AH — Approved observation refresh consumption

## Purpose
Consume one Phase 17.5-AG `changed + approve_refresh` authorization and stage the exact changed item without broad remote access or canonical Evidence mutation.

## Preconditions
- AG authorization integrity valid;
- authorization result is `changed`;
- active source profile still matches the authorization;
- active Evidence-family binding still matches the authorization;
- canonical current Document is unchanged from the AG approval snapshot;
- originating due-tick observation is a completed `changed` observation and matches the authorization hashes.

## Execution
1. Lock the exact AG authorization.
2. Revalidate current authority and canonical Document.
3. Reconstruct the exact provider-item locator from governed lineage.
4. Build only the exact-item content-read policy.
5. Read that item once.
6. Reconcile version token, byte count and MIME class to the originating changed observation.
7. Stage verified bytes to governed quarantine storage under a deterministic key.
8. Persist one immutable execution and receipt.

## Hard boundaries
No remote listing, remote write/delete, Document mutation, Evidence admission, processing enqueue, AI, Claim mutation, or checkpoint advancement.

## Consumption semantics
A unique one-to-one execution for `authorization_id` is the durable consumption marker. Completed replay returns the same execution and performs no provider read.

## Next phase
A later phase may authorize the verified AH staged refresh for canonical N+1 Evidence admission, reusing the existing family-version admission safety model where possible.