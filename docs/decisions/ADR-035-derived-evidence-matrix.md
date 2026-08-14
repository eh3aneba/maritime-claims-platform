# ADR-035 — Evidence Matrix is a derived provenance read model

## Status

Accepted for Sprint 8 Phase C.

## Context

Claim Facts, reviewed extractions, document versions and chronology conflicts already have separate authoritative lifecycles. Copying them into a new mutable matrix table would create stale parallel truth and could silently detach a conclusion from the bytes and human review that supported it.

## Decision

1. Build the Evidence Matrix at read time from existing tenant-scoped records.
2. Populate the Fact column only from current human-approved Claim Facts.
3. Preserve the Claim Fact's recorded source extraction as authoritative provenance.
4. Group corroborating reviewed fact extractions only by exact field path and approved-value equality.
5. Attach active conflicts by extraction identifier; preserve unlinked conflicts as conflict-only rows.
6. Flag superseded sources without moving approval to a replacement document.
7. Keep the Matrix read-only and make no AI call.
8. Treat conflict status as human workflow state, never adjudication of source truth.

## Consequences

- Operators receive one coherent evidence view without a second source of truth.
- Reissued evidence cannot make an old approval appear to apply to new bytes.
- Matrix output always reflects the latest conflict resolution and document-version state.
- Larger portfolios may later need measured query optimization, but denormalization is deferred until real usage data justifies it.

## Rejected alternatives

### Persist a separate matrix table

Rejected because changes in facts, conflicts or document versions could leave copied rows stale.

### Include pending AI candidates as provisional facts

Rejected because the Fact column must remain human-authoritative.

### Select the current document as automatically authoritative

Rejected because a replacement requires fresh extraction and human review.
