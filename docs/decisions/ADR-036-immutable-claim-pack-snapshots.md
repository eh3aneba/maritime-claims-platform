# ADR-036 — Persist immutable claim-pack snapshots and render formats from one source

- Status: Accepted
- Date: 2026-08-14

## Context

Claim handlers need portable PDF and Excel packs, but generating files directly
from the live database at download time would make an old export silently change
after facts, documents, conflicts or assessments are updated. Separate PDF and
Excel assembly paths could also produce materially different claim narratives.

## Decision

A claim-pack generation request creates one canonical server-side JSON snapshot.
Both PDF and XLSX are rendered from that snapshot. The snapshot, its SHA-256
hash, generated file hash and immutable storage key are persisted in a
tenant-scoped `claim_pack_exports` record.

Only current human-approved Claim Facts populate factual sections. Active
conflicts, outstanding requirements, open tasks, source version state and open
financial flags remain explicit. Only the latest approved Initial Assessment may
be included; drafts are excluded.

Generation and download are audited. A new claim state requires a new export
rather than mutation of an existing record.

## Consequences

- previously generated packs remain reproducible and independently verifiable
- PDF and Excel carry the same substantive snapshot
- export history provides a defensible record of what was known at a point in time
- storage usage grows with each export and will need retention policy controls
- the current pilot PDF font path is limited to CP1252; XLSX preserves full Unicode
- future object storage can replace local storage behind the existing boundary

## Rejected alternatives

### Render directly from live data on every download

Rejected because an old export identifier would not describe stable content.

### Store only generated files

Rejected because the exact structured snapshot could not be inspected or
re-rendered consistently.

### Build separate PDF and Excel queries

Rejected because format-specific data selection could create inconsistent packs.

### Include pending AI candidates or draft assessments

Rejected because unreviewed material must not be represented as authoritative
claim truth.
