# ADR-098: Evidence Matrix operator consolidation

**Status:** Accepted

## Context

Phase 13.4A made evidence completeness depend on usable/security-safe evidence rather than physical upload alone. Phase 13.4B added deterministic requirement evidence-state identity, stale-write protection and append-only human decision lineage.

The remaining maturity gap is operator fragmentation: readiness/document requirements are primarily visible in Rules while approved ClaimFact provenance and chronology conflicts are visible in Evidence Matrix. Adding another dashboard would increase surface sprawl and create competing interpretations of the same evidence state.

## Decision

### 1. Evidence Matrix is the consolidated read-only evidence-completeness view

The existing claim Evidence Matrix route remains the single read-only operator surface that brings together:

- deterministic readiness score and blocking evidence;
- active `ClaimDocumentRequirement` lifecycle state;
- request/review context;
- direct-document versus human-accepted equivalent-evidence basis;
- requirement evidence-state version;
- latest human disposition and append-only decision history;
- approved ClaimFacts and source-version provenance; and
- active/reviewed chronology conflicts.

No new top-level route, dashboard, domain or AI stage is introduced.

### 2. Write authority remains outside Evidence Matrix

Evidence Matrix does not accept equivalent evidence, re-review evidence, resolve conflicts, send correspondence or mutate canonical ClaimFacts.

Controlled human writes remain on their established authority surfaces and APIs, including Rules, AI Review, Chronology and Correspondence. Evidence Matrix links the handler to those workflows when action is required.

This prevents a second write path from drifting from optimistic-concurrency, confirmation, permission and audit controls already enforced by the authoritative workflow.

### 3. Current state and historical decisions stay visually distinct

Requirement status describes the current operational read model. Human decision history is append-only evidence of what was reviewed previously.

The UI therefore shows current status/basis separately from latest/history entries. A prior accepted equivalent decision is not presented as currently satisfying a superseded requirement.

### 4. Locale changes are presentation-only

English/Persian switching and RTL/LTR directionality must not re-evaluate rules, append decisions, change requirement status or mutate ClaimFacts.

Technical identifiers, rule versions, ClaimFact/source versions and source quotations remain data and may render in their original language/direction.

### 5. Recovery and permission states are explicit

The consolidated surface distinguishes loading, empty, permission-denied and recoverable failure states. Recoverable failures provide an explicit refresh/retry path. Requirement-history conflicts or stale state direct the operator back to the controlled Rules review flow rather than attempting an implicit repair.

## Browser acceptance

The MT ORION synthetic design-partner journey gates this contract by exercising:

- consolidated readiness/requirement rendering;
- EN/FA and RTL/LTR presentation without mutation;
- a real source-linked equivalent-evidence acceptance through the production authority API;
- canonical ClaimFact version evolution followed by deterministic rules refresh;
- visible superseded/stale requirement state;
- explicit human re-review of the changed evidence; and
- two append-only hash-chained requirement decisions visible in Evidence Matrix history.

Backend Phase 13.4A/13.4B tests remain authoritative for upload/processing/security transitions, idempotency, stale-write rejection, direct-document takeover/recovery and tenant isolation.

## Authority boundary

This consolidation identifies evidence gaps and displays human review lineage. It does not determine coverage, liability, causation, fraud, reserve, settlement, payment, recovery, legal outcome, source truth, or whether substitute evidence is legally/substantively sufficient.

## Consequences

- handlers gain one evidence-completeness/provenance view without another product surface;
- current readiness and historical human judgments are less likely to be conflated;
- write controls remain centralized on their existing authority surfaces;
- EN/FA/RTL behavior becomes part of the evidence-completeness acceptance gate; and
- Phase 13.4 can close on workflow maturity rather than feature expansion.
