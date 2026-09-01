# AI Operations / Decision Log Architecture

Phase 12H adds an operator-grade, content-free governance and observability layer over existing authoritative AI operational ledgers.

## Source ledgers

The console does not introduce a third authoritative run ledger. It reads from:

1. `ai_production_decision_logs` — Sprint 11T Production-wide document-processing AI Decision Log.
2. `claim_qa_synthesis_runs` — Phase 12G governed Claim Q&A synthesis execution lineage.

Both are queried with an organization predicate before rows are normalized. Cross-tenant discovery is therefore rejected before any normalized result is returned.

## Unified read model

`app.modules.ai_operations` normalizes only governance-safe fields: workflow, claim/document identifiers, authorization and eligibility identifiers/hashes, status/failure/fallback state, model/bundle lineage, different-human review state, source-grounding counters, token/latency/cost metrics and immutable run/result/review hashes.

The read model explicitly excludes raw prompts, raw questions, source passages, source quotations, provider response text and synthesized answer text. Phase 12G source-unit identifiers are also not returned by the general operator event contract; only source count and hashes are exposed.

No projection table is created. Metrics and attention signals are recomputed from the source ledgers. Queries are deterministically ordered and bounded.

## Human review

Only Production Decision Log events have a retrospective human review action in Phase 12H. The operator endpoint delegates to the existing Sprint 11T `review_decision_log` service, preserving:

- different-human enforcement;
- no second review of an already-reviewed row;
- immutable run hash and generated review hash;
- source workflow metrics;
- no ClaimFact, reserve, settlement/payment, coverage or liability mutation.

Phase 12G synthesis rows are observability-only. Phase 12H does not persist transient synthesis wording to manufacture a retrospective review screen.

## Attention signals and metrics

Attention is derived rather than persisted as authoritative state. Examples include pending different-human review, human edit/reject, unsupported output, incomplete grounding, synthesis block/provider error/verification failure and extractive fallback.

Metrics include mixed workflow counts, pending reviews, review-action distribution, grounding/unsupported counters, synthesis block/fallback/verification counts, token totals, observed document-processing provider cost and latency mean/P95 where the source ledger supports them.

## Incident handoff

An operator may explicitly hand a selected event to the existing Sprint 11T Production-wide incident service when that event has an authorization lineage. Phase 12H does not automatically declare incidents, revoke authorization or activate a kill switch. Existing Production-wide controls continue to own pause/revoke/kill-switch semantics.

## Audit export

Manager/admin export is allowlist-based JSON or CSV. Export generation writes a standard audit event containing only format, row count, filter hash and content-free boundary flags. Export does not include claim/document text, prompts/questions, passages/quotes, provider output or credentials.

## UI

`/ai-operations` provides KPI cards, filters, unified event table, different-human review queue, lineage drill-down, claim deep links, explicit incident handoff and audited content-free export.

The page prominently states that observability does not create authorization or autonomous claims/legal/financial authority.
