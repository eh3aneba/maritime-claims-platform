# ADR-190: Bounded recovery write-ownership transition authorization

## Status
Accepted for Phase 17.3-AD implementation.

## Context
Phase 17.3-AC independently qualified one completed routable dual-write canary window after exact rollback to local-only write authority. The platform now has evidence that one bounded secondary recovery write can be performed and verified without changing the authoritative local write path.

That evidence is not itself permission to transition write ownership. A stronger step needs a separate governance boundary so operational evidence cannot silently become execution authority.

## Decision
Phase 17.3-AD introduces a tenant-scoped, short-lived, non-routable authorization for one later bounded recovery write-ownership transition.

Admission requires one exact Phase AC artifact with `status=qualified` and `health_state=healthy`, exactly one matching qualified receipt, and fresh revalidation of the complete AC → AB → AA → Z → Y → X → W → V → U → T → replica lineage.

Request and independent approval both re-run the Phase AC fresh snapshot verification. This includes the terminal Phase AB lease and receipts, clean `local_source` read route, exact `local_only` write route with no canary pointer, authoritative local bytes, replica lineage/configuration, and HEAD+GET verification of the inert deterministic Phase AB canary object.

A recovery-storage outage is retryable and leaves a pending authorization unchanged. Lineage, route, configuration, or byte-integrity drift invalidates fail-closed during second review.

Authorization uses Four-Eyes control. The approver must differ from the requester and from the Phase AC qualifier, Phase AB activator, Phase AA requester/approver, Phase Z qualifier, Phase Y executor, and Phase X approver. The second-review window and approved consumption window are each bounded to ten minutes.

One exact Phase AC qualification may create at most one Phase AD authorization. Receipts are append-only and hash-bound.

## Safety boundary
Phase AD is authorization-only. It performs no document or storage write, creates no write-route lease, does not reactivate dual-write, does not switch read or write routing, does not mutate `Document.storage_key`, does not change authoritative storage ownership, and grants no destructive or disposal authority.

Database constraints pin local authority true and every execution/routing/storage/destructive flag false, including S3 PUT/COPY/DELETE and local deletion.

## Consequences
A later separately reviewed Phase 17.3-AE may consume one exact approved and unexpired Phase AD authorization to implement a bounded reversible recovery write-ownership transition. AE must preserve local evidence as the rollback source and will require a separate production PR and fresh explicit merge authorization.

Phase AD itself does not make recovery storage authoritative and cannot execute the future transition.
