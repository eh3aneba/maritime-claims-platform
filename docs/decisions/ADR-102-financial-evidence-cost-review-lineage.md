# ADR-102: Financial evidence and human cost-review lineage

- **Status:** Accepted for Phase 13.6A
- **Date:** 2026-09-05
- **Parent:** #185 / #154

## Context

The existing Financial Review materializes invoice and quotation line items into `CostItem` rows and lets a handler mutate `CostItem.review_status`. That is useful operationally, but it conflates two different concepts:

1. the **current derived financial evidence state**, which must change when reviewed source evidence changes; and
2. the **human disposition recorded against the evidence state the handler actually saw**, which must remain auditable after the source changes.

The prior implementation also selected the latest completed invoice/quotation AI run without requiring the source document to remain current, non-deleted, processed and security-usable. A reviewed source could therefore remain visible after becoming failed, quarantined, superseded or deleted. A status such as `accepted`, `rejected` or `paid` could also remain attached to a changed derived row without an explicit stale/current relationship.

These behaviors are incompatible with the Phase 13 production-maturity gate and with the existing technical-review state model.

## Decision

### 1. `CostItem` is current derived evidence, not human authority

`CostItem` remains the materialized current line-item cache used by Financial Review and downstream support. It is rebuilt only from human-reviewed invoice/quotation extractions whose source document is:

- tenant/claim scoped;
- the current document-family version;
- not deleted;
- successfully processed; and
- security-usable (`clean` or backward-compatible `legacy_unscanned`).

Failed, quarantined, scan-error, superseded and deleted documents do not feed the live financial evidence state.

Deleting/replacing a derived `CostItem` does not delete an approved Adjustment snapshot because Adjustment lines already snapshot their source values and their `cost_item_id` foreign key is nullable on source deletion.

### 2. Stable cost identity is based on document family + semantic line path

A cost item receives a deterministic logical key derived from:

`document_family_id + document_kind + source_field_prefix`

This survives normal source-document replacement within the same document family. A line-position change is deliberately conservative: it changes the logical key/path relationship rather than silently transferring a prior human disposition to a potentially different line.

### 3. Exact evidence state is fingerprinted

The current cost state fingerprint includes the material line-item values plus source provenance, including:

- current document id/family/version/file hash and source-admission state;
- AI run id/input-text hash/task/prompt/schema version; and
- supplier/document metadata, description, quantity, unit, unit price, amount, currency, category and source field path.

A changed reviewed extraction, source version or other material input therefore produces a different fingerprint.

### 4. `CostReviewDecision` is append-only human operational lineage

A new `cost_review_decisions` table stores what a human decided about one exact cost evidence state. Each decision records:

- stable item key;
- exact state fingerprint/version;
- decision number;
- human status and reason;
- immutable source/item snapshot;
- reviewer and time; and
- previous-decision hash + decision hash.

Exact semantic replay is idempotent. A materially new decision after any prior decision requires explicit re-review. A stale browser state is rejected rather than replayed against changed evidence.

### 5. Prior status never silently transfers to changed evidence

If the latest human decision fingerprint matches the current evidence fingerprint, the decision is `current` and its status is reflected in the current `CostItem` cache.

If evidence changes, the prior decision becomes `stale`, the current `CostItem.review_status` cache resets to `under_review`, and the prior decision remains in append-only history. If the source becomes unavailable entirely, no stale `CostItem` is recreated; the historical decision is shown separately as source-unavailable audit history.

This prevents an old `accepted`, `rejected` or `paid` status from influencing current downstream calculations merely because the source changed.

### 6. Financial flags remain advisory

Financial flags continue to be deterministic review cues only. Their current trigger set is rebuilt from current usable reviewed evidence. They do not determine coverage, recoverability, betterment, ordinary maintenance, supplier selection, reserve, settlement or payment.

### 7. Severity / Reserve Support refreshes derived financial evidence, not human authority

Before producing an immutable Severity/Reserve Support snapshot, the support service refreshes the existing derived Financial Review evidence cache. This ensures the support snapshot cannot consume a superseded or quarantined CostItem, or a stale transferred human status.

That refresh:

- does not append/change `CostReviewDecision`;
- does not write `ReserveHistory`; and
- does not make coverage, liability, causation, settlement or payment decisions.

Reserve-range support remains non-authoritative.

### 8. Adjustment, reserve, settlement and payment remain separate authorities

Phase 13.6A does not merge financial authorities:

- **Financial Review / CostItem:** current source-grounded commercial evidence.
- **CostReviewDecision:** human operational review lineage for a cost item; not coverage/recoverability authority.
- **Adjustment Statement:** separate versioned human adjustment/calculation authority. Approved statements remain immutable historical records. Live source-staleness/new-version behavior is Phase 13.6B.
- **Severity & Reserve Support:** non-authoritative candidate range only.
- **ReserveHistory:** authoritative reserve history. A dedicated explicit human reserve-change workflow is Phase 13.6C; support output never writes it automatically.
- **Settlement / Payment:** separate downstream human authorities with existing approval controls. A cost-review status, including legacy `paid`, is not payment authorization or evidence of money movement.

## Failure and recovery semantics

- Unusable current source: exclude from live Financial Review; retain prior human decision history separately.
- Evidence changes during review: reject write with `409`; browser refreshes current state before another disposition.
- Prior decision exists: deliberate re-review is required for a new history entry.
- Exact retry: return the existing decision rather than duplicating history.
- Cross-tenant claim/item: fail closed.
- No current source: do not infer amount/status from prior history.

## Consequences

Financial evidence can evolve without rewriting human history, and human review can evolve without becoming an autonomous coverage/reserve/settlement authority. Downstream reserve support consumes only current source-admissible financial evidence while the approved Adjustment and settlement/payment chains retain their independent authority boundaries.
