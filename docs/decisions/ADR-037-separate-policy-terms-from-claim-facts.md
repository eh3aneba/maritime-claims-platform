# ADR-037 — Keep reviewed policy terms outside Claim Facts

- Status: Accepted
- Date: 2026-08-14

## Context

Policy wording contains contractual propositions, limits, exclusions,
warranties and procedural obligations. These are not facts about the casualty.
Promoting them into the same `ClaimFact` store as equipment identity,
maintenance records or incident events would blur source meaning and could make
an extracted clause appear to be a coverage decision.

## Decision

Policy/contract extraction reuses the existing `AIRun`,
`DocumentExtraction` and append-only Human Review infrastructure, but all
`policy.*` and `contract.*` paths are non-promotable to `ClaimFact`.

Approved/edited policy candidates are assembled at read time into a separate
tenant-scoped Policy Term Register. A deterministic service compares only
explicit structured values with known claim dates to produce issue spots. Every
issue states its trigger and required human review. No exclusion, warranty,
deductible, notice clause, time bar or policy period is automatically applied.

## Consequences

- casualty facts and contractual terms keep distinct semantics
- existing source preview, field-level review and audit history are reused
- no new parallel authoritative write model is required
- replacements preserve historical terms without transferring approval
- claim-pack snapshots can include reviewed policy intelligence without implying coverage
- local rule extraction remains intentionally incomplete and requires manual review

## Rejected alternatives

### Promote reviewed clauses to Claim Facts

Rejected because a contractual term is not a casualty fact and could be
misinterpreted by downstream workflows.

### Generate an automatic coverage opinion

Rejected because coverage depends on complete wording, endorsements, facts,
causation, notice, applicable law and professional judgment.

### Hide superseded policy terms

Rejected because historical provenance is required, but reliance must trigger
re-review against the current wording.

### Send policy evidence to an external AI by default

Rejected because confidentiality permission and provider controls are not
assumed.
