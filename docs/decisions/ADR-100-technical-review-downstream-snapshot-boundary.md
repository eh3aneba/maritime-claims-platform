# ADR-100: Technical review downstream snapshot boundary

## Status
Accepted for Phase 13.5C implementation.

## Context
Technical Review now has stable topic identity, evidence-state fingerprint/version and append-only human investigation dispositions. Phase 13.5C must prove the real MT ORION stale/re-review lifecycle and audit downstream integration without creating a second source of causation authority.

Evidence completeness, chronology, Initial Assessment and Claim Pack already have separate responsibilities and mature lineage/snapshot behavior. Copying Technical Review decisions into mutable ClaimIssue, chronology conflict or document-requirement state would blur authority and allow the same human reasoning to drift independently in multiple domains.

## Decision
1. `TechnicalInvestigationDecision` and the current `build_technical_review` state remain the sole technical-investigation lineage source.
2. Evidence Matrix remains authoritative for evidence completeness, requirement state and evidence/conflict provenance. Technical review may link to it but never mutates requirement dispositions.
3. Chronology remains authoritative for event/conflict lineage. Technical review does not create or resolve chronology conflicts.
4. Initial Assessment continues to snapshot its existing technical findings/issues and chronology/evidence sections. It does not become a second mutable store for technical decision lineage in Phase 13.5C.
5. Claim Pack schema 1.1 snapshots the exact current technical topic state, state fingerprint/version and latest append-only human disposition alongside the existing Evidence Matrix and approved Initial Assessment snapshot.
6. A stale technical disposition is preserved in downstream snapshot history and is surfaced as `attention_required`; it is never silently promoted to current.
7. Downstream snapshots are review aids. They do not write back to Technical Review and do not establish proximate cause, coverage, liability, negligence, unseaworthiness, workmanship responsibility, fraud, reserve, settlement, payment or recovery.

## Assessment integration note
The Initial Assessment service already consumes Technical Review workshop findings and independently snapshots active technical ClaimIssues. Direct copying of TechnicalInvestigationDecision lineage into Initial Assessment is deliberately deferred to avoid two independent immutable copies with different review timing. Claim Pack 1.1 is the consolidated immutable downstream record containing both the approved assessment snapshot (when present) and the exact Technical Review lineage at pack generation time.

This defer is acceptable only while the Technical Review route remains the live lineage source and the Claim Pack records the exact state used for authorized circulation. A later assessment-specific decision-lineage snapshot must reuse the Technical Review state identity rather than invent a second decision model.

## Acceptance
Phase 13.5C tests must demonstrate:
- current technical disposition -> evidence evolution -> stale prior disposition -> explicit re-review -> append-only hash lineage;
- stale and current state are represented exactly in Claim Pack snapshots;
- Evidence Matrix/chronology/assessment remain separate authority surfaces;
- real MT ORION browser acceptance exercises the live API rather than mocking the technical state transition;
- exact-head CI and Supply Chain Security pass before merge.

## Consequences
- No new top-level route, dashboard, AI stage or causation engine is added.
- Claim Pack snapshot schema advances from 1.0 to 1.1.
- Consumers of stored Claim Pack JSON must tolerate the added `technical_investigation` object and technical summary counters.
- Existing 1.0 exports remain immutable and readable; they are not rewritten.

Refs #179
Refs #154
