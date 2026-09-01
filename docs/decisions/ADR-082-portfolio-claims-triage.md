# ADR-082: Deterministic portfolio claims triage

- Status: Accepted for Phase 12J implementation
- Date: 2026-09-01

## Context
MCRI now has multiple controlled claim-level decision-support and governance workflows. A handler still needs to visit several workspaces to understand which claims require attention. Creating another authoritative claims state or an opaque AI ranking would increase governance risk and duplicate existing sources.

## Decision
Introduce a read-time **Claims Workbench** that normalizes current tenant-scoped operational attention signals and ranks them with deterministic, versioned weights.

The workbench:
1. consumes only existing controlled source state;
2. uses the latest source snapshot where a source is snapshot-versioned;
3. records factor-by-factor lineage and a deterministic rank hash;
4. preserves candidate/legal uncertainty semantics;
5. performs no LLM ranking and creates no new AI authority;
6. does not persist or mutate claim-merits state;
7. deep-links humans to the source workflow for action.

## Consequences
### Positive
- one cross-claim operational queue;
- explainable priority ordering;
- no new migration for the foundation;
- no duplicated authoritative evaluations;
- straightforward tenant-isolation and regression testing.

### Trade-offs
- read-time aggregation is bounded and may need a materialized projection at much larger scale;
- ranking weights require explicit versioned change control;
- source availability controls workbench completeness.

## Permanent boundaries
The workbench score is not a loss, coverage, liability, causation, recoverability, fraud, reserve, settlement, payment or legal-rights score. Candidate time-bars remain candidate dates. No workbench read may modify ClaimFacts, ReserveHistory, settlement/payment state, correspondence or source evaluations.
