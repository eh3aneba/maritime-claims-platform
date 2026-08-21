# ADR-074 — Claims Intelligence is source-linked and non-authoritative

## Status
Accepted for Phase 12A.

## Context

The platform now has mature evidence controls, human-reviewed extraction, chronology/conflict handling, deterministic H&M rules, policy intelligence, financial controls and a Production-wide human-reviewed AI authorization plane. The next product problem is not another rollout percentage; it is helping a claims handler synthesize those controlled layers into a faster, defensible first assessment.

A naive approach would generate free-form claim conclusions or allow an AI assistant to update the claim record directly. That would weaken source lineage, blur the boundary between candidate analysis and authoritative facts, and create unacceptable coverage, liability and causation risk.

## Decision

Phase 12A will create a versioned Claims Intelligence snapshot composed from controlled platform records. Every material item must expose structured source lineage. Intelligence is a candidate until a human explicitly accepts, edits or dismisses it.

Snapshots and items are immutable after creation. Human decisions are append-only records with chained SHA-256 hashes. An accepted suggestion may create a controlled claim task only through an explicit user action.

The engine will not automatically write or revise `ClaimFact`, chronology conflict resolution, policy review conclusions, reserve, settlement, payment, recovery responsibility or an authoritative initial assessment.

Phase 12A also does not widen external-provider authorization. Its initial synthesis is deterministic over existing controlled records; any later provider-assisted synthesis must enter through the existing AI governance and production authorization framework.

## Consequences

### Positive
- preserves evidence lineage and auditability;
- makes claim intelligence reviewable and reproducible;
- supports measurable handler productivity without autonomous claim decisions;
- allows later model-assisted improvements behind the same authority boundary;
- creates a stable foundation for Marine Rules, Recovery/Time-bar and semantic claim search.

### Trade-offs
- handlers must explicitly review candidate intelligence;
- some conclusions remain less concise than a free-form chatbot response;
- richer marine issue spotting requires versioned domain rules and references rather than prompt-only logic.

## Permanent boundary

No intelligence item is itself a coverage, liability, causation, recoverability, reserve, settlement, payment, fraud or recovery decision. Those decisions remain human-owned under the applicable policy wording, law, evidence and organizational authority.
