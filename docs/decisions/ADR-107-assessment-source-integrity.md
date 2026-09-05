# ADR-107 — Initial Assessment source-state integrity and stale-write safety

- **Status:** Accepted for Phase 13.8A implementation
- **Parent:** #193
- **Core maturity roadmap:** #154

## Context

The existing Initial Assessment already provides human-reviewed, monotonically versioned claim snapshots and prevents mutation after approval. That is necessary but not sufficient for a production claims workflow: an operator can keep an assessment open while Claim Facts, documents, chronology, evidence conflicts, financial state, reserve history, tasks, or other upstream human-reviewed evidence evolves. Without a bound source identity, the platform cannot distinguish a current draft from a historically valid but stale draft.

The Initial Assessment must remain a review snapshot. It must not become a second authority for technical causation, reserve, recovery, settlement, payment, coverage, or legal conclusions.

## Decision

### 1. Bind every newly generated assessment to a compact deterministic source snapshot

At generation time the service records `source_snapshot` and `source_fingerprint` on `initial_assessments`.

The snapshot contains only deterministic row identities and row hashes for claim-scoped upstream state that can drive the existing Initial Assessment renderer, including the Claim record, Claim Facts, active documents, reviewed extraction state, chronology/evidence linkage, conflicts, requirements/issues, cost/financial records, reserve history, and open tasks.

It does **not** copy source documents, evidence text, technical conclusions, reserve authority, recovery opinions, settlement terms, or other canonical module content into the Assessment authority boundary.

The canonical SHA-256 fingerprint is computed from sorted JSON-safe data. A second fingerprint is computed before generation commits; if the upstream state changed during generation, the transaction is rolled back and no assessment version is committed.

### 2. Treat source evolution as staleness, never as historical mutation

For a source-bound assessment:

- `current`: the current upstream fingerprint equals the stored generation fingerprint.
- `stale`: the current upstream fingerprint differs.
- `legacy_unbound`: a pre-13.8 historical row has no stored source fingerprint.

A stale or legacy assessment remains readable. Its sections, human edits, approvals, and historical meaning are not rewritten or invalidated.

### 3. Fail closed on stale review and approval writes

Section review/edit and assessment approval require the exact `expected_source_fingerprint` presented to the operator.

A write is rejected with HTTP 409 when:

- the browser/session fingerprint does not equal the assessment's bound fingerprint;
- current upstream state no longer equals the assessment's bound fingerprint; or
- the historical row is `legacy_unbound`.

The recovery path is deliberate: reload and, where upstream state evolved, generate a new assessment version. The platform never silently refreshes or replaces an existing version.

Service-layer calls also recompute current source state before mutation. API clients must additionally provide the optimistic fingerprint.

### 4. Hash the approved human record

On approval, after all sections have been human-reviewed, the service writes `approved_content_hash` over persisted approved assessment content, section decisions/text, provenance manifests, approval identity/time, and the bound source fingerprint.

This hash is an audit/export identity only. It is not a coverage, causation, reserve, recovery, settlement, payment, or closure decision.

Approved assessment versions remain mutation-blocked. Later source evolution can make the approved version `stale` relative to today's claim file, but cannot change its `approved_content_hash`.

### 5. Improve explicit Claim Fact provenance without transferring authority

Equipment and maintenance Claim Facts already influence the Damage & Technical Findings draft. Their Claim Fact IDs are now included in the section source manifest so the visible provenance matches the generated content more closely.

## Compatibility

Migration `0075_assessment_source_integrity` adds nullable fields so historical rows are preserved unchanged. Existing rows without source fingerprints are surfaced as `legacy_unbound` and are read-only for further review/approval. A newly generated version is required to enter the source-bound workflow.

## Authority boundary

Initial Assessment is a human-reviewed claims-handling snapshot. It does not autonomously determine:

- policy coverage or legal entitlement;
- machinery causation or fault;
- liability allocation;
- recovery entitlement or time-bar legal effect;
- reserve amount;
- settlement amount or acceptance;
- payment authorization; or
- claim closure.

Technical, Financial/Reserve, Recovery/Time-Bar, Adjustment, Settlement and Payment remain the canonical authorities for their existing records. Source-state integrity only records whether this Assessment version still corresponds to the upstream state from which it was generated.

## Verification

Phase 13.8A requires regression coverage for:

- deterministic source-bound generation;
- current → stale transition after upstream evolution;
- stale section-review rejection;
- stale approval rejection;
- optimistic browser fingerprint mismatch rejection;
- compatibility-safe `legacy_unbound` behavior;
- deliberate new-version recovery; and
- stable approved-content hash after later source evolution.

Backend, migration, frontend, browser and Supply Chain gates must be green on the exact PR head before merge consideration.
