# ADR-185: Bounded dual-write rehearsal authorization

## Status
Accepted for Phase 17.3-X implementation.

## Context
Phase V proved a bounded, reversible recovery read-ownership transition and Phase W independently qualified one completed Phase V window as healthy. The next storage-hardening step must not jump directly from read evidence to a live write cutover. Write-side rehearsal needs an explicit, short-lived governance authorization with independent approval and immutable lineage.

## Decision
Phase 17.3-X introduces a non-executing authorization for one later bounded dual-write rehearsal.

Admission requires one exact Phase W artifact with `status=qualified` and `health_state=healthy`, its exact qualified receipt, intact W→V→U→T lineage, a clean local shared route, and fresh verification that local authoritative bytes and the recovery replica still match the immutable source hash and size.

The request uses local Admin + MFA and enters `pending_second_approval` for at most ten minutes. Approval requires a different Admin + MFA actor who is also distinct from the Phase W qualifier, Phase V activator, and Phase U approver. An approved authorization expires after at most ten minutes if a later execution tranche does not consume it. One Phase W qualification can produce at most one Phase X authorization.

Phase X authorizes at most one future rehearsal write. It records that envelope as governance evidence only; it performs no write.

## Safety boundary
Phase X does not:

- write or copy document bytes;
- enable live or durable dual-write;
- switch the read or write path;
- create durable write authority;
- mutate `Document.storage_key`;
- change authoritative storage ownership;
- overwrite, move, or delete authoritative local evidence;
- issue object-storage COPY, DELETE, or lifecycle mutations;
- authorize disposal; or
- make recovery storage permanently authoritative.

Database constraints keep all execution, routing, ownership-changing, copy, and destructive flags false for both authorizations and receipts.

Temporary recovery-storage unavailability is retryable and does not consume the approval opportunity. Immutable lineage, route, or integrity drift invalidates the pending authorization fail-closed.

## Consequences
A later, separately reviewed Phase 17.3-Y may consume one exact approved and unexpired Phase X authorization to execute a reversible dual-write rehearsal with post-write hash verification and explicit rollback/cleanup semantics. Phase Y must continue to keep local evidence authoritative and must not be conflated with final storage-ownership migration.

## References
Issues #356 and #25; PRs #355, #353, and #351.
