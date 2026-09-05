# ADR-103 — Adjustment source evolution and human financial controls

**Status:** Accepted for Phase 13.6B  
**Date:** 2026-09-05

## Context

Phase 13.6A made Financial Review cost evidence current-source-aware and introduced append-only human CostReviewDecision lineage. Adjustment Statements already provided versioned human calculations and immutable approval, but they did not record the exact Financial Review evidence state from which a version was built. A later invoice correction, replacement document, source-security change, or cost-review re-review could therefore leave an Adjustment looking operationally current even though its source evidence had evolved.

Adjustment also needs explicit support for common claims-adjusting inputs such as FX, tax, depreciation, betterment and allocation without turning those inputs into autonomous recoverability, coverage or legal decisions.

## Decision

### 1. Financial Review remains the live commercial-evidence authority

`CostItem` and its current evidence fingerprint remain the current derived commercial-evidence surface. `CostReviewDecision` remains the append-only human operational cost-review lineage.

Adjustment does not create a second mutable source-evidence authority.

### 2. Each new Adjustment version is bound to an exact source state

A state-bound Adjustment stores a deterministic `source_state_hash` over the current invoice manifest for the claim and target statement currency. The manifest records stable cost-item identity, source document family/version, source amount/currency, evidence fingerprint/version, current cost-review state and latest human cost-review decision hash.

The runtime source state is:

- `current` — stored and current source hashes match;
- `stale` — current Financial Review evidence differs;
- `legacy_unbound` — the statement predates state-bound source tracking;
- `source_unavailable` — the claim/source state cannot currently be rebuilt.

Historical values are never rewritten merely because the live source state changes.

### 3. Stale Adjustment versions fail closed for new decisions

A stale or legacy-unbound draft/rejected statement cannot be edited or submitted. A stale statement under review cannot be approved. The operator must deliberately create a rebased version against current evidence.

Rejection remains available for an under-review stale version because rejecting a historical proposal does not promote stale evidence.

### 4. Rebase always creates a new version

Rebase never mutates the prior statement. The new statement records `rebased_from_statement_id`.

A prior line judgment may carry forward only when all relevant source identity remains unchanged, including stable item key, evidence fingerprint, current human cost-review lineage hash, source amount and source currency. New or changed lines reset to `pending` / `unallocated` with zero considered amount. Removed lines remain visible only in the historical statement.

Statement-level deductible and other-deduction controls are not carried by default. Carry requires an explicit operator choice during rebase.

### 5. FX is human supplied; the platform only validates arithmetic

For a same-currency invoice line, claimed amount remains the reviewed source amount and no FX input is permitted.

For cross-currency evidence, the operator must enter:

- FX rate;
- rate date;
- source currency;
- target statement currency; and
- source reference.

The platform verifies `source amount × human-entered rate = claimed amount` within currency rounding. It does not select a rate, rate date, source, accounting convention or legal entitlement.

### 6. Tax, depreciation, betterment and allocation are source-grounded human controls

These controls may record a human-entered amount and/or percentage together with a mandatory basis and source reference. If a percentage is supplied, the platform may calculate a reference amount for arithmetic consistency. That computed amount is not a recoverability, coverage, betterment, depreciation, tax or allocation decision.

Treatment, adjustment basis, considered amount and explanatory reason remain human decisions.

### 7. Approved Adjustment remains separate from Settlement and Payment authority

An approved Adjustment is an immutable human-reviewed calculation record, not payment authority.

A **new** Settlement proposal may be created only from an approved Adjustment that is still `current` against Financial Review evidence. If the Adjustment later becomes stale, existing Settlement and Payment records remain immutable historical records; they are not silently withdrawn, recomputed or rewritten.

### 8. Reserve authority remains separate

Neither Financial Review, Adjustment nor Severity/Reserve Support may silently write authoritative reserve state. Phase 13.6C will mature the separate human-controlled Reserve lineage.

## Consequences

### Positive

- Evidence evolution can no longer silently validate stale Adjustment decisions.
- Approved historical versions remain auditable and reproducible.
- Rebase behavior is explicit and selective rather than copying every prior judgment.
- Cross-currency arithmetic becomes reviewable without an autonomous FX engine.
- Common financial-adjusting inputs gain structured provenance while preserving human authority.
- New Settlement proposals cannot begin from an outdated Adjustment state.

### Costs

- Existing pre-13.6B Adjustment versions appear as `legacy_unbound` and require a new state-bound version before new downstream use.
- Financial Review must be rebuildable when evaluating Adjustment current/stale status.
- Operators must provide source references for structured financial controls instead of relying on implicit assumptions.

## Explicit non-goals

Phase 13.6B does **not** autonomously determine:

- policy coverage or admissibility;
- recoverability;
- causation or liability;
- betterment or depreciation entitlement/rate;
- tax entitlement/treatment;
- FX source/rate/date;
- reserve amount;
- settlement amount or acceptance;
- payment authorization/execution; or
- any legal outcome.

Those remain controlled human or downstream authorities.