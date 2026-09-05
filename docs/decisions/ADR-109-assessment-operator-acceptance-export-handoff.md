# ADR-109: Initial Assessment operator maturity and approved export handoff

## Status
Accepted for Phase 13.8C.

## Context
Phase 13.8A bound Initial Assessment review/approval writes to deterministic upstream source state and added an approved-content digest. Phase 13.8B exposed exact version history and current read-only Technical / Financial / Reserve / Recovery status references. The final maturity tranche must make those controls understandable to operators and carry an approved assessment into downstream reporting without creating a second decision authority.

## Decision

### Exact historical navigation
The Assessment workspace exposes claim-scoped version history and retrieves an exact selected version. `is_latest` and `source_state` are separate properties. Selecting or refreshing a historical version must not silently replace it with the latest version.

A historical assessment remains readable. Source evolution may mark it `stale`, but never rewrites the persisted assessment, human review lineage, approval metadata or approved-content digest.

### Localized operator controls
Assessment operator chrome is available in English and Persian and follows the global LTR/RTL locale. Persisted assessment text, source labels and evidence content are not machine-translated because they are claim-file records; they render with content-aware direction instead.

Stale, legacy, permission, validation, empty, history and recovery/current-domain states have localized operator messaging. A stale or legacy version exposes a deliberate `Generate new version` recovery path.

### Bounded live current-domain context
Technical, Financial, Reserve and Recovery/Time-Bar status references shown in Assessment are live read-only projections from their canonical modules. They are not persisted into the assessment and are not included in its approved-content digest. Their display does not transfer authority into Initial Assessment.

### Claim Pack handoff
Claim Pack schema 1.3 may consume only an Initial Assessment that is:
1. explicitly `approved`; and
2. bound to a non-null `approved_content_hash`.

Draft, under-review and legacy approved rows without a digest are excluded rather than assigned fabricated integrity metadata.

The Claim Pack stores the approved assessment content, bound source fingerprint, approved-content digest, approval/classification metadata and the source state observed at export. `source_state_at_export` is reporting context only: a later `stale` state does not invalidate or rewrite the historical human approval.

PDF and XLSX exports surface the approved digest and source identity so downstream reviewers can verify which immutable human-approved assessment was handed off.

## Authority boundary
Initial Assessment is a human-reviewed claim-handling snapshot. Claim Pack is downstream reporting. Neither determines coverage, causation, liability, recoverability, governing law, time-bar legal effect, reserve adequacy, settlement, payment or claim closure. Technical, Financial/Reserve, Recovery/Time-Bar, Adjustment, Settlement and Payment retain their canonical authority boundaries.

## Acceptance
The real MT ORION browser gate must prove on one continuous claim journey:
- human review and approval of a source-bound assessment;
- upstream source evolution making the historical approved version stale without changing its digest;
- a stale open-version write rejected with HTTP 409;
- deliberate regeneration, human section review and manager approval;
- exact history navigation and EN/FA/RTL stale/history controls;
- Claim Pack schema 1.3 containing exactly the latest eligible approved assessment digest and immutable export hash.
