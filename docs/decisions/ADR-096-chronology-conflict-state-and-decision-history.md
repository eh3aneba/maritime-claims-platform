# ADR-096: Bind chronology conflict dispositions to immutable conflict state

## Status
Accepted for Phase 13.3A implementation.

## Context
The chronology engine already derives events and evidence conflicts only from human-reviewed claim evidence. A conflict row has a stable workflow identity (`conflict_key`) and a mutable current disposition (`status`, `resolution_note`, reviewer and time).

That model is insufficient for production maturity. A second human disposition overwrites the first one, and a conflict that disappears from a rebuild and later reappears can inherit an old resolved status even though the reviewer did not review the newly active conflict state. The current API also has no state token a client can use to detect that the conflict changed after it was displayed.

## Decision
### Separate conflict identity from conflict state
`conflict_key` continues to identify the same logical source/event relationship. Phase 13.3 does not change its historical hash semantics.

Each active conflict additionally carries:
- `state_fingerprint`: a deterministic SHA-256 over the material conflict values, materiality and source/event lineage;
- `state_version`: a monotonic version for that conflict identity.

An unchanged active rebuild preserves both fields and the current human disposition. If material state changes, or an inactive conflict reappears, `state_version` increments and the current read model returns to `open`.

### Append-only human decision history
Every non-replayed human disposition creates an `EvidenceConflictDecision` row containing:
- exact conflict state fingerprint/version reviewed;
- monotonic decision number;
- disposition and note;
- reviewer and decision time;
- previous decision hash and current decision hash.

The mutable fields on `EvidenceConflict` remain as a compatibility/read model for the latest disposition. They no longer represent the only history.

### Retry versus re-review
An exact replay by the same reviewer for the same conflict state, disposition and note is idempotent: it returns the existing decision and does not append decision/audit history.

A materially different decision while the current conflict already has a non-open human disposition requires explicit `confirm_re_review=true`. This prevents a transport/UI mistake from silently replacing a prior human decision while still allowing deliberate re-review.

### Stale-state protection
The resolution request may carry `expected_state_fingerprint` and `expected_state_version` as a pair. When supplied, the server compares them after locking and re-reading the current conflict. A mismatch fails closed and requires the operator to refresh and review current evidence.

Phase 13.3A keeps this pair optional for backward compatibility with the existing chronology UI. The following operator-UX tranche will send it on every disposition and can then tighten the API contract.

### Concurrency
On PostgreSQL, chronology rebuild and conflict resolution serialize through a claim-level row lock. Conflict resolution then re-reads and locks the active conflict row. This prevents a concurrent rebuild and human decision from committing against different current states.

## Migration
Migration `0067_chronology_conflict_decisions` backfills state fingerprints/version for existing conflict rows and converts existing non-open dispositions into decision-history row 1 without deleting the current compatibility fields.

## Consequences
- human conflict decisions become reviewable, append-only lineage;
- stale decisions cannot silently remain current after a conflict disappears/reappears or materially changes;
- unchanged rebuilds remain idempotent and preserve valid dispositions;
- event `source_signature` and conflict `conflict_key` identities remain stable;
- future UI can show current versus stale disposition history without a new backend data model;
- no source is automatically selected as true.

## Authority boundary
Conflict disposition is workflow metadata only. It does not authorize automated causation, coverage, liability, recoverability, reserve, settlement, payment, fraud or legal conclusions. Human authority and tenant/source controls remain server-enforced.

Refs #169
Refs #154
