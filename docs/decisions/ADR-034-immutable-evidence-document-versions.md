# ADR-034 — Evidence replacements create immutable document versions

## Status

Accepted for Sprint 8 Phase B.

## Context

Marine claim evidence is often corrected, reissued or supplemented after surveyor, owner, class, workshop or adjuster review. Overwriting a previously reviewed file would destroy provenance and could make existing Claim Facts, chronology events, financial items or approved assessments appear to rely on bytes that were never reviewed.

The existing document model already retained hashes, storage keys and a predecessor pointer, but it did not enforce a document family, a single current version or a controlled replacement transition.

## Decision

1. Each claim document belongs to a tenant- and claim-scoped document family.
2. Every family has monotonic version numbers and no more than one non-deleted current version.
3. A replacement is a new immutable document record with its own bytes, hash, processing and review lifecycle.
4. The operator must select the current source document and provide a human replacement reason.
5. Exact-byte duplicates are rejected.
6. Signature validation and the existing ClamAV quarantine gate run before any active-version transition.
7. The old version becomes superseded only in the same database transaction that creates the admitted new version.
8. Scanner-error and infected replacements retain their replacement intent in quarantine but do not change the current version.
9. Superseded evidence remains downloadable and cannot be soft-deleted through the ordinary document endpoint.
10. Rule-based document completeness uses current versions only.
11. Existing Claim Facts, AI reviews, chronology, financial items and approved assessment snapshots remain attached to the version actually reviewed. Approval is never transferred automatically.
12. Every transition is tenant-scoped, UTC-stamped and audited.

## Consequences

- Claims handlers can distinguish current evidence from preserved history.
- The claim file keeps a defensible chain of custody when reports or invoices are reissued.
- A new version may require fresh extraction and human review before downstream conclusions are updated.
- Historical and current versions consume storage by design.
- Future claim-pack export and Evidence Matrix work can select current versions while still citing historical provenance.

## Rejected alternatives

### Overwrite the existing storage object

Rejected because the hash, review history and source citations would no longer describe the bytes that were reviewed.

### Copy prior approvals to the replacement

Rejected because the new bytes may contain material changes; approval must remain a human decision.

### Treat every upload as an unrelated document

Rejected because operators need a clear family history and a deterministic current version.
