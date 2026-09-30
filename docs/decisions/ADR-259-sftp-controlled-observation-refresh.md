# ADR-259: Controlled SFTP observation refresh execution

## Status

Proposed for Phase 17.6-AB.

## Context

Phase AA makes SFTP human review decisions provider-neutral but intentionally keeps `approve_refresh` closed.

The existing observation-refresh execution model is the correct downstream contract for AC, but its content-read resolver is still SharePoint/Google Drive-specific.

## Decision

Reuse the existing `ExternalDocumentSourceObservationRefreshAuthorization` and `ExternalDocumentSourceObservationRefreshExecution` persistence boundaries for SFTP.

Refactor only provider lineage/content-read resolution:

- SharePoint/Google Drive preserve their historical generation-3 lineage and read adapter behavior;
- SFTP resolves the trusted W recurring lineage and derives one exact-file content request from trusted profile/checkpoint facts;
- caller-supplied remote paths remain impossible;
- the existing governed observation-refresh quarantine, proof hash, receipt and replay lifecycle remain shared.

## SFTP authority

AB widens:
- observation refresh authorization provider constraint;
- observation refresh execution provider constraint.

SFTP `approve_refresh` becomes available only after all existing human decision checks succeed.

## Content-read boundary

Exactly one bounded SFTP exact-file read is allowed.

The adapter contract enforces:
- one connection/authentication/read attempt;
- pinned host-key verification;
- read-only SFTP session;
- exact file target;
- no symlink following;
- no listing/stat/write/rename/delete/mkdir/chmod/chown/touch/command;
- no credential/session/raw-response/content persistence by the adapter.

Returned bytes must match the changed due-tick observation byte count.

The refreshed digest must differ from the current canonical Evidence digest.

## Shared quarantine

After validation, bytes are written to the existing observation-refresh quarantine store and verified by digest/size.

AB does not create or mutate canonical Documents. AC remains the sole canonical N+1 admission boundary.

## Validation boundary

The complete SFTP exact-read and exact-replay integration scenario is retained in Full Backend pre-merge validation. PostgreSQL concurrency validation retains the database migration/provider constraints and the fail-closed size-mismatch path without duplicating the long end-to-end replay chain. This preserves coverage while keeping the concurrency gate scoped to database-sensitive behavior.

## Compatibility

Legacy SharePoint/Google Drive scope/hash/read behavior remains unchanged.

## Next

Phase AC authorizes and admits the integrity-valid shared refresh execution as canonical Evidence version N+1.
