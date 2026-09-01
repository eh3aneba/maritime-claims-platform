# ADR-080 — AI Operations is a content-free read model, not a new AI authority

## Status
Accepted for Phase 12H implementation.

## Context
Sprint 11T already persists the Production-wide `AIProductionDecisionLog`, including human-review, grounding, latency/cost and authorization lineage. Phase 12G separately persists `ClaimQaSynthesisRun`, deliberately excluding raw questions, evidence passages and provider/synthesis text. Operators need one searchable workflow across both sources.

A tempting design would copy both sources into a new observability table or persist transient Q&A text for retrospective review. That would create a second source of truth and materially weaken the established content-minimization boundary.

## Decision
Phase 12H uses a tenant-scoped, rebuildable read model over the existing source ledgers.

- No new run/event persistence is introduced.
- Raw prompts, raw questions, evidence passages/quotes, provider responses and synthesized answers remain excluded from the governance plane.
- Metrics and attention signals are recomputed from source rows.
- Existing Sprint 11T review semantics are reused for document-processing Decision Log rows.
- Phase 12G synthesis rows remain observability-only.
- Incident handoff requires an explicit human action and delegates to the existing Production-wide incident service.
- Export is based on an explicit allowlist and is itself audited.
- Observability does not grant AI runtime authorization, Restricted-data permission, new document classes or claims/legal/financial decision authority.

## Consequences
The operator console can trace failures, blocks, fallbacks, review state, lineage and operational quality without creating a parallel authoritative ledger. Some workflow-specific data will remain unavailable where the source ledger does not persist it—for example provider cost for Phase 12G currently has no persisted cost field. Phase 12H reports only what the source supports rather than inventing values.

The first implementation uses bounded source queries and deterministic in-process normalization. If future scale requires a materialized projection, that projection must remain rebuildable, tenant-scoped and content-free and must not become authoritative truth.
