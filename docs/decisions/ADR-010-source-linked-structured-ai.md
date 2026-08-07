# ADR-010: Require structured, source-linked AI extraction before human review

## Status
Accepted — Sprint 3 Phase B

## Decision
For claims evidence extraction, LLMs must return a document-specific strict schema rather than free-form summaries. Every non-null candidate fact/opinion must include a source segment index and exact quote. AI classification and extraction are persisted separately from approved claim data.

## Rationale
Marine claims decisions must be reproducible and auditable. A fluent summary without provenance is insufficient for coverage, causation, maintenance and financial review. Structured source-linked candidates let a human reviewer inspect what the model saw and correct it before any official record changes.

## Consequences
- More schema and validation engineering per document class.
- Provider output can be evaluated field-by-field.
- Hallucinated or mismatched citations can be detected and flagged.
- Model/provider/prompt/schema upgrades remain traceable through `ai_runs`.
