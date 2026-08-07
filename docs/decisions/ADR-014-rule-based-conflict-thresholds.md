# ADR-014 — Use deterministic conflict thresholds before LLM reasoning

## Status
Accepted — Sprint 3 Phase E

## Decision
Initial chronology conflict detection uses deterministic domain thresholds: <=10 minutes clusters compatible events, 10–30 minutes creates Medium review, >30 minutes creates High conflict, and date-level discrepancies create Critical review.

## Rationale
Claims users need explainable and reproducible discrepancy detection. The LLM may later explain evidence, but it must not silently decide whether two sources conflict or which source is more credible.

## Consequences
Thresholds can later become tenant/configuration rules. Every generated conflict is traceable to the compared events/extractions and can be resolved only by a human action.
